import json
import re
from pathlib import Path
from typing import Any

from api.auth import ESCOPOS
from api.decupagem import Decupagem
from api.documentacao_dos_sistemas import (
    ARQUIVO,
    ERRO_EM_TEXTO,
    OPERACOES,
    esquema_dos_sistemas,
    json_do_esquema,
)
from api.main import criar_app
from api.tests.test_escopos import Mundo

RAIZ = Path(__file__).resolve().parents[2]
GUIA = RAIZ / "docs" / "api" / "guia.md"
EXEMPLOS = RAIZ / "docs" / "api" / "exemplos"


def _operacoes_do_esquema() -> list[tuple[str, str, dict[str, Any]]]:
    esquema = esquema_dos_sistemas(criar_app())
    return [
        (metodo.upper(), caminho, operacao)
        for caminho, metodos in esquema["paths"].items()
        for metodo, operacao in metodos.items()
    ]


def _exemplos_de(resposta: dict[str, Any]) -> list[Any]:
    """Os exemplos de um erro: um `example`, ou um por nome em `examples`."""
    conteudo = resposta["content"]["application/json"]
    if "example" in conteudo:
        return [conteudo["example"]]
    return [e["value"] for e in conteudo["examples"].values()]


def test_toda_rota_documentada_existe_no_app() -> None:
    do_app = {
        (metodo.upper(), caminho)
        for caminho, metodos in criar_app().openapi()["paths"].items()
        for metodo in metodos
    }

    assert {(o.metodo, o.caminho) for o in OPERACOES} <= do_app


def test_toda_rota_dos_sistemas_tem_descricao_e_exemplo() -> None:
    for metodo, caminho, operacao in _operacoes_do_esquema():
        onde = f"{metodo} {caminho}"
        assert operacao.get("summary"), onde
        assert len(operacao.get("description", "")) > 40, onde
        corpo = operacao.get("requestBody")
        if corpo is not None:
            conteudo = corpo["content"]
            if "application/json" in conteudo:
                assert "example" in conteudo["application/json"], onde
            else:
                assert "multipart/form-data" in conteudo, onde
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
            if status == "304":
                continue  # sem corpo
            for exemplo in _exemplos_de(resposta):
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


def _textos_do_codigo() -> list[re.Pattern[str]]:
    """Cada texto entre aspas de `api/`, com o que varia num f-string como `.+`."""
    textos: set[str] = set()
    for fonte in (RAIZ / "api").glob("*.py"):
        if fonte.name != "documentacao_dos_sistemas.py":
            textos.update(re.findall(r'"([^"\n]+)"', fonte.read_text()))
    padroes = []
    for texto in textos:
        partes = re.split(r"\{[^}]*\}", texto)
        # Um literal quase só de `{...}` casaria com qualquer mensagem.
        if len("".join(partes)) >= 8:
            padroes.append(re.compile(".+".join(map(re.escape, partes))))
    return padroes


def test_cada_mensagem_de_erro_documentada_existe_no_codigo() -> None:
    padroes = _textos_do_codigo()
    for o in OPERACOES:
        for erro in o.erros:
            if erro.sem_corpo:
                continue
            detalhe = erro.corpo["detail"]
            if isinstance(detalhe, list):
                continue  # a lista da validação vem do FastAPI
            assert any(p.fullmatch(detalhe) for p in padroes), (
                f"{o.metodo} {o.caminho}: {detalhe}"
            )


def test_o_esquema_de_cada_erro_aceita_o_exemplo() -> None:
    for metodo, caminho, operacao in _operacoes_do_esquema():
        for status, resposta in operacao["responses"].items():
            if status.startswith("2"):
                continue
            if status == "304":
                continue
            refs = json.dumps(resposta["content"]["application/json"]["schema"])
            for exemplo in _exemplos_de(resposta):
                em_texto = isinstance(exemplo["detail"], str)
                assert (ERRO_EM_TEXTO if em_texto else "HTTPValidationError") in refs, (
                    f"{metodo} {caminho} {status}"
                )


def test_o_guia_cita_cada_rota_e_cada_erro_entre_crases() -> None:
    guia = GUIA.read_text()
    for o in OPERACOES:
        assert f"`{o.metodo} {o.caminho}" in guia, f"{o.metodo} {o.caminho}"
        for erro in o.erros:
            assert f"`{erro.detalhe}`" in guia, (
                f"{o.metodo} {o.caminho}: {erro.detalhe}"
            )


