"""O laço das janelas pela interface do módulo, com um transporte falso por janela.

O vídeo simulado tem 2h30 (30 janelas de 300 s, uma depois da outra). O modelo
falso conta os tempos do início do arquivo, em MM:SS com minutos acima de 59,
como a Vertex.
"""

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from api.analise import executar
from api.analise_por_janelas import analisar_video
from api.decupagem import Decupagem, Video
from api.gemini import AnaliseFalhou, Chamada, ErroHttp
from api.janelas import LIMITE_DE_TENTATIVAS
from api.jobs import Job, RepositorioEmMemoria
from api.progresso_das_janelas import JanelasEmMemoria
from api.tests.test_analise import DecupagensEmMemoria
from api.tests.test_gemini import BOA, TransporteFalso

DURACAO_MS = 150 * 60_000
VIDEO = Video(sha256="c" * 64, duracao_ms=DURACAO_MS)
URI = "gs://aceitos/j/proxy.mp4"


def mm_ss(ms: int) -> str:
    return f"{ms // 60_000:02d}:{ms // 1000 % 60:02d}"


def intervalo(inicio_ms: int, fim_ms: int) -> dict[str, str]:
    return {"inicio": mm_ss(inicio_ms), "fim": mm_ss(fim_ms)}


def resposta(
    *,
    falas: list[tuple[int, int, str]] = (),  # type: ignore[assignment]
    comerciais: list[tuple[int, int]] = (),  # type: ignore[assignment]
) -> str:
    return json.dumps(
        {
            "programa": {"resumo": "", "blocos": []},
            "pautas": [],
            "pessoas": [],
            "planos": [],
            "comerciais": [
                {
                    "marca": "Marca X",
                    "tipo": "intervalo",
                    "evidencias": ["logo"],
                    **intervalo(i, f),
                }
                for i, f in comerciais
            ],
            "transcricao": [
                {"locutor": "Ana", "texto": t, **intervalo(i, f)} for i, f, t in falas
            ],
            "textos_na_tela": [],
        }
    )


class ModeloFalso:
    """Um transporte que responde por janela, pelo trecho que a chamada pede."""

    def __init__(self, por_trecho: Callable[[int, int], str | Exception]) -> None:
        self.por_trecho = por_trecho
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        assert chamada.trecho_ms is not None
        r = self.por_trecho(*chamada.trecho_ms)
        if isinstance(r, Exception):
            raise r
        return r

    def trechos(self) -> list[tuple[int, int]]:
        return [c.trecho_ms for c in self.chamadas if c.trecho_ms]


def _fala_no_inicio_do_nucleo(inicio_ctx: int, fim_ctx: int) -> str:
    """Uma fala de 10 s no começo do núcleo (o contexto à esquerda é de 10 s)."""
    inicio = inicio_ctx + (10_000 if inicio_ctx else 0)
    return resposta(falas=[(inicio, inicio + 10_000, f"fala {inicio}")])


def _decupar(modelo: ModeloFalso, **kwargs: Any) -> Decupagem:
    return analisar_video(
        modelo, video_uri=URI, job_id="j", video=VIDEO, dormir=lambda _s: None, **kwargs
    )


def test_cada_janela_vai_ao_modelo_com_o_trecho_e_o_contexto() -> None:
    modelo = ModeloFalso(_fala_no_inicio_do_nucleo)

    _decupar(modelo)

    trechos = modelo.trechos()
    assert len(trechos) == 30
    assert trechos[0] == (0, 310_000)
    assert trechos[1] == (290_000, 610_000)
    assert trechos[-1] == (8_690_000, DURACAO_MS)


def test_tempos_depois_da_primeira_hora_saem_certos() -> None:
    falas = [(3_750_000, 3_760_000), (8_950_000, 8_960_000)]  # 62:30 e 149:10

    def por_trecho(inicio: int, fim: int) -> str:
        return resposta(
            falas=[
                (i, f, "depois de 1 h") for i, f in falas if inicio + 10_000 <= i < fim
            ]
        )

    d = _decupar(ModeloFalso(por_trecho))

    assert [(f.inicio_ms, f.fim_ms) for f in d.transcricao] == falas


def test_o_resultado_junta_as_janelas_em_ordem() -> None:
    d = _decupar(ModeloFalso(_fala_no_inicio_do_nucleo))

    inicios = [f.inicio_ms for f in d.transcricao]
    assert len(inicios) == 30
    assert inicios == sorted(inicios)
    assert d.video == VIDEO


