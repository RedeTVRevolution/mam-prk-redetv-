"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import BaseModel, StringConstraints, field_validator, model_validator

from api.comparador import normalizar
from api.pessoas import LISTAS, nao_identificado

TipoNovo = Literal["pessoa.renomear", "pauta.titulo", "pauta.resumo", "item.tempos"]
TipoDeCorrecao = Literal[TipoNovo, "desfazer", "descartar"]
TIPOS_DE_PAUTA = ("pauta.titulo", "pauta.resumo", "item.tempos")
CORRIGIVEIS = ("pessoa.renomear", *TIPOS_DE_PAUTA)
LIMITE_DO_MOTIVO = 500
LIMITE_DO_NOME = 200  # o mesmo de `Rotulo` na decupagem
LIMITE_DO_TEXTO = 2000  # o mesmo de `Texto` na decupagem
_TEMPOS = re.compile(r"^(\d{1,12})-(\d{1,12})$")


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
    tipo_do_item: Literal["pessoa", "pauta"]
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


EstadoNoHistorico = Literal["ativa", "desfeita", "reaplicada", "descartada"]


class ItemDoHistorico(Correcao):
    estado: EstadoNoHistorico


def tempos_de(valor: str) -> tuple[int, int]:
    """Lê "<inicio_ms>-<fim_ms>"; `ValueError` se não for isso ou se o início passar do fim."""
    achado = _TEMPOS.match(valor)
    if achado is None:
        raise ValueError("tempos fora do formato inicio_ms-fim_ms")
    inicio, fim = int(achado[1]), int(achado[2])
    if inicio > fim:
        raise ValueError("início depois do fim")
    return inicio, fim


