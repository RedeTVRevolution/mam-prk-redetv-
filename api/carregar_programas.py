"""`make carregar-programas`: carga única dos programas e das pessoas (#338).

Leva para o Firestore o que estava em `programas.toml`: cada programa com o perfil e as
pessoas, e o papel de cada pessoa vira o papel dela naquele programa. A pessoa que já
está no catálogo (pelo nome ou apelido) é reaproveitada; as outras entram. Um programa
que já existe pelo nome fica como está, então rodar de novo não duplica nem desfaz
edições feitas no formulário. O casamento é pelo nome: um programa renomeado no
formulário volta como programa novo se a carga rodar de novo. Usa as credenciais da máquina; sem teste automático
contra a nuvem (a carga em si é testada com o dublê).
"""

import os
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from api.bancos import cliente_do_firestore
from api.catalogo import Catalogo
from api.nuvem import CatalogoFirestore, ProgramasFirestore
from api.programas import (
    Programa,
    RepositorioDeProgramas,
    VinculoDaPessoa,
    novo_id,
)


def carregar(
    programas: RepositorioDeProgramas,
    catalogo: Catalogo,
    dados: Mapping[str, Mapping[str, Any]],
) -> tuple[int, int]:
    """Devolve quantos programas e quantas pessoas entraram."""
    ja_existem = {p.nome.casefold() for p in programas.listar()}
    novos_programas = novas_pessoas = 0
    for nome, programa in dados.items():
        if nome.casefold() in ja_existem:
            continue
        vinculos: list[VinculoDaPessoa] = []
        for p in programa.get("pessoas", []):
            achadas = catalogo.achar(p["nome"])
            if achadas:
                pessoa = achadas[0]
            else:
                pessoa = catalogo.acrescentar(p["nome"], "", list(p["apelidos"]))
                novas_pessoas += 1
            if all(v.pessoa_id != pessoa.id for v in vinculos):
                vinculos.append(VinculoDaPessoa(pessoa_id=pessoa.id, papel=p["papel"]))
        programas.salvar(
            Programa(
                id=novo_id(),
                nome=nome,
                perfil=programa["perfil"].strip(),
                pessoas=vinculos,
            )
        )
        novos_programas += 1
    return novos_programas, novas_pessoas


if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID") or sys.exit("defina GCP_PROJECT_ID")
    if len(sys.argv) != 2 or not sys.argv[1]:
        sys.exit("uso: make carregar-programas ARQUIVO=<arquivo.toml>")
    cliente = cliente_do_firestore(projeto)
    entraram = carregar(
        ProgramasFirestore(cliente),
        CatalogoFirestore(cliente),
        tomllib.loads(Path(sys.argv[1]).read_text()),
    )
    print(f"{entraram[0]} programa(s) e {entraram[1]} pessoa(s) acrescentados")
