"""O aviso do `falhou` que o Workflows grava (#379), sem rede."""

from datetime import UTC, datetime, timedelta

import pytest

from api.eventos_de_uso import EventoDeUso, EventosEmMemoria
from api.eventos_do_job import MensagemDeEvento, PublicadorEmMemoria
from api.fim_do_job import avisar_o_fim, main
from api.jobs import RepositorioEmMemoria
from api.modelo_do_job import Job
from api.webhook import (
    CofreEmMemoria,
    RepositorioDeWebhooksEmMemoria,
    registrar_webhook,
)

AGORA = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _job(estado: str = "falhou", **campos: object) -> Job:
    return Job.model_validate(
        {
            "id": "job-1",
            "nome": "a.mp4",
            "tamanho_bytes": 10,
            "estado": estado,
            "codigo_falha": "arquivo_corrompido" if estado == "falhou" else None,
            "criado_por": "sistema:Legado",
            "sistema": "Legado",
            "programa": "TV Fama",
            "criado_em": AGORA - timedelta(minutes=5),
            "atualizado_em": AGORA,
            **campos,
        }
    )


class Mundo:
    def __init__(self, job: Job | None = None) -> None:
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(job or _job())
        self.webhooks = RepositorioDeWebhooksEmMemoria()
        registrar_webhook(
            "Legado",
            "https://legado.redetv.example/callback",
            CofreEmMemoria(),
            self.webhooks,
            lambda host: ["93.184.216.34"],
        )
        self.publicador = PublicadorEmMemoria()
        self.eventos = EventosEmMemoria()

    def avisar(self, job_id: str = "job-1") -> bool:
        return avisar_o_fim(
            job_id,
            self.jobs,
            self.webhooks,
            self.publicador,
            self.eventos,
        )


def test_a_falha_gravada_pelo_workflow_publica_o_webhook_e_o_evento_de_uso() -> None:
    m = Mundo()

    assert m.avisar() is True

    (mensagem,) = m.publicador.mensagens
    assert mensagem.sistema == "Legado"
    assert (mensagem.evento.tipo, mensagem.evento.codigo_falha) == (
        "job.falhou",
        "arquivo_corrompido",
    )
    (evento,) = m.eventos.publicados
    assert evento.tipo == "fim_de_processamento"
    assert (evento.quem_tipo, evento.quem_id) == ("sistema", "Legado")
    assert (evento.job_id, evento.programa) == ("job-1", "TV Fama")
    assert (evento.estado, evento.codigo_falha) == ("falhou", "arquivo_corrompido")
    assert evento.segundos_de_processamento == 300
    # A hora é a da falha gravada, não a de quando o aviso roda.
    assert mensagem.evento.data == evento.quando == AGORA


def test_a_mesma_falha_marcada_duas_vezes_publica_uma_vez_so() -> None:
    m = Mundo()

    assert m.avisar() is True
    assert m.avisar() is False

    assert len(m.publicador.mensagens) == 1
    assert len(m.eventos.publicados) == 1


def test_falha_de_novo_depois_de_reprocessar_avisa_de_novo() -> None:
    m = Mundo()
    m.avisar()
    m.jobs.salvar(m.jobs.obter("job-1").model_copy(update={"reprocessamentos": 1}))  # type: ignore[union-attr]

    assert m.avisar() is True

    assert len(m.publicador.mensagens) == 2
    assert len(m.eventos.publicados) == 2


def test_job_que_nao_falhou_ou_nao_existe_nao_avisa() -> None:
    for estado in ("cancelado", "concluido", "analisando"):
        m = Mundo(_job(estado))
        assert m.avisar() is False
        assert m.publicador.mensagens == [] and m.eventos.publicados == []

    assert Mundo().avisar("outro") is False


def test_sem_webhook_o_evento_de_uso_sai_mesmo_assim() -> None:
    m = Mundo(_job(sistema=None, criado_por="ana"))

    m.avisar()

    assert m.publicador.mensagens == []
    (evento,) = m.eventos.publicados
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "ana")


def test_o_job_exige_job_id_e_projeto_no_ambiente() -> None:
    assert main({}) == 2
    assert main({"GCP_PROJECT_ID": "p"}) == 2
    ambiente = {"GCP_PROJECT_ID": "p", "JOB_ID": "j", "PUBSUB_TOPICO_EVENTOS": "t"}
    assert main(ambiente) == 2


def test_tempo_esgotado_na_validacao_tambem_monta_o_evento_de_fim() -> None:
    m = Mundo(_job(codigo_falha="processamento_demorou_demais"))

    assert m.avisar() is True

    (mensagem,) = m.publicador.mensagens
    assert mensagem.evento.codigo_falha == "processamento_demorou_demais"
    (evento,) = m.eventos.publicados
    assert evento.codigo_falha == "processamento_demorou_demais"


