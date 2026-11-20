"""O fim do upload expirado na varredura diária (#782): o Job fecha também no painel."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.eventos_de_uso import EventoDeUso, EventosEmMemoria
from api.eventos_do_job import MensagemDeEvento, PublicadorEmMemoria
from api.fim_do_job import avisar_fins_pendentes
from api.jobs import RepositorioEmMemoria, expirar_uploads
from api.lixeira import ArquivosEmMemoria
from api.modelo_do_job import FiltroDeJobs, Job
from api.purga import Purga, rodar_a_varredura_diaria
from api.tests import test_jobs_do_painel as painel
from api.tests import test_resumos_de_uso as resumos
from api.tests.test_jobs import ArmazenamentoFalso
from api.webhook import (
    CofreEmMemoria,
    RepositorioDeWebhooksEmMemoria,
    registrar_webhook,
)

CRIADO = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
DIA1 = CRIADO + timedelta(hours=25)  # a varredura que expira o upload
DIA4 = DIA1 + timedelta(days=3)


class Quebra(Exception):
    pass


class PublicadorQuePodeFalhar(PublicadorEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.falhas = 0  # as próximas publicações que falham

    def publicar(self, mensagem: MensagemDeEvento) -> None:
        if self.falhas:
            self.falhas -= 1
            raise Quebra
        super().publicar(mensagem)


class EventosQuePodemFalhar(EventosEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.falhas = 0

    def publicar(self, evento: EventoDeUso) -> None:
        if self.falhas:
            self.falhas -= 1
            raise Quebra
        super().publicar(evento)


def _job(id: str = "j1", sistema: str | None = "Playout") -> Job:
    return Job(
        id=id,
        nome="clipe.mp4",
        tamanho_bytes=10,
        estado="aguardando_upload",
        criado_por=f"sistema:{sistema}" if sistema else "ana",
        sistema=sistema,
        programa="Hoje",
        criado_em=CRIADO,
        atualizado_em=CRIADO,
    )


class Mundo:
    def __init__(self, *jobs: Job, com_webhook: bool = True) -> None:
        self.jobs = RepositorioEmMemoria()
        for job in jobs or (_job(),):
            self.jobs.salvar(job)
        self.webhooks = RepositorioDeWebhooksEmMemoria()
        if com_webhook:
            registrar_webhook(
                "Playout",
                "https://playout.redetv.example/cb",
                CofreEmMemoria(),
                self.webhooks,
                lambda host: ["93.184.216.34"],
            )
        self.publicador = PublicadorQuePodeFalhar()
        self.eventos = EventosQuePodemFalhar()

    def varrer(self, agora: datetime) -> None:
        purga = Purga(
            self.jobs,
            RepositorioDeCorrecoesEmMemoria(),
            ArquivosEmMemoria(),
            None,
            RepositorioDeAuditoriaEmMemoria(),
            lambda: agora,
        )
        rodar_a_varredura_diaria(
            self.jobs,
            purga,
            ArmazenamentoFalso(),
            lambda: 0,
            agora,
            lambda: 0,
            lambda: avisar_fins_pendentes(
                self.jobs, self.webhooks, self.publicador, self.eventos, agora
            ),
        )

    def job(self, id: str = "j1") -> Job:
        job = self.jobs.obter(id)
        assert job is not None
        return job


def test_o_upload_expirado_de_sistema_com_webhook_publica_os_dois_fins() -> None:
    m = Mundo()

    m.varrer(DIA1)

    (mensagem,) = m.publicador.mensagens
    assert (mensagem.sistema, mensagem.evento.tipo) == ("Playout", "job.falhou")
    assert mensagem.evento.codigo_falha == "upload_expirado"
    assert mensagem.evento.data == DIA1
    (evento,) = m.eventos.publicados
    assert (evento.tipo, evento.job_id, evento.estado) == (
        "fim_de_processamento",
        "j1",
        "falhou",
    )
    assert (evento.quem_tipo, evento.quem_id) == ("sistema", "Playout")
    assert evento.quando == DIA1
    assert m.job().fim_a_avisar == []


def test_sem_webhook_so_o_evento_do_painel_sai_e_a_pendencia_some() -> None:
    m = Mundo(_job(sistema=None), com_webhook=False)

    m.varrer(DIA1)

    assert m.publicador.mensagens == []
    (evento,) = m.eventos.publicados
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "ana")
    assert m.job().fim_a_avisar == []


def test_a_varredura_seguinte_nao_republica_o_que_ja_saiu() -> None:
    m = Mundo()
    m.varrer(DIA1)

    m.varrer(DIA1 + timedelta(days=1))

    assert len(m.publicador.mensagens) == 1
    assert len(m.eventos.publicados) == 1


def test_com_o_segundo_evento_falhando_a_seguinte_publica_so_ele_com_a_hora_dela() -> (
    None
):
    m = Mundo()
    m.eventos.falhas = 1

    m.varrer(DIA1)

    assert len(m.publicador.mensagens) == 1 and m.eventos.publicados == []
    assert m.job().fim_a_avisar == ["uso"]

    m.varrer(DIA4)

    assert len(m.publicador.mensagens) == 1
    (evento,) = m.eventos.publicados
    assert evento.quando == DIA4
    assert m.job().fim_a_avisar == []


def test_o_webhook_repetido_leva_o_mesmo_id() -> None:
    m = Mundo()
    m.publicador.falhas = 1
    m.varrer(DIA1)
    assert m.publicador.mensagens == [] and len(m.eventos.publicados) == 1
    m.publicador.falhas = 0
    primeira = m.job()
    assert primeira.fim_a_avisar == ["webhook"]

    m.varrer(DIA4)
    # Um segundo ciclo igual, de outro Job, dá outro id: o id é do Job.
    (mensagem,) = m.publicador.mensagens
    assert mensagem.evento.data == DIA4
    m2 = Mundo()
    m2.varrer(DIA1)
    assert m2.publicador.mensagens[0].evento.id == mensagem.evento.id
    assert len(m.eventos.publicados) == 1


def test_publicador_falhando_sempre_deixa_a_pendencia_e_a_purga_segue() -> None:
    m = Mundo(_job("j1"), _job("j2"))
    m.publicador.falhas = 99
    m.eventos.falhas = 99

    m.varrer(DIA1)

    for id in ("j1", "j2"):
        assert m.job(id).estado == "falhou"
        assert sorted(m.job(id).fim_a_avisar) == ["uso", "webhook"]


def test_webhook_falhando_sempre_nao_impede_o_evento_do_painel() -> None:
    m = Mundo()
    m.publicador.falhas = 99

    m.varrer(DIA1)
    m.varrer(DIA4)

    assert len(m.eventos.publicados) == 1
    assert m.job().fim_a_avisar == ["webhook"]
    m.publicador.falhas = 0
    m.varrer(DIA4 + timedelta(days=1))
    assert len(m.publicador.mensagens) == 1
    assert len(m.eventos.publicados) == 1
    assert m.job().fim_a_avisar == []


def test_job_expirado_antes_da_mudanca_nao_publica_nada() -> None:
    antigo = _job("velho").model_copy(
        update={"estado": "falhou", "codigo_falha": "upload_expirado"}
    )
    m = Mundo(antigo, _job("novo").model_copy(update={"criado_em": DIA1}))

    m.varrer(DIA1)

    assert m.publicador.mensagens == [] and m.eventos.publicados == []


def _gravar(banco: sqlite3.Connection, evento: EventoDeUso) -> None:
    linha = evento.model_dump(mode="json", exclude={"filtros"})
    linha["quando"] = evento.quando.isoformat()
    banco.execute(
        f"INSERT INTO eventos_de_uso ({', '.join(linha)}) "
        f"VALUES ({', '.join('?' * len(linha))})",
        list(linha.values()),
    )


def test_repeticao_tres_dias_depois_ainda_fecha_o_job_na_tabela_do_painel() -> None:
    m = Mundo()
    m.eventos.falhas = 1
    m.varrer(DIA1)
    banco = painel._banco()
    painel._evento(
        banco, "env", "envio", CRIADO.isoformat(), job_id="j1", programa="Hoje"
    )
    painel._rodar(banco)
    assert painel._linhas(banco)["j1"]["estado"] == "em_andamento"

    m.varrer(DIA4)
    for evento in m.eventos.publicados:
        _gravar(banco, evento)
    # A tabela dos Jobs só lê os eventos dos últimos 2 dias pela hora do evento.
    painel._rodar(banco, f"'{(DIA4 - timedelta(days=2)).isoformat()}'")

    assert painel._linhas(banco)["j1"]["estado"] == "falhou"


def test_marca_falhando_depois_do_evento_repete_com_id_novo_e_conta_uma_falha() -> None:
    m = Mundo()
    banco = resumos._banco()
    trocar = m.jobs.trocar
    chamadas: list[int] = []

    def trocar_que_quebra(job_id: str, mudar: Callable[[Job], Any]) -> Job | None:
        chamadas.append(1)
        if len(chamadas) == 2:  # a marca do evento de uso, depois da do webhook
            raise Quebra
        return trocar(job_id, mudar)

    m.jobs.trocar = trocar_que_quebra  # type: ignore[method-assign]
    m.varrer(DIA1)
    antes = list(m.eventos.publicados)
    assert m.job().fim_a_avisar == ["uso"]
    for evento in antes:
        _gravar(banco, evento)
    resumos._resumir(banco)

    m.varrer(DIA4)

    novos = m.eventos.publicados[len(antes) :]
    assert len(novos) == 1
    assert novos[0].id not in {e.id for e in antes}
    _gravar(banco, novos[0])
    resumos._resumir(banco, f"'{(DIA4 - timedelta(days=2)).isoformat()}'")
    (por_usuario,) = resumos._tabela(banco, "uso_por_usuario", "quem_id")
    assert por_usuario["videos_falhos"] == 1
    assert banco.execute(
        "SELECT SUM(videos_falhos) FROM uso_por_dia_e_programa"
    ).fetchone() == (1,)


def test_a_pendencia_e_gravada_pela_transicao() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job())

    assert expirar_uploads(repositorio, ArmazenamentoFalso(), DIA1) == ["j1"]

    pendentes = repositorio.consultar(
        FiltroDeJobs(com_fim_a_avisar=True, na_lixeira=None)
    ).jobs
    assert [j.id for j in pendentes] == ["j1"]
    assert sorted(pendentes[0].fim_a_avisar) == ["uso", "webhook"]


def test_a_purga_sem_um_dos_topicos_sai_com_erro_antes_de_mexer_em_job(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from api.purga import main

    base = {
        "GCP_PROJECT_ID": "p",
        "BUCKET_QUARENTENA": "q",
        "BUCKET_ACEITOS": "a",
        "BUCKET_DECUPAGENS": "d",
        "BUCKET_REFERENCIAS": "r",
        "BUSCA_COLECAO": "c",
    }
    for falta in ("PUBSUB_TOPICO_EVENTOS", "PUBSUB_TOPICO_USO"):
        ambiente = {
            **base,
            "PUBSUB_TOPICO_EVENTOS": "t1",
            "PUBSUB_TOPICO_USO": "t2",
        }
        del ambiente[falta]
        assert main(ambiente) == 2
        assert falta in capsys.readouterr().err


def test_falha_pontual_num_job_nao_deixa_os_seguintes_pendentes() -> None:
    m = Mundo(_job("j1"), _job("j2"))
    obter = m.jobs.obter

    def obter_que_quebra(job_id: str) -> Job | None:
        if job_id == "j2":
            raise Quebra
        return obter(job_id)

    m.jobs.obter = obter_que_quebra  # type: ignore[method-assign]

    m.varrer(DIA1)

    assert sorted(str(e.job_id) for e in m.eventos.publicados) == ["j1", "j2"]
    assert obter("j1").fim_a_avisar == []  # type: ignore[union-attr]


def test_a_varredura_avisa_os_antigos_antes_de_expirar_e_os_novos_depois() -> None:
    antigo = _job("velho").model_copy(
        update={"estado": "falhou", "fim_a_avisar": ["uso"]}
    )
    m = Mundo(antigo, _job("novo"))
    vistos: list[tuple[str, ...]] = []

    def avisar() -> int:
        vistos.append(
            tuple(
                j.id
                for j in m.jobs.consultar(
                    FiltroDeJobs(estados=frozenset({"falhou"}), na_lixeira=None)
                ).jobs
            )
        )
        return 0

    purga = Purga(
        m.jobs,
        RepositorioDeCorrecoesEmMemoria(),
        ArquivosEmMemoria(),
        None,
        RepositorioDeAuditoriaEmMemoria(),
        lambda: DIA1,
    )
    rodar_a_varredura_diaria(
        m.jobs, purga, ArmazenamentoFalso(), lambda: 0, DIA1, lambda: 0, avisar
    )

    assert [sorted(v) for v in vistos] == [["velho"], ["novo", "velho"]]


def test_a_expiracao_que_falha_nao_impede_o_aviso_do_antigo() -> None:
    antigo = _job("velho").model_copy(
        update={"estado": "falhou", "fim_a_avisar": ["uso"]}
    )
    m = Mundo(antigo, _job("novo"))
    consultar = m.jobs.consultar

    def consultar_que_quebra(filtro: FiltroDeJobs) -> Any:
        if filtro.estados:  # a consulta da expiração
            raise Quebra
        return consultar(filtro)

    m.jobs.consultar = consultar_que_quebra  # type: ignore[method-assign]

    m.varrer(DIA1)

    assert [e.job_id for e in m.eventos.publicados] == ["velho"]
