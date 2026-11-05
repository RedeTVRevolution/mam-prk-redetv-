"""Eventos de uso (#279): cada ponto publica o evento certo, sem derrubar a ação."""

import base64
import json
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Escopo, Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.eventos_de_uso import (
    ErroAoPublicarUso,
    EventoDeUso,
    EventosEmMemoria,
    EventosEmSegundoPlano,
    EventosPubSub,
    SemEventos,
    registrar,
)
from api.eventos_do_job import (
    RepositorioQueRegistraOFim,
    eventos_do_ambiente,
    repositorio_do_ambiente,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_aprovacao import CURADOR
from api.tests.test_auth import VerificadorFalso
from api.tests.test_busca import (
    AUTORIZACAO as AUTORIZACAO_DA_BUSCA,
)
from api.tests.test_busca import EmbeddingDeTexto, job, pedido, plano
from api.tests.test_busca import cliente as cliente_da_busca
from api.tests.test_busca_por_imagem import com_planos, enviar, foto
from api.tests.test_correcoes import AUTORIZACAO as AUTORIZACAO_DAS_CORRECOES
from api.tests.test_correcoes import BYTES, MODELO, VERSAO, _pessoa
from api.tests.test_correcoes import Mundo as MundoDasCorrecoes
from api.tests.test_jobs import ArmazenamentoFalso

AGORA = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
ANA = {"Authorization": "Bearer ana"}


class EventosQueFalham:
    def publicar(self, evento: EventoDeUso) -> None:
        raise RuntimeError("Pub/Sub fora do ar")


class Mundo:
    def __init__(
        self,
        eventos: Any = None,
        login_em: datetime | None = None,
        papeis_da_ana: list[Any] | None = None,
    ) -> None:
        self.eventos = eventos if eventos is not None else EventosEmMemoria()
        self.agora = AGORA
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(
            Job(
                id="j1",
                nome="a.mp4",
                tamanho_bytes=10,
                estado="concluido",
                criado_por="ana",
                programa="TV Fama",
                criado_em=AGORA,
                atualizado_em=AGORA,
            )
        )
        self.armazenamento = ArmazenamentoFalso()
        self.armazenamento.decupagens["j1"] = [BYTES]
        self.chaves = RepositorioDeChavesEmMemoria()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("ana", papeis_da_ana or ["editor", "operador"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "ana": Usuario(
                            uid="ana", email="ana@redetv.com.br", login_em=login_em
                        )
                    }
                ),
                self.jobs,
                self.armazenamento,
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
                papeis=papeis,
                correcoes=RepositorioDeCorrecoesEmMemoria(),
                relogio=lambda: self.agora,
                eventos=self.eventos,
            )
        )

    def chave(self, *escopos: Escopo) -> dict[str, str]:
        emitida = emitir_chave(
            "Playout",
            frozenset(escopos),
            MAC,
            self.chaves,
            AGORA,
        )
        return {"X-API-Key": emitida.chave}

    def tipos(self) -> list[str]:
        return [e.tipo for e in self.eventos.publicados]


def _novo(**campos: Any) -> dict[str, Any]:
    return {
        "nome": "b.mp4",
        "tamanho_bytes": 123,
        "tipo": "video/mp4",
        "programa": "TV Fama",
        "data_exibicao": "2026-10-01",
        **campos,
    }


# O evento e a mensagem


def test_a_mensagem_leva_o_quando_em_microssegundos_e_nada_de_vazio() -> None:
    evento = EventoDeUso(
        id="e1", tipo="envio", quando=AGORA, quem_tipo="usuario", quem_id="ana"
    )

    assert evento.para_json() == {
        "id": "e1",
        "tipo": "envio",
        "quem_tipo": "usuario",
        "quem_id": "ana",
        "quando": int(AGORA.timestamp()) * 1_000_000,
    }


