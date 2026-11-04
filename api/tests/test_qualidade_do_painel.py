"""A fonte da aba Revisão do painel (#284): tempo de revisão por período, programa e pessoa,
e o período de São Paulo repassado à taxa de correção."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.jobs import Job, RepositorioEmMemoria
from api.qualidade_do_painel import QualidadeReal
from api.revisao import Pulso, RepositorioDeRevisaoEmMemoria

AGORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class SemDecupagens:
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        raise AssertionError("não devia ler a decupagem")
        yield b""


def _job(id: str, programa: str | None, duracao_s: float | None = None) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        estado="concluido",
        criado_por="u1",
        programa=programa,
        duracao_s=duracao_s,
        criado_em=AGORA,
        atualizado_em=AGORA,
    )


def _revisar(
    revisao: RepositorioDeRevisaoEmMemoria,
    job: str,
    uid: str,
    quando: datetime,
    ativo_s: int,
    duracao_s: float | None,
) -> None:
    """Um início e uma atividade `ativo_s` depois: soma esse tempo ativo."""
    base: dict[str, Any] = {"job_id": job, "uid": uid, "email": f"{uid}@x"}
    revisao.aplicar(
        Pulso(**base, quando=quando, evento="inicio", duracao_s=duracao_s), 10_000
    )
    revisao.aplicar(
        Pulso(**base, quando=quando + timedelta(seconds=ativo_s), evento="atividade"),
        10_000,
    )


def _qualidade() -> tuple[QualidadeReal, RepositorioDeRevisaoEmMemoria]:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("v1", "Hoje"))
    jobs.salvar(_job("v2", "Fala"))
    revisao = RepositorioDeRevisaoEmMemoria()
    return (
        QualidadeReal(
            jobs, SemDecupagens(), RepositorioDeCorrecoesEmMemoria(), revisao
        ),
        revisao,
    )


def test_tempo_de_revisao_filtra_por_periodo_programa_e_pessoa() -> None:
    qualidade, revisao = _qualidade()
    _revisar(revisao, "v1", "ana", datetime(2026, 11, 2, 15, tzinfo=UTC), 600, 3600)
    _revisar(revisao, "v2", "beto", datetime(2026, 11, 5, 15, tzinfo=UTC), 1200, 1800)
    _revisar(revisao, "v2", "ana", datetime(2026, 11, 5, 16, tzinfo=UTC), 60, None)

    def quem(
        desde: date | None, ate: date | None, programa: str | None, usuario: str | None
    ) -> set[tuple[str, str, str | None, float, float | None]]:
        return {
            (m.job_id, m.uid, m.programa, m.ativo_s, m.duracao_s)
            for m in qualidade.tempo_de_revisao(desde, ate, programa, usuario)
        }

    assert quem(None, None, None, None) == {
        ("v1", "ana", "Hoje", 600, 3600),
        ("v2", "beto", "Fala", 1200, 1800),
        ("v2", "ana", "Fala", 60, None),
    }
    assert quem(date(2026, 11, 3), None, None, None) == {
        ("v2", "beto", "Fala", 1200, 1800),
        ("v2", "ana", "Fala", 60, None),
    }
    assert quem(None, date(2026, 11, 4), None, None) == {
        ("v1", "ana", "Hoje", 600, 3600)
    }
    assert quem(None, None, "Fala", "ana") == {("v2", "ana", "Fala", 60, None)}


def test_o_periodo_e_de_dias_de_sao_paulo() -> None:
    qualidade, revisao = _qualidade()
    # 02:00 UTC do dia 3 ainda é dia 2 em São Paulo (-03:00).
    _revisar(revisao, "v1", "ana", datetime(2026, 11, 3, 2, tzinfo=UTC), 60, 3600)

    def n(desde: date | None, ate: date | None) -> int:
        return len(qualidade.tempo_de_revisao(desde, ate, None, None))

    assert n(None, date(2026, 11, 2)) == 1
    assert n(date(2026, 11, 3), None) == 0
    assert n(date(2026, 11, 2), date(2026, 11, 2)) == 1


def test_job_sem_programa_vem_sem_programa_e_job_apagado_fica_de_fora() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("v3", None))
    revisao = RepositorioDeRevisaoEmMemoria()
    qualidade = QualidadeReal(
        jobs, SemDecupagens(), RepositorioDeCorrecoesEmMemoria(), revisao
    )
    _revisar(revisao, "v3", "ana", datetime(2026, 11, 2, 15, tzinfo=UTC), 60, 3600)
    _revisar(revisao, "v9", "ana", datetime(2026, 11, 2, 15, tzinfo=UTC), 60, 3600)

    assert [
        (m.job_id, m.programa)
        for m in qualidade.tempo_de_revisao(None, None, None, None)
    ] == [("v3", None)]


def test_a_duracao_e_a_do_job_e_sem_ela_a_da_medida() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("v1", "Hoje", duracao_s=1800))
    jobs.salvar(_job("v2", "Hoje"))
    revisao = RepositorioDeRevisaoEmMemoria()
    qualidade = QualidadeReal(
        jobs, SemDecupagens(), RepositorioDeCorrecoesEmMemoria(), revisao
    )
    _revisar(revisao, "v1", "ana", datetime(2026, 11, 2, 15, tzinfo=UTC), 60, None)
    _revisar(revisao, "v2", "ana", datetime(2026, 11, 2, 15, tzinfo=UTC), 60, 3600)

    assert {
        m.job_id: m.duracao_s
        for m in qualidade.tempo_de_revisao(None, None, None, None)
    } == {"v1": 1800, "v2": 3600}


def test_a_taxa_de_correcao_do_periodo_e_calculada_pelo_modulo_da_taxa() -> None:
    qualidade, _ = _qualidade()

    # Nenhuma correção nem pulso: nenhuma decupagem é lida (`SemDecupagens` falharia).
    assert (
        qualidade.taxa_de_correcao(date(2026, 11, 1), date(2026, 11, 30), "Hoje") == []
    )
