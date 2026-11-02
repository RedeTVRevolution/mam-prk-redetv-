"""Job de objetos (Florence-2): lê a Decupagem e os quadros, grava o resultado bruto."""

import io
from typing import Any

import pytest
from PIL import Image

from api import objetos_job, teste_dos_jobs
from api.decupagem import Decupagem
from api.florence import (
    NOME_DO_MODELO,
    ObjetoDetectado,
    ObjetosDaDecupagem,
    RegiaoLegendada,
)
from api.leitura_da_tela import Caixa
from api.nuvem import ObjetosStorage, objeto_do_resultado_dos_objetos
from api.objetos_job import ObjetosEmMemoria, executar


def _jpeg(largura: int, altura: int) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (largura, altura)).save(saida, format="JPEG")
    return saida.getvalue()


def _decupagem(quadros_dos_planos: list[list[str]]) -> Decupagem:
    planos = [
        {
            "id": f"pla{i}",
            "inicio_ms": i * 1000,
            "fim_ms": (i + 1) * 1000,
            "ambiente": "estúdio",
            "plano_limpo": True,
            "quadros": quadros,
        }
        for i, quadros in enumerate(quadros_dos_planos)
    ]
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.3",
            "video": {"sha256": "a" * 64, "duracao_ms": 6_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": [],
            "planos": planos,
            "comerciais": [],
            "transcricao": [],
        }
    )


class DetectorFalso:
    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.tamanhos: list[tuple[int, int]] = []

    def detectar(
        self, imagem: Image.Image
    ) -> tuple[list[ObjetoDetectado], list[RegiaoLegendada]]:
        if self.erro:
            raise self.erro
        self.tamanhos.append(imagem.size)
        caixa = Caixa(x=0.1, y=0.1, largura=0.5, altura=0.5)
        return (
            [ObjetoDetectado(rotulo=f"coisa {len(self.tamanhos)}", caixa=caixa)],
            [RegiaoLegendada(legenda="uma coisa", caixa=caixa)],
        )


def _armazenamento() -> ObjetosEmMemoria:
    armazenamento = ObjetosEmMemoria()
    armazenamento.decupagens["j1"] = _decupagem(
        [["quadros/plano-0.jpg"], [], ["quadros/plano-2a.jpg", "quadros/plano-2b.jpg"]]
    )
    for caminho, tamanho in {
        "quadros/plano-0.jpg": (40, 20),
        "quadros/plano-2a.jpg": (80, 40),
        "quadros/plano-2b.jpg": (80, 40),
    }.items():
        armazenamento.quadros[("j1", caminho)] = _jpeg(*tamanho)
    return armazenamento


def test_grava_um_quadro_por_jpeg_com_o_indice_do_plano() -> None:
    armazenamento = _armazenamento()
    detector = DetectorFalso()

    executar("j1", armazenamento, detector)

    resultado = armazenamento.resultados[("j1", None)]
    assert resultado.modelo == NOME_DO_MODELO
    assert [(q.plano, q.caminho, q.largura, q.altura) for q in resultado.quadros] == [
        (0, "quadros/plano-0.jpg", 40, 20),
        (2, "quadros/plano-2a.jpg", 80, 40),
        (2, "quadros/plano-2b.jpg", 80, 40),
    ]
    assert resultado.quadros[0].objetos[0].rotulo == "coisa 1"
    assert resultado.quadros[0].regioes[0].legenda == "uma coisa"
    assert detector.tamanhos == [(40, 20), (80, 40), (80, 40)]


def test_o_destino_alternativo_vem_da_variavel() -> None:
    armazenamento = _armazenamento()
    executar("j1", armazenamento, DetectorFalso(), destino="teste/saida.json")
    assert ("j1", "teste/saida.json") in armazenamento.resultados


def test_sem_decupagem_o_erro_diz_o_que_falta() -> None:
    with pytest.raises(RuntimeError, match="Decupagem"):
        executar("j9", ObjetosEmMemoria(), DetectorFalso())


def test_decupagem_sem_quadros_e_erro() -> None:
    armazenamento = ObjetosEmMemoria()
    armazenamento.decupagens["j1"] = _decupagem([[], []])
    with pytest.raises(RuntimeError, match="quadros"):
        executar("j1", armazenamento, DetectorFalso())
    assert armazenamento.resultados == {}


def test_erro_do_detector_sobe_sem_gravar() -> None:
    armazenamento = _armazenamento()
    with pytest.raises(ValueError):
        executar("j1", armazenamento, DetectorFalso(ValueError("falhou")))
    assert armazenamento.resultados == {}


def test_o_resultado_guardado_e_lido_de_volta() -> None:
    armazenamento = _armazenamento()
    executar("j1", armazenamento, DetectorFalso())
    resultado = armazenamento.resultados[("j1", None)]
    assert (
        ObjetosDaDecupagem.model_validate_json(resultado.model_dump_json()) == resultado
    )


def test_o_objeto_do_resultado_fica_na_pasta_do_job() -> None:
    assert objeto_do_resultado_dos_objetos("j1") == "j1/objetos/florence.json"


class _Blob:
    def __init__(self, guardado: dict[str, Any], nome: str) -> None:
        self.guardado, self.nome = guardado, nome

    def upload_from_string(self, conteudo: str, content_type: str) -> None:
        self.guardado[self.nome] = (conteudo, content_type)

    def download_as_bytes(self) -> bytes:
        return bytes(self.guardado[self.nome])


class _Bucket:
    def __init__(self, nome: str, guardado: dict[str, Any]) -> None:
        self.nome, self.guardado = nome, guardado

    def blob(self, nome: str) -> _Blob:
        return _Blob(self.guardado, f"{self.nome}/{nome}")


class _Cliente:
    def __init__(self) -> None:
        self.guardado: dict[str, Any] = {}

    def bucket(self, nome: str) -> _Bucket:
        return _Bucket(nome, self.guardado)


def test_o_storage_grava_so_no_bucket_das_decupagens() -> None:
    cliente = _Cliente()
    armazenamento = ObjetosStorage(cliente, "decupagens-x")
    resultado = ObjetosDaDecupagem(modelo="m", quadros=[])

    armazenamento.gravar_resultado("j1", resultado, None)
    armazenamento.gravar_resultado("j1", resultado, "alt.json")

    assert set(cliente.guardado) == {
        "decupagens-x/j1/objetos/florence.json",
        "decupagens-x/alt.json",
    }
    conteudo, tipo = cliente.guardado["decupagens-x/alt.json"]
    assert tipo == "application/json"
    assert ObjetosDaDecupagem.model_validate_json(conteudo) == resultado


def test_main_em_modo_de_teste_nao_toca_a_nuvem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODO_TESTE", "1")
    for variavel in ("GCP_PROJECT_ID", "JOB_ID", "BUCKET_DECUPAGENS"):
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setattr(teste_dos_jobs, "testar_objetos", lambda: 21)

    with pytest.raises(SystemExit) as saida:
        objetos_job.main()

    assert saida.value.code == 21
