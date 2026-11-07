"""Job de análise, com dublês em memória do repositório e do Storage.

O Gemini é sempre o `TransporteFalso`. A leitura da Decupagem gravada, pela API
web, é o único teste que pede os emuladores (pulado sem eles).
"""

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.analise import executar
from api.auth import Usuario
from api.decupagem import Decupagem, Video
from api.gemini import Chamada, ErroHttp
from api.jobs import Job, RepositorioDeJobs, RepositorioEmMemoria
from api.main import criar_app as criar_app_web
from api.nuvem import ArmazenamentoStorage, DecupagensStorage, RepositorioFirestore
from api.tests.programas_de_teste import perfis_da_tv_fama
from api.tests.test_gemini import BOA, TransporteFalso, resposta_em_mm_ss
from api.tests.test_nuvem import _credencial_local
from api.versao_pipeline import VERSAO_PIPELINE

EMULADOR_FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
EMULADOR_STORAGE = os.environ.get("STORAGE_EMULATOR_HOST")
BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
DEPOIS = BASE + timedelta(minutes=5)
SHA = "a" * 64


class DecupagensEmMemoria:
    def __init__(self, aceitos: str) -> None:
        self.aceitos = aceitos
        self.gravadas: dict[str, str] = {}

    def uri_do_proxy(self, job_id: str) -> str:
        return f"gs://{self.aceitos}/{job_id}/proxy.mp4"

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self.gravadas[job_id] = conteudo


@dataclass
class Ambiente:
    repositorio: RepositorioDeJobs
    decupagens: DecupagensEmMemoria
    transporte: TransporteFalso
    executar: Callable[[str], str]

    def registrar(
        self,
        job_id: str,
        estado: str = "analisando",
        programa: str | None = None,
        cortes_ms: list[int] | None = None,
        timecode_origem: str | None = None,
    ) -> Job:
        job = Job(
            id=job_id,
            nome=f"{job_id}.mp4",
            tamanho_bytes=10,
            sha256=SHA,
            duracao_s=60.0,
            estado=estado,  # type: ignore[arg-type]
            criado_por="uid-1",
            programa=programa,
            cortes_ms=cortes_ms,
            timecode_origem=timecode_origem,
            criado_em=BASE,
            atualizado_em=BASE,
        )
        self.repositorio.salvar(job)
        return job

    def job(self, job_id: str) -> Job:
        job = self.repositorio.obter(job_id)
        assert job is not None
        return job


def _ambiente(
    *respostas: str | Exception, repositorio: RepositorioDeJobs | None = None
) -> Ambiente:
    repositorio = repositorio or RepositorioEmMemoria()
    decupagens = DecupagensEmMemoria("teste-aceitos")
    transporte = TransporteFalso(*respostas)
    return Ambiente(
        repositorio,
        decupagens,
        transporte,
        lambda job_id: executar(
            job_id,
            repositorio,
            decupagens,
            transporte,
            dormir=lambda _s: None,
            perfis=perfis_da_tv_fama(),
            relogio=lambda: DEPOIS,
        ),
    )


def _analisar(ambiente: Ambiente, job_id: str) -> str:
    return ambiente.executar(job_id)


def test_sucesso_grava_a_decupagem_e_leva_o_job_a_concluido() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j1")

    assert _analisar(ambiente, "j1") == "concluido"

    job = ambiente.job("j1")
    assert (job.estado, job.codigo_falha) == ("concluido", None)
    assert job.atualizado_em == DEPOIS
    gravada = Decupagem.model_validate_json(ambiente.decupagens.gravadas["j1"])
    # O bloco `video` vem do Job, não do modelo.
    assert (gravada.video.sha256, gravada.video.duracao_ms) == (SHA, 60_000)
    chamada = ambiente.transporte.chamadas[0]
    assert chamada.video_uri == "gs://teste-aceitos/j1/proxy.mp4"
    assert chamada.rotulos == {"job_id": "j1"}


def test_o_job_concluido_leva_a_versao_do_pipeline_da_decupagem() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j1")

    _analisar(ambiente, "j1")

    gravada = Decupagem.model_validate_json(ambiente.decupagens.gravadas["j1"])
    assert (
        ambiente.job("j1").versao_pipeline == gravada.versao_pipeline == VERSAO_PIPELINE
    )


def test_timecode_de_origem_do_job_vai_ao_bloco_video() -> None:
    ambiente = _ambiente(BOA, BOA)
    ambiente.registrar("j11", timecode_origem="01:00:00;00")
    ambiente.registrar("j12")

    _analisar(ambiente, "j11")
    _analisar(ambiente, "j12")

    def video(job_id: str) -> Video:
        return Decupagem.model_validate_json(ambiente.decupagens.gravadas[job_id]).video

    assert video("j11").timecode_origem == "01:00:00;00"
    assert video("j12").timecode_origem is None


