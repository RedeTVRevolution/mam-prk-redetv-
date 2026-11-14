"""`REQUISITO_DO_TIPO` fica à mão, mas este teste a liga às fontes de onde os nomes vêm (#658)."""

import json
from pathlib import Path
from typing import get_args

from api.comparacao_de_passadas import REQUISITOS
from api.correcoes import CORRIGIVEIS, TipoDoItem
from api.pareamento import TIPOS
from api.regressao import _CATEGORIA_DO_ITEM
from api.regressao_da_versao import REQUISITO_DO_TIPO

METAS = Path(__file__).parents[2] / "evals" / "regressao" / "metas.json"
# Tipos de item com conversão própria em `regressao._itens_da_correcao`, fora da tabela
# `_CATEGORIA_DO_ITEM`: a pessoa vira `aparicao` ou `mencao`, o objeto tem as suas regras.
COM_CONVERSAO_PROPRIA = {"pessoa", "objeto"}


def test_todo_tipo_do_pareamento_tem_requisito_e_nenhum_sobra() -> None:
    assert set(REQUISITO_DO_TIPO) == set(TIPOS)


def test_os_requisitos_do_nucleo_da_comparacao_batem() -> None:
    # `broll_limpos` é um subconjunto dos planos: não é tipo de item, só um recorte.
    do_nucleo = set(REQUISITOS) - {"broll_limpos"}

    assert do_nucleo <= set(REQUISITO_DO_TIPO.values())
    assert {REQUISITO_DO_TIPO[t] for t in ("aparicao", "mencao", "pauta")} == {
        "famosos",
        "mencoes",
        "pautas",
    }
    assert REQUISITO_DO_TIPO["comercial"] == "comerciais"
    assert REQUISITO_DO_TIPO["plano"] == "broll_descricoes"


def test_todo_tipo_de_item_corrigivel_vira_item_ou_tem_conversao_propria() -> None:
    # `item.tempos` vale para qualquer item; `aparicao.*` age sobre a aparição de uma pessoa.
    corrigidos = {operacao.split(".")[0] for operacao in CORRIGIVEIS} - {
        "item",
        "aparicao",
    }

    assert corrigidos <= set(get_args(TipoDoItem))
    assert corrigidos <= set(_CATEGORIA_DO_ITEM) | COM_CONVERSAO_PROPRIA
    assert set(_CATEGORIA_DO_ITEM.values()) <= set(REQUISITO_DO_TIPO)


def test_as_chaves_das_metas_sao_requisitos_validos() -> None:
    metas = json.loads(METAS.read_text(encoding="utf-8"))

    assert set(metas) <= set(REQUISITO_DO_TIPO.values())
