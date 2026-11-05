"""Medição das variações do Florence-2 (#329), sem nuvem."""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from api.comparar_objetos import DisparadorDoCloudRun
from api.decupagem import CaixaDoQuadro, Decupagem, ObjetoDoInventario
from api.florence import ObjetosDaDecupagem, QuadroDetectado
from api.gemini import Chamada
from api.inventario import Inventarios
from api.medir_florence import (
    BASE,
    VARIACOES,
    avaliar,
    main,
    medir,
    objeto_da_medicao,
    tabela,
)
from api.tests.test_inventario import decupagem as decupagem_com_planos
from api.tests.test_inventario_job import CONVERTIDO


class TransporteFalso:
    def gerar(self, chamada: Chamada) -> str:
        return CONVERTIDO


def _obj(nome: str, categoria: str = "movel", destaque: int = 1) -> ObjetoDoInventario:
    return ObjetoDoInventario.model_validate(
        {
            "nome": nome,
            "categoria": categoria,
            "caixas": [
                CaixaDoQuadro(quadro="q/a.jpg", x=0.1, y=0.1, largura=0.2, altura=0.2)
            ],
            "destaque": destaque,
        }
    )


def _hoje() -> Inventarios:
    return {
        0: [
            _obj("cadeira", "movel", 3),
            *(_obj(f"móvel {i}", "movel") for i in range(10)),
            _obj("camisa", "roupa"),
            _obj("bota", "calcado"),
        ],
        1: [_obj("carro", "veiculo", 3)],
    }


# --- critério de qualidade ---


def test_inventario_igual_passa() -> None:
    c = avaliar(_hoje(), _hoje())
    assert c.passa and c.cena == c.cena_hoje == 12 and c.destaque_3_perdidos == []


def test_perder_um_de_dez_objetos_de_cena_ainda_passa() -> None:
    variacao = _hoje()
    variacao[0] = [o for o in variacao[0] if o.nome != "móvel 0"]
    c = avaliar(_hoje(), variacao)
    assert (c.cena, c.cena_hoje) == (11, 12) and c.passa


def test_perder_dois_de_dez_objetos_de_cena_reprova() -> None:
    variacao = _hoje()
    variacao[0] = [o for o in variacao[0] if o.nome not in ("móvel 0", "móvel 1")]
    c = avaliar(_hoje(), variacao)
    assert (c.cena, c.cena_hoje) == (10, 12) and not c.passa


def test_categoria_que_cai_reprova_mesmo_com_a_cena_inteira_passando() -> None:
    hoje = _hoje()
    hoje[1] += [_obj(f"carro {i}", "veiculo") for i in range(1, 10)]  # 10 veículos
    variacao = {
        0: hoje[0],
        1: [o for o in hoje[1] if o.nome not in ("carro 1", "carro 2")],  # 8 de 10
    }
    c = avaliar(hoje, variacao)
    assert c.fracao_da_cena >= 0.9  # 18 de 20
    assert (c.pior_categoria, c.pior_fracao) == ("veiculo", 0.8)
    assert not c.passa


def test_roupa_fora_da_cena_mas_a_categoria_conta_no_pior() -> None:
    variacao = _hoje()
    variacao[0] = [o for o in variacao[0] if o.categoria != "roupa"]
    c = avaliar(_hoje(), variacao)
    assert c.cena == c.cena_hoje  # a roupa não entra na soma de cena
    assert c.pior_categoria == "roupa" and c.pior_fracao == 0 and not c.passa


def test_destaque_3_que_some_reprova_e_diz_qual() -> None:
    variacao = _hoje()
    variacao[1] = []
    variacao[0] += [_obj(f"extra {i}", "movel") for i in range(3)]  # a soma compensa
    c = avaliar(_hoje(), variacao)
    assert c.destaque_3_perdidos == ["plano 1: carro (veiculo)"]
    assert not c.passa


def test_destaque_3_que_so_perdeu_o_destaque_nao_some() -> None:
    variacao = _hoje()
    variacao[1] = [_obj("Carro", "veiculo", 1)]  # sem acento/caixa é o mesmo nome
    assert avaliar(_hoje(), variacao).destaque_3_perdidos == []


# --- medição ---


def _bruto(segundos: float | None) -> ObjetosDaDecupagem:
    quadro = QuadroDetectado(
        plano=0, caminho="q/a.jpg", largura=10, altura=10, objetos=[], regioes=[]
    )
    return ObjetosDaDecupagem(modelo="m", quadros=[quadro] * 4, segundos=segundos)


class ArmazemFalso:
    def __init__(self) -> None:
        self.decupagem: Decupagem | None = decupagem_com_planos(["q/a.jpg"])
        self.resultados: dict[tuple[str, str | None], ObjetosDaDecupagem] = {}
        self.textos: dict[str, str] = {}

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return self.decupagem

    def ler_resultado(
        self, job_id: str, destino: str | None = None
    ) -> ObjetosDaDecupagem | None:
        return self.resultados.get((job_id, destino))

    def gravar_texto(self, objeto: str, conteudo: str) -> None:
        self.textos[objeto] = conteudo


