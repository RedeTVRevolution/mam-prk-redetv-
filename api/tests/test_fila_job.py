"""O Job que amostra a fila de processamento no log (#288), sem nuvem."""

import json
from datetime import UTC, datetime, timedelta

from api.fila_job import ESTADOS_DA_FILA, amostrar_a_fila
from api.jobs import Job, RepositorioEmMemoria

AGORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _job(id: str, estado: str, minutos: float) -> Job:
    criado = AGORA - timedelta(minutes=minutos)
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        sha256="a" * 64,
        duracao_s=60.0,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        criado_em=criado,
        atualizado_em=AGORA,
    )


def _amostrar(*jobs: Job) -> dict[str, dict[str, object]]:
    repositorio = RepositorioEmMemoria()
    for job in jobs:
        repositorio.salvar(job)
    linhas: list[str] = []
    amostrar_a_fila(repositorio, AGORA, linhas.append)
    registros = [json.loads(linha) for linha in linhas]
    assert {r["evento"] for r in registros} == {"fila_de_jobs"}
    return {r["estado"]: r for r in registros}


def test_cada_estado_da_fila_sai_com_a_quantidade_e_a_idade_do_mais_antigo() -> None:
    por_estado = _amostrar(
        _job("a", "analisando", 30),
        _job("b", "analisando", 90),
        _job("c", "validando", 5),
    )

    assert por_estado["analisando"]["quantidade"] == 2
    assert por_estado["analisando"]["idade_do_mais_antigo_s"] == 5400
    assert por_estado["validando"]["quantidade"] == 1
    assert por_estado["validando"]["idade_do_mais_antigo_s"] == 300


def test_estado_vazio_sai_com_zero_para_a_fila_vazia_aparecer_no_painel() -> None:
    por_estado = _amostrar(_job("a", "analisando", 1))

    assert set(por_estado) == set(ESTADOS_DA_FILA)
    assert por_estado["aguardando_upload"]["quantidade"] == 0
    assert por_estado["aguardando_upload"]["idade_do_mais_antigo_s"] == 0


def test_job_que_terminou_nao_entra_na_fila() -> None:
    por_estado = _amostrar(
        _job("a", "concluido", 600), _job("b", "falhou", 600), _job("c", "cancelado", 6)
    )

    assert all(r["quantidade"] == 0 for r in por_estado.values())