def test_a_lista_de_rotas_do_guia_e_a_das_operacoes() -> None:
    lista = GUIA.read_text().split("## Rotas deste guia", 1)[1]
    citadas = set(re.findall(r"`((?:GET|POST|PUT|DELETE|PATCH) /v1[^`]*)`", lista))

    assert citadas == {f"{o.metodo} {o.caminho}" for o in OPERACOES}


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


def _valida(valor: Any, esquema: dict[str, Any], raiz: dict[str, Any]) -> str | None:
    """Um validador mínimo de JSON Schema: `$ref`, `anyOf`, `type`, `properties`, `required`, `items`."""
    if "$ref" in esquema:
        esquema = raiz["components"]["schemas"][esquema["$ref"].rsplit("/", 1)[1]]
    if "anyOf" in esquema:
        erros = [_valida(valor, e, raiz) for e in esquema["anyOf"]]
        return None if None in erros else f"nenhuma opção de anyOf: {erros}"
    tipos: dict[str, Any] = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    tipo = esquema.get("type")
    if tipo and not isinstance(valor, tipos[tipo]):
        return f"{valor!r} não é {tipo}"
    if tipo == "integer" and isinstance(valor, bool):
        return f"{valor!r} não é integer"
    if isinstance(valor, dict):
        for campo in esquema.get("required", []):
            if campo not in valor:
                return f"falta {campo}"
        for campo, filho in esquema.get("properties", {}).items():
            if campo in valor:
                erro = _valida(valor[campo], filho, raiz)
                if erro:
                    return f"{campo}: {erro}"
    if isinstance(valor, list) and "items" in esquema:
        for item in valor:
            erro = _valida(item, esquema["items"], raiz)
            if erro:
                return erro
    return None


def test_o_exemplo_de_sucesso_de_cada_rota_vale_no_esquema_da_resposta() -> None:
    esquema = esquema_dos_sistemas(criar_app())
    for metodo, caminho, operacao in _operacoes_do_esquema():
        for status, resposta in operacao["responses"].items():
            if not status.startswith("2"):
                continue
            for conteudo in resposta.get("content", {}).values():
                if "example" in conteudo and "schema" in conteudo:
                    assert (
                        _valida(conteudo["example"], conteudo["schema"], esquema)
                        is None
                    ), f"{metodo} {caminho} {status}"


def _caminho_de_prova(caminho: str) -> str:
    """O caminho com o Job `j1` e um quadro válido no lugar dos parâmetros."""
    caminho = caminho.replace("{arquivo}", "plano-0.jpg")
    return re.sub(r"\{[^}]+\}", "j1", caminho)


def _aceita_a_chave(
    mundo: Mundo, chave: dict[str, str], metodo: str, caminho: str
) -> bool:
    caminho = _caminho_de_prova(caminho)
    argumentos: dict[str, Any] = {"json": {}} if metodo in ("POST", "PUT") else {}
    resposta = mundo.cliente.request(metodo, caminho, headers=chave, **argumentos)
    if resposta.status_code == 401:
        return False
    recusou = resposta.status_code == 403 and str(
        resposta.json().get("detail", "")
    ).startswith("Chave de sistema não")
    return not recusou


def test_toda_rota_que_aceita_a_chave_esta_documentada_e_so_ela() -> None:
    mundo = Mundo()
    mundo.job("j1", "sis")
    chave = mundo.chave("sis", *ESCOPOS)
    aceitas: set[tuple[str, str]] = set()
    abertas_sem_chave: set[tuple[str, str]] = set()
    for caminho, metodos in mundo.cliente.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        if not caminho.startswith("/v1"):
            continue
        for metodo in metodos:
            if metodo.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            if (metodo.upper(), caminho) == ("GET", "/v1/health"):
                continue  # pública: não pede chave
            if _aceita_a_chave(mundo, chave, metodo.upper(), caminho):
                aceitas.add((metodo.upper(), caminho))
            else:
                sem_chave = mundo.cliente.request(metodo, _caminho_de_prova(caminho))
                if sem_chave.status_code != 401:
                    abertas_sem_chave.add((metodo.upper(), caminho))

    assert not abertas_sem_chave
    assert aceitas == {(o.metodo, o.caminho) for o in OPERACOES}