class DisparadorFalso:
    """Cada variação leva um tempo: 8 s a base, 2 s as outras (0,5 s por quadro)."""

    def __init__(self, armazem: ArmazemFalso, falham: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.armazem, self.falham = armazem, falham
        self.pedidos: list[tuple[str, Mapping[str, str] | None]] = []

    def rodar(
        self, job_id: str, destino: str, ambiente: Mapping[str, str] | None = None
    ) -> None:
        self.pedidos.append((destino, ambiente))
        if any(f"/{n}/" in destino for n in self.falham):
            raise RuntimeError("sem memória na GPU")
        segundos = 8.0 if ambiente == {} else 2.0
        self.armazem.resultados[(job_id, destino)] = _bruto(segundos)


def _medir(
    armazem: ArmazemFalso, disparador: DisparadorFalso, nomes: list[str]
) -> list[Any]:
    return medir(
        "j1",
        armazem=armazem,
        disparador=disparador,
        transporte=TransporteFalso(),
        modelo="gemini-x",
        variacoes={n: VARIACOES[n] for n in nomes},
        dormir=lambda _: None,
    )


def test_roda_a_base_primeiro_mesmo_sem_pedir_e_passa_as_variaveis_de_cada_uma() -> (
    None
):
    armazem = ArmazemFalso()
    disparador = DisparadorFalso(armazem)

    resultados = _medir(armazem, disparador, ["guloso", "lote8"])

    assert [r.variacao for r in resultados] == [BASE, "guloso", "lote8"]
    assert [a for _, a in disparador.pedidos] == [
        {},
        {"FLORENCE_FEIXES": "1"},
        {"FLORENCE_LOTE": "8"},
    ]


def test_tempo_por_quadro_e_criterio_contra_a_base() -> None:
    armazem = ArmazemFalso()
    resultados = _medir(armazem, DisparadorFalso(armazem), ["guloso"])

    base, guloso = resultados
    assert base.medida.segundos_por_quadro == 2.0 and base.criterio is None
    assert guloso.medida.segundos_por_quadro == 0.5
    assert guloso.criterio.passa  # o transporte falso devolve o mesmo inventário


def test_grava_cada_variacao_so_na_pasta_da_medicao_sem_tocar_no_job() -> None:
    armazem = ArmazemFalso()
    disparador = DisparadorFalso(armazem)
    _medir(armazem, disparador, ["guloso"])

    assert set(armazem.textos) == {
        objeto_da_medicao("j1", n, a)
        for n in (BASE, "guloso")
        for a in ("inventario.json", "medida.json")
    }
    todos = [*armazem.textos, *(d for d, _ in disparador.pedidos)]
    assert all(o.startswith("j1/objetos/medicao/") for o in todos)
    assert "j1/objetos/florence.json" not in todos
    medida = json.loads(armazem.textos["j1/objetos/medicao/guloso/medida.json"])
    assert medida["segundos_por_quadro"] == 0.5
    assert medida["criterio"]["passa"] is True
    assert "0" in json.loads(
        armazem.textos["j1/objetos/medicao/guloso/inventario.json"]
    )


def test_variacao_que_falha_vira_erro_e_as_outras_seguem() -> None:
    armazem = ArmazemFalso()
    resultados = _medir(
        armazem, DisparadorFalso(armazem, falham={"lote16"}), ["lote16", "guloso"]
    )

    assert [r.erro for r in resultados] == [None, "sem memória na GPU", None]
    assert "lote16" not in "".join(armazem.textos)
    saida = tabela(resultados)
    assert "lote16" in saida and "falhou: sem memória na GPU" in saida


def test_job_que_nao_gravou_os_segundos_e_erro_da_variacao() -> None:
    armazem = ArmazemFalso()

    class SemSegundos(DisparadorFalso):
        def rodar(self, job_id: str, destino: str, ambiente: Any = None) -> None:
            armazem.resultados[(job_id, destino)] = _bruto(None)

    (base,) = _medir(armazem, SemSegundos(armazem), [])
    assert base.erro and "segundos" in base.erro


def test_sem_decupagem_e_erro() -> None:
    armazem = ArmazemFalso()
    armazem.decupagem = None
    with pytest.raises(RuntimeError, match="Decupagem"):
        _medir(armazem, DisparadorFalso(armazem), [])


def test_a_tabela_mostra_tempo_criterio_e_a_mais_rapida_que_passa() -> None:
    armazem = ArmazemFalso()
    saida = tabela(_medir(armazem, DisparadorFalso(armazem), ["guloso"]))

    assert "hoje" in saida and "guloso" in saida
    assert "4.0x" in saida and "passa" in saida
    assert "A mais rápida que passa no critério: guloso" in saida


def test_a_tabela_aponta_o_reprovado() -> None:
    armazem = ArmazemFalso()
    resultados = _medir(armazem, DisparadorFalso(armazem), ["guloso"])
    resultados[1].criterio = avaliar(_hoje(), {0: [], 1: []})
    saida = tabela(resultados)
    assert "reprova" in saida and "plano 1: carro (veiculo)" in saida
    assert "A mais rápida que passa no critério: hoje" in saida


def test_toda_variacao_so_usa_variaveis_florence() -> None:
    assert VARIACOES[BASE] == {}
    assert all(v.startswith("FLORENCE_") for a in VARIACOES.values() for v in a)


def test_o_disparador_soma_as_variaveis_da_variacao_ao_job() -> None:
    enviados: list[Any] = []

    class Resposta:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, Any]:
            return {"done": True, "name": "op"}

    class Sessao:
        def post(self, url: str, **kwargs: Any) -> Resposta:
            enviados.append(kwargs["json"])
            return Resposta()

    DisparadorDoCloudRun("p", "r", "job", Sessao()).rodar(  # type: ignore[arg-type]
        "j1", "d.json", {"FLORENCE_LOTE": "8"}
    )
    env = enviados[0]["overrides"]["containerOverrides"][0]["env"]
    assert {"name": "FLORENCE_LOTE", "value": "8"} in env
    assert {"name": "DESTINO_DO_RESULTADO", "value": "d.json"} in env


def test_main_rejeita_variacao_desconhecida_e_ambiente_incompleto(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert main(["j1", "inventada"], {}) == 2
    assert "inventada" in capsys.readouterr().err
    assert main(["j1"], {}) == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err
