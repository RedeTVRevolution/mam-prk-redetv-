"""Job de objetos (Florence-2): lê a Decupagem e os quadros, grava o resultado bruto."""

import io
from threading import Condition, get_ident
from typing import Any

import pytest
from google.api_core.exceptions import NotFound
from PIL import Image

from api import objetos_job, teste_dos_jobs
from api.decupagem import Decupagem
from api.florence import (
    MODELOS,
    Configuracao,
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
        self.lotes: list[int] = []

    def detectar_lote(
        self, imagens: list[Image.Image]
    ) -> list[tuple[list[ObjetoDetectado], list[RegiaoLegendada]]]:
        if self.erro:
            raise self.erro
        self.lotes.append(len(imagens))
        resultados = []
        for imagem in imagens:
            self.tamanhos.append(imagem.size)
            caixa = Caixa(x=0.1, y=0.1, largura=0.5, altura=0.5)
            resultados.append(
                (
                    [
                        ObjetoDetectado(
                            rotulo=f"coisa {len(self.tamanhos)}", caixa=caixa
                        )
                    ],
                    [RegiaoLegendada(legenda="uma coisa", caixa=caixa)],
                )
            )
        return resultados


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


def _imagem_com(quadrados: list[tuple[int, int, int, int]], fundo: int = 0) -> bytes:
    imagem = Image.new("RGB", (160, 160), (fundo,) * 3)
    for x0, y0, x1, y1 in quadrados:
        imagem.paste((255, 255, 255), (x0, y0, x1, y1))
    saida = io.BytesIO()
    imagem.save(saida, format="PNG")
    return saida.getvalue()


def test_grava_um_quadro_por_jpeg_com_o_indice_do_plano() -> None:
    armazenamento = _armazenamento()
    detector = DetectorFalso()

    executar("j1", armazenamento, detector)

    resultado = armazenamento.resultados[("j1", None)]
    assert resultado.modelo == MODELOS["large"]
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


def test_com_a_configuracao_padrao_o_lote_e_de_um_quadro() -> None:
    detector = DetectorFalso()
    executar("j1", _armazenamento(), detector, configuracao=Configuracao())
    assert detector.lotes == [1, 1, 1]


def test_o_lote_junta_quadros_de_planos_diferentes_e_mantem_a_ordem() -> None:
    padrao, em_lote = _armazenamento(), _armazenamento()
    executar("j1", padrao, DetectorFalso())
    detector = DetectorFalso()
    executar("j1", em_lote, detector, configuracao=Configuracao(lote=2))

    assert detector.lotes == [2, 1]
    quadros = em_lote.resultados[("j1", None)].quadros
    assert [q.caminho for q in quadros] == [
        q.caminho for q in padrao.resultados[("j1", None)].quadros
    ]
    assert [q.objetos[0].rotulo for q in quadros] == ["coisa 1", "coisa 2", "coisa 3"]
    assert em_lote.resultados == padrao.resultados


def test_le_quadros_durante_a_inferencia_com_so_dois_lotes_a_frente() -> None:
    condicao = Condition()
    lidos: list[str] = []
    feitos = 0
    principal = get_ident()

    class Armazem(ObjetosEmMemoria):
        def ler_quadro(self, job_id: str, caminho: str) -> bytes:
            assert get_ident() != principal
            with condicao:
                lidos.append(caminho)
                assert len(lidos) <= feitos + 6  # lote atual (2) e dois à frente (4)
                condicao.notify_all()
            return _jpeg(int(caminho.removesuffix(".jpg")) + 10, 10)

    class Detector(DetectorFalso):
        def detectar_lote(self, imagens: list[Image.Image]) -> Any:
            nonlocal feitos
            with condicao:
                assert condicao.wait_for(
                    lambda: len(lidos) == min(feitos + 6, 12), timeout=2
                )
                feitos += len(imagens)
            return super().detectar_lote(imagens)

    armazem = Armazem()
    caminhos = [f"{i}.jpg" for i in range(12)]
    armazem.decupagens["j1"] = _decupagem([caminhos])
    detector = Detector()
    executar("j1", armazem, detector, configuracao=Configuracao(lote=2))

    quadros = armazem.resultados[("j1", None)].quadros
    assert lidos == caminhos == [q.caminho for q in quadros]
    assert detector.tamanhos == [(i + 10, 10) for i in range(12)]
    assert [q.objetos[0].rotulo for q in quadros] == [
        f"coisa {i}" for i in range(1, 13)
    ]


@pytest.mark.parametrize("lote", [1, 2])
@pytest.mark.parametrize("caminho", ["quadros/plano-2a.jpg", "quadros/plano-2b.jpg"])
def test_erro_na_leitura_antecipada_propaga_sem_gravar(lote: int, caminho: str) -> None:
    armazem = _armazenamento()
    del armazem.quadros[("j1", caminho)]

    with pytest.raises(KeyError, match=caminho):
        executar("j1", armazem, DetectorFalso(), configuracao=Configuracao(lote=lote))

    assert armazem.resultados == {}


def test_o_resultado_sem_destino_nao_leva_segundos() -> None:
    armazenamento = _armazenamento()
    executar("j1", armazenamento, DetectorFalso())
    assert armazenamento.resultados[("j1", None)].segundos is None


def test_no_destino_alternativo_o_resultado_leva_os_segundos() -> None:
    armazenamento = _armazenamento()
    tempos = iter([10.0, 14.5])
    executar(
        "j1",
        armazenamento,
        DetectorFalso(),
        destino="m.json",
        relogio=lambda: next(tempos),
    )
    assert armazenamento.resultados[("j1", "m.json")].segundos == 4.5


def _com_repetidos() -> ObjetosEmMemoria:
    armazenamento = ObjetosEmMemoria()
    armazenamento.decupagens["j1"] = _decupagem(
        [["a.png", "b.png", "c.png"], ["d.png"]]
    )
    armazenamento.quadros[("j1", "a.png")] = _imagem_com([(0, 0, 80, 160)])
    armazenamento.quadros[("j1", "b.png")] = _imagem_com(
        [(0, 0, 80, 160)]
    )  # igual a "a"
    armazenamento.quadros[("j1", "c.png")] = _imagem_com([(0, 0, 160, 80)])  # outro
    armazenamento.quadros[("j1", "d.png")] = _imagem_com(
        [(0, 0, 80, 160)]
    )  # outro plano
    return armazenamento


def test_quadro_repetido_do_mesmo_plano_reaproveita_o_resultado() -> None:
    armazenamento, detector = _com_repetidos(), DetectorFalso()
    executar(
        "j1", armazenamento, detector, configuracao=Configuracao(pular_repetidos=4)
    )

    quadros = armazenamento.resultados[("j1", None)].quadros
    assert detector.lotes == [1, 1, 1]  # "b" não foi para o modelo
    assert [q.caminho for q in quadros] == ["a.png", "b.png", "c.png", "d.png"]
    assert quadros[1].objetos == quadros[0].objetos
    assert quadros[1].caminho == "b.png"
    assert quadros[3].objetos != quadros[0].objetos  # outro plano: não reaproveita


def test_sem_pular_repetidos_todo_quadro_vai_para_o_modelo() -> None:
    detector = DetectorFalso()
    executar("j1", _com_repetidos(), detector)
    assert sum(detector.lotes) == 4


def test_repetido_dentro_de_um_lote_aberto_tambem_e_reaproveitado() -> None:
    armazenamento, detector = _com_repetidos(), DetectorFalso()
    executar(
        "j1",
        armazenamento,
        detector,
        configuracao=Configuracao(pular_repetidos=4, lote=8),
    )
    assert detector.lotes == [3]
    quadros = armazenamento.resultados[("j1", None)].quadros
    assert quadros[1].objetos == quadros[0].objetos


def test_o_log_de_progresso_sai_a_cada_n_quadros_e_no_fim(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="api.objetos_job")
    executar(
        "j1", _armazenamento(), DetectorFalso(), configuracao=Configuracao(log_a_cada=2)
    )
    assert [r.getMessage() for r in caplog.records] == [
        "Quadros: 2/3",
        "Quadros: 3/3",
    ]


def test_com_lote_o_progresso_so_conta_o_que_saiu_do_modelo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="api.objetos_job")
    executar(
        "j1",
        _armazenamento(),
        DetectorFalso(),
        configuracao=Configuracao(log_a_cada=1, lote=2),
    )
    assert [r.getMessage() for r in caplog.records] == [
        "Quadros: 2/3",
        "Quadros: 3/3",
    ]


