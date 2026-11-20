import ast
import sys
from pathlib import Path

from api import operacao_do_google
from api.operacao_do_google import terminou


def test_operacao_com_nome_e_sem_done_nao_terminou() -> None:
    assert terminou({"name": "operations/1"}) is False


def test_done_falso_nao_terminou() -> None:
    assert terminou({"name": "operations/1", "done": False}) is False


def test_done_verdadeiro_terminou() -> None:
    assert terminou({"name": "operations/1", "done": True}) is True


def test_resposta_sem_nome_terminou_porque_nao_ha_operacao_a_acompanhar() -> None:
    assert terminou({}) is True


def test_so_importa_a_biblioteca_padrao() -> None:
    # o pre_voo roda no CD sem instalar nada
    arvore = ast.parse(Path(operacao_do_google.__file__).read_text())
    raizes = {
        (n.module or "").split(".")[0]
        if isinstance(n, ast.ImportFrom)
        else a.name.split(".")[0]
        for n in ast.walk(arvore)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert raizes <= set(sys.stdlib_module_names)