def test_cortes_do_job_viram_os_planos_da_decupagem() -> None:
    ambiente = _ambiente(BOA)
    # O plano do modelo vai de 0 a 4 s.
    ambiente.registrar("j9", cortes_ms=[1_000, 2_000])

    _analisar(ambiente, "j9")

    gravada = Decupagem.model_validate_json(ambiente.decupagens.gravadas["j9"])
    assert [(p.inicio_ms, p.fim_ms) for p in gravada.planos] == [
        (0, 1_000),
        (1_000, 2_000),
    ]
    assert {(p.inicio_modelo_ms, p.fim_modelo_ms) for p in gravada.planos} == {
        (0, 4_000)
    }


def test_cada_intervalo_entre_cortes_fica_com_a_sua_descricao() -> None:
    resposta = resposta_em_mm_ss()
    resposta["planos"] = [
        {
            "id": f"pla00{n}",
            "ambiente": a,
            "acao": acao,
            "plano_limpo": False,
            "inicio": i,
            "fim": f,
        }
        for n, (a, acao, i, f) in enumerate(
            [
                ("estúdio", "apresentadora abre o programa", "00:00", "00:20"),
                ("rua", "carro na estrada", "00:20", "00:40"),
                ("tela preta", None, "00:40", "01:00"),
            ],
            1,
        )
    ]
    ambiente = _ambiente(json.dumps(resposta))
    ambiente.registrar("j13", cortes_ms=[20_000, 40_000])

    _analisar(ambiente, "j13")

    gravada = Decupagem.model_validate_json(ambiente.decupagens.gravadas["j13"])
    assert [(p.inicio_ms, p.fim_ms, p.ambiente, p.acao) for p in gravada.planos] == [
        (0, 20_000, "estúdio", "apresentadora abre o programa"),
        (20_000, 40_000, "rua", "carro na estrada"),
        (40_000, 60_000, "tela preta", None),
    ]
    assert "(MM:SS): 00:20, 00:40." in ambiente.transporte.chamadas[0].instrucao


def test_job_sem_cortes_nao_muda_os_planos_do_modelo() -> None:
    sem, com = _ambiente(BOA), _ambiente(BOA)
    sem.registrar("j10")
    com.registrar("j10", cortes_ms=[])

    _analisar(sem, "j10")
    _analisar(com, "j10")

    assert sem.decupagens.gravadas["j10"] == com.decupagens.gravadas["j10"]
    gravada = Decupagem.model_validate_json(sem.decupagens.gravadas["j10"])
    assert all(p.inicio_modelo_ms is None for p in gravada.planos)


def test_programa_do_job_leva_o_perfil_a_instrucao() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j8", programa="TV Fama")

    _analisar(ambiente, "j8")

    assert (
        perfis_da_tv_fama()["TV Fama"].texto()
        in ambiente.transporte.chamadas[0].instrucao
    )


def test_analise_falhou_grava_falhou_sem_decupagem() -> None:
    ambiente = _ambiente(ErroHttp(400))
    ambiente.registrar("j2")

    assert _analisar(ambiente, "j2") == "falhou"

    job = ambiente.job("j2")
    assert (job.estado, job.codigo_falha) == ("falhou", "analise_falhou")
    assert "j2" not in ambiente.decupagens.gravadas


@pytest.mark.parametrize(
    "estado", ["aguardando_upload", "validando", "concluido", "falhou", "cancelado"]
)
def test_job_fora_de_analisando_nao_muda(estado: str) -> None:
    ambiente = _ambiente()
    antes = ambiente.registrar("j3", estado)

    assert _analisar(ambiente, "j3") == "ignorado"

    assert ambiente.job("j3") == antes
    assert ambiente.transporte.chamadas == []
    assert "j3" not in ambiente.decupagens.gravadas


def test_job_inexistente_sai_sem_fazer_nada() -> None:
    ambiente = _ambiente()

    assert _analisar(ambiente, "fantasma") == "ignorado"

    assert ambiente.repositorio.obter("fantasma") is None
    assert ambiente.transporte.chamadas == []


