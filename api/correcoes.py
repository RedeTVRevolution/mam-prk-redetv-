"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
import unicodedata
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, StringConstraints, field_validator

from api.comparador import normalizar
from api.pessoas import LISTAS, nao_identificado

TipoDeCorrecao = Literal["pessoa.renomear", "desfazer"]
LIMITE_DO_MOTIVO = 500
LIMITE_DO_NOME = 200  # o mesmo de `Rotulo` na decupagem


# Controles (C0, C1), formatação invisível (largura zero, direção do texto) e
# separadores de linha e parágrafo do Unicode.
_PROIBIDAS = {"Cc", "Cf", "Zl", "Zp"}


def _sem_controle(texto: str, permitidos: str = "") -> str:
    if any(
        unicodedata.category(c) in _PROIBIDAS and c not in permitidos for c in texto
    ):
        raise ValueError("caractere de controle")
    return texto


def _sem_controle_salvo_quebra(texto: str) -> str:
    """O motivo vem de um campo de várias linhas: aceita só a quebra de linha."""
    return _sem_controle(texto.replace("\r\n", "\n"), permitidos="\n")


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
    item_id: str = ""  # id da pessoa no JSON do modelo
    desfaz: str | None = None  # só no tipo "desfazer": o id da correção revertida
    antes: str
    depois: str
    ancora: Ancora


Motivo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=LIMITE_DO_MOTIVO),
]


class ItemDoHistorico(Correcao):
    estado: Literal["ativa", "desfeita"]


class NovoDesfazer(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/correcoes/{cid}/desfazer`."""

    motivo: Motivo

    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)


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
    motivo: Motivo
    versao: Annotated[str, StringConstraints(min_length=1, max_length=64)]

    _valor_sem_controle = field_validator("valor")(_sem_controle)
    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)


class ItemInexistente(Exception):
    """O item da correção não existe no JSON do modelo."""


class CorrecaoJaExiste(Exception):
    """Já há um registro com esse id: o repositório nunca sobrescreve."""


class RepositorioDeCorrecoes(Protocol):
    """Porta para o Firestore; só acrescenta, nunca altera nem apaga."""

    def acrescentar(self, correcao: Correcao) -> None:
        """`CorrecaoJaExiste` se o id já foi gravado."""
        ...

    def listar(self, job_id: str) -> list[Correcao]:
        """Da mais antiga para a mais recente."""
        ...


class RepositorioDeCorrecoesEmMemoria:
    def __init__(self) -> None:
        self._correcoes: list[Correcao] = []

    def acrescentar(self, correcao: Correcao) -> None:
        if any(c.id == correcao.id for c in self._correcoes):
            raise CorrecaoJaExiste(correcao.id)
        self._correcoes.append(correcao)

    def listar(self, job_id: str) -> list[Correcao]:
        return em_ordem([c for c in self._correcoes if c.job_id == job_id])


def em_ordem(correcoes: list[Correcao]) -> list[Correcao]:
    """Por data; o id desempata, para a ordem não depender de quem listou."""
    return sorted(correcoes, key=lambda c: (c.criada_em, c.id))


def versao_do_modelo(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _intervalo_da_pessoa(
    pessoa: dict[str, Any], listas: tuple[str, ...] = LISTAS
) -> tuple[int, int]:
    ocorrencias = [o for lista in listas for o in pessoa.get(lista, [])]
    if not ocorrencias:
        return 0, 0
    return (
        min(o["inicio_ms"] for o in ocorrencias),
        max(o["fim_ms"] for o in ocorrencias),
    )


def identidade_da_pessoa(pessoa: dict[str, Any]) -> str:
    """O nome normalizado como na união de pessoas entre janelas (#42).

    "Não identificado" não distingue ninguém: a identidade vira o intervalo
    das aparições (só elas mostram quem é).
    """
    nome = str(pessoa["nome"])
    if nao_identificado(nome):
        inicio, fim = _intervalo_da_pessoa(pessoa, ("na_imagem",))
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
        item_id=novo.item_id,
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


class NaoDesfazivel(Exception):
    """A correção já foi desfeita, é ela mesma um desfazer ou é de outra versão."""


def _desfeitas(correcoes: list[Correcao]) -> set[str]:
    return {c.desfaz for c in correcoes if c.tipo == "desfazer" and c.desfaz}


def id_do_desfazer(alvo_id: str) -> str:
    """Fixo por alvo: dois desfazer simultâneos colidem no repositório."""
    return f"{alvo_id}-desfeita"


def _nome_pela_ancora(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao], ancora: Ancora
) -> str:
    """O nome entregue hoje na pessoa da âncora (casa como `aplicar`)."""
    entregue = _pessoas(aplicar(modelo, versao, correcoes))
    for original, pessoa in zip(_pessoas(modelo), entregue, strict=True):
        if identidade_da_pessoa(original) == ancora.identidade:
            return str(pessoa["nome"])
    raise ItemInexistente(ancora.identidade)


def montar_desfazer(
    modelo: dict[str, Any],
    versao: str,
    alvo: Correcao,
    correcoes: list[Correcao],
    motivo: str,
    **registro: Any,
) -> Correcao:
    """O registro que reverte `alvo`; nada é apagado. Um desfazer não se desfaz.

    Antes e depois são o nome entregue sem e com o desfazer: com uma correção
    mais nova no mesmo item, desfazer a antiga não muda o que se vê.
    """
    if (
        alvo.tipo == "desfazer"
        or alvo.id in _desfeitas(correcoes)
        or alvo.ancora.versao != versao
    ):
        raise NaoDesfazivel(alvo.id)
    restantes = [c for c in correcoes if c.id != alvo.id]
    return Correcao(
        tipo="desfazer",
        desfaz=alvo.id,
        item_id=alvo.item_id,
        motivo=motivo,
        antes=_nome_pela_ancora(modelo, versao, correcoes, alvo.ancora),
        depois=_nome_pela_ancora(modelo, versao, restantes, alvo.ancora),
        ancora=alvo.ancora,
        **registro,
    )


def historico(correcoes: list[Correcao]) -> list[ItemDoHistorico]:
    """Da mais recente para a mais antiga, cada uma ativa ou desfeita."""
    desfeitas = _desfeitas(correcoes)
    ordenadas = list(reversed(em_ordem(correcoes)))
    return [
        ItemDoHistorico(
            **c.model_dump(), estado="desfeita" if c.id in desfeitas else "ativa"
        )
        for c in ordenadas
    ]


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
    Correção desfeita não conta: o item volta ao valor que teria sem ela.
    Correção de outra versão do JSON fica de fora: reconciliar é outro ticket.
    """
    resultado: dict[str, Any] = json.loads(json.dumps(modelo))
    pessoas = _pessoas(resultado)
    for pessoa in pessoas:
        pessoa["origem"] = "modelo"
    # Casa pela identidade do modelo, calculada antes de qualquer renomeação.
    identidades = [identidade_da_pessoa(p) for p in pessoas]
    desfeitas = _desfeitas(correcoes)
    # Em ordem de data: a mais nova vence, e desfazer uma antiga não a derruba.
    for c in em_ordem(correcoes):
        if (
            c.ancora.versao != versao
            or c.tipo != "pessoa.renomear"
            or c.id in desfeitas
        ):
            continue
        for pessoa, identidade in zip(pessoas, identidades, strict=True):
            if identidade == c.ancora.identidade:
                pessoa["nome"] = c.depois
                pessoa["origem"] = "revisao"
    return resultado