def test_o_pubsub_recebe_o_evento_em_json_no_topico_com_os_atributos() -> None:
    pedidos: list[tuple[str, str, dict[str, Any] | None]] = []

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        pedidos.append((metodo, caminho, corpo))
        return 200, {"messageIds": ["1"]}

    EventosPubSub("projects/p/topics/t", transporte).publicar(
        EventoDeUso(
            id="e1",
            tipo="busca",
            quando=AGORA,
            quem_tipo="sistema",
            quem_id="Playout",
            tamanho_da_consulta=7,
        )
    )

    [(metodo, caminho, corpo)] = pedidos
    assert (metodo, caminho) == ("POST", "projects/p/topics/t:publish")
    assert corpo is not None
    [mensagem] = corpo["messages"]
    assert mensagem["attributes"] == {"evento_id": "e1", "tipo": "busca"}
    assert json.loads(base64.b64decode(mensagem["data"]))["tamanho_da_consulta"] == 7


def test_o_pubsub_nao_repete_e_levanta_quando_recusa() -> None:
    chamadas: list[int] = []

    def transporte(*_: Any) -> tuple[int, dict[str, Any]]:
        chamadas.append(1)
        return 503, {"error": {"status": "UNAVAILABLE"}}

    publicador = EventosPubSub("projects/p/topics/t", transporte)

    with pytest.raises(ErroAoPublicarUso, match="503 UNAVAILABLE"):
        publicador.publicar(
            EventoDeUso(
                id="e1", tipo="login", quem_tipo="usuario", quem_id="a", quando=AGORA
            )
        )
    assert len(chamadas) == 1


def test_registrar_nao_levanta_quando_a_publicacao_falha_e_deixa_o_rastro_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        registrar(EventosQueFalham(), "login", ("usuario", "ana"), AGORA)

    assert "evento de uso login" in caplog.text


class ExecutorNaMao(ThreadPoolExecutor):
    """Guarda as tarefas e só as roda quando o teste manda."""

    def __init__(self) -> None:
        super().__init__(max_workers=1)
        self.pendentes: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def submit(
        self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any
    ) -> Future[Any]:
        self.pendentes.append((fn, args))
        return Future()

    def rodar(self) -> None:
        for fn, args in self.pendentes:
            fn(*args)
        self.pendentes.clear()


def _evento() -> EventoDeUso:
    return EventoDeUso(
        id="e1", tipo="login", quem_tipo="usuario", quem_id="a", quando=AGORA
    )


def test_em_segundo_plano_a_publicacao_nao_acontece_na_chamada() -> None:
    eventos = EventosEmMemoria()
    executor = ExecutorNaMao()
    publicador = EventosEmSegundoPlano(eventos, executor)

    publicador.publicar(_evento())
    assert eventos.publicados == []

    executor.rodar()
    assert [e.id for e in eventos.publicados] == ["e1"]


def test_em_segundo_plano_a_falha_vai_ao_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    executor = ExecutorNaMao()
    publicador = EventosEmSegundoPlano(EventosQueFalham(), executor)

    publicador.publicar(_evento())
    with caplog.at_level(logging.ERROR):
        executor.rodar()

    assert "evento de uso login" in caplog.text


def test_o_quando_em_outro_fuso_vira_utc() -> None:
    eventos = EventosEmMemoria()
    brasilia = timezone(timedelta(hours=-3))

    registrar(eventos, "login", ("usuario", "ana"), AGORA.astimezone(brasilia))

    assert eventos.publicados[0].quando.tzinfo == UTC
    assert eventos.publicados[0].quando == AGORA


# Login


def test_o_login_recente_publica_um_evento_com_o_momento_do_login() -> None:
    entrou = AGORA - timedelta(seconds=20)
    mundo = Mundo(login_em=entrou)

    assert mundo.cliente.get("/v1/eu", headers=ANA).status_code == 200

    [evento] = mundo.eventos.publicados
    assert (evento.tipo, evento.quem_tipo, evento.quem_id) == (
        "login",
        "usuario",
        "ana",
    )
    assert evento.quando == entrou


