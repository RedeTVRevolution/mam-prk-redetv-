"""Escalonamento: decide quais janelas de análise são reanalisadas e por quê.

Dois motivos: `duvida` (a primeira passada deixou alguém aparecendo sem nome,
ou um texto na tela com a duração de um bloco ou pauta inteira) e `amostra`
(sorteio determinístico, para medir o que a primeira passada nem marcou como
dúvida).
"""

import hashlib
from typing import Literal

from api.decupagem import Decupagem
from api.pessoas import nao_identificado

# ponytail: 10% é um chute; o valor real sai do piloto.
FRACAO_PADRAO = 0.1

Motivo = Literal["duvida", "amostra"]


def janelas_a_escalonar(
    chave_de_conteudo: str,
    resultados: dict[int, Decupagem],
    fracao: float,
) -> dict[int, set[Motivo]]:
    """Janelas escalonadas (índice → motivos `"duvida"` e/ou `"amostra"`).

    O sorteio depende só da chave e do índice, nunca da decupagem da janela:
    uma nova tentativa do mesmo job sorteia as mesmas janelas. `fracao` fora
    de [0, 1] é erro.
    """
    if not 0 <= fracao <= 1:
        raise ValueError(f"fração da amostra fora de [0, 1]: {fracao}")
    escalonadas: dict[int, set[Motivo]] = {}
    for indice, decupagem in resultados.items():
        motivos: set[Motivo] = set()
        if _tem_duvida(decupagem):
            motivos.add("duvida")
        if _na_amostra(chave_de_conteudo, indice, fracao):
            motivos.add("amostra")
        if motivos:
            escalonadas[indice] = motivos
    return escalonadas


def _na_amostra(chave_de_conteudo: str, indice: int, fracao: float) -> bool:
    digest = hashlib.sha256(f"{chave_de_conteudo}:{indice}".encode()).digest()
    # Compara inteiro com `fracao * 2**256` (exato): dividir o hash por 2**256
    # arredonda para 1.0 perto do máximo, e `fracao` 1 deixaria janelas de fora.
    return int.from_bytes(digest, "big") < fracao * 2**256


def _tem_duvida(decupagem: Decupagem) -> bool:
    return bool(decupagem.textos_com_a_duracao_de_bloco_ou_pauta()) or any(
        p.na_imagem and nao_identificado(p.nome) for p in decupagem.pessoas
    )
