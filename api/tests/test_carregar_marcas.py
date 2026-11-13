"""A leitura das Decupagens da carga de marcas (#150), com dublês."""

import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from api.carregar_marcas import decupagens_dos_jobs
from api.marcas import CatalogoDeMarcasEmMemoria, carregar_marcas


class _Decupagens:
    def __init__(self, por_job: dict[str, bytes]) -> None:
        self._por_job = por_job

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        yield self._por_job[job_id]  # KeyError: a Decupagem não abre


class _SemCorrecoes:
    def listar(self, job_id: str) -> list[Any]:
        return []


def _modelo(*marcas: str) -> bytes:
    return json.dumps(
        {
            "versao_esquema": "1.4",
            "comerciais": [
                {"marca": m, "tipo": "intervalo", "inicio_ms": 0, "fim_ms": 1000}
                for m in marcas
            ],
            "pessoas": [],
            "pautas": [],
        }
    ).encode()


def test_a_decupagem_que_nao_abre_e_pulada_com_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    jobs = [SimpleNamespace(id="sem-arquivo", estado="concluido")]
    # o log vem da leitura corrigida do módulo; o `configurar` do log estruturado troca os
    # handlers da raiz, então ligo o do caplog direto
    logger = logging.getLogger("api.leitura_da_decupagem")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING"):
            lidas = list(decupagens_dos_jobs(jobs, _Decupagens({}), _SemCorrecoes()))
    finally:
        logger.removeHandler(caplog.handler)

    assert lidas == []
    assert "sem-arquivo" in caplog.text


def test_le_so_jobs_concluidos_e_pula_a_decupagem_que_nao_abre() -> None:
    jobs = [
        SimpleNamespace(id="a", estado="concluido"),
        SimpleNamespace(id="b", estado="analisando"),
        SimpleNamespace(id="c", estado="concluido"),  # sem decupagem no armazenamento
        SimpleNamespace(id="d", estado="concluido"),
    ]
    decupagens = _Decupagens(
        {"a": _modelo("Banco Verde"), "b": _modelo("Fora"), "d": _modelo("Loja Sol")}
    )
    catalogo = CatalogoDeMarcasEmMemoria()

    entraram = carregar_marcas(
        catalogo, decupagens_dos_jobs(jobs, decupagens, _SemCorrecoes())
    )

    assert entraram == 2
    assert sorted(m.nome for m in catalogo.todas()) == ["Banco Verde", "Loja Sol"]