def test_recarregar_a_pagina_nao_publica_outro_login() -> None:
    mundo = Mundo(login_em=AGORA - timedelta(seconds=20))

    for _ in range(3):
        mundo.cliente.get("/v1/eu", headers=ANA)

    assert mundo.tipos() == ["login"]


def test_o_login_antigo_ou_sem_momento_nao_publica() -> None:
    antigo = Mundo(login_em=AGORA - timedelta(hours=3))
    sem_momento = Mundo(login_em=None)

    antigo.cliente.get("/v1/eu", headers=ANA)
    sem_momento.cliente.get("/v1/eu", headers=ANA)

    assert antigo.tipos() == [] and sem_momento.tipos() == []


def test_o_login_nao_leva_o_e_mail() -> None:
    mundo = Mundo(login_em=AGORA)
    mundo.cliente.get("/v1/eu", headers=ANA)

    assert "redetv.com.br" not in json.dumps(mundo.eventos.publicados[0].para_json())


def test_falha_ao_publicar_o_login_nao_derruba_o_eu() -> None:
    mundo = Mundo(eventos=EventosQueFalham(), login_em=AGORA)

    r = mundo.cliente.get("/v1/eu", headers=ANA)

    assert r.status_code == 200 and r.json()["uid"] == "ana"


# Envio


def test_o_envio_por_pessoa_publica_o_job_o_programa_e_o_tamanho() -> None:
    mundo = Mundo()

    r = mundo.cliente.post("/v1/jobs", json=_novo(), headers=ANA)

    assert r.status_code == 202
    [evento] = mundo.eventos.publicados
    assert evento.tipo == "envio"
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "ana")
    assert evento.job_id == r.json()["id"]
    assert (evento.programa, evento.tamanho_bytes) == ("TV Fama", 123)
    assert evento.quando == AGORA


def test_o_envio_por_sistema_publica_o_nome_do_sistema() -> None:
    mundo = Mundo()

    mundo.cliente.post("/v1/jobs", json=_novo(), headers=mundo.chave("criar"))

    envios = [e for e in mundo.eventos.publicados if e.tipo == "envio"]
    assert [(e.quem_tipo, e.quem_id) for e in envios] == [("sistema", "Playout")]


def test_a_repeticao_com_a_mesma_idempotency_key_nao_publica_outro_envio() -> None:
    mundo = Mundo()
    cabecalhos = {**ANA, "Idempotency-Key": "k1"}

    primeira = mundo.cliente.post("/v1/jobs", json=_novo(), headers=cabecalhos)
    segunda = mundo.cliente.post("/v1/jobs", json=_novo(), headers=cabecalhos)

    assert (primeira.status_code, segunda.status_code) == (202, 200)
    assert mundo.tipos() == ["envio"]


def test_o_envio_recusado_nao_publica() -> None:
    mundo = Mundo()

    r = mundo.cliente.post("/v1/jobs", json=_novo(tamanho_bytes=0), headers=ANA)

    assert r.status_code == 422 and mundo.tipos() == []


def test_falha_ao_publicar_o_envio_nao_derruba_o_envio() -> None:
    mundo = Mundo(eventos=EventosQueFalham())

    r = mundo.cliente.post("/v1/jobs", json=_novo(), headers=ANA)

    assert r.status_code == 202 and r.json()["url_de_upload"]
    assert mundo.jobs.obter(r.json()["id"]) is not None


# Fim de processamento


def _job_em(estado: str, **campos: Any) -> Job:
    base: dict[str, Any] = {
        "id": "j1",
        "nome": "a.mp4",
        "tamanho_bytes": 10,
        "estado": estado,
        "criado_por": "ana",
        "programa": "TV Fama",
        "criado_em": AGORA,
        "atualizado_em": AGORA,
    }
    return Job(**{**base, **campos})


def _repositorio_com(job: Job, eventos: Any) -> RepositorioQueRegistraOFim:
    base = RepositorioEmMemoria()
    base.salvar(job)
    return RepositorioQueRegistraOFim(base, eventos, lambda: AGORA)