class NovoDesfazer(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/correcoes/{cid}/desfazer`."""

    motivo: Motivo

    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)


class NovaCorrecao(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/correcoes`."""

    tipo: TipoNovo
    item_id: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    # `item.tempos`: "<inicio_ms>-<fim_ms>".
    valor: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_TEXTO
        ),
    ]
    motivo: Motivo
    versao: Annotated[str, StringConstraints(min_length=1, max_length=64)]

    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)

    @model_validator(mode="after")
    def _valor_do_tipo(self) -> Self:
        if self.tipo == "item.tempos":
            tempos_de(self.valor)
        elif self.tipo == "pauta.resumo":
            self.valor = _sem_controle_salvo_quebra(self.valor)
        else:
            _sem_controle(self.valor)
            if len(self.valor) > LIMITE_DO_NOME:
                raise ValueError("valor longo demais")
        return self


class Candidato(BaseModel):
    """Item (pessoa ou pauta) da versão atual que sobrepõe o intervalo ancorado."""

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


def _pautas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("pautas", []) if isinstance(p, dict)]


def _tipo_do_item(tipo: str) -> Literal["pessoa", "pauta"]:
    return "pessoa" if tipo == "pessoa.renomear" else "pauta"


def _itens(modelo: dict[str, Any], tipo_do_item: str) -> list[dict[str, Any]]:
    return _pessoas(modelo) if tipo_do_item == "pessoa" else _pautas(modelo)


def _intervalo_da_pauta(pauta: dict[str, Any]) -> tuple[int, int]:
    return int(pauta["inicio_ms"]), int(pauta["fim_ms"])


def _intervalo_do_item(item: dict[str, Any], tipo_do_item: str) -> tuple[int, int]:
    if tipo_do_item == "pessoa":
        return _intervalo_da_pessoa(item)
    return _intervalo_da_pauta(item)


def _rotulo_do_item(item: dict[str, Any], tipo_do_item: str) -> str:
    return str(item["nome" if tipo_do_item == "pessoa" else "titulo"])


def _valor_do_item(item: dict[str, Any], tipo: str) -> str:
    """O valor que a correção do `tipo` troca neste item."""
    if tipo == "pessoa.renomear":
        return str(item["nome"])
    if tipo == "pauta.titulo":
        return str(item["titulo"])
    if tipo == "pauta.resumo":
        return str(item["resumo"])
    inicio, fim = _intervalo_da_pauta(item)
    return f"{inicio}-{fim}"


class TemposInvalidos(Exception):
    """Os tempos passam da duração do vídeo."""


def _confere_duracao(modelo: dict[str, Any], tipo: str, valor: str) -> None:
    """`TemposInvalidos` se os tempos de um `item.tempos` passam da duração."""
    if tipo != "item.tempos":
        return
    duracao = int(modelo.get("video", {}).get("duracao_ms", 0))
    if tempos_de(valor)[1] > duracao:
        raise TemposInvalidos(valor)


def montar_correcao(
    modelo: dict[str, Any],
    versao: str,
    novo: NovaCorrecao,
    antes: str,
    **registro: Any,
) -> Correcao:
    """A correção de `novo` sobre o item do JSON do modelo, com a âncora pronta."""
    tipo_do_item = _tipo_do_item(novo.tipo)
    item = next(
        (i for i in _itens(modelo, tipo_do_item) if i.get("id") == novo.item_id), None
    )
    if item is None:
        raise ItemInexistente(novo.item_id)
    _confere_duracao(modelo, novo.tipo, novo.valor)
    return Correcao(
        tipo=novo.tipo,
        item_id=novo.item_id,
        motivo=novo.motivo,
        antes=antes,
        depois=novo.valor,
        ancora=_ancora_do_item(item, tipo_do_item, versao),
        **registro,
    )


def _ancora_do_item(item: dict[str, Any], tipo_do_item: str, versao: str) -> Ancora:
    if tipo_do_item == "pessoa":
        return _ancora_da_pessoa(item, versao)
    inicio, fim = _intervalo_da_pauta(item)
    return Ancora(
        versao=versao,
        tipo_do_item="pauta",
        identidade=normalizar(str(item["titulo"])),
        inicio_ms=inicio,
        fim_ms=fim,
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
    return {c.reaplica for c in correcoes if c.reaplica} | {
        c.descarta for c in correcoes if c.descarta
    }


def id_do_desfazer(alvo_id: str) -> str:
    """Fixo por alvo: dois desfazer simultâneos colidem no repositório."""
    return f"{alvo_id}-desfeita"


def _valor_do_alvo(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao], alvo: Correcao
) -> str:
    """O valor entregue hoje no item do alvo (casa como `aplicar`): a pessoa
    pela identidade da âncora; a pauta pelo id, que na mesma versão é estável."""
    if alvo.tipo != "pessoa.renomear":
        return valor_atual(modelo, versao, correcoes, alvo.tipo, alvo.item_id)
    entregue = _pessoas(aplicar(modelo, versao, correcoes))
    for original, pessoa in zip(_pessoas(modelo), entregue, strict=True):
        if identidade_da_pessoa(original) == alvo.ancora.identidade:
            return str(pessoa["nome"])
    raise ItemInexistente(alvo.ancora.identidade)


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
    mais nova no mesmo campo, desfazer a antiga não muda o que se vê. A de outra
    versão só se desfaz se `reconciliar` a casar; o registro aponta o item novo.
    """
    if (
        alvo.tipo not in CORRIGIVEIS
        or alvo.id in _desfeitas(correcoes)
        or alvo.id in _resolvidas(correcoes)
    ):
        raise NaoDesfazivel(alvo.id)
    restantes = [c for c in correcoes if c.id != alvo.id]
    if alvo.ancora.versao == versao:
        alvo_atual = alvo
        antes = _valor_do_alvo(modelo, versao, correcoes, alvo)
        depois = _valor_do_alvo(modelo, versao, restantes, alvo)
    else:
        casadas = reconciliar(modelo, versao, correcoes).casadas
        reapontada = next((c for c in casadas if c.id == alvo.id), None)
        if reapontada is None:
            raise NaoDesfazivel(alvo.id)
        alvo_atual = reapontada
        # A reapontada vale pelo id do item novo, como em `aplicar`.
        antes = valor_atual(
            modelo, versao, correcoes, alvo_atual.tipo, alvo_atual.item_id
        )
        depois = valor_atual(
            modelo, versao, restantes, alvo_atual.tipo, alvo_atual.item_id
        )
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
    """Da mais recente para a mais antiga, cada uma ativa, desfeita ou fora da
    fila (reaplicada ou descartada)."""
    desfeitas = _desfeitas(correcoes)
    reaplicadas = {c.reaplica for c in correcoes if c.reaplica}
    descartadas = {c.descarta for c in correcoes if c.descarta}

    def estado(c: Correcao) -> EstadoNoHistorico:
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


def valor_atual(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    tipo: str,
    item_id: str,
) -> str:
    """O valor que o Editor vê hoje no campo do `tipo` do item `item_id`."""
    for item in _itens(aplicar(modelo, versao, correcoes), _tipo_do_item(tipo)):
        if item.get("id") == item_id:
            return _valor_do_item(item, tipo)
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


def _sobrepoe_metade(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """A sobreposição cobre pelo menos metade do menor dos dois intervalos.

    Um intervalo de duração zero (um instante) conta se cai dentro do outro.
    """
    sobreposicao = min(a[1], b[1]) - max(a[0], b[0])
    menor = min(a[1] - a[0], b[1] - b[0])
    return sobreposicao >= 0 and sobreposicao * 2 >= menor


def _candidatos(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    """Itens da versão nova que a correção pode estar apontando.

    Pauta: a que sobrepõe o intervalo ancorado em pelo menos metade do menor
    dos dois. Pessoa: a com a identidade da âncora (ou já com o "depois").
    """
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    if c.ancora.tipo_do_item == "pauta":
        return [
            p
            for p in _pautas(modelo)
            if _sobrepoe_metade(ancora, _intervalo_da_pauta(p))
        ]
    return _candidatos_pessoa(modelo, c)


def _candidatos_pessoa(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
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
    desfeitas, as que saíram da fila e os registros que não corrigem um item.
    """
    fora = _desfeitas(correcoes) | _resolvidas(correcoes)
    resultado = Reconciliacao(casadas=[], atendidas=[], sem_casar=[])
    for c in em_ordem(correcoes):
        if c.ancora.versao == versao or c.tipo not in CORRIGIVEIS or c.id in fora:
            continue
        candidatos = _candidatos(modelo, c)
        if len(candidatos) != 1:
            resultado.sem_casar.append(c)
            continue
        pessoa = candidatos[0]
        nova = c.model_copy(
            update={
                "item_id": str(pessoa.get("id", "")),
                "ancora": _ancora_do_item(pessoa, c.ancora.tipo_do_item, versao),
            }
        )
        resultado.casadas.append(nova)
        if c.tipo == "pessoa.renomear" and normalizar(str(pessoa["nome"])) == (
            normalizar(c.depois)
        ):
            resultado.atendidas.append(nova)
    return resultado


def _aplicar_na_pauta(resultado: dict[str, Any], c: Correcao) -> None:
    """A pauta é achada pelo id: na versão atual o id do item é estável, e a
    reapontada já traz o id novo."""
    for pauta in _pautas(resultado):
        if pauta.get("id") != c.item_id:
            continue
        if c.tipo == "item.tempos":
            pauta["inicio_ms"], pauta["fim_ms"] = tempos_de(c.depois)
        else:
            pauta["titulo" if c.tipo == "pauta.titulo" else "resumo"] = c.depois
        pauta["origem"] = "revisao"


def aplicar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """Cópia do modelo com as correções da versão atual por cima.

    Pessoa ou pauta corrigida vem com `origem: "revisao"`; as demais, com
    `"modelo"`.
    A atendida (o modelo já traz o "depois") deixa o nome como o modelo o
    escreveu, com `origem: "modelo"`.
    Correção desfeita não conta: o item volta ao valor que teria sem ela.
    Correção de outra versão do JSON só vale se `reconciliar` a casar com um
    item único; as que não casam não se aplicam (e seguem no histórico).
    """
    resultado: dict[str, Any] = json.loads(json.dumps(modelo))
    pessoas = _pessoas(resultado)
    for item in [*pessoas, *_pautas(resultado)]:
        item["origem"] = "modelo"
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
        c for c in correcoes if c.ancora.versao == versao and c.tipo in CORRIGIVEIS
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
        if c.tipo in TIPOS_DE_PAUTA:
            _aplicar_na_pauta(resultado, c)
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


class NaoCandidato(Exception):
    """O item escolhido para reaplicar não é candidato do item da fila."""


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
        tipo_do_item = c.ancora.tipo_do_item
        candidatos = []
        for item in _itens(modelo, tipo_do_item):
            intervalo = _intervalo_do_item(item, tipo_do_item)
            if _sobrepoe(ancora, intervalo):
                candidatos.append(
                    Candidato(
                        item_id=str(item.get("id", "")),
                        nome=_rotulo_do_item(item, tipo_do_item),
                        inicio_ms=intervalo[0],
                        fim_ms=intervalo[1],
                    )
                )
        itens.append(ItemDaFila(**c.model_dump(), candidatos=candidatos))
    return itens


def _na_fila(
    modelo: dict[str, Any], versao: str, alvo: Correcao, correcoes: list[Correcao]
) -> ItemDaFila:
    item = next((i for i in fila(modelo, versao, correcoes) if i.id == alvo.id), None)
    if item is None:
        raise NaoNaFila(alvo.id)
    return item


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
    original (`reaplica`). A original sai da fila e continua no histórico.
    O item tem de ser um dos candidatos que a fila oferece."""
    item = _na_fila(modelo, versao, alvo, correcoes)
    if item_id not in {c.item_id for c in item.candidatos}:
        raise NaoCandidato(item_id)
    tipo_do_item = alvo.ancora.tipo_do_item
    novo = next(i for i in _itens(modelo, tipo_do_item) if i.get("id") == item_id)
    # O vídeo reprocessado pode ser mais curto que o da correção original.
    _confere_duracao(modelo, alvo.tipo, alvo.depois)
    return Correcao(
        tipo=alvo.tipo,
        reaplica=alvo.id,
        item_id=item_id,
        motivo=motivo,
        antes=valor_atual(modelo, versao, correcoes, alvo.tipo, item_id),
        depois=alvo.depois,
        ancora=_ancora_do_item(novo, tipo_do_item, versao),
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
    _na_fila(modelo, versao, alvo, correcoes)
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
