"""O serviço indisponível mora num módulo leve de erros (#604), sem ciclo com o módulo de Jobs."""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import GoogleAPIError

import api.erros
import api.jobs
from api.main import criar_app

API = Path(api.erros.__file__).parent


def _importados(modulo: str) -> set[str]:
    achados: set[str] = set()
    for no in ast.walk(ast.parse((API / f"{modulo}.py").read_text())):
        if isinstance(no, ast.Import):
            achados |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            achados.add(no.module)
            achados |= {f"{no.module}.{a.name}" for a in no.names}
    return achados


def test_jobs_reexporta_a_mesma_classe() -> None:
    assert api.jobs.ServicoIndisponivel is api.erros.ServicoIndisponivel


def test_excecao_do_modulo_de_erros_cai_no_503_da_aplicacao(tmp_path: Path) -> None:
    app = criar_app(pasta_web=tmp_path)

    def falha() -> None:
        raise api.erros.ServicoIndisponivel("fora do ar")

    # Na frente das rotas da aplicação: a rota coringa do front responderia 404 antes.
    app.add_api_route("/_falha", falha)
    app.router.routes.insert(0, app.router.routes.pop())

    resposta = TestClient(app, raise_server_exceptions=False).get("/_falha")

    assert resposta.status_code == 503
    assert resposta.json() == {"detail": "Serviço indisponível"}


def test_lido_converte_erro_do_google_em_servico_indisponivel() -> None:
    def falha() -> None:
        raise GoogleAPIError("firestore fora")

    with pytest.raises(api.erros.ServicoIndisponivel):
        api.erros.lido(falha)


def test_lido_devolve_o_valor_e_nao_engole_outros_erros() -> None:
    assert api.erros.lido(lambda: 7) == 7
    with pytest.raises(KeyError):
        api.erros.lido(lambda: {"a": 1}["x"])


def test_modulo_de_erros_nao_importa_o_dominio() -> None:
    assert not {m for m in _importados("erros") if m.split(".")[0] == "api"}


def test_leitura_da_lixeira_nao_importa_o_modulo_de_jobs() -> None:
    assert "api.jobs" not in _importados("lixeira_na_leitura")