@pytest.mark.skipif(
    not (EMULADOR_FIRESTORE and EMULADOR_STORAGE), reason="sem emuladores"
)
def test_decupagem_gravada_e_servida_pela_api_web() -> None:
    sufixo = uuid.uuid4().hex[:8]
    storage = ClienteStorage(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
        client_options={"api_endpoint": EMULADOR_STORAGE},
    )
    storage.create_bucket(f"teste-decupagens-{sufixo}")
    repositorio = RepositorioFirestore(
        firestore.Client(
            project="teste",
            credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
        ),
        colecao=f"jobs-{sufixo}",
    )
    ambiente = _ambiente(BOA, repositorio=repositorio)
    ambiente.registrar("j4")
    ambiente.executar = lambda job_id: executar(
        job_id,
        repositorio,
        DecupagensStorage(storage, "aceitos", f"teste-decupagens-{sufixo}"),
        ambiente.transporte,
        dormir=lambda _s: None,
        relogio=lambda: DEPOIS,
    )
    _analisar(ambiente, "j4")
    credencial = _credencial_local()
    armazenamento = ArmazenamentoStorage(
        storage,
        "quarentena",
        "aceitos",
        f"teste-decupagens-{sufixo}",
        assinatura=lambda: {"credentials": credencial},
    )

    class Verificador:
        def verificar(self, token: str) -> Usuario:
            return Usuario(uid="u", email="a@b.c")

    web = TestClient(criar_app_web(Verificador(), ambiente.repositorio, armazenamento))

    resposta = web.get("/v1/jobs/j4/decupagem", headers={"Authorization": "Bearer x"})

    assert resposta.status_code == 200
    assert resposta.json()["programa"]["resumo"] == "Jornal da noite"
    assert json.loads(resposta.content)["video"]["sha256"] == SHA


def _cancelar_durante_a_chamada(ambiente: Ambiente, job_id: str) -> None:
    """O cancelamento chega enquanto o Gemini ainda responde."""
    chamar = ambiente.transporte.gerar

    def chamar_e_cancelar(chamada: Chamada) -> str:
        ambiente.repositorio.salvar(
            ambiente.job(job_id).model_copy(update={"estado": "cancelado"})
        )
        return chamar(chamada)

    ambiente.transporte.gerar = chamar_e_cancelar  # type: ignore[method-assign]


def test_cancelado_durante_a_analise_continua_cancelado_e_sem_decupagem_visivel() -> (
    None
):
    ambiente = _ambiente(BOA)
    ambiente.registrar("j6")
    _cancelar_durante_a_chamada(ambiente, "j6")

    assert _analisar(ambiente, "j6") == "cancelado"

    assert ambiente.job("j6").estado == "cancelado"


def test_cancelado_durante_a_analise_nao_vira_falhou_se_o_gemini_falhar() -> None:
    ambiente = _ambiente(ErroHttp(400))
    ambiente.registrar("j7")
    _cancelar_durante_a_chamada(ambiente, "j7")

    assert _analisar(ambiente, "j7") == "cancelado"

    job = ambiente.job("j7")
    assert (job.estado, job.codigo_falha) == ("cancelado", None)


class _CancelaDepoisDaUltimaLeitura(RepositorioEmMemoria):
    """O cancelamento chega logo depois de cada leitura do Job em `analisando`.

    A leitura devolve o Job de antes do cancelamento, como se ele chegasse
    entre a última releitura do worker e a gravação.
    """

    def obter(self, job_id: str) -> Job | None:
        job = super().obter(job_id)
        if job is not None and job.estado == "cancelado":
            return job.model_copy(update={"estado": "analisando"})
        if job is not None and job.estado == "analisando":
            self.salvar(job.model_copy(update={"estado": "cancelado"}))
        return job


@pytest.mark.parametrize("resposta", [BOA, ErroHttp(400)])
def test_cancelamento_depois_da_ultima_leitura_nao_e_sobrescrito(
    resposta: str | Exception,
) -> None:
    repositorio = _CancelaDepoisDaUltimaLeitura()
    ambiente = _ambiente(resposta, repositorio=repositorio)
    ambiente.registrar("j9")

    assert _analisar(ambiente, "j9") == "cancelado"

    job = RepositorioEmMemoria.obter(repositorio, "j9")
    assert job is not None
    assert (job.estado, job.codigo_falha) == ("cancelado", None)
    # Uma Decupagem já gravada fica invisível: a leitura exige `concluido`.


def test_a_transcricao_do_job_entra_na_instrucao() -> None:
    from api.transcricao import Palavra, Transcricao, TranscricoesEmMemoria

    transcricoes = TranscricoesEmMemoria()
    transcricoes.gravar_transcricao(
        "j9",
        Transcricao(
            modelo="m",
            idioma="pt",
            palavras=[Palavra(texto="olá", inicio_s=3.0, fim_s=3.4)],
        ),
    )
    repositorio = RepositorioEmMemoria()
    transporte = TransporteFalso(BOA)
    decupagens = DecupagensEmMemoria("teste-aceitos")
    ambiente = Ambiente(
        repositorio,
        decupagens,
        transporte,
        lambda job_id: executar(
            job_id,
            repositorio,
            decupagens,
            transporte,
            transcricoes,
            dormir=lambda _s: None,
            perfis=perfis_da_tv_fama(),
            relogio=lambda: DEPOIS,
        ),
    )
    ambiente.registrar("j9")

    _analisar(ambiente, "j9")

    assert "[00:03] olá" in transporte.chamadas[0].instrucao
