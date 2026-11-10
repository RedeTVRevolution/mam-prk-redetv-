"""Mede o agrupamento de objetos por tipo (#544): `make medir-agrupamento-de-objetos`.

Lê uma pasta de Decupagens em JSON (uma subpasta por programa; sem subpasta, o programa é
`sem-programa`) e mostra:

- o diagnóstico: quantos objetos a tela exibia antes (nome + categoria + cor idênticos) e
  quantos exibe com o dicionário, sem reprocessar (não é meta);
- a amostra para a pessoa marcar a precisão: grupos sorteados de forma estável (pelo hash da
  chave do grupo, como `reservado_pelo_sorteio`), estratificados por programa, e um par de
  nomes diferentes dentro de cada grupo, não pares soltos;
- a amostra para a cobertura: pares de nomes de grupos diferentes (de qualquer tipo) do mesmo
  programa que são vizinhos pela assinatura (dividem uma palavra), não pares ao acaso.

Só lê arquivos locais. Os nomes usados para montar o dicionário não valem como amostra de
qualidade: a pessoa escolhe vídeos de outros programas.
"""

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

from api.assinatura_do_nome import assinatura
from api.comparador import normalizar
from api.taxonomia_de_objetos import OUTRO
from api.tipo_do_objeto import chave_de_agrupamento, tipo_canonico_de

SEM_PROGRAMA = "sem-programa"
Nome = tuple[str, str | None, str]  # nome bruto, cor, categoria
# Os grupos de um programa: chave do grupo → nomes brutos (sem repetir).
Grupos = dict[str, dict[str, set[str]]]


def _nomes_do_video(decupagem: dict[str, Any]) -> list[Nome]:
    """Todo nome de objeto do vídeo: o inventário dos planos e os `objetos` da análise."""
    nomes: list[Nome] = []
    for plano in decupagem.get("planos", []):
        for i in plano.get("inventario") or []:
            nomes.append((i["nome"], i.get("cor"), i["categoria"]))
    for o in decupagem.get("objetos", []):
        cor = o["cor_base"][0] if o.get("cor_base") else None
        nomes.append((o["tipo"], cor, o["categoria"]))
    return nomes


def chave_de_antes(nome: Nome) -> tuple[str, str, str | None]:
    return (normalizar(nome[0]), nome[2], nome[1])


def chave_de_depois(nome: Nome) -> str:
    bruto, cor, categoria = nome
    cores = [cor] if cor else []
    tipo = tipo_canonico_de(None, bruto, cores)
    chave = chave_de_agrupamento(tipo, bruto, cores)
    return chave if tipo != OUTRO else f"{chave}|{categoria}"


def diagnostico(videos: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Quantos objetos distintos a tela mostrava antes e mostra depois, no conjunto."""
    todos = [n for v in videos for n in _nomes_do_video(v)]
    return {
        "ocorrencias": len(todos),
        "antes": len({chave_de_antes(n) for n in todos}),
        "depois": len({chave_de_depois(n) for n in todos}),
    }


def _hash(chave: str) -> int:
    return int(hashlib.sha256(chave.encode()).hexdigest()[:12], 16)


def grupos_por_programa(videos_por_programa: dict[str, list[dict[str, Any]]]) -> Grupos:
    grupos: Grupos = {}
    for programa, videos in videos_por_programa.items():
        por_chave: dict[str, set[str]] = defaultdict(set)
        for v in videos:
            for n in _nomes_do_video(v):
                por_chave[chave_de_depois(n)].add(normalizar(n[0]))
        grupos[programa] = por_chave
    return grupos


def amostra_de_precisao(grupos: Grupos, quantos: int) -> list[dict[str, str]]:
    """`quantos` pares, um por grupo sorteado: só grupos com pelo menos dois nomes diferentes
    (um grupo de nomes iguais não tem o que conferir). O sorteio é estável e estratificado:
    cada programa dá um grupo por rodada, na ordem do hash da chave."""
    filas = {
        programa: sorted(
            (c for c, nomes in por_chave.items() if len(nomes) >= 2), key=_hash
        )
        for programa, por_chave in sorted(grupos.items())
    }
    pares: list[dict[str, str]] = []
    rodada = 0
    while len(pares) < quantos and any(rodada < len(f) for f in filas.values()):
        for programa, fila in filas.items():
            if rodada < len(fila) and len(pares) < quantos:
                chave = fila[rodada]
                nomes = sorted(grupos[programa][chave])
                # O par também é estável: os dois nomes de menor hash dentro do grupo.
                a, b = sorted(nomes, key=_hash)[:2]
                pares.append({"programa": programa, "grupo": chave, "a": a, "b": b})
        rodada += 1
    return pares


def amostra_de_cobertura(grupos: Grupos, quantos: int) -> list[dict[str, str]]:
    """Pares de nomes de grupos diferentes (de qualquer tipo) do mesmo programa que dividem
    uma palavra da assinatura: vizinhos próximos, onde as duplicatas que ficaram separadas
    aparecem. O programa vai no par."""
    pares: set[tuple[str, str, str, str]] = set()
    for programa, por_chave in grupos.items():
        por_palavra: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for chave, nomes in por_chave.items():
            for nome in nomes:
                for palavra in assinatura(nome).split():
                    por_palavra[palavra].add((chave, nome))
        for palavra, vizinhos in por_palavra.items():
            for (ca, a), (cb, b) in combinations(sorted(vizinhos), 2):
                if ca != cb and a != b:
                    menor, maior = sorted((a, b))
                    pares.add((programa, palavra, menor, maior))
    ordenados = sorted(pares, key=lambda p: _hash("|".join(p)))
    return [
        {"programa": g, "palavra": p, "a": a, "b": b}
        for g, p, a, b in ordenados[:quantos]
    ]


def margem_de_confianca(pares: int, precisao: float = 0.95) -> float:
    """A margem de 95% de confiança, em pontos percentuais."""
    return 196 * math.sqrt(precisao * (1 - precisao) / pares)


def pares_para_margem(margem_em_pontos: float, precisao: float = 0.95) -> int:
    return math.ceil((196 / margem_em_pontos) ** 2 * precisao * (1 - precisao))


def _ler(pasta: Path) -> dict[str, list[dict[str, Any]]]:
    videos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for arquivo in sorted(pasta.rglob("*.json")):
        programa = arquivo.parent.name if arquivo.parent != pasta else SEM_PROGRAMA
        videos[programa].append(json.loads(arquivo.read_text("utf-8")))
    return videos


def medir(pasta: Path, quantos: int = 100) -> dict[str, Any]:
    videos = _ler(pasta)
    todos = [v for lista in videos.values() for v in lista]
    return {
        "videos": len(todos),
        "diagnostico": diagnostico(todos),
        "amostra_de_precisao": amostra_de_precisao(
            grupos_por_programa(videos), quantos
        ),
        "amostra_de_cobertura": amostra_de_cobertura(
            grupos_por_programa(videos), quantos
        ),
        "margem_com_essa_amostra_pontos": round(margem_de_confianca(quantos), 1),
        "pares_para_margem_de_3_pontos": pares_para_margem(3),
    }


def main(argv: Sequence[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("pasta", type=Path)
    analisador.add_argument("--amostra", type=int, default=100)
    args = analisador.parse_args(argv)
    json.dump(medir(args.pasta, args.amostra), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
