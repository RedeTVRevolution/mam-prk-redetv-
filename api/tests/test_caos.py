"""Teste de caos local (#274): um Job só por chave de idempotência, nenhum processamento em
dobro e cada sistema vendo só os próprios Jobs.

O Firestore é o emulador (sem `FIRESTORE_EMULATOR_HOST`, os testes são pulados, como os de
`test_nuvem.py`). O Storage é um falso que só devolve URL assinada, porque nada aqui sobe
arquivo. O Pub/Sub é um corretor em memória que entrega mais de uma vez e fora de ordem: o
emulador do Pub/Sub não sobe nem no CI nem no loop, e o que se testa é o lado da API
(a rota do push e a entrega idempotente), que o corretor exercita igual.
"""

import base64
import os
import random
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from api.caos import CORPO, em_paralelo, roteiro
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.ciclo_de_vida import transitar
from api.eventos_do_job import (
    CAMINHO_DO_PUSH,
    MensagemDeEvento,
    RepositorioQuePublicaOFim,
    criar_rotas_do_push,
)
from api.jobs import Job, RepositorioDeJobs
from api.main import criar_app
from api.nuvem import RepositorioDeIdempotenciaFirestore, RepositorioFirestore
from api.tests.test_jobs import ArmazenamentoFalso
from api.webhook import (
    CofreEmMemoria,
    RepositorioDeWebhooksEmMemoria,
    registrar_webhook,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"),
    reason="sem o emulador do Firestore",
)

AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
TOKEN = "Bearer token-do-pubsub"
URL = "https://legado.redetv.example/callback"


class CaiDepoisDeGravar:
    """O processo morre depois de gravar o Job e antes de responder."""

    def __init__(self, repositorio: RepositorioDeJobs) -> None:
        self._repositorio = repositorio
        self.quedas = 1

    def criar(self, job: Job) -> bool:
        gravou = self._repositorio.criar(job)
        if self.quedas:
            self.quedas -= 1
            raise SystemError("processo morto depois de gravar")
        return gravou

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._repositorio, nome)


class CaiAntesDeGravar:
    """O processo morre depois de reservar a chave e antes de gravar o Job."""

    def __init__(self, repositorio: RepositorioDeJobs) -> None:
        self._repositorio = repositorio
        self.quedas = 1

    def criar(self, job: Job) -> bool:
        if self.quedas:
            self.quedas -= 1
            raise SystemError("processo morto antes de gravar")
        return self._repositorio.criar(job)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._repositorio, nome)


class Mundo:
    """O app contra o Firestore do emulador, com coleções próprias e duas chaves de sistema."""

    def __init__(
        self, defeito: Callable[[RepositorioDeJobs], RepositorioDeJobs] | None = None
    ) -> None:
        self.cliente_firestore = firestore.Client(
            project="teste",
            credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
        )
        self.colecao = f"jobs-{uuid.uuid4().hex}"
        self.jobs = RepositorioFirestore(self.cliente_firestore, self.colecao)
        chaves = RepositorioDeChavesEmMemoria()
        self.chaves = {
            nome: emitir_chave(
                nome, frozenset({"criar", "ler", "cancelar"}), MAC, chaves, AGORA
            ).chave
            for nome in ("Legado A", "Legado B")
        }
        self.app = criar_app(
            repositorio=defeito(self.jobs) if defeito else self.jobs,
            armazenamento=ArmazenamentoFalso(),
            chaves=VerificadorDeChaveDeApi(chaves, MAC),
            idempotencia=RepositorioDeIdempotenciaFirestore(
                self.cliente_firestore, f"idempotencia-{uuid.uuid4().hex}"
            ),
            relogio=lambda: AGORA,
        )

    def gravados(self) -> list[str]:
        return [d.id for d in self.cliente_firestore.collection(self.colecao).stream()]


class ApiLocal:
    def __init__(self, mundo: Mundo) -> None:
        self._mundo = mundo

    def requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        sistema: str,
        corpo: dict[str, Any] | None = None,
        chave: str | None = None,
    ) -> tuple[int, Any]:
        cabecalhos = {"X-API-Key": self._mundo.chaves[sistema]}
        if chave is not None:
            cabecalhos["Idempotency-Key"] = chave
        # Um cliente por chamada: cada thread tem o seu.
        cliente = TestClient(self._mundo.app, raise_server_exceptions=False)
        resposta = cliente.request(
            metodo, f"/v1{caminho}", json=corpo, headers=cabecalhos
        )
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, None


