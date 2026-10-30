"""Perfis de programa, lidos de `programas.toml`: nome → contexto para a instrução."""

import tomllib
from pathlib import Path

PERFIS: dict[str, str] = {
    nome: dados["perfil"].strip()
    for nome, dados in tomllib.loads(
        (Path(__file__).parent / "programas.toml").read_text()
    ).items()
}
