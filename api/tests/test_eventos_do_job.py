"""Eventos de fim de Job no Pub/Sub e a entrega pelo push (#273), sem rede."""

import base64
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ciclo_de_vida import transitar
from api.eventos_do_job import (
    CAMINHO_DO_PUSH,
    ErroDoPubSub,
    MensagemDeEvento,
    PublicadorEmMemoria,
    PublicadorPubSub,
    RepositorioQuePublicaOFim,
    criar_rotas_do_push,
    repositorio_do_ambiente,
)
from api.jobs import Job, RepositorioEmMemoria
from api.webhook import (
    CofreEmMemoria,
    RepositorioDeWebhooksEmMemoria,
    registrar_webhook,
)

AGORA = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
URL = "https://legado.redetv.example/callback"
TOKEN = "Bearer token-do-pubsub"


def _publico(host: str) -> list[str]:
    return ["93.184.216.34"]


def _job(estado: str = "analisando", sistema: str | None = "Legado") -> Job:
    return Job.model_validate(
        {
            "id": "job-1",
            "nome": "a.mp4",
            "tamanho_bytes": 10,
            "estado": estado,
            "criado_por": f"sistema:{sistema}" if sistema else "uid-1",
            "sistema": sistema,
            "criado_em": AGORA,
            "atualizado_em": AGORA,
        }
    )


class Mundo:
    def __init__(self, com_webhook: bool = True) -> None:
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(_job())
        self.webhooks = RepositorioDeWebhooksEmMemoria()
        self.cofre = CofreEmMemoria()
        if com_webhook:
            registrar_webhook("Legado", URL, self.cofre, self.webhooks, _publico)
        self.publicador = PublicadorEmMemoria()
        self.repositorio = RepositorioQuePublicaOFim(
            self.jobs, self.webhooks, self.publicador, lambda: AGORA
        )


def test_o_job_que_conclui_publica_o_evento_com_o_sistema() -> None:
    m = Mundo()

    transitar(m.repositorio, "job-1", "analisando", "concluido", AGORA)

    (mensagem,) = m.publicador.mensagens
    assert mensagem.sistema == "Legado"
    assert (mensagem.evento.tipo, mensagem.evento.job_id) == ("job.concluido", "job-1")


def test_o_job_que_falha_publica_o_evento_com_o_codigo() -> None:
    m = Mundo()

    transitar(
        m.repositorio,
        "job-1",
        "analisando",
        "falhou",
        AGORA,
        codigo_falha="analise_falhou",
    )

    (mensagem,) = m.publicador.mensagens
    assert mensagem.evento.tipo == "job.falhou"
    assert mensagem.evento.codigo_falha == "analise_falhou"


def test_cancelar_sem_webhook_ou_sem_sistema_nao_publica() -> None:
    m = Mundo()
    transitar(m.repositorio, "job-1", "analisando", "cancelado", AGORA)
    assert m.publicador.mensagens == []

    sem_webhook = Mundo(com_webhook=False)
    transitar(sem_webhook.repositorio, "job-1", "analisando", "concluido", AGORA)
    assert sem_webhook.publicador.mensagens == []

    de_pessoa = Mundo()
    de_pessoa.jobs.salvar(_job(sistema=None))
    transitar(de_pessoa.repositorio, "job-1", "analisando", "concluido", AGORA)
    assert de_pessoa.publicador.mensagens == []


def test_transicao_que_nao_aconteceu_ou_que_nao_muda_o_estado_nao_publica() -> None:
    m = Mundo()
    assert (
        m.repositorio.transitar("job-1", "validando", {"estado": "concluido"}) is None
    )
    m.jobs.salvar(_job("concluido"))
    m.repositorio.transitar("job-1", "concluido", {"capa": "q.jpg"})  # os quadros-chave
    assert m.publicador.mensagens == []


def test_falha_do_pubsub_nao_desfaz_a_transicao() -> None:
    m = Mundo()

    class Quebrado:
        def publicar(self, mensagem: MensagemDeEvento) -> None:
            raise ErroDoPubSub("fora do ar")

    repositorio = RepositorioQuePublicaOFim(m.jobs, m.webhooks, Quebrado())

    job = transitar(repositorio, "job-1", "analisando", "concluido", AGORA)

    assert job is not None and job.estado == "concluido"


def test_publicador_pubsub_envia_o_evento_em_base64_com_o_id_nos_atributos() -> None:
    pedidos: list[tuple[str, str, dict[str, Any] | None]] = []

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        pedidos.append((metodo, caminho, corpo))
        return 200, {"messageIds": ["1"]}

    m = Mundo()
    PublicadorPubSub("projects/p/topics/t", transporte).publicar(
        MensagemDeEvento(
            sistema="Legado",
            evento=_evento(m),
        )
    )

    metodo, caminho, corpo = pedidos[0]
    assert (metodo, caminho) == ("POST", "projects/p/topics/t:publish")
    assert corpo is not None
    (enviada,) = corpo["messages"]
    dados = json.loads(base64.b64decode(enviada["data"]))
    assert dados["sistema"] == "Legado"
    assert enviada["attributes"]["evento_id"] == dados["evento"]["id"]


