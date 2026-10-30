import json
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from api.jobs import Job
from api.webhook import (
    CofreEmMemoria,
    RepositorioDeWebhooksEmMemoria,
    UrlInvalida,
    assinar,
    entregar,
    montar_evento,
    registrar_webhook,
    registrar_webhook_main,
    validar_url,
    verificar_assinatura,
)

AGORA = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
URL = "https://legado.redetv.example/callback"


def _publico(host: str) -> list[str]:
    return ["93.184.216.34"]


def _job(
    estado: str = "concluido", sistema: str | None = "Legado", **extra: object
) -> Job:
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
            **extra,
        }
    )


class Ambiente:
    def __init__(self) -> None:
        self.cofre = CofreEmMemoria()
        self.webhooks = RepositorioDeWebhooksEmMemoria()
        self.segredo = registrar_webhook(
            "Legado", URL, self.cofre, self.webhooks, _publico
        )


# --- assinatura ---


def test_assinatura_confere_com_o_segredo() -> None:
    corpo = b'{"a":1}'
    data = AGORA.isoformat()
    assinatura = assinar("segredo", data, corpo)

    assert verificar_assinatura("segredo", data, corpo, assinatura, AGORA)


def test_assinatura_falha_com_corpo_data_ou_segredo_alterados() -> None:
    corpo = b'{"a":1}'
    data = AGORA.isoformat()
    assinatura = assinar("segredo", data, corpo)
    outra_data = (AGORA + timedelta(seconds=1)).isoformat()

    assert not verificar_assinatura("segredo", data, b'{"a":2}', assinatura, AGORA)
    assert not verificar_assinatura("segredo", outra_data, corpo, assinatura, AGORA)
    assert not verificar_assinatura("outro", data, corpo, assinatura, AGORA)


def test_evento_antigo_e_recusado_como_repetido() -> None:
    corpo = b"{}"
    data = AGORA.isoformat()
    assinatura = assinar("s", data, corpo)

    assert not verificar_assinatura(
        "s", data, corpo, assinatura, AGORA + timedelta(hours=1)
    )


# --- URL ---


@pytest.mark.parametrize(
    "url",
    [
        "http://legado.redetv.example/cb",
        "https://localhost/cb",
        "https://LOCALHOST./cb",
        "https://10.1.2.3/cb",
        "https://127.0.0.1/cb",
        "https://169.254.169.254/cb",
        "https://192.168.0.1/cb",
        "https://[::1]/cb",
        "https://[::ffff:10.0.0.1]/cb",
        "https://100.64.0.1/cb",
        "https://0.0.0.0/cb",
        "https://usuario:senha@legado.redetv.example/cb",
        "https://usuario@legado.redetv.example/cb",
        "https:///cb",
        "ftp://legado.redetv.example/cb",
    ],
)
def test_url_hostil_e_recusada_no_registro(url: str) -> None:
    with pytest.raises(UrlInvalida):
        validar_url(url, _publico)
    with pytest.raises(UrlInvalida):
        registrar_webhook(
            "Legado", url, CofreEmMemoria(), RepositorioDeWebhooksEmMemoria(), _publico
        )


def test_host_que_resolve_para_ip_privado_e_recusado() -> None:
    with pytest.raises(UrlInvalida):
        validar_url(URL, lambda host: ["93.184.216.34", "10.0.0.5"])


def test_host_que_nao_resolve_e_recusado() -> None:
    def falha(host: str) -> list[str]:
        raise socket.gaierror

    with pytest.raises(UrlInvalida):
        validar_url(URL, falha)


def test_registro_guarda_o_segredo_no_cofre_e_nao_no_repositorio() -> None:
    a = Ambiente()

    assert a.cofre.obter("Legado") == a.segredo
    registro = a.webhooks.obter("Legado")
    assert registro is not None and registro.url == URL
    assert a.segredo not in registro.model_dump_json()


# --- montagem do evento ---


@pytest.mark.parametrize(
    ("estado", "tipo"), [("concluido", "job.concluido"), ("falhou", "job.falhou")]
)
def test_job_de_sistema_com_webhook_gera_evento(estado: str, tipo: str) -> None:
    a = Ambiente()
    extra = {"codigo_falha": "analise_falhou"} if estado == "falhou" else {}

    evento = montar_evento(_job(estado, **extra), a.webhooks, AGORA)

    assert evento is not None
    assert evento.tipo == tipo
    assert evento.job_id == "job-1"
    assert evento.estado == estado
    assert evento.codigo_falha == extra.get("codigo_falha")
    assert evento.data == AGORA
    assert evento.id


def test_eventos_tem_ids_unicos() -> None:
    a = Ambiente()

    e1 = montar_evento(_job(), a.webhooks, AGORA)
    e2 = montar_evento(_job(), a.webhooks, AGORA)

    assert e1 and e2 and e1.id != e2.id


def test_job_de_pessoa_cancelado_ou_sem_webhook_nao_gera_evento() -> None:
    a = Ambiente()

    assert montar_evento(_job(sistema=None), a.webhooks, AGORA) is None
    assert montar_evento(_job("cancelado"), a.webhooks, AGORA) is None
    assert montar_evento(_job("analisando"), a.webhooks, AGORA) is None
    assert montar_evento(_job(sistema="Outro"), a.webhooks, AGORA) is None