def test_item_que_cruza_a_borda_de_duas_janelas_sai_uma_vez_so_emendado() -> None:
    def por_trecho(inicio: int, fim: int) -> str:
        if inicio == 0:  # janela 0 vê até 310 s
            return resposta(comerciais=[(295_000, 305_000)])
        if inicio == 290_000:  # janela 1 já vê o mesmo comercial, mais longo
            return resposta(comerciais=[(295_000, 308_000)])
        return resposta()

    d = _decupar(ModeloFalso(por_trecho))

    assert [(c.inicio_ms, c.fim_ms) for c in d.comerciais] == [(295_000, 308_000)]


def test_janela_que_falha_e_repetida_e_depois_passa() -> None:
    falhas = {"restantes": LIMITE_DE_TENTATIVAS - 1}

    def por_trecho(inicio: int, fim: int) -> str | Exception:
        if inicio == 290_000 and falhas["restantes"]:
            falhas["restantes"] -= 1
            return ErroHttp(400)
        return resposta()

    modelo = ModeloFalso(por_trecho)

    _decupar(modelo)

    assert modelo.trechos().count((290_000, 610_000)) == LIMITE_DE_TENTATIVAS


def test_janela_que_esgota_as_tentativas_derruba_a_analise() -> None:
    modelo = ModeloFalso(
        lambda inicio, fim: ErroHttp(400) if inicio == 290_000 else resposta()
    )

    with pytest.raises(AnaliseFalhou):
        _decupar(modelo)

    assert modelo.trechos().count((290_000, 610_000)) == LIMITE_DE_TENTATIVAS
    # As janelas seguintes nem começam.
    assert max(f for _, f in modelo.trechos()) == 610_000


def test_job_com_janela_falha_vai_a_analise_falhou_sem_decupagem() -> None:
    repositorio = RepositorioEmMemoria()
    decupagens = DecupagensEmMemoria("aceitos")
    modelo = ModeloFalso(
        lambda inicio, fim: ErroHttp(400) if inicio == 290_000 else resposta()
    )
    agora = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    repositorio.salvar(
        Job(
            id="j",
            nome="j.mp4",
            tamanho_bytes=10,
            sha256="c" * 64,
            duracao_s=DURACAO_MS / 1000,
            estado="analisando",
            criado_por="uid-1",
            criado_em=agora,
            atualizado_em=agora,
        )
    )

    resultado = executar("j", repositorio, decupagens, modelo, dormir=lambda _s: None)

    assert resultado == "falhou"

    job = repositorio.obter("j")
    assert job is not None
    assert (job.estado, job.codigo_falha) == ("falhou", "analise_falhou")
    assert decupagens.gravadas == {}


def test_video_curto_e_uma_janela_so_sobre_o_arquivo_inteiro() -> None:
    curto = Video(sha256="d" * 64, duracao_ms=60_000)
    transporte = TransporteFalso(BOA)

    d = analisar_video(transporte, video_uri=URI, job_id="j", video=curto)

    assert len(transporte.chamadas) == 1
    assert transporte.chamadas[0].trecho_ms is None
    assert d.video == curto


def test_com_escalonamento_a_janela_sorteada_e_decupada_de_novo() -> None:
    modelo = ModeloFalso(_fala_no_inicio_do_nucleo)

    _decupar(modelo, fracao_escalonada=1.0)

    assert len(modelo.chamadas) == 60


def test_sem_fracao_o_escalonamento_nao_roda_nem_por_duvida() -> None:
    def por_trecho(inicio: int, fim: int) -> str:
        r = json.loads(resposta())
        r["pessoas"] = [
            {
                "id": "pes01",
                "nome": "não identificado",
                "na_imagem": [
                    {
                        "evidencia": "rosto",
                        **intervalo(inicio + 10_000, inicio + 20_000),
                    }
                ],
                "citada_na_fala": [],
                "citada_no_texto": [],
            }
        ]
        return json.dumps(r)

    modelo = ModeloFalso(por_trecho)

    _decupar(modelo)

    assert len(modelo.chamadas) == 30


def test_sem_cortes_a_regra_de_tempos_nao_roda() -> None:
    d = _decupar(ModeloFalso(_fala_no_inicio_do_nucleo))

    assert all(c.inicio_modelo_ms is None for c in d.comerciais)


class ModeloContador(ModeloFalso):
    """Conta quantas chamadas estão em andamento ao mesmo tempo."""

    def __init__(self, por_trecho: Callable[[int, int], str | Exception]) -> None:
        super().__init__(por_trecho)
        self._trava = threading.Lock()
        self.em_andamento = 0
        self.maximo = 0

    def gerar(self, chamada: Chamada) -> str:
        with self._trava:
            self.em_andamento += 1
            self.maximo = max(self.maximo, self.em_andamento)
        try:
            time.sleep(0.03)
            return super().gerar(chamada)
        finally:
            with self._trava:
                self.em_andamento -= 1