def test_sem_segundos_o_json_gravado_e_o_de_antes() -> None:
    cliente = _Cliente()
    armazenamento = ObjetosStorage(cliente, "decupagens-x")
    armazenamento.gravar_resultado(
        "j1", ObjetosDaDecupagem(modelo="m", quadros=[]), None
    )
    armazenamento.gravar_resultado(
        "j1", ObjetosDaDecupagem(modelo="m", quadros=[], segundos=1.5), "alt.json"
    )
    assert (
        "segundos" not in cliente.guardado["decupagens-x/j1/objetos/florence.json"][0]
    )
    assert '"segundos":1.5' in cliente.guardado["decupagens-x/alt.json"][0]


def test_o_storage_grava_texto_solto_no_bucket_das_decupagens() -> None:
    cliente = _Cliente()
    ObjetosStorage(cliente, "decupagens-x").gravar_texto(
        "j1/objetos/medicao/a.json", "{}"
    )
    assert cliente.guardado == {
        "decupagens-x/j1/objetos/medicao/a.json": ("{}", "application/json")
    }


def test_o_storage_le_a_base_em_utf8_e_so_ausencia_vira_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _Cliente()
    caminho = "j1/objetos/medicao/hoje/inventario.json"
    cliente.guardado[f"decupagens-x/{caminho}"] = '{"nome":"sofá"}'.encode()
    armazem = ObjetosStorage(cliente, "decupagens-x")
    assert armazem.ler_texto(caminho) == '{"nome":"sofá"}'

    def falhar(self: _Blob) -> bytes:
        raise NotFound("não há base")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(_Blob, "download_as_bytes", falhar)
    assert armazem.ler_texto(caminho) is None

    def indisponivel(self: _Blob) -> bytes:
        raise OSError("Storage fora")

    monkeypatch.setattr(_Blob, "download_as_bytes", indisponivel)
    with pytest.raises(OSError, match="Storage fora"):
        armazem.ler_texto(caminho)


def test_grava_o_nome_e_a_revisao_do_modelo_base_que_rodou() -> None:
    armazenamento = _armazenamento()
    executar(
        "j1", armazenamento, DetectorFalso(), configuracao=Configuracao(modelo="base")
    )
    assert armazenamento.resultados[("j1", None)].modelo == (
        "florence-community/Florence-2-base@00921df66db728a9ceb750f5eca43e5c203a2051"
    )