def test_concluir_publica_o_fim_do_processamento() -> None:
    eventos = EventosEmMemoria()
    repositorio = _repositorio_com(_job_em("analisando"), eventos)

    repositorio.transitar("j1", "analisando", {"estado": "concluido"})

    [evento] = eventos.publicados
    assert evento.tipo == "fim_de_processamento"
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "ana")
    assert (evento.job_id, evento.programa) == ("j1", "TV Fama")
    assert (evento.estado, evento.codigo_falha) == ("concluido", None)


def test_o_fim_leva_quanto_o_job_levou_do_registro_ao_fim() -> None:
    eventos = EventosEmMemoria()
    job = _job_em("analisando", criado_em=AGORA - timedelta(minutes=20, seconds=30))
    repositorio = _repositorio_com(job, eventos)

    repositorio.transitar("j1", "analisando", {"estado": "concluido"})

    assert eventos.publicados[0].segundos_de_processamento == 20 * 60 + 30


def test_falhar_publica_o_codigo_da_falha_e_o_sistema_dono() -> None:
    eventos = EventosEmMemoria()
    repositorio = _repositorio_com(
        _job_em("analisando", sistema="Playout", criado_por="sistema:Playout"), eventos
    )

    repositorio.transitar(
        "j1", "analisando", {"estado": "falhou", "codigo_falha": "analise_falhou"}
    )

    [evento] = eventos.publicados
    assert (evento.quem_tipo, evento.quem_id) == ("sistema", "Playout")
    assert (evento.estado, evento.codigo_falha) == ("falhou", "analise_falhou")


def test_a_transicao_que_nao_termina_o_job_nao_publica() -> None:
    eventos = EventosEmMemoria()
    repositorio = _repositorio_com(_job_em("validando"), eventos)

    repositorio.transitar("j1", "validando", {"estado": "analisando"})

    assert eventos.publicados == []


def test_a_transicao_que_nao_aconteceu_nao_publica() -> None:
    eventos = EventosEmMemoria()
    repositorio = _repositorio_com(_job_em("concluido"), eventos)

    assert repositorio.transitar("j1", "analisando", {"estado": "falhou"}) is None
    assert eventos.publicados == []


def test_a_correcao_de_estado_a_mao_nao_publica() -> None:
    eventos = EventosEmMemoria()
    repositorio = _repositorio_com(_job_em("analisando"), eventos)

    repositorio.trocar("j1", lambda _: {"estado": "concluido"})

    assert eventos.publicados == []


def test_falha_ao_publicar_o_fim_nao_desfaz_a_transicao() -> None:
    repositorio = _repositorio_com(_job_em("analisando"), EventosQueFalham())

    job = repositorio.transitar("j1", "analisando", {"estado": "concluido"})

    assert job is not None and job.estado == "concluido"
    assert repositorio.obter("j1") is not None


def test_o_ambiente_com_o_topico_de_uso_registra_o_fim_e_sem_ele_nao_embrulha() -> None:
    base = RepositorioEmMemoria()

    sem = repositorio_do_ambiente(base, lambda: pytest.fail("sem webhook"), {})
    com = repositorio_do_ambiente(
        base,
        lambda: pytest.fail("sem tópico de webhook"),
        {"PUBSUB_TOPICO_USO": "projects/p/topics/uso"},
        transporte_de_uso=lambda _: lambda *a: (200, {}),
    )

    assert sem is base
    assert isinstance(com, RepositorioQueRegistraOFim)


def test_eventos_do_ambiente_sem_topico_descarta() -> None:
    assert isinstance(eventos_do_ambiente({}), SemEventos)


# Busca


def _busca_com_eventos() -> tuple[TestClient, EventosEmMemoria]:
    eventos = EventosEmMemoria()
    c, _ = cliente_da_busca(
        ["consulta"], pedido(texto_livre="vestido"), eventos=eventos
    )
    return c, eventos


