"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, StringConstraints, field_validator

from api.comparador import normalizar
from api.pessoas import LISTAS, nao_identificado

TipoDeCorrecao = Literal["pessoa.renomear"]
LIMITE_DO_MOTIVO = 500
LIMITE_DO_NOME = 200  # o mesmo de `Rotulo` na decupagem


def _sem_controle(texto: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in texto):
        raise ValueError("caractere de controle")
    return texto


class Ancora(BaseModel):
    versao: str  # SHA-256 do JSON do modelo no Storage
    tipo_do_item: Literal["pessoa"]
    identidade: str
    inicio_ms: int
    fim_ms: int


class Correcao(BaseModel):
    id: str
    job_id: str
    autor_uid: str
    autor_email: str
    criada_em: datetime
    motivo: str
    tipo: TipoDeCorrecao
    antes: str
    depois: str
    ancora: Ancora


class NovaCorrecao(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/correcoes`."""

    tipo: TipoDeCorrecao
    item_id: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    valor: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
        ),
    ]
    motivo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_MOTIVO
        ),
    ]
    versao: Annotated[str, StringConstraints(min_length=1, max_length=64)]

    _valor_sem_controle = field_validator("valor")(_sem_controle)
    _motivo_sem_controle = field_validator("motivo")(_sem_controle)


class ItemInexistente(Exception):
    """O item da correção não existe no JSON do modelo."""


class RepositorioDeCorrecoes(Protocol):
    """Porta para o Firestore; só acrescenta, nunca altera nem apaga."""

    def acrescentar(self, correcao: Correcao) -> None: ...

    def listar(self, job_id: str) -> list[Correcao]:
        """Da mais antiga para a mais recente."""
        ...


class RepositorioDeCorrecoesEmMemoria:
    def __init__(self) -> None:
        self._correcoes: list[Correcao] = []

    def acrescentar(self, correcao: Correcao) -> None:
        self._correcoes.append(correcao)

    def listar(self, job_id: str) -> list[Correcao]:
        achadas = [c for c in self._correcoes if c.job_id == job_id]
        return sorted(achadas, key=lambda c: c.criada_em)


def versao_do_modelo(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _intervalo_da_pessoa(pessoa: dict[str, Any]) -> tuple[int, int]:
    ocorrencias = [o for lista in LISTAS for o in pessoa.get(lista, [])]
    if not ocorrencias:
        return 0, 0
    return (
        min(o["inicio_ms"] for o in ocorrencias),
        max(o["fim_ms"] for o in ocorrencias),
    )


def identidade_da_pessoa(pessoa: dict[str, Any]) -> str:
    """O nome normalizado como na união de pessoas entre janelas (#42).

    "Não identificado" não distingue ninguém: a identidade vira o intervalo
    das ocorrências.
    """
    nome = str(pessoa["nome"])
    if nao_identificado(nome):
        inicio, fim = _intervalo_da_pessoa(pessoa)
        return f"{normalizar(nome)}@{inicio}-{fim}"
    return normalizar(nome)


def _pessoas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("pessoas", []) if isinstance(p, dict)]


def montar_correcao(
    modelo: dict[str, Any],
    versao: str,
    novo: NovaCorrecao,
    antes: str,
    **registro: Any,
) -> Correcao:
    """A correção de `novo` sobre o item do JSON do modelo, com a âncora pronta."""
    pessoa = next((p for p in _pessoas(modelo) if p.get("id") == novo.item_id), None)
    if pessoa is None:
        raise ItemInexistente(novo.item_id)
    inicio, fim = _intervalo_da_pessoa(pessoa)
    return Correcao(
        tipo=novo.tipo,
        motivo=novo.motivo,
        antes=antes,
        depois=novo.valor,
        ancora=Ancora(
            versao=versao,
            tipo_do_item="pessoa",
            identidade=identidade_da_pessoa(pessoa),
            inicio_ms=inicio,
            fim_ms=fim,
        ),
        **registro,
    )


def nome_atual(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao], item_id: str
) -> str:
    """O nome que o Editor vê hoje na pessoa `item_id`."""
    for pessoa in _pessoas(aplicar(modelo, versao, correcoes)):
        if pessoa.get("id") == item_id:
            return str(pessoa["nome"])
    raise ItemInexistente(item_id)


def aplicar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """Cópia do modelo com as correções da versão atual por cima.

    Pessoa corrigida vem com `origem: "revisao"`; as demais, com `"modelo"`.
    Correção de outra versão do JSON fica de fora: reconciliar é outro ticket.
    """
    resultado: dict[str, Any] = json.loads(json.dumps(modelo))
    pessoas = _pessoas(resultado)
    for pessoa in pessoas:
        pessoa["origem"] = "modelo"
    # Casa pela identidade do modelo, calculada antes de qualquer renomeação.
    identidades = [identidade_da_pessoa(p) for p in pessoas]
    for c in correcoes:
        if c.ancora.versao != versao or c.tipo != "pessoa.renomear":
            continue
        for pessoa, identidade in zip(pessoas, identidades, strict=True):
            if identidade == c.ancora.identidade:
                pessoa["nome"] = c.depois
                pessoa["origem"] = "revisao"
    return resultado