@pytest.mark.parametrize("n", [1, 3, 8])
def test_nunca_mais_de_n_chamadas_ao_mesmo_tempo(n: int) -> None:
    modelo = ModeloContador(_fala_no_inicio_do_nucleo)

    d = _decupar(modelo, max_paralelas=n)

    assert modelo.maximo <= n
    # Com mais de uma janela por vez, elas de fato se sobrepõem.
    assert modelo.maximo == n
    assert len(modelo.chamadas) == 30
    assert [f.inicio_ms for f in d.transcricao] == sorted(
        f.inicio_ms for f in d.transcricao
    )


def test_em_paralelo_o_resultado_e_o_mesmo_do_serial() -> None:
    serial = _decupar(ModeloFalso(_fala_no_inicio_do_nucleo))
    paralelo = _decupar(ModeloFalso(_fala_no_inicio_do_nucleo), max_paralelas=6)

    assert paralelo == serial


def test_em_paralelo_a_janela_que_esgota_as_tentativas_derruba_a_analise() -> None:
    modelo = ModeloFalso(
        lambda inicio, fim: ErroHttp(400) if inicio == 290_000 else resposta()
    )

    with pytest.raises(AnaliseFalhou):
        _decupar(modelo, max_paralelas=4)

    assert modelo.trechos().count((290_000, 610_000)) == LIMITE_DE_TENTATIVAS


def test_em_paralelo_o_escalonamento_refaz_as_janelas_sorteadas() -> None:
    modelo = ModeloFalso(_fala_no_inicio_do_nucleo)

    _decupar(modelo, fracao_escalonada=1.0, max_paralelas=5)

    assert len(modelo.chamadas) == 60


def test_max_paralelas_menor_que_um_e_erro_de_quem_chamou() -> None:
    with pytest.raises(ValueError):
        _decupar(ModeloFalso(_fala_no_inicio_do_nucleo), max_paralelas=0)


def test_retomada_nao_chama_o_gemini_para_janelas_concluidas() -> None:
    janelas = JanelasEmMemoria()

    def cai_na_janela_20(inicio: int, fim: int) -> str:
        if inicio == 20 * 300_000 - 10_000:
            raise RuntimeError("o processo caiu")
        return _fala_no_inicio_do_nucleo(inicio, fim)

    with pytest.raises(RuntimeError):
        _decupar(ModeloFalso(cai_na_janela_20), janelas_do_job=janelas)
    gravadas = janelas.ler("j")
    concluidas = {i for i, g in gravadas.items() if g.situacao == "concluida"}
    assert concluidas == set(range(20))
    assert gravadas[20].situacao == "em_andamento"

    segunda = ModeloFalso(_fala_no_inicio_do_nucleo)
    d = _decupar(segunda, janelas_do_job=janelas)

    # Só as dez janelas que faltavam; a que caiu conta mais uma tentativa.
    assert [c.trecho_ms for c in segunda.chamadas] == [
        (j * 300_000 - 10_000, min(j * 300_000 + 310_000, DURACAO_MS))
        for j in range(20, 30)
    ]
    assert janelas.ler("j")[20].tentativas == 2
    assert len(d.transcricao) == 30


def test_retomada_junta_o_que_estava_gravado_com_o_que_rodou_agora() -> None:
    janelas = JanelasEmMemoria()
    _decupar(ModeloFalso(_fala_no_inicio_do_nucleo), janelas_do_job=janelas)

    modelo = ModeloFalso(_fala_no_inicio_do_nucleo)
    d = _decupar(modelo, janelas_do_job=janelas)

    assert modelo.chamadas == []
    assert len(d.transcricao) == 30


def test_retomada_nao_refaz_o_que_o_escalonamento_ja_refez() -> None:
    janelas = JanelasEmMemoria()
    _decupar(
        ModeloFalso(_fala_no_inicio_do_nucleo),
        janelas_do_job=janelas,
        fracao_escalonada=1.0,
    )

    modelo = ModeloFalso(_fala_no_inicio_do_nucleo)
    _decupar(modelo, janelas_do_job=janelas, fracao_escalonada=1.0)

    assert modelo.chamadas == []


def test_janela_que_esgotou_as_tentativas_nao_gasta_mais_chamadas_ao_retomar() -> None:
    janelas = JanelasEmMemoria()
    modelo = ModeloFalso(
        lambda inicio, fim: ErroHttp(400) if inicio == 290_000 else resposta()
    )
    with pytest.raises(AnaliseFalhou):
        _decupar(modelo, janelas_do_job=janelas)

    gravada = janelas.ler("j")[1]
    assert (gravada.situacao, gravada.tentativas) == ("falhou", LIMITE_DE_TENTATIVAS)
    outra = ModeloFalso(_fala_no_inicio_do_nucleo)
    with pytest.raises(AnaliseFalhou):
        _decupar(outra, janelas_do_job=janelas)
    assert (290_000, 610_000) not in outra.trechos()
