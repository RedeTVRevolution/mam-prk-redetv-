"""Comparação dos motores do inventário de objetos (#244), sem nuvem."""

import json
from pathlib import Path
from typing import Any

import pytest

from api.comparar_objetos import (
    DisparadorDoCloudRun,
    FaltaNoAmbiente,
    Preco,
    comparar,
    destino_do_florence,
    main,
    precos_do_ambiente,
)
from api.gemini import Chamada
from api.tests.test_inventario_job import CONVERTIDO, VISTO, _armazem

PRECOS = {"flash-lite": Preco(0.10, 0.40), "flash": Preco(1.0, 4.0)}
RAIZ = Path(__file__).parents[2]


class TransporteContado:
    """Devolve, por modelo, o texto e soma tokens como o TransporteVertex."""

    def __init__(self) -> None:
        self.tokens_de_entrada = 0
        self.tokens_de_saida = 0
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        self.tokens_de_entrada += 1000
        self.tokens_de_saida += 200
        return VISTO if chamada.imagens else CONVERTIDO


class DisparadorFalso:
    def __init__(self, armazem: Any, falha: bool = False) -> None:
        self.armazem = armazem
        self.falha = falha
        self.pedidos: list[tuple[str, str]] = []

    def rodar(self, job_id: str, destino: str) -> None:
        self.pedidos.append((job_id, destino))
        if self.falha:
            raise RuntimeError("falhou")
        self.armazem.resultados[(job_id, destino)] = self.armazem.resultados[
            (job_id, None)
        ]


class Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        self.agora += 2.0
        return self.agora


def _rodar(tmp_path: Path, **extra: Any) -> tuple[list[Any], Any, Any, Any]:
    armazem = _armazem()
    disparador = DisparadorFalso(armazem)
    transporte = TransporteContado()
    medidas = comparar(
        "j1",
        tmp_path,
        armazem=armazem,
        disparador=disparador,
        transporte=transporte,
        modelos=["flash-lite", "flash"],
        precos=PRECOS,
        relogio=Relogio(),
        **extra,
    )
    return medidas, armazem, disparador, transporte


def test_dispara_o_florence_com_o_destino_alternativo(tmp_path: Path) -> None:
    _, _, disparador, _ = _rodar(tmp_path)

    assert disparador.pedidos == [("j1", destino_do_florence("j1"))]
    assert destino_do_florence("j1") != "j1/objetos/florence.json"


def test_guarda_por_motor_o_inventario_os_tokens_o_tempo_e_o_custo(
    tmp_path: Path,
) -> None:
    medidas, _, _, _ = _rodar(tmp_path)

    assert [(m.motor, m.modelo) for m in medidas] == [
        ("florence", "flash-lite"),
        ("gemini", "flash-lite"),
        ("gemini", "flash"),
    ]
    florence = json.loads((tmp_path / "florence" / "medida.json").read_text())
    # 1000 de entrada e 200 de saída no Flash-Lite, mais 2 s de GPU a US$ 1,05 por hora.
    assert florence["tokens_de_entrada"] == 1000 and florence["tokens_de_saida"] == 200
    assert florence["segundos_na_gpu"] == 2.0
    assert florence["custo_usd"] == pytest.approx(
        1000 * 0.10 / 1e6 + 200 * 0.40 / 1e6 + 2 / 3600 * 1.05, abs=1e-6
    )
    forte = json.loads((tmp_path / "gemini-flash" / "medida.json").read_text())
    assert forte["custo_usd"] == pytest.approx(1000 * 1.0 / 1e6 + 200 * 4.0 / 1e6)
    assert forte["segundos_na_gpu"] == 0
    inventario = json.loads((tmp_path / "florence" / "inventario.json").read_text())
    assert inventario["0"][0]["nome"] == "cadeira"
    assert (tmp_path / "gemini-flash-lite" / "inventario.json").exists()


def test_o_gemini_recebe_as_imagens_e_a_conversao_so_texto(tmp_path: Path) -> None:
    *_, transporte = _rodar(tmp_path)

    assert [bool(c.imagens) for c in transporte.chamadas] == [False, True, True]
    assert [c.modelo for c in transporte.chamadas] == [
        "flash-lite",
        "flash-lite",
        "flash",
    ]


def test_nao_grava_na_decupagem(tmp_path: Path) -> None:
    _, armazem, _, _ = _rodar(tmp_path)

    assert armazem.gravadas == []