def _criar(mundo: Mundo, chave: str, sistema: str = "Legado A") -> tuple[int, Any]:
    return ApiLocal(mundo).requisitar(
        "POST", "/jobs", sistema=sistema, corpo=CORPO, chave=chave
    )


def test_o_roteiro_inteiro_passa_contra_o_firestore_e_deixa_um_job_por_sistema() -> (
    None
):
    mundo = Mundo()

    relatorio = roteiro(ApiLocal(mundo), "Legado A", "Legado B")

    assert relatorio.passou, relatorio.texto()
    assert sorted(mundo.gravados()) == sorted(relatorio.jobs_criados)


def test_cinquenta_envios_em_paralelo_com_a_mesma_chave_criam_um_job() -> None:
    mundo = Mundo()
    chave = str(uuid.uuid4())

    with ThreadPoolExecutor(max_workers=25) as pool:
        respostas = list(pool.map(lambda _: _criar(mundo, chave), range(50)))

    assert sorted(s for s, _ in respostas) == [200] * 49 + [202]
    assert len({c["id"] for _, c in respostas}) == 1
    assert len(mundo.gravados()) == 1


def test_chaves_diferentes_criam_jobs_diferentes_mesmo_em_paralelo() -> None:
    mundo = Mundo()

    with ThreadPoolExecutor(max_workers=10) as pool:
        respostas = list(
            pool.map(lambda _: _criar(mundo, str(uuid.uuid4())), range(10))
        )

    assert all(s == 202 for s, _ in respostas)
    assert len(mundo.gravados()) == 10


def test_queda_depois_de_gravar_e_antes_de_responder_a_repeticao_acha_o_mesmo_job() -> (
    None
):
    mundo = Mundo(CaiDepoisDeGravar)
    chave = str(uuid.uuid4())

    status, _ = _criar(mundo, chave)
    assert status == 500  # o cliente não viu a resposta
    (gravado,) = mundo.gravados()

    status, corpo = _criar(mundo, chave)
    assert (status, corpo["id"]) == (200, gravado)
    assert mundo.gravados() == [gravado]


def test_queda_depois_de_reservar_e_antes_de_gravar_a_repeticao_grava_com_o_mesmo_id() -> (
    None
):
    mundo = Mundo(CaiAntesDeGravar)
    chave = str(uuid.uuid4())

    status, _ = _criar(mundo, chave)
    assert status == 500 and mundo.gravados() == []

    with ThreadPoolExecutor(max_workers=8) as pool:
        respostas = list(pool.map(lambda _: _criar(mundo, chave), range(8)))

    assert all(s in (200, 202) for s, _ in respostas)
    ids = {c["id"] for _, c in respostas}
    assert len(ids) == 1 and mundo.gravados() == list(ids)


def test_repeticao_depois_de_o_job_andar_nao_desfaz_o_estado() -> None:
    mundo = Mundo()
    chave = str(uuid.uuid4())
    _, criado = _criar(mundo, chave)
    transitar(mundo.jobs, criado["id"], "aguardando_upload", "validando", AGORA)

    status, repetido = _criar(mundo, chave)

    assert status == 200 and repetido["estado"] == "validando"
    assert repetido["url_de_upload"] is None
    job = mundo.jobs.obter(criado["id"])
    assert job is not None and job.estado == "validando"


# --- Pub/Sub: entrega repetida, fora de ordem, e o webhook que falha e volta ---


class Corretor:
    """Pub/Sub em memória, ao menos uma vez: não confirma o que não recebeu 2xx,
    repete mensagens e as entrega em ordem qualquer."""

    def __init__(self, semente: int = 7) -> None:
        self.fila: list[dict[str, Any]] = []
        self._sorteio = random.Random(semente)
        self._trava = threading.Lock()

    def publicar(self, mensagem: MensagemDeEvento) -> None:
        dados = base64.b64encode(mensagem.model_dump_json().encode()).decode()
        with self._trava:
            self.fila.append(
                {"message": {"data": dados, "messageId": mensagem.evento.id}}
            )

    def eventos(self) -> list[MensagemDeEvento]:
        return [
            MensagemDeEvento.model_validate_json(
                base64.b64decode(corpo["message"]["data"])
            )
            for corpo in self.fila
        ]

    def entregar(self, cliente: TestClient, rodadas: int = 6) -> None:
        for _ in range(rodadas):
            pendentes, self.fila = self.fila, []
            # Cada mensagem vai duas vezes (entrega repetida) e a ordem é sorteada.
            lote = [*pendentes, *pendentes]
            self._sorteio.shuffle(lote)
            for corpo in lote:
                resposta = cliente.post(
                    CAMINHO_DO_PUSH, json=corpo, headers={"Authorization": TOKEN}
                )
                if resposta.status_code != 204 and corpo not in self.fila:
                    self.fila.append(
                        corpo
                    )  # sem confirmação: o Pub/Sub entrega de novo


