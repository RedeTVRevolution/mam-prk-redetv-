"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, StringConstraints, field_validator

from api.comparador import normalizar
from api.pessoas import LISTAS, nao_identificado

TipoDeCorrecao = Literal["pessoa.renomear", "desfazer", "descartar"]
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
    descarta: str | None = None  # só no tipo "descartar": o id da que saiu da fila
    reaplica: str | None = None  # na reaplicação: o id da original que ela refaz
    antes: str
    depois: str
    ancora: Ancora


Motivo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=LIMITE_DO_MOTIVO),
]


class ItemDoHistorico(Correcao):
    estado: Literal["ativa", "desfeita", "reaplicada", "descartada"]


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


class Candidato(BaseModel):
    """Pessoa da versão atual que sobrepõe o intervalo ancorado."""

    item_id: str
    nome: str
    inicio_ms: int
    fim_ms: int


class ItemDaFila(Correcao):
    candidatos: list[Candidato]


class NovaResolucao(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/fila/{cid}/descartar`."""

    motivo: Motivo

    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)


class NovaReaplicacao(NovaResolucao):
    """Corpo de `POST /v1/jobs/{id}/fila/{cid}/reaplicar`."""

    item_id: Annotated[str, StringConstraints(min_length=1, max_length=40)]


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
    return Correcao(
        tipo=novo.tipo,
        item_id=novo.item_id,
        motivo=novo.motivo,
        antes=antes,
        depois=novo.valor,
        ancora=_ancora_da_pessoa(pessoa, versao),
        **registro,
    )


def _ancora_da_pessoa(pessoa: dict[str, Any], versao: str) -> Ancora:
    inicio, fim = _intervalo_da_pessoa(pessoa)
    return Ancora(
        versao=versao,
        tipo_do_item="pessoa",
        identidade=identidade_da_pessoa(pessoa),
        inicio_ms=inicio,
        fim_ms=fim,
    )


class NaoDesfazivel(Exception):
    """A correção já foi desfeita, é ela mesma um desfazer ou, sendo de outra
    versão, não casa com a decupagem atual (não está aplicada)."""


def _desfeitas(correcoes: list[Correcao]) -> set[str]:
    return {c.desfaz for c in correcoes if c.tipo == "desfazer" and c.desfaz}


def _resolvidas(correcoes: list[Correcao]) -> set[str]:
    """As que saíram da fila: reaplicadas ou descartadas."""
    return {c.reaplica or c.descarta for c in correcoes if c.reaplica or c.descarta}  # type: ignore[misc]


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
    mais nova no mesmo item, desfazer a antiga não muda o que se vê. A de outra
    versão só se desfaz se `reconciliar` a casar; o registro aponta o item novo.
    """
    if (
        alvo.tipo != "pessoa.renomear"
        or alvo.id in _desfeitas(correcoes)
        or alvo.id in _resolvidas(correcoes)
    ):
        raise NaoDesfazivel(alvo.id)
    restantes = [c for c in correcoes if c.id != alvo.id]
    if alvo.ancora.versao == versao:
        alvo_atual = alvo
        antes = _nome_pela_ancora(modelo, versao, correcoes, alvo.ancora)
        depois = _nome_pela_ancora(modelo, versao, restantes, alvo.ancora)
    else:
        casadas = reconciliar(modelo, versao, correcoes).casadas
        reapontada = next((c for c in casadas if c.id == alvo.id), None)
        if reapontada is None:
            raise NaoDesfazivel(alvo.id)
        alvo_atual = reapontada
        # A reapontada vale pelo id do item novo, como em `aplicar`.
        antes = nome_atual(modelo, versao, correcoes, alvo_atual.item_id)
        depois = nome_atual(modelo, versao, restantes, alvo_atual.item_id)
    return Correcao(
        tipo="desfazer",
        desfaz=alvo.id,
        item_id=alvo_atual.item_id,
        motivo=motivo,
        antes=antes,
        depois=depois,
        ancora=alvo_atual.ancora,
        **registro,
    )


def historico(correcoes: list[Correcao]) -> list[ItemDoHistorico]:
    """Da mais recente para a mais antiga, cada uma ativa ou desfeita."""
    desfeitas = _desfeitas(correcoes)
    reaplicadas = {c.reaplica for c in correcoes if c.reaplica}
    descartadas = {c.descarta for c in correcoes if c.descarta}

    def estado(c: Correcao) -> Literal["ativa", "desfeita", "reaplicada", "descartada"]:
        if c.id in desfeitas:
            return "desfeita"
        if c.id in reaplicadas:
            return "reaplicada"
        if c.id in descartadas:
            return "descartada"
        return "ativa"

    return [
        ItemDoHistorico(**c.model_dump(), estado=estado(c))
        for c in reversed(em_ordem(correcoes))
    ]


def nome_atual(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao], item_id: str
) -> str:
    """O nome que o Editor vê hoje na pessoa `item_id`."""
    for pessoa in _pessoas(aplicar(modelo, versao, correcoes)):
        if pessoa.get("id") == item_id:
            return str(pessoa["nome"])
    raise ItemInexistente(item_id)


@dataclass(frozen=True)
class Reconciliacao:
    """`casadas` já apontam para o item novo; `atendidas` são as casadas cujo
    "depois" o modelo já traz; `sem_casar` não se aplicam, mas não se perdem."""

    casadas: list[Correcao]
    atendidas: list[Correcao]
    sem_casar: list[Correcao]


def _sobrepoe(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _candidatos(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    """Pessoas da versão nova com a identidade da âncora (ou já com o "depois")."""
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    sem_nome = nao_identificado(c.ancora.identidade.split("@")[0])
    achados = []
    for pessoa in _pessoas(modelo):
        nome = str(pessoa["nome"])
        if sem_nome and nao_identificado(nome):
            # Só as aparições mostram quem é.
            intervalo = _intervalo_da_pessoa(pessoa, ("na_imagem",))
        elif normalizar(nome) == normalizar(c.depois) or (
            not sem_nome and normalizar(nome) == c.ancora.identidade
        ):
            intervalo = _intervalo_da_pessoa(pessoa)
        else:
            continue
        if _sobrepoe(ancora, intervalo):
            achados.append(pessoa)
    return achados


def reconciliar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> Reconciliacao:
    """Casa as correções de versões antigas com a decupagem atual do modelo.

    Casa só com exatamente um item de mesma identidade e intervalo sobreposto;
    zero ou vários candidatos não casam. Ignora as da versão atual, as
    desfeitas, as que saíram da fila e os registros que não são renomeações.
    """
    fora = _desfeitas(correcoes) | _resolvidas(correcoes)
    resultado = Reconciliacao(casadas=[], atendidas=[], sem_casar=[])
    for c in em_ordem(correcoes):
        if c.ancora.versao == versao or c.tipo != "pessoa.renomear" or c.id in fora:
            continue
        candidatos = _candidatos(modelo, c)
        if len(candidatos) != 1:
            resultado.sem_casar.append(c)
            continue
        pessoa = candidatos[0]
        nova = c.model_copy(
            update={
                "item_id": str(pessoa.get("id", "")),
                "ancora": _ancora_da_pessoa(pessoa, versao),
            }
        )
        resultado.casadas.append(nova)
        if normalizar(str(pessoa["nome"])) == normalizar(c.depois):
            resultado.atendidas.append(nova)
    return resultado


def aplicar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """Cópia do modelo com as correções da versão atual por cima.

    Pessoa corrigida vem com `origem: "revisao"`; as demais, com `"modelo"`.
    A atendida (o modelo já traz o "depois") deixa o nome como o modelo o
    escreveu, com `origem: "modelo"`.
    Correção desfeita não conta: o item volta ao valor que teria sem ela.
    Correção de outra versão do JSON só vale se `reconciliar` a casar com um
    item único; as que não casam não se aplicam (e seguem no histórico).
    """
    resultado: dict[str, Any] = json.loads(json.dumps(modelo))
    pessoas = _pessoas(resultado)
    for pessoa in pessoas:
        pessoa["origem"] = "modelo"
    # Casa pela identidade do modelo, calculada antes de qualquer renomeação.
    identidades = [identidade_da_pessoa(p) for p in pessoas]
    nomes_do_modelo = [p["nome"] for p in pessoas]
    desfeitas = _desfeitas(correcoes)
    # ponytail: reconciliar a cada leitura relê as pessoas do modelo por
    # correção antiga (custo pequeno hoje); guardar o resultado quando houver
    # reprocessamentos frequentes ou muitas correções por vídeo.
    reconciliadas = reconciliar(modelo, versao, correcoes)
    atendidas = {c.id for c in reconciliadas.atendidas}
    reapontadas = {c.id for c in reconciliadas.casadas}
    da_versao = [
        c
        for c in correcoes
        if c.ancora.versao == versao and c.tipo == "pessoa.renomear"
    ]

    def casa(c: Correcao, pessoa: dict[str, Any], identidade: str) -> bool:
        # A reapontada vai só ao item que casou, pelo id novo.
        if c.id in reapontadas:
            return pessoa.get("id") == c.item_id
        return identidade == c.ancora.identidade

    # Em ordem de data: a mais nova vence, e desfazer uma antiga não a derruba.
    for c in em_ordem(da_versao + reconciliadas.casadas):
        if c.id in desfeitas:
            continue
        for pessoa, identidade, nome in zip(
            pessoas, identidades, nomes_do_modelo, strict=True
        ):
            if not casa(c, pessoa, identidade):
                continue
            if c.id in atendidas:
                pessoa["nome"], pessoa["origem"] = nome, "modelo"
            else:
                pessoa["nome"], pessoa["origem"] = c.depois, "revisao"
    return resultado


class NaoNaFila(Exception):
    """A correção não está na fila de revisão (casou, saiu da fila ou é de outro tipo)."""


def id_da_resolucao(alvo_id: str) -> str:
    """Fixo por alvo: reaplicar e descartar simultâneos colidem no repositório."""
    return f"{alvo_id}-resolvida"


def fila(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> list[ItemDaFila]:
    """As correções que não casaram, da mais antiga para a mais nova, cada uma
    com as pessoas da versão atual que sobrepõem o intervalo ancorado."""
    itens = []
    for c in reconciliar(modelo, versao, correcoes).sem_casar:
        ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
        candidatos = []
        for pessoa in _pessoas(modelo):
            intervalo = _intervalo_da_pessoa(pessoa)
            if _sobrepoe(ancora, intervalo):
                candidatos.append(
                    Candidato(
                        item_id=str(pessoa.get("id", "")),
                        nome=str(pessoa["nome"]),
                        inicio_ms=intervalo[0],
                        fim_ms=intervalo[1],
                    )
                )
        itens.append(ItemDaFila(**c.model_dump(), candidatos=candidatos))
    return itens


def _exige_na_fila(
    modelo: dict[str, Any], versao: str, alvo: Correcao, correcoes: list[Correcao]
) -> None:
    if alvo.id not in {i.id for i in fila(modelo, versao, correcoes)}:
        raise NaoNaFila(alvo.id)


def montar_reaplicacao(
    modelo: dict[str, Any],
    versao: str,
    alvo: Correcao,
    correcoes: list[Correcao],
    item_id: str,
    motivo: str,
    **registro: Any,
) -> Correcao:
    """A correção nova, ancorada na versão atual no item escolhido e ligada à
    original (`reaplica`). A original sai da fila e continua no histórico."""
    _exige_na_fila(modelo, versao, alvo, correcoes)
    pessoa = next((p for p in _pessoas(modelo) if p.get("id") == item_id), None)
    if pessoa is None:
        raise ItemInexistente(item_id)
    return Correcao(
        tipo="pessoa.renomear",
        reaplica=alvo.id,
        item_id=item_id,
        motivo=motivo,
        antes=nome_atual(modelo, versao, correcoes, item_id),
        depois=alvo.depois,
        ancora=_ancora_da_pessoa(pessoa, versao),
        **registro,
    )


def montar_descarte(
    modelo: dict[str, Any],
    versao: str,
    alvo: Correcao,
    correcoes: list[Correcao],
    motivo: str,
    **registro: Any,
) -> Correcao:
    """O registro que tira `alvo` da fila; ela não se aplica mais."""
    _exige_na_fila(modelo, versao, alvo, correcoes)
    return Correcao(
        tipo="descartar",
        descarta=alvo.id,
        item_id=alvo.item_id,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
        **registro,
    )