def test_sem_preco_do_modelo_falha_antes_de_disparar_o_job(tmp_path: Path) -> None:
    armazem = _armazem()
    disparador = DisparadorFalso(armazem)

    with pytest.raises(FaltaNoAmbiente, match="outro"):
        comparar(
            "j1",
            tmp_path,
            armazem=armazem,
            disparador=disparador,
            transporte=TransporteContado(),
            modelos=["flash-lite", "outro"],
            precos=PRECOS,
        )

    assert disparador.pedidos == []


def test_falha_do_job_com_gpu_sobe_e_nao_guarda_nada(tmp_path: Path) -> None:
    armazem = _armazem()

    with pytest.raises(RuntimeError, match="falhou"):
        comparar(
            "j1",
            tmp_path,
            armazem=armazem,
            disparador=DisparadorFalso(armazem, falha=True),
            transporte=TransporteContado(),
            modelos=["flash-lite"],
            precos=PRECOS,
        )

    assert list(tmp_path.iterdir()) == []


def test_sem_decupagem_o_erro_e_claro(tmp_path: Path) -> None:
    armazem = _armazem()

    with pytest.raises(RuntimeError, match="Decupagem"):
        comparar(
            "outro",
            tmp_path,
            armazem=armazem,
            disparador=DisparadorFalso(armazem),
            transporte=TransporteContado(),
            modelos=["flash-lite"],
            precos=PRECOS,
        )


def test_precos_do_ambiente() -> None:
    assert precos_do_ambiente("a=0.1:0.4, b=1:4") == {
        "a": Preco(0.1, 0.4),
        "b": Preco(1.0, 4.0),
    }
    with pytest.raises(FaltaNoAmbiente):
        precos_do_ambiente("a=caro")


def test_main_sem_argumentos_ou_sem_ambiente_nao_toca_a_nuvem(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([], {}) == 2
    assert main(["j1", "pasta"], {}) == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err


class RespostaRest:
    def __init__(self, dados: dict[str, Any]) -> None:
        self._dados = dados

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._dados


class SessaoRest:
    def __init__(self, operacoes: list[dict[str, Any]]) -> None:
        self.operacoes = operacoes
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []

    def post(self, url: str, **kwargs: Any) -> RespostaRest:
        self.posts.append((url, kwargs["json"]))
        return RespostaRest(self.operacoes.pop(0))

    def get(self, url: str, **kwargs: Any) -> RespostaRest:
        self.gets.append(url)
        return RespostaRest(self.operacoes.pop(0))


def test_o_disparador_roda_o_job_com_o_destino_e_espera_a_operacao() -> None:
    sessao = SessaoRest(
        [{"name": "operations/1"}, {"name": "operations/1", "done": True}]
    )
    esperas: list[float] = []

    DisparadorDoCloudRun("p", "r", "j", sessao, esperas.append).rodar("j1", "d.json")

    url, corpo = sessao.posts[0]
    assert url.endswith("/projects/p/locations/r/jobs/j:run")
    env = corpo["overrides"]["containerOverrides"][0]["env"]
    assert {"name": "JOB_ID", "value": "j1"} in env
    assert {"name": "DESTINO_DO_RESULTADO", "value": "d.json"} in env
    assert sessao.gets == ["https://run.googleapis.com/v2/operations/1"]
    assert len(esperas) == 1


def test_o_disparador_levanta_quando_a_operacao_traz_erro() -> None:
    sessao = SessaoRest([{"name": "o", "done": True, "error": {"message": "sem GPU"}}])

    with pytest.raises(RuntimeError, match="sem GPU"):
        DisparadorDoCloudRun("p", "r", "j", sessao).rodar("j1", "d.json")


def test_o_alvo_do_makefile_le_os_nomes_do_terraform_e_passa_o_job() -> None:
    makefile = (RAIZ / "Makefile").read_text()
    alvo = makefile[makefile.index("\ncomparar-objetos:") :].split("\n\n")[0]

    assert "comparar-objetos" in makefile.splitlines()[0]
    for saida in ("bucket_decupagens", "regiao_gpu", "job_de_objetos_gpu"):
        assert f"output -raw {saida}" in alvo
    assert "python -m api.comparar_objetos" in alvo and '"$(JOB)"' in alvo