class DestinoQueFalhaEVolta:
    """O webhook do sistema: cai nas primeiras tentativas e depois atende. Do lado do
    cliente, o `X-Webhook-Id` repetido é descartado."""

    def __init__(self, falhas: int) -> None:
        self._falhas = falhas
        self._trava = threading.Lock()
        self.tentativas = 0
        self.processados: list[str] = []
        self._vistos: set[str] = set()

    def enviar(
        self, url: str, ips: list[str], corpo: bytes, cabecalhos: dict[str, str]
    ) -> int:
        with self._trava:
            self.tentativas += 1
            if self._falhas:
                self._falhas -= 1
                return 503
            id_ = cabecalhos["X-Webhook-Id"]
            if id_ not in self._vistos:
                self._vistos.add(id_)
                self.processados.append(id_)
            return 200


class Verificador:
    def confere(self, autorizacao: str | None) -> bool:
        return autorizacao == TOKEN


def test_evento_de_fim_chega_uma_vez_apesar_de_entrega_repetida_fora_de_ordem_e_destino_caindo() -> (
    None
):
    mundo = Mundo()
    webhooks, cofre = RepositorioDeWebhooksEmMemoria(), CofreEmMemoria()
    registrar_webhook("Legado A", URL, cofre, webhooks, lambda host: ["93.184.216.34"])
    corretor = Corretor()
    jobs = RepositorioQuePublicaOFim(mundo.jobs, webhooks, corretor, lambda: AGORA)
    ids = []
    for _ in range(5):
        job = Job(
            id=uuid.uuid4().hex,
            nome="a.mp4",
            tamanho_bytes=10,
            estado="analisando",
            criado_por="sistema:Legado A",
            sistema="Legado A",
            criado_em=AGORA,
            atualizado_em=AGORA,
        )
        jobs.salvar(job)
        ids.append(job.id)

    # O mesmo Job terminado duas vezes (o segundo `transitar` não acha mais o estado de
    # origem): o evento sai uma vez.
    for i in ids * 2:
        transitar(jobs, i, "analisando", "concluido", AGORA)
    assert sorted(m.evento.job_id for m in corretor.eventos()) == sorted(ids)

    destino = DestinoQueFalhaEVolta(falhas=3)
    app = FastAPI()
    app.include_router(
        criar_rotas_do_push(
            Verificador(), webhooks, cofre, destino, lambda host: ["93.184.216.34"]
        )
    )
    corretor.entregar(TestClient(app))

    assert corretor.fila == []  # tudo confirmado no fim
    assert destino.tentativas > 5  # houve repetição e houve falha
    assert len(destino.processados) == 5  # cada evento, uma vez só, para o cliente
    assert len(set(destino.processados)) == 5


def test_doze_trabalhadores_terminando_o_mesmo_job_ao_mesmo_tempo_um_vence_e_ninguem_estoura() -> (
    None
):
    mundo = Mundo()
    job = Job(
        id=uuid.uuid4().hex,
        nome="a.mp4",
        tamanho_bytes=10,
        estado="analisando",
        criado_por="sistema:Legado A",
        sistema="Legado A",
        criado_em=AGORA,
        atualizado_em=AGORA,
    )
    mundo.jobs.salvar(job)

    def terminar() -> tuple[int, Any]:
        novo = mundo.jobs.transitar(job.id, "analisando", {"estado": "concluido"})
        return (1 if novo else 0), None

    vitorias = sum(v for v, _ in em_paralelo(12, terminar))
    assert vitorias == 1
    gravado = mundo.jobs.obter(job.id)
    assert gravado is not None and gravado.estado == "concluido"
