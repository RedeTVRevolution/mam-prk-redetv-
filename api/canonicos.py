"""Enquadramento e ambiente canônicos (#545).

O texto livre do modelo continua gravado; o valor canônico é um campo à parte, preenchido
pelo modelo nos vídeos novos e, no acervo, por estes dicionários na leitura (depois das
Correções). O que o dicionário não conhece cai em `indefinido` (enquadramento) ou `outro`
(ambiente). Em cada lista a primeira regra que casa vence: as mais específicas vêm antes.
"""

import re
from typing import Any

from api.comparador import normalizar
from api.decupagem import Ambiente, Enquadramento

# Começos de palavra do texto normalizado (sem acento nem maiúscula) -> valor.
_ENQUADRAMENTOS: list[tuple[tuple[str, ...], Enquadramento]] = [
    (
        ("primeirissimo", "super close", "big close", "extreme close"),
        "primeiríssimo plano",
    ),
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
    (
        ("carro", "veiculo", "onibus", "caminhao", "viatura", "helicoptero", "aviao"),
        "veículo",
    ),
    (
        ("escritorio", "empresa", "sala de reuniao", "delegacia", "tribunal"),
        "escritório",
    ),
    (("loja", "mercado", "shopping", "restaurante", "comercio", "feira"), "comércio"),
    (
        ("casa", "residencia", "sala de estar", "cozinha", "quarto", "apartamento"),
        "residência",
    ),
    (
        ("praia", "floresta", "mata", "campo", "rio", "natureza", "montanha", "parque"),
        "natureza",
    ),
    (
        (
            "rua",
            "externa",
            "exterior",
            "avenida",
            "praca",
            "ao ar livre",
            "calcada",
            "estrada",
        ),
        "externa",
    ),
]


def _classificar[T](
    texto: str, regras: list[tuple[tuple[str, ...], T]], padrao: T
) -> T:
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


def com_os_canonicos(entregue: dict[str, Any]) -> None:
    """Preenche, nos planos da decupagem entregue, o que o modelo não trouxe.

    O canônico do modelo vale; falta nos vídeos antigos, e o plano corrigido
    (`origem: "revisao"`) tem o texto novo, que o canônico antigo não conhece.
    """
    for plano in entregue.get("planos", []):
        corrigido = plano.get("origem") == "revisao"
        for texto, canonico, f in (
            ("ambiente", "ambiente_canonico", ambiente_canonico),
            ("enquadramento", "enquadramento_canonico", enquadramento_canonico),
        ):
            if corrigido or canonico not in plano:
                plano[canonico] = f(plano.get(texto) or "")
