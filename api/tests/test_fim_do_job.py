"""O aviso do `falhou` que o Workflows grava (#379), sem rede."""

from datetime import UTC, datetime, timedelta

from api.eventos_de_uso import EventosEmMemoria
from api.eventos_do_job import PublicadorEmMemoria
from api.fim_do_job import avisar_o_fim, main
from api.jobs import Job, RepositorioEmMemoria
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
