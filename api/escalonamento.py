"""Escalonamento: decide quais janelas de análise são reanalisadas e por quê.

Dois motivos: `duvida` (a primeira passada deixou alguém aparecendo sem nome)
e `amostra` (sorteio determinístico, para medir o que a primeira passada nem
marcou como dúvida).
"""

import hashlib

from api.comparador import normalizar
from api.decupagem import Decupagem

# ponytail: 10% é um chute; o valor real sai do piloto.
FRACAO_PADRAO = 0.1

_NAO_IDENTIFICADO = normalizar("não identificado")


def janelas_a_escalonar(
    chave_de_conteudo: str,
    resultados: dict[int, Decupagem],
    fracao: float,
) -> dict[int, set[str]]:
    """Janelas escaladas (índice → motivos `"duvida"` e/ou `"amostra"`).

    O sorteio depende só da chave e do índice, nunca do resultado: uma nova
    tentativa do mesmo job sorteia as mesmas janelas.
    """
    escalonadas: dict[int, set[str]] = {}
    for indice, decupagem in resultados.items():
        motivos: set[str] = set()
        if _tem_duvida(decupagem):
            motivos.add("duvida")
        if _na_amostra(chave_de_conteudo, indice, fracao):
            motivos.add("amostra")
        if motivos:
            escalonadas[indice] = motivos
    return escalonadas


def _na_amostra(chave_de_conteudo: str, indice: int, fracao: float) -> bool:
    digest = hashlib.sha256(f"{chave_de_conteudo}:{indice}".encode()).digest()
    return int.from_bytes(digest, "big") / 2**256 < fracao


def _tem_duvida(decupagem: Decupagem) -> bool:
    return any(
        p.na_imagem and normalizar(p.nome) == _NAO_IDENTIFICADO
        for p in decupagem.pessoas
    )