def test_publicador_pubsub_levanta_se_o_pubsub_recusa() -> None:
    m = Mundo()
    publicador = PublicadorPubSub(
        "projects/p/topics/t", lambda *_: (403, {"error": {"status": "DENIED"}})
    )
    with pytest.raises(ErroDoPubSub):
        publicador.publicar(MensagemDeEvento(sistema="Legado", evento=_evento(m)))


def test_sem_topico_no_ambiente_o_repositorio_fica_como_esta() -> None:
    jobs = RepositorioEmMemoria()
    assert repositorio_do_ambiente(jobs, RepositorioDeWebhooksEmMemoria, {}) is jobs
    com = repositorio_do_ambiente(
        jobs,
        RepositorioDeWebhooksEmMemoria,
        {"PUBSUB_TOPICO_EVENTOS": "projects/p/topics/t"},
        lambda: lambda *_: (200, {}),
    )
    assert isinstance(com, RepositorioQuePublicaOFim)


def _evento(m: Mundo) -> Any:
    transitar(m.repositorio, "job-1", "analisando", "concluido", AGORA)
    return m.publicador.mensagens[0].evento


# --- push ---


class HttpFalso:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.chamadas: list[tuple[str, dict[str, str], bytes]] = []

    def enviar(
        self, url: str, ips: list[str], corpo: bytes, cabecalhos: dict[str, str]
    ) -> int:
        self.chamadas.append((url, cabecalhos, corpo))
        return self.status


class Verificador:
    def confere(self, autorizacao: str | None) -> bool:
        return autorizacao == TOKEN


def _cliente(m: Mundo, http: HttpFalso) -> TestClient:
    app = FastAPI()
    app.include_router(
        criar_rotas_do_push(
            Verificador(), m.webhooks, m.cofre, http, _publico, lambda: AGORA
        )
    )
    return TestClient(app)


def _push(m: Mundo) -> dict[str, Any]:
    evento = _evento(m)
    mensagem = MensagemDeEvento(sistema="Legado", evento=evento)
    dados = base64.b64encode(mensagem.model_dump_json().encode()).decode()
    return {"message": {"data": dados, "messageId": "9"}, "subscription": "s"}


def _enviar(cliente: TestClient, corpo: Any, token: str | None = TOKEN) -> Any:
    cabecalhos = {"Authorization": token} if token else {}
    return cliente.post(CAMINHO_DO_PUSH, json=corpo, headers=cabecalhos)


def test_o_push_entrega_o_webhook_assinado_e_confirma() -> None:
    m, http = Mundo(), HttpFalso()
    resposta = _enviar(_cliente(m, http), _push(m))

    assert resposta.status_code == 204
    ((url, cabecalhos, _),) = http.chamadas
    assert url == URL
    assert cabecalhos["X-Webhook-Id"] == m.publicador.mensagens[0].evento.id


def test_o_push_repetido_leva_o_mesmo_id_de_evento() -> None:
    m, http = Mundo(), HttpFalso()
    corpo = _push(m)
    cliente = _cliente(m, http)

    _enviar(cliente, corpo)
    _enviar(cliente, corpo)  # o Pub/Sub entrega de novo se a confirmação se perdeu

    ids = {c[1]["X-Webhook-Id"] for c in http.chamadas}
    assert len(http.chamadas) == 2 and len(ids) == 1


@pytest.mark.parametrize("status", [500, 502, 503, 429, 408])
def test_erro_repetivel_do_destino_devolve_503_para_o_pubsub_tentar_de_novo(
    status: int,
) -> None:
    m = Mundo()
    resposta = _enviar(_cliente(m, HttpFalso(status)), _push(m))
    assert resposta.status_code == 503


@pytest.mark.parametrize("status", [400, 401, 404, 301])
def test_erro_que_repetir_nao_conserta_e_confirmado(status: int) -> None:
    m = Mundo()
    resposta = _enviar(_cliente(m, HttpFalso(status)), _push(m))
    assert resposta.status_code == 204


def test_sem_token_do_pubsub_a_rota_recusa() -> None:
    m, http = Mundo(), HttpFalso()
    cliente = _cliente(m, http)
    corpo = _push(m)

    assert _enviar(cliente, corpo, token=None).status_code == 401
    assert _enviar(cliente, corpo, token="Bearer outro").status_code == 401
    assert http.chamadas == []


@pytest.mark.parametrize(
    "corpo", [{}, {"message": {}}, {"message": {"data": "!!"}}, [1]]
)
def test_mensagem_malformada_e_confirmada_sem_entregar(corpo: Any) -> None:
    m, http = Mundo(), HttpFalso()
    resposta = _enviar(_cliente(m, http), corpo)
    assert resposta.status_code == 204 and http.chamadas == []


def test_sistema_que_apagou_o_webhook_tem_o_evento_descartado() -> None:
    m, http = Mundo(), HttpFalso()
    corpo = _push(m)
    m.webhooks = RepositorioDeWebhooksEmMemoria()  # outro repositório, vazio
    resposta = _enviar(_cliente(m, http), corpo)
    assert resposta.status_code == 204 and http.chamadas == []
