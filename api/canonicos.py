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

# Termos que só valem como palavra inteira ("media" não casa com "mediante").
_PALAVRA_INTEIRA = {"media"}

# Começos de palavra do texto normalizado (sem acento nem maiúscula) -> valor.
_ENQUADRAMENTOS: list[tuple[tuple[str, ...], Enquadramento]] = [
    (
        ("primeirissimo", "super close", "big close", "extreme close"),
        "primeiríssimo plano",
    ),
    (("detalhe",), "detalhe"),
    (("conjunto", "corpo inteiro"), "plano de conjunto"),
    (("americano",), "plano americano"),
    (("geral", "aberto", "panoramic", "wide"), "plano geral"),
    (("medio", "medium", "media"), "plano médio"),
    (
        ("primeiro plano", "close", "fechado", "proximo", "aproximado"),
        "primeiro plano",
    ),
    # Por último: "amplo desfoque" não pode vencer um enquadramento explícito.
    (("amplo",), "plano geral"),
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
    (
        (
            "loja",
            "mercado",
            "supermercado",
            "padaria",
            "lanchonete",
            "shopping",
            "restaurante",
            "comercio",
            "feira",
        ),
        "comércio",
    ),
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
            "externo",
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


def _regex(termo: str) -> str:
    return rf"\b{re.escape(termo)}" + (r"\b" if termo in _PALAVRA_INTEIRA else "")


def _classificar[T](
    texto: str, regras: list[tuple[tuple[str, ...], T]], padrao: T
) -> T:
    normal = normalizar(texto)
    for trechos, valor in regras:
        # No começo de uma palavra: "rio" não casa com "criado".
        if any(re.search(_regex(t), normal) for t in trechos):
            return valor
    return padrao


def enquadramento_canonico(texto: str) -> Enquadramento:
    return _classificar(texto, _ENQUADRAMENTOS, "indefinido")


def ambiente_canonico(texto: str) -> Ambiente:
    return _classificar(texto, _AMBIENTES, "outro")


_PADROES = {"ambiente_canonico": "outro", "enquadramento_canonico": "indefinido"}


def com_os_canonicos(modelo: dict[str, Any], entregue: dict[str, Any]) -> None:
    """Preenche, nos planos da decupagem entregue, o canônico que o modelo não trouxe.

    O canônico gravado vale se não é o padrão (`outro`, `indefinido`: o que a Decupagem
    antiga ganha ao ser regravada) e o texto livre não mudou em relação ao do modelo
    (uma Correção); senão o dicionário o refaz do texto.
    """
    brutos = {p.get("id"): p for p in modelo.get("planos", [])}
    for plano in entregue.get("planos", []):
        bruto = brutos.get(plano.get("id"), {})
        for texto, canonico, f in (
            ("ambiente", "ambiente_canonico", ambiente_canonico),
            ("enquadramento", "enquadramento_canonico", enquadramento_canonico),
        ):
            vale = plano.get(canonico) not in (None, _PADROES[canonico]) and plano.get(
                texto
            ) == bruto.get(texto)
            if not vale:
                plano[canonico] = f(plano.get(texto) or "")
