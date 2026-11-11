"""A lógica pura do teste em escala: Jobs falsos com prefixo, intervalo do apagar, contas."""

from datetime import UTC, datetime
from typing import Any

from api.firestore_em_escala import (
    FIM_DO_INTERVALO,
    PREFIXO,
    PROGRAMAS,
    casos,
    entradas_automaticas,
    entradas_compostas,
    job_falso,
    limites_do_apagar,
)

AGORA = datetime(2026, 11, 11, tzinfo=UTC)


class Colecao:
    def document(self, id: str) -> str:
        return id


def test_todo_job_falso_tem_o_prefixo_e_e_o_mesmo_para_o_mesmo_indice() -> None:
    jobs = [job_falso(i, AGORA) for i in range(300)]
    assert all(j.id.startswith(PREFIXO) for j in jobs)
    assert len({j.id for j in jobs}) == 300
    assert job_falso(7, AGORA) == jobs[7]
    assert {j.programa for j in jobs} <= set(PROGRAMAS)


def test_os_limites_do_apagar_cercam_so_os_ids_teste() -> None:
    ini, fim = limites_do_apagar(Colecao())
    assert (ini, fim) == ("teste_", "teste`")
    assert FIM_DO_INTERVALO == "teste" + chr(ord("_") + 1)
    assert ini <= "teste_0000001" < fim
    assert not ini <= "teste" < fim and not ini <= "testf" < fim
    assert not ini <= "teste`" < fim


def test_cancelado_nunca_cai_no_programa_grande_e_falhou_acontece() -> None:
    jobs = [job_falso(i, AGORA) for i in range(20_000)]
    assert not [
        j for j in jobs if j.estado == "cancelado" and j.programa == PROGRAMAS[0]
    ]
    assert any(j.estado == "cancelado" for j in jobs)
    assert any(j.estado == "falhou" and j.codigo_falha for j in jobs)


def test_contas_de_entradas_do_indice() -> None:
    doc: dict[str, Any] = {
        "a": 1,
        "b": None,
        "p": ["x", "y", "z"],
        "m": {"k": 1},
        "cortes_ms": [1, 2],
    }
    assert entradas_automaticas(doc) == 2 + 2 + 3 + 2
    assert entradas_compostas({"palavras": ["a", "b"]}) == 2 + 2 + 2 + 4 + 1 + 1


def test_os_casos_incluem_o_pior_caso_com_pagina_de_50() -> None:
    todos = casos(AGORA.date())
    assert [c for c in todos if "RUIM" in c.nome]
    assert all(c.filtro.limite == 50 for c in todos)
