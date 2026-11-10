"""Enquadramento e ambiente canônicos (#545).

O texto livre do modelo continua gravado; o valor canônico é um campo à parte, preenchido
pelo modelo nos vídeos novos e, no acervo, por estes dicionários na leitura (depois das
Correções). O que o dicionário não conhece cai em `indefinido` (enquadramento) ou `outro`
(ambiente). Em cada lista a primeira regra que casa vence: as mais específicas vêm antes.
"""

import re
from typing import Literal

from api.comparador import normalizar

Enquadramento = Literal[
    "plano geral",
    "plano de conjunto",
    "plano americano",
    "plano médio",
    "primeiro plano",
    "primeiríssimo plano",
    "detalhe",
    "indefinido",
]

Ambiente = Literal[
    "estúdio",
    "externa",
    "bastidor",
    "residência",
    "escritório",
    "estádio",
    "aeroporto",
    "veículo",
    "hospital",
    "comércio",
    "palco",
    "natureza",
    "outro",
]

# Começos de palavra do texto normalizado (sem acento nem maiúscula) -> valor.
_ENQUADRAMENTOS: list[tuple[tuple[str, ...], Enquadramento]] = [
    (("primeirissimo", "super close", "big close", "extreme close"), "primeiríssimo plano"),
    (("detalhe",), "detalhe"),
    (("conjunto",), "plano de conjunto"),
    (("americano",), "plano americano"),
    (("geral", "aberto", "panoramic", "wide"), "plano geral"),
    (("medio", "medium"), "plano médio"),
    (("primeiro plano", "close", "fechado", "proximo"), "primeiro plano"),
]

_AMBIENTES: list[tuple[tuple[str, ...], Ambiente]] = [
    (("estudio", "bancada", "set de gravacao"), "estúdio"),
    (("estadio", "arena", "campo de futebol", "quadra", "ginasio"), "estádio"),
    (("aeroporto", "terminal aereo"), "aeroporto"),
    (("hospital", "clinica", "consultorio"), "hospital"),
    (("bastidor", "camarim", "redacao", "corredor"), "bastidor"),
    (("palco", "auditorio", "teatro", "plateia"), "palco"),
    (("carro", "veiculo", "onibus", "caminhao", "viatura", "helicoptero", "aviao"), "veículo"),
    (("escritorio", "empresa", "sala de reuniao", "delegacia", "tribunal"), "escritório"),
    (("loja", "mercado", "shopping", "restaurante", "comercio", "feira"), "comércio"),
    (("casa", "residencia", "sala de estar", "cozinha", "quarto", "apartamento"), "residência"),
    (("praia", "floresta", "mata", "campo", "rio", "natureza", "montanha", "parque"), "natureza"),
    (("rua", "externa", "exterior", "avenida", "praca", "ao ar livre", "calcada", "estrada"), "externa"),
]


def _classificar[T](texto: str, regras: list[tuple[tuple[str, ...], T]], padrao: T) -> T:
    normal = normalizar(texto)
    for trechos, valor in regras:
        # No começo de uma palavra: "rio" não casa com "criado".
        if any(re.search(rf"\b{re.escape(t)}", normal) for t in trechos):
            return valor
    return padrao


def enquadramento_canonico(texto: str) -> Enquadramento:
    return _classificar(texto, _ENQUADRAMENTOS, "indefinido")


def ambiente_canonico(texto: str) -> Ambiente:
    return _classificar(texto, _AMBIENTES, "outro")
