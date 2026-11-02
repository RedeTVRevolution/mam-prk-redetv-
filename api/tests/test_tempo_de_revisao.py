"""O comando `make tempo-de-revisao` (#251): CSV por vídeo e por pessoa."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest

from api.revisao import Pulso, RepositorioDeRevisaoEmMemoria
from api.tempo_de_revisao import listar, main

BASE = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _pulsar(
    repo: RepositorioDeRevisaoEmMemoria, job: str, uid: str, de: float, ate: float
) -> None:
    for evento, segundos in (("inicio", de), ("fim", ate)):
        repo.aplicar(
            Pulso(
                job_id=job,
                uid=uid,
                email=f"{uid}@redetv.com.br",
                quando=BASE + timedelta(seconds=segundos),
                evento=evento,  # type: ignore[arg-type]
                duracao_s=1800.0 if job == "j1" else None,
            ),
            300,
        )


def _linhas(
    repo: RepositorioDeRevisaoEmMemoria, desde: datetime | None = None
) -> list[dict[str, str]]:
    saida: list[str] = []
    listar(repo, desde, saida.append)
    return list(csv.DictReader(io.StringIO("\n".join(saida))))


def test_uma_linha_por_video_e_por_pessoa() -> None:
    repo = RepositorioDeRevisaoEmMemoria()
    _pulsar(repo, "j2", "u1", 0, 60)
    _pulsar(repo, "j1", "u2", 0, 150)
    _pulsar(repo, "j1", "u1", 0, 300)

    assert _linhas(repo) == [
        {
            "job_id": "j1",
            "pessoa": "u1@redetv.com.br",
            "uid": "u1",
            "minutos": "5.0",
            "sessoes": "1",
            "duracao_do_video_min": "30.0",
            "minutos_por_hora_de_video": "10.0",
        },
        {
            "job_id": "j1",
            "pessoa": "u2@redetv.com.br",
            "uid": "u2",
            "minutos": "2.5",
            "sessoes": "1",
            "duracao_do_video_min": "30.0",
            "minutos_por_hora_de_video": "5.0",
        },
        {
            "job_id": "j2",
            "pessoa": "u1@redetv.com.br",
            "uid": "u1",
            "minutos": "1.0",
            "sessoes": "1",
            "duracao_do_video_min": "",
            "minutos_por_hora_de_video": "",
        },
    ]


def test_desde_deixa_de_fora_o_que_parou_antes() -> None:
    repo = RepositorioDeRevisaoEmMemoria()
    _pulsar(repo, "j1", "u1", 0, 60)
    _pulsar(repo, "j2", "u1", 86400, 86460)

    linhas = _linhas(repo, BASE + timedelta(days=1))

    assert [linha["job_id"] for linha in linhas] == ["j2"]


def test_sem_medidas_sai_so_o_cabecalho() -> None:
    assert _linhas(RepositorioDeRevisaoEmMemoria()) == []


def test_sem_projeto_o_comando_avisa_e_sai_com_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([], {}) == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err


def test_desde_invalido_avisa_e_sai_com_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ontem"], {"GCP_PROJECT_ID": "p"}) == 2
    assert "ontem" in capsys.readouterr().err
