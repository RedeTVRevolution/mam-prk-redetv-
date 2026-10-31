"""Perfis de programa, lidos de `programas.toml`: nome → contexto para a instrução."""

import tomllib
from pathlib import Path
from typing import Any


def _perfil(dados: dict[str, Any]) -> str:
    """O texto livre do perfil, seguido das pessoas frequentes com papel e apelidos."""
    linhas = [dados["perfil"].strip()]
    if dados.get("pessoas"):
        linhas.append("Pessoas frequentes:")
    for p in dados.get("pessoas", []):
        apelidos = ", ".join(f'"{a}"' for a in p["apelidos"])
        linhas.append(
            f"- {p['nome']}, {p['papel']}"
            + (f"; também chamado de {apelidos}" if apelidos else "")
            + "."
        )
    return "\n".join(linhas)


DADOS: dict[str, dict[str, Any]] = tomllib.loads(
    (Path(__file__).parent / "programas.toml").read_text()
)
PERFIS: dict[str, str] = {nome: _perfil(dados) for nome, dados in DADOS.items()}