def test_a_busca_publica_o_tamanho_e_os_filtros_e_nunca_o_texto() -> None:
    c, eventos = _busca_com_eventos()

    r = c.get(
        "/v1/busca",
        params={"q": "vestido vermelho", "programa": "TV Fama"},
        headers=AUTORIZACAO_DA_BUSCA,
    )

    assert r.status_code == 200
    [evento] = eventos.publicados
    assert evento.tipo == "busca"
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "u1")
    assert evento.tamanho_da_consulta == len("vestido vermelho")
    assert evento.programa == "TV Fama"
    assert {(f.nome, f.valor) for f in evento.filtros} == {
        ("modo", "texto"),
        ("ordem", "relevancia"),
    }
    assert evento.n_resultados == len(r.json()["videos"]) == 1
    assert "vestido" not in evento.model_dump_json()
    assert "vermelho" not in json.dumps(evento.para_json())


def test_a_busca_por_imagem_publica_so_o_tamanho_da_foto() -> None:
    eventos = EventosEmMemoria()
    c, _ = com_planos(EmbeddingDeTexto([1.0, 0.0]), eventos=eventos)
    dados = foto("PNG")

    r = enviar(c, dados, programa="TV Fama")

    assert r.status_code == 200
    [evento] = eventos.publicados
    assert evento.tipo == "busca" and evento.tamanho_da_consulta == len(dados)
    assert evento.programa == "TV Fama"
    assert ("modo", "imagem") in {(f.nome, f.valor) for f in evento.filtros}
    assert "dados" not in json.dumps(evento.para_json())


def test_a_busca_de_parecidos_publica_o_video_e_o_plano_sem_tamanho() -> None:
    eventos = EventosEmMemoria()
    c, m = cliente_da_busca(["consulta"], eventos=eventos)
    m.com(job("j2"), plano("j2:plano:1", [1.0, 0.0], "rua escura"))

    r = c.get(
        "/v1/busca/parecidos",
        params={"job": "j2", "plano": 1},
        headers=AUTORIZACAO_DA_BUSCA,
    )

    assert r.status_code == 200, r.text
    [evento] = eventos.publicados
    assert (evento.tipo, evento.job_id, evento.tamanho_da_consulta) == (
        "busca",
        "j2",
        None,
    )
    assert {(f.nome, f.valor) for f in evento.filtros} == {
        ("modo", "parecidos"),
        ("plano", "1"),
    }


def test_a_busca_recusada_nao_publica() -> None:
    c, eventos = _busca_com_eventos()

    r = c.get(
        "/v1/busca",
        params={"q": "x", "desde": "2026-02-01", "ate": "2026-01-01"},
        headers=AUTORIZACAO_DA_BUSCA,
    )

    assert r.status_code == 422 and eventos.publicados == []


# Correção


def _corrigir(mundo: Mundo, **campos: Any) -> Any:
    corpo = {
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "valor": "Ana Souza Lima",
        "motivo": "sobrenome completo",
        "versao": VERSAO,
        **campos,
    }
    return mundo.cliente.post("/v1/jobs/j1/correcoes", json=corpo, headers=ANA)


def test_a_correcao_publica_o_tipo_o_job_e_o_programa() -> None:
    mundo = Mundo()

    r = _corrigir(mundo)

    assert r.status_code == 201, r.text
    [evento] = mundo.eventos.publicados
    assert evento.tipo == "correcao"
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "ana")
    assert (evento.job_id, evento.programa) == ("j1", "TV Fama")
    assert evento.tipo_de_correcao == "pessoa.renomear"
    # O valor e o motivo digitados ficam fora do evento.
    assert "Souza Lima" not in evento.model_dump_json()


def test_desfazer_a_correcao_tambem_publica() -> None:
    mundo = Mundo()
    correcao_id = _corrigir(mundo).json()["id"]

    r = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{correcao_id}/desfazer",
        json={"motivo": "enganei-me"},
        headers=ANA,
    )

    assert r.status_code == 201
    assert [e.tipo_de_correcao for e in mundo.eventos.publicados] == [
        "pessoa.renomear",
        "desfazer",
    ]