class _FalhaNoPubSub(Exception):
    pass


class PublicadorQueFalha(PublicadorEmMemoria):
    def __init__(self, falhas: int) -> None:
        super().__init__()
        self.falhas = falhas

    def publicar(self, mensagem: MensagemDeEvento) -> None:
        if self.falhas:
            self.falhas -= 1
            raise _FalhaNoPubSub
        super().publicar(mensagem)


class EventosQueFalham(EventosEmMemoria):
    def __init__(self, falhas: int) -> None:
        super().__init__()
        self.falhas = falhas

    def publicar(self, evento: EventoDeUso) -> None:
        if self.falhas:
            self.falhas -= 1
            raise _FalhaNoPubSub
        super().publicar(evento)


def _marcado(m: Mundo) -> bool:
    return m.jobs.obter("job-1").fim_avisado_no_reprocessamento == 0  # type: ignore[union-attr]


def test_falha_no_segundo_evento_repete_so_o_que_nao_saiu() -> None:
    m = Mundo()
    m.eventos = EventosQueFalham(1)

    with pytest.raises(_FalhaNoPubSub):
        m.avisar()
    assert len(m.publicador.mensagens) == 1 and m.eventos.publicados == []
    assert not _marcado(m)

    assert m.avisar() is True

    assert len(m.publicador.mensagens) == 1
    assert len(m.eventos.publicados) == 1
    assert _marcado(m)


def test_falha_no_primeiro_evento_nao_marca_e_a_repeticao_envia_os_dois() -> None:
    m = Mundo()
    m.publicador = PublicadorQueFalha(1)

    with pytest.raises(_FalhaNoPubSub):
        m.avisar()
    assert m.eventos.publicados == [] and not _marcado(m)

    m.avisar()

    assert len(m.publicador.mensagens) == 1 and len(m.eventos.publicados) == 1


def test_o_webhook_do_mesmo_fim_tem_o_mesmo_id_nas_duas_tentativas() -> None:
    m = Mundo()
    ids = []
    for _ in range(2):
        # A marcação falha depois de publicar: a repetição publica de novo.
        m.jobs.trocar(
            "job-1", lambda j: {"fim_webhook_enviado_no_reprocessamento": None}
        )
        m.avisar()
        m.jobs.trocar("job-1", lambda j: {"fim_avisado_no_reprocessamento": None})
        ids.append(m.publicador.mensagens[-1].evento.id)

    assert ids[0] == ids[1]


def test_publicador_falhando_sempre_faz_o_main_sair_com_erro_sem_marcar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m = Mundo()
    m.publicador = PublicadorQueFalha(99)
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "JOB_ID": "job-1",
        "PUBSUB_TOPICO_EVENTOS": "t",
        "PUBSUB_TOPICO_USO": "u",
    }
    from api import fim_do_job

    monkeypatch.setattr(fim_do_job, "cliente_do_firestore", lambda *a, **k: None)
    monkeypatch.setattr(
        fim_do_job,
        "_dependencias",
        lambda cliente, amb: (m.jobs, m.webhooks, m.publicador, m.eventos),
    )

    assert fim_do_job.main(ambiente) == 1
    assert not _marcado(m)


def test_sem_webhook_cadastrado_nao_e_erro_e_marca() -> None:
    m = Mundo(_job(sistema="Outro"))

    assert m.avisar() is True

    assert m.publicador.mensagens == []
    assert len(m.eventos.publicados) == 1
    assert _marcado(m)


def test_aviso_antigo_nao_apaga_o_marcador_da_passada_nova() -> None:
    m = Mundo()
    m.eventos = EventosQueFalham(1)

    class ReprocessaNoMeioDoAvisoAntigo(PublicadorEmMemoria):
        feito = False

        def publicar(self, mensagem: MensagemDeEvento) -> None:
            super().publicar(mensagem)
            if not self.feito:
                self.feito = True
                # Enquanto o aviso da passada 0 publica, o Job é reprocessado, falha de
                # novo e o aviso da passada 1 publica o webhook e falha no uso.
                m.jobs.trocar("job-1", lambda j: {"reprocessamentos": 1})
                with pytest.raises(_FalhaNoPubSub):
                    m.avisar()

    m.publicador = ReprocessaNoMeioDoAvisoAntigo()

    assert m.avisar() is False

    job = m.jobs.obter("job-1")
    assert job is not None
    assert job.fim_webhook_enviado_no_reprocessamento == 1
    assert job.fim_avisado_no_reprocessamento is None

    assert m.avisar() is True

    assert len(m.eventos.publicados) == 1
    assert len(m.publicador.mensagens) == 2
