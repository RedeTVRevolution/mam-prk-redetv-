"""O banco de cada coleção (#368): papéis, chaves e auditoria no banco de segurança."""

from typing import Any

import pytest

from api.bancos import (
    BANCO_PADRAO,
    VARIAVEL_DO_BANCO_DE_SEGURANCA,
    banco_da_colecao,
    cliente_da_colecao,
)
from api.nuvem import (
    COLECAO_DA_AUDITORIA,
    COLECAO_DA_REVISAO,
    COLECAO_DE_CHAVES,
    COLECAO_DE_CORRECOES,
    COLECAO_DE_JOBS,
    COLECAO_DE_PAPEIS,
)

COM_BANCO = {VARIAVEL_DO_BANCO_DE_SEGURANCA: "seguranca-teste"}


@pytest.mark.parametrize(
    "colecao", [COLECAO_DE_PAPEIS, COLECAO_DE_CHAVES, COLECAO_DA_AUDITORIA]
)
def test_com_a_variavel_as_colecoes_de_seguranca_vao_para_o_banco_de_seguranca(
    colecao: str,
) -> None:
    assert banco_da_colecao(colecao, COM_BANCO) == "seguranca-teste"


@pytest.mark.parametrize(
    "colecao", [COLECAO_DE_JOBS, COLECAO_DE_CORRECOES, COLECAO_DA_REVISAO, "outra"]
)
def test_com_a_variavel_as_outras_colecoes_ficam_no_default(colecao: str) -> None:
    assert banco_da_colecao(colecao, COM_BANCO) == BANCO_PADRAO


@pytest.mark.parametrize("ambiente", [{}, {VARIAVEL_DO_BANCO_DE_SEGURANCA: ""}])
@pytest.mark.parametrize(
    "colecao", [COLECAO_DE_PAPEIS, COLECAO_DE_CHAVES, COLECAO_DA_AUDITORIA]
)
def test_sem_a_variavel_tudo_fica_no_default(
    colecao: str, ambiente: dict[str, str]
) -> None:
    assert banco_da_colecao(colecao, ambiente) == BANCO_PADRAO


def test_le_a_variavel_do_ambiente_do_processo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIAVEL_DO_BANCO_DE_SEGURANCA, "seguranca-teste")
    assert banco_da_colecao(COLECAO_DE_PAPEIS) == "seguranca-teste"
    monkeypatch.delenv(VARIAVEL_DO_BANCO_DE_SEGURANCA)
    assert banco_da_colecao(COLECAO_DE_PAPEIS) == BANCO_PADRAO


def test_o_cliente_nasce_apontado_para_o_banco_da_colecao() -> None:
    chamadas: list[dict[str, Any]] = []

    def fabrica(**kwargs: Any) -> object:
        chamadas.append(kwargs)
        return object()

    cliente_da_colecao("proj", COLECAO_DE_PAPEIS, COM_BANCO, fabrica)
    cliente_da_colecao("proj", COLECAO_DE_JOBS, COM_BANCO, fabrica)
    assert chamadas == [
        {"project": "proj", "database": "seguranca-teste"},
        {"project": "proj", "database": BANCO_PADRAO},
    ]
