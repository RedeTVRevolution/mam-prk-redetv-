import json
from typing import Any

import pytest
import requests

from api.decupagem import Video
from api.gemini import (
    AnaliseFalhou,
    Chamada,
    ErroHttp,
    TransporteVertex,
    analisar,
)
from api.tests.test_decupagem import DURACAO_MS, decupagem_valida

JOB = "job-123"
VIDEO = "gs://quarentena/proxy.mp4"
VIDEO_CONFIAVEL = Video(sha256="b" * 64, duracao_ms=DURACAO_MS)


class TransporteFalso:
    """Devolve, em ordem, textos ou levanta as exceções da fila."""

    def __init__(self, *respostas: str | Exception) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Relogio:
    def __init__(self) -> None:
        self.esperas: list[float] = []

    def dormir(self, s: float) -> None:
        self.esperas.append(s)


def _rodar(transporte: TransporteFalso, relogio: Relogio | None = None) -> Any:
    relogio = relogio or Relogio()
    return analisar(
        transporte,
        video_uri=VIDEO,
        job_id=JOB,
        video=VIDEO_CONFIAVEL,
        dormir=relogio.dormir,
        sortear=lambda teto: teto,  # pior caso: jitter no teto
    )


def resposta_do_modelo() -> dict[str, Any]:
    """O modelo não devolve o bloco `video`: ele vem da quarentena."""
    dados = decupagem_valida()
    del dados["video"]
    return dados


BOA = json.dumps(resposta_do_modelo())


def test_devolve_decupagem_valida() -> None:
    t = TransporteFalso(BOA)
    d = _rodar(t)
    assert d.programa.resumo == "Jornal da noite"
    assert len(t.chamadas) == 1


def test_chamada_leva_job_como_rotulo_e_nenhuma_ferramenta() -> None:
    t = TransporteFalso(BOA)
    _rodar(t)
    c = t.chamadas[0]
    assert c.rotulos == {"job_id": JOB}
    assert c.ferramentas == ()
    assert c.video_uri == VIDEO
    assert c.esquema["additionalProperties"] is False
    assert "video" not in c.esquema["properties"]


def test_bloco_video_vem_da_quarentena_e_nao_do_modelo() -> None:
    d = _rodar(TransporteFalso(BOA))
    assert d.video == VIDEO_CONFIAVEL


def test_resposta_com_bloco_video_e_refeita() -> None:
    t = TransporteFalso(json.dumps(decupagem_valida()), BOA)
    _rodar(t)
    assert len(t.chamadas) == 2


def test_resposta_fora_do_esquema_e_refeita_ate_2_vezes() -> None:
    t = TransporteFalso("não é json", '{"x": 1}', BOA)
    d = _rodar(t)
    assert d.video.duracao_ms == DURACAO_MS
    assert len(t.chamadas) == 3


def test_terceira_resposta_ruim_vira_analise_falhou() -> None:
    t = TransporteFalso("lixo", "lixo", "lixo", BOA)
    with pytest.raises(AnaliseFalhou) as e:
        _rodar(t)
    assert e.value.codigo == "analise_falhou"
    assert len(t.chamadas) == 3


def test_tempo_fora_da_duracao_conta_como_resposta_invalida() -> None:
    ruim = resposta_do_modelo()
    ruim["planos"][0]["fim_ms"] = DURACAO_MS + 1
    t = TransporteFalso(json.dumps(ruim), BOA)
    _rodar(t)
    assert len(t.chamadas) == 2


@pytest.mark.parametrize("status", [429, 500, 503])
def test_429_e_5xx_tentam_de_novo_com_backoff_exponencial(status: int) -> None:
    relogio = Relogio()
    t = TransporteFalso(ErroHttp(status), ErroHttp(status), ErroHttp(status), BOA)
    _rodar(t, relogio)
    assert len(t.chamadas) == 4
    assert relogio.esperas == [1.0, 2.0, 4.0]


def test_jitter_total_sorteia_entre_zero_e_o_teto() -> None:
    tetos: list[float] = []

    def sortear(teto: float) -> float:
        tetos.append(teto)
        return 0.0

    t = TransporteFalso(ErroHttp(429), ErroHttp(429), BOA)
    analisar(
        t,
        video_uri=VIDEO,
        job_id=JOB,
        video=VIDEO_CONFIAVEL,
        dormir=lambda s: None,
        sortear=sortear,
    )
    assert tetos == [1.0, 2.0]


