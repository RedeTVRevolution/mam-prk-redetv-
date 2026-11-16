"""Caracterização: o status de cada rota de `/v1` e `/admin` para cada papel, chave e sem token.

Congela o comportamento antes de a permissão virar uma dependência única (#660): o
refator não pode mudar nenhum status. Regerar só de propósito: `REGERAR_MATRIZ=1`.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient

from api.auth import Escopo, Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.modelo_do_job import Job
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

GOLDEN = Path(__file__).with_name("matriz_de_permissoes.json")
BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
PAPEIS: dict[str, list[Papel] | None] = {
    "sem_documento": None,
    "sem_papel": [],
    "consulta": ["consulta"],
    "editor": ["editor"],
    "curador": ["curador"],
    "diretoria": ["diretoria"],
    "administrador": ["administrador"],
}
CHAVES: dict[str, tuple[str, ...]] = {
    "chave_so_criar": ("criar",),
    "chave_so_ler": ("ler",),
    "chave_so_cancelar": ("cancelar",),
    "chave_todos": ("criar", "ler", "cancelar"),
}


def _rotas() -> list[tuple[str, str]]:
    # Pelo OpenAPI do app real: o FastAPI novo não expõe as rotas incluídas em `app.routes`.
    rotas = {
        (metodo.upper(), caminho)
        for caminho, operacoes in _app()[0].app.openapi()["paths"].items()  # type: ignore[attr-defined]
        if caminho.startswith(("/v1", "/admin"))
        for metodo in operacoes
    }
    return sorted(rotas)


def _app() -> tuple[TestClient, dict[str, dict[str, str]]]:
    papeis = RepositorioDePapeisEmMemoria()
    verificador: dict[str, Usuario] = {}
    cabecalhos: dict[str, dict[str, str]] = {}
    for nome, lista in PAPEIS.items():
        verificador[f"t-{nome}"] = Usuario(uid=nome, email=f"{nome}@b.c")
        cabecalhos[nome] = {"Authorization": f"Bearer t-{nome}"}
        if lista is not None:
            papeis.salvar(nome, lista)
    repo_chaves = RepositorioDeChavesEmMemoria()
    for nome, escopos in CHAVES.items():
        emitida = emitir_chave(
            nome, cast(frozenset[Escopo], frozenset(escopos)), MAC, repo_chaves, BASE
        )
        cabecalhos[nome] = {"X-API-Key": emitida.chave}
    cabecalhos["sem_token"] = {}
    jobs = RepositorioEmMemoria()
    jobs.salvar(
        Job(
            id="j1",
            nome="a.mp4",
            tamanho_bytes=10,
            estado="concluido",
            criado_por="administrador",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    armazenamento = ArmazenamentoFalso()
    armazenamento.decupagens["j1"] = [b"{}"]
    app = criar_app(
        VerificadorFalso(verificador),
        jobs,
        armazenamento,
        chaves=VerificadorDeChaveDeApi(repo_chaves, MAC),
        papeis=papeis,
    )
    return TestClient(app, raise_server_exceptions=False), cabecalhos


def _resultado(resposta: Any) -> str:
    """O status; no 403, também o texto, que o refator tem de manter."""
    if resposta.status_code != 403:
        return str(resposta.status_code)
    return f"403 {resposta.json().get('detail')}"


def _matriz() -> dict[str, dict[str, str]]:
    matriz: dict[str, dict[str, str]] = {}
    for metodo, caminho in _rotas():
        cliente, cabecalhos = (
            _app()
        )  # um mundo novo por rota: um DELETE não muda o seguinte
        url = caminho.replace("{", "\0").replace("}", "\1")
        while "\0" in url:
            ini, fim = url.index("\0"), url.index("\1")
            url = url[:ini] + "j1" + url[fim + 1 :]
        corpo: dict[str, str] | None = (
            {} if metodo in {"POST", "PUT", "PATCH"} else None
        )
        matriz[f"{metodo} {caminho}"] = {
            quem: _resultado(cliente.request(metodo, url, headers=h, json=corpo))
            for quem, h in cabecalhos.items()
        }
    return matriz


def test_status_de_cada_rota_por_papel_e_chave_nao_mudou() -> None:
    matriz = _matriz()
    if os.environ.get("REGERAR_MATRIZ"):
        GOLDEN.write_text(json.dumps(matriz, indent=1, sort_keys=True) + "\n")
    assert matriz == json.loads(GOLDEN.read_text())