def test_descartar_da_fila_publica_a_correcao() -> None:
    eventos = EventosEmMemoria()
    mundo = MundoDasCorrecoes(["editor"], eventos=eventos)
    cid = mundo.corrigir().json()["id"]
    mundo.avancar()
    mundo.reprocessar({**MODELO, "pessoas": [_pessoa("p1", "Carla Dias", 1000, 5000)]})

    r = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{cid}/descartar",
        json={"motivo": "revisei"},
        headers=AUTORIZACAO_DAS_CORRECOES,
    )

    assert r.status_code == 201, r.text
    assert [e.tipo_de_correcao for e in eventos.publicados] == [
        "pessoa.renomear",
        "descartar",
    ]


def test_a_decisao_do_curador_publica_a_correcao_com_quem_decidiu() -> None:
    eventos = EventosEmMemoria()
    mundo = MundoDasCorrecoes(["editor"], eventos=eventos)
    mundo.aprovacao.definir(frozenset({"pessoa.renomear"}))
    cid = mundo.corrigir().json()["id"]

    r = mundo.cliente.post(f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=CURADOR)

    assert r.status_code == 201, r.text
    decisao = eventos.publicados[-1]
    assert (decisao.tipo_de_correcao, decisao.quem_id) == ("aprovar", "u2")


def test_a_correcao_recusada_nao_publica() -> None:
    mundo = Mundo()

    r = _corrigir(mundo, item_id="nao-existe")

    assert r.status_code == 422 and mundo.eventos.publicados == []


def test_falha_ao_publicar_a_correcao_nao_derruba_a_correcao() -> None:
    mundo = Mundo(eventos=EventosQueFalham())

    assert _corrigir(mundo).status_code == 201


# Chamada de API


def test_a_chamada_de_sistema_publica_metodo_rota_e_status() -> None:
    mundo = Mundo()

    mundo.cliente.get("/v1/jobs/j1", headers=mundo.chave("ler"))

    [evento] = [e for e in mundo.eventos.publicados if e.tipo == "chamada_de_api"]
    assert (evento.quem_tipo, evento.quem_id) == ("sistema", "Playout")
    # A rota com o modelo do caminho, não o id: o painel agrupa por rota.
    assert (evento.metodo, evento.rota) == ("GET", "/v1/jobs/{job_id}")
    assert evento.status in (200, 404)


def test_a_chamada_recusada_pela_rota_tambem_conta_com_o_status() -> None:
    mundo = Mundo()

    mundo.cliente.post(
        "/v1/jobs", json=_novo(tamanho_bytes=0), headers=mundo.chave("criar")
    )

    [evento] = [e for e in mundo.eventos.publicados if e.tipo == "chamada_de_api"]
    assert (evento.metodo, evento.rota, evento.status) == ("POST", "/v1/jobs", 422)


def test_a_chamada_sem_rota_nao_leva_o_caminho_com_os_valores() -> None:
    mundo = Mundo()

    mundo.cliente.get("/v1/nada/segredo-123", headers=mundo.chave("ler"))

    [evento] = [e for e in mundo.eventos.publicados if e.tipo == "chamada_de_api"]
    assert evento.rota == "(sem rota)" and evento.status == 404


def test_a_chamada_de_pessoa_nao_e_chamada_de_api() -> None:
    mundo = Mundo()

    mundo.cliente.get("/v1/programas", headers=ANA)

    assert "chamada_de_api" not in mundo.tipos()


def test_a_chamada_sem_chave_valida_nao_publica() -> None:
    mundo = Mundo()

    r = mundo.cliente.get("/v1/jobs/j1", headers={"X-API-Key": "invalida"})

    assert r.status_code == 401 and mundo.eventos.publicados == []


def test_falha_ao_publicar_a_chamada_nao_derruba_a_resposta() -> None:
    mundo = Mundo(eventos=EventosQueFalham())

    r = mundo.cliente.get("/v1/programas", headers=mundo.chave("ler"))

    assert r.status_code == 200