def test_cinco_novas_tentativas_e_depois_analise_falhou() -> None:
    t = TransporteFalso(*[ErroHttp(503)] * 6, BOA)
    with pytest.raises(AnaliseFalhou) as e:
        _rodar(t)
    assert e.value.codigo == "analise_falhou"
    assert len(t.chamadas) == 6  # 1 chamada + 5 novas


def test_erro_4xx_diferente_de_429_nao_tenta_de_novo() -> None:
    t = TransporteFalso(ErroHttp(400), BOA)
    with pytest.raises(AnaliseFalhou):
        _rodar(t)
    assert len(t.chamadas) == 1


def test_os_dois_orcamentos_de_tentativas_sao_independentes() -> None:
    t = TransporteFalso(ErroHttp(429), "lixo", ErroHttp(500), "lixo", BOA)
    _rodar(t)
    assert len(t.chamadas) == 5


class SessaoFalsa:
    """Imita `AuthorizedSession.post`: devolve respostas ou levanta, em ordem."""

    def __init__(self, *respostas: "RespostaFalsa | Exception") -> None:
        self.respostas = list(respostas)
        self.pedidos: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> "RespostaFalsa":
        self.pedidos.append({"url": url, **kwargs})
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class RespostaFalsa:
    def __init__(self, status: int, corpo: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._corpo = corpo or {}

    def json(self) -> dict[str, Any]:
        return self._corpo


def _chamada() -> Chamada:
    return Chamada(
        modelo="gemini-3.5-flash-lite",
        video_uri=VIDEO,
        esquema={"type": "OBJECT", "additionalProperties": False},
        rotulos={"job_id": JOB},
    )


def _ok(texto: str) -> RespostaFalsa:
    return RespostaFalsa(
        200, {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
    )


def test_transporte_vertex_monta_a_chamada_global_com_video_esquema_e_rotulo() -> None:
    sessao = SessaoFalsa(_ok("{}"))

    texto = TransporteVertex("projeto-x", sessao).gerar(_chamada())

    assert texto == "{}"
    pedido = sessao.pedidos[0]
    assert pedido["url"] == (
        "https://aiplatform.googleapis.com/v1/projects/projeto-x/locations/global"
        "/publishers/google/models/gemini-3.5-flash-lite:generateContent"
    )
    corpo = pedido["json"]
    arquivo = corpo["contents"][0]["parts"][0]
    assert arquivo["fileData"] == {"mimeType": "video/mp4", "fileUri": VIDEO}
    assert arquivo["videoMetadata"] == {"fps": 1}
    assert corpo["generationConfig"]["responseMimeType"] == "application/json"
    assert corpo["generationConfig"]["responseJsonSchema"] == _chamada().esquema
    assert "mediaResolution" not in corpo["generationConfig"]
    assert corpo["labels"] == {"job_id": JOB}
    assert "tools" not in corpo
    assert "systemInstruction" in corpo
    # Flex: só ele, sem Provisioned Throughput antes.
    assert pedido["headers"]["X-Vertex-AI-LLM-Shared-Request-Type"] == "flex"
    assert pedido["headers"]["X-Vertex-AI-LLM-Request-Type"] == "shared"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transporte_vertex_converte_status_diferente_de_200_em_erro_http(
    status: int,
) -> None:
    transporte = TransporteVertex("p", SessaoFalsa(RespostaFalsa(status)))

    with pytest.raises(ErroHttp) as erro:
        transporte.gerar(_chamada())

    assert erro.value.status == status


@pytest.mark.parametrize(
    "falha", [requests.Timeout(), requests.ConnectionError(), ConnectionResetError()]
)
def test_transporte_vertex_converte_timeout_e_queda_em_503(falha: Exception) -> None:
    transporte = TransporteVertex("p", SessaoFalsa(falha))

    with pytest.raises(ErroHttp) as erro:
        transporte.gerar(_chamada())

    assert erro.value.status == 503


def test_erros_do_transporte_entram_nas_tentativas() -> None:
    sessao = SessaoFalsa(RespostaFalsa(429), RespostaFalsa(500), _ok(BOA))
    relogio = Relogio()

    d = analisar(
        TransporteVertex("p", sessao),
        video_uri=VIDEO,
        job_id=JOB,
        video=VIDEO_CONFIAVEL,
        dormir=relogio.dormir,
    )

    assert d.programa.resumo == "Jornal da noite"
    assert len(sessao.pedidos) == 3
    assert len(relogio.esperas) == 2


def test_resposta_sem_texto_vira_texto_vazio_para_a_validacao_repetir() -> None:
    transporte = TransporteVertex("p", SessaoFalsa(RespostaFalsa(200, {})))

    assert transporte.gerar(_chamada()) == ""