# --- entrega ---


class HttpFalso:
    def __init__(self, *respostas: int | Exception) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[tuple[str, bytes, dict[str, str]]] = []
        self.ips: list[list[str]] = []

    def enviar(
        self, url: str, ips: list[str], corpo: bytes, cabecalhos: dict[str, str]
    ) -> int:
        self.chamadas.append((url, corpo, cabecalhos))
        self.ips.append(ips)
        r = self.respostas.pop(0) if self.respostas else 200
        if isinstance(r, Exception):
            raise r
        return r


def _entregar(
    a: Ambiente,
    http: HttpFalso,
    esperas: list[float] | None = None,
    resolver: Callable[[str], list[str]] = _publico,
) -> bool:
    evento = montar_evento(_job(), a.webhooks, AGORA)
    assert evento is not None
    registro = a.webhooks.obter("Legado")
    assert registro is not None
    esperas = [] if esperas is None else esperas
    return entregar(
        evento,
        registro,
        a.cofre,
        http,
        resolver=resolver,
        dormir=esperas.append,
        sortear=lambda teto: teto,
        relogio=lambda: AGORA,
    )


def test_entrega_assinada_como_o_cliente_confere() -> None:
    a = Ambiente()
    http = HttpFalso(204)

    assert _entregar(a, http)

    url, corpo, cab = http.chamadas[0]
    assert url == URL
    assert http.ips == [["93.184.216.34"]]
    assert verificar_assinatura(
        a.segredo, cab["X-Webhook-Data"], corpo, cab["X-Webhook-Assinatura"], AGORA
    )
    dados = json.loads(corpo)
    assert dados["id"] == cab["X-Webhook-Id"]
    assert dados["job_id"] == "job-1"


def test_2xx_encerra_a_entrega() -> None:
    http = HttpFalso(200)

    assert _entregar(Ambiente(), http)
    assert len(http.chamadas) == 1


@pytest.mark.parametrize("status", [400, 401, 404, 410])
def test_4xx_nao_repete(status: int) -> None:
    http = HttpFalso(status)

    assert not _entregar(Ambiente(), http)
    assert len(http.chamadas) == 1


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_408_429_e_5xx_repetem_com_o_mesmo_id(status: int) -> None:
    http = HttpFalso(status, status, 200)
    esperas: list[float] = []

    assert _entregar(Ambiente(), http, esperas)

    ids = {c[2]["X-Webhook-Id"] for c in http.chamadas}
    assert len(http.chamadas) == 3 and len(ids) == 1
    assert len(esperas) == 2


def test_falha_de_rede_repete() -> None:
    http = HttpFalso(ConnectionError(), 200)

    assert _entregar(Ambiente(), http)
    assert len(http.chamadas) == 2


def test_desiste_no_limite_com_esperas_crescentes_dentro_do_teto() -> None:
    from api.webhook import ESPERA_TETO_S, REENTREGAS

    http = HttpFalso(*[500] * 100)
    esperas: list[float] = []

    assert not _entregar(Ambiente(), http, esperas)

    assert len(http.chamadas) == REENTREGAS + 1
    assert esperas == sorted(esperas) and esperas[0] < esperas[-1]
    assert max(esperas) <= ESPERA_TETO_S


def test_dns_fora_do_ar_na_entrega_repete() -> None:
    respostas: list[list[str] | OSError] = [socket.gaierror(), ["93.184.216.34"]]

    def resolver(host: str) -> list[str]:
        r = respostas.pop(0)
        if isinstance(r, OSError):
            raise r
        return r

    http = HttpFalso(200)
    esperas: list[float] = []

    assert _entregar(Ambiente(), http, esperas, resolver)
    assert len(http.chamadas) == 1 and len(esperas) == 1


def test_host_que_passa_a_resolver_para_ip_privado_nao_e_chamado() -> None:
    a = Ambiente()
    http = HttpFalso()

    assert not _entregar(a, http, resolver=lambda host: ["10.0.0.9"])
    assert http.chamadas == []


# --- comando de linha ---


def test_comando_registra_e_mostra_o_segredo_uma_vez() -> None:
    cofre, webhooks = CofreEmMemoria(), RepositorioDeWebhooksEmMemoria()
    saida: list[str] = []

    codigo = registrar_webhook_main(
        ["Legado", URL], cofre, webhooks, saida.append, _publico
    )

    assert codigo == 0
    assert cofre.obter("Legado") == saida[-1]
    assert webhooks.obter("Legado") is not None


def test_comando_recusa_url_hostil_e_uso_errado() -> None:
    cofre, webhooks = CofreEmMemoria(), RepositorioDeWebhooksEmMemoria()
    saida: list[str] = []

    assert (
        registrar_webhook_main(["Legado", "http://x"], cofre, webhooks, saida.append)
        == 2
    )
    assert registrar_webhook_main(["Legado"], cofre, webhooks, saida.append) == 2
    assert cofre.obter("Legado") is None and webhooks.obter("Legado") is None
