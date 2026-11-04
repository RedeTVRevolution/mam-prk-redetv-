import json
import re
from pathlib import Path
from typing import Any

from api.decupagem import Decupagem
from api.documentacao_dos_sistemas import (
    OPERACOES,
    esquema_dos_sistemas,
    json_do_esquema,
)
from api.main import criar_app

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = RAIZ / "docs" / "api" / "openapi.json"
GUIA = RAIZ / "docs" / "api" / "guia.md"
EXEMPLOS = RAIZ / "docs" / "api" / "exemplos"


def _operacoes_do_esquema() -> list[tuple[str, str, dict[str, Any]]]:
    esquema = esquema_dos_sistemas(criar_app())
    return [
        (metodo.upper(), caminho, operacao)
        for caminho, metodos in esquema["paths"].items()
        for metodo, operacao in metodos.items()
    ]


def test_toda_rota_dos_sistemas_existe_no_app_e_vice_versa() -> None:
    do_app = {
        (metodo.upper(), caminho)
        for caminho, metodos in criar_app().openapi()["paths"].items()
        for metodo in metodos
    }
    documentadas = {(o.metodo, o.caminho) for o in OPERACOES}

    assert documentadas <= do_app
    assert {(m, c) for m, c, _ in _operacoes_do_esquema()} == documentadas


def test_toda_rota_dos_sistemas_tem_descricao_e_exemplo() -> None:
    for metodo, caminho, operacao in _operacoes_do_esquema():
        onde = f"{metodo} {caminho}"
        assert operacao.get("summary"), onde
        assert len(operacao.get("description", "")) > 40, onde
        corpo = operacao.get("requestBody")
        if corpo is not None:
            assert "example" in corpo["content"]["application/json"], onde
        sucesso = [s for s in operacao["responses"] if s.startswith("2")]
        assert sucesso, onde
        for status in sucesso:
            resposta = operacao["responses"][status]
            assert resposta["description"], onde
            conteudo = resposta.get("content", {})
            assert conteudo, f"{onde} {status}"
            assert any("example" in c for c in conteudo.values()), f"{onde} {status}"


def test_todo_erro_de_cada_rota_tem_exemplo_e_pelo_menos_o_401() -> None:
    for metodo, caminho, operacao in _operacoes_do_esquema():
        onde = f"{metodo} {caminho}"
        assert "401" in operacao["responses"], onde
        for status, resposta in operacao["responses"].items():
            if status.startswith("2"):
                continue
            exemplo = resposta["content"]["application/json"]["example"]
            assert "detail" in exemplo, f"{onde} {status}"


def test_o_openapi_do_repositorio_bate_com_o_gerado() -> None:
    assert ARQUIVO.read_text() == json_do_esquema(criar_app()), (
        "rode `make atualizar-openapi`"
    )


def test_o_exemplo_da_decupagem_vale_no_esquema() -> None:
    operacao = next(o for o in OPERACOES if o.caminho == "/v1/jobs/{job_id}/decupagem")

    Decupagem.model_validate(
        {k: v for k, v in operacao.resposta.items() if k != "versao_decupagem"}
    )


def test_o_json_publicado_e_json_valido() -> None:
    assert json.loads(ARQUIVO.read_text())["info"]["title"]


def test_o_guia_cita_cada_rota_e_cada_erro_entre_crases() -> None:
    guia = GUIA.read_text()
    for o in OPERACOES:
        assert f"{o.metodo} {o.caminho}" in guia, f"{o.metodo} {o.caminho}"
        for erro in o.erros:
            assert f"`{erro.detalhe}`" in guia, (
                f"{o.metodo} {o.caminho}: {erro.detalhe}"
            )


def test_o_guia_cita_cada_exemplo_e_cada_exemplo_citado_existe() -> None:
    guia = GUIA.read_text()
    existentes = {
        f"exemplos/{p.parent.name}/{p.name}"
        for p in EXEMPLOS.glob("*/*")
        if p.is_file()
    }
    citados = set(re.findall(r"exemplos/(?:curl|python)/[\w.-]+\.(?:sh|py)", guia))

    assert existentes
    assert citados == existentes
