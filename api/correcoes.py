"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, Self, cast, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from api import catalogo_de_correcoes as textos
from api.catalogo import Catalogo
from api.comparador import normalizar
from api.decupagem import (
    Comercial,
    EvidenciaDoComercial,
    FonteDoNome,
    TextoNaTela,
    TomDaPauta,
)
from api.identidade import (
    identidade_do_comercial as _identidade_do_comercial,
)
from api.identidade import identidade_do_nome, nao_identificado
from api.pessoas import LISTAS

TipoNovo = Literal[
    "pessoa.renomear",
    "pauta.titulo",
    "pauta.resumo",
    "item.tempos",
    "comercial.marca",
    "comercial.tipo",
    "comercial.acrescentar",
    "pessoa.nao_e",
    "pessoa.aparicao_para_mencao",
    "pessoa.mencao_para_aparicao",
    "pessoa.acrescentar_aparicao",
    "plano.descricao",
    "plano.limpo",
    "fala.texto",
    "pauta.tom",
    "pessoa.fontes_do_nome",
    "aparicao.papel_visual",
    "texto_na_tela.texto",
    "texto_na_tela.acrescentar",
]
TipoDeCorrecao = Literal[TipoNovo, "desfazer", "descartar", "aprovar", "recusar"]
TipoDoItem = Literal["pessoa", "pauta", "comercial", "plano", "fala", "texto_na_tela"]
CORRIGIVEIS = get_args(TipoNovo)
Lista = Literal["na_imagem", "citada_na_fala", "citada_no_texto"]
MENCOES = ("citada_na_fala", "citada_no_texto")
# Prefixo do id da pessoa ou do comercial que a revisão cria.
PREFIXO_ACRESCENTADO = "acr-"
PREFIXO_NAO_IDENTIFICADO = "nid-"
NOME_NAO_IDENTIFICADO = "Não identificado"
# Os tipos do esquema 1.2, a mesma lista que o Gemini recebe.
TIPOS_DE_COMERCIAL = get_args(Comercial.model_fields["tipo"].annotation)
CAMPOS_DO_COMERCIAL = ("marca", "tipo", "inicio_ms", "fim_ms", "evidencias")
LIMITE_DO_MOTIVO = 500
LIMITE_DO_NOME = 200  # o mesmo de `Rotulo` na decupagem
LIMITE_DO_TEXTO = 2000  # o mesmo de `Texto` na decupagem
# A descrição de plano e o texto de fala vão em JSON: cabe a maior descrição
# válida (200 + 2000 + 50 × 200 caracteres) com folga para aspas e escapes.
LIMITE_DO_JSON = 16000
LIMITE_DE_OBJETOS = 50
# Os planos seguem os cortes: o plano da versão nova está a até 1 s dos ancorados.
TOLERANCIA_DO_PLANO_MS = 1000
TIPOS_DE_TEXTO_NA_TELA = get_args(TextoNaTela.model_fields["tipo"].annotation)
FONTES_DO_NOME = get_args(FonteDoNome)
TONS_DA_PAUTA = get_args(TomDaPauta)
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
    tipo_do_item: TipoDoItem
    identidade: str
    inicio_ms: int
    fim_ms: int


class Ocorrencia(BaseModel):
    """Uma aparição ou menção da pessoa: a lista e o intervalo que a identificam.

    No pedido o intervalo é o da ocorrência na decupagem entregue; ela é achada
    pela sobreposição de intervalo na mesma lista.
    """

    lista: Lista
    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


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
    # Nasce pendente: só entra na decupagem entregue depois de aprovada.
    exige_aprovacao: bool = False
    aprova: str | None = None  # só no tipo "aprovar": o id da correção aprovada
    recusa: str | None = None  # só no tipo "recusar": o id da correção recusada
    ocorrencia: Ocorrencia | None = None  # nas correções de aparição e menção
    # Só no `pessoa.renomear` cujo nome casa com uma pessoa do catálogo.
    catalogo_id: str | None = None
    antes: str
    depois: str
    ancora: Ancora


Motivo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=LIMITE_DO_MOTIVO),
]


EstadoNoHistorico = Literal[
    "ativa",
    "desfeita",
    "reaplicada",
    "descartada",
    "pendente",
    "aprovada",
    "recusada",
]


class ItemDoHistorico(Correcao):
    estado: EstadoNoHistorico
    antes_legivel: str
    depois_legivel: str


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


class NovoComercial(BaseModel):
    """O comercial de um `comercial.acrescentar`, com os campos do esquema 1.2."""

    model_config = ConfigDict(extra="forbid")

    marca: Annotated[str, StringConstraints(min_length=1, max_length=LIMITE_DO_NOME)]
    tipo: str
    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]
    evidencias: Annotated[list[EvidenciaDoComercial], Field(min_length=1)]

    @field_validator("marca")
    @classmethod
    def _texto_sem_controle(cls, valor: str) -> str:
        return _sem_controle(valor)

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.tipo not in TIPOS_DE_COMERCIAL:
            raise ValueError("tipo de comercial desconhecido")
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


class NovaAparicao(BaseModel):
    """A aparição de um `pessoa.acrescentar_aparicao`; `nome` só para pessoa nova."""

    model_config = ConfigDict(extra="forbid")

    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]
    evidencia: Annotated[
        str, StringConstraints(min_length=1, max_length=LIMITE_DO_NOME)
    ]
    nome: (
        Annotated[str, StringConstraints(min_length=1, max_length=LIMITE_DO_NOME)]
        | None
    ) = None

    @field_validator("nome", "evidencia")
    @classmethod
    def _texto_sem_controle(cls, valor: str | None) -> str | None:
        return None if valor is None else _sem_controle(valor)

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        if self.nome is not None and nao_identificado(self.nome):
            raise ValueError("nome de pessoa nova não pode ser não identificado")
        return self


class NovaDescricao(BaseModel):
    """O valor de um `plano.descricao`: ambiente, ação e objetos."""

    model_config = ConfigDict(extra="forbid")

    ambiente: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
        ),
    ]
    acao: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, max_length=LIMITE_DO_TEXTO)
        ]
        | None
    ) = None
    objetos: Annotated[
        list[
            Annotated[
                str,
                StringConstraints(
                    strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
                ),
            ]
        ],
        Field(max_length=LIMITE_DE_OBJETOS),
    ] = []

    @field_validator("ambiente", "objetos")
    @classmethod
    def _sem_controle_nos_rotulos(cls, valor: str | list[str]) -> str | list[str]:
        for texto in [valor] if isinstance(valor, str) else valor:
            _sem_controle(texto)
        return valor

    @field_validator("acao")
    @classmethod
    def _acao(cls, valor: str | None) -> str | None:
        if not valor:
            return None
        return _sem_controle_salvo_quebra(valor)


class NovoTexto(BaseModel):
    """O valor de um `fala.texto`: o texto e o locutor; os tempos não mudam."""

    model_config = ConfigDict(extra="forbid")

    texto: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_TEXTO
        ),
    ]
    locutor: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
        ),
    ]

    @field_validator("texto")
    @classmethod
    def _texto(cls, valor: str) -> str:
        return _sem_controle_salvo_quebra(valor)

    @field_validator("locutor")
    @classmethod
    def _locutor(cls, valor: str) -> str:
        return _sem_controle(valor)


class NovoPapelVisual(BaseModel):
    """O valor de um `aparicao.papel_visual`: os dois campos, cada um texto ou null."""

    model_config = ConfigDict(extra="forbid")

    papel: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
            ),
        ]
        | None
    )
    visual: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
            ),
        ]
        | None
    )

    @field_validator("papel", "visual")
    @classmethod
    def _sem_controle_nos_rotulos(cls, valor: str | None) -> str | None:
        return None if valor is None else _sem_controle(valor)


class NovoTextoNaTela(BaseModel):
    """O valor de um `texto_na_tela.texto`: o tipo e o texto; os tempos não mudam."""

    model_config = ConfigDict(extra="forbid")

    tipo: str
    texto: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_TEXTO
        ),
    ]

    @field_validator("texto")
    @classmethod
    def _texto(cls, valor: str) -> str:
        return _sem_controle_salvo_quebra(valor)

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, valor: str) -> str:
        if valor not in TIPOS_DE_TEXTO_NA_TELA:
            raise ValueError("tipo de texto na tela desconhecido")
        return valor


class NovoTextoAcrescentado(NovoTextoNaTela):
    """O texto na tela de um `texto_na_tela.acrescentar`: tempos, tipo e texto."""

    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


_FONTES = TypeAdapter(list[FonteDoNome])


def _json_das_fontes(fontes: Sequence[str]) -> str:
    """A lista na ordem do esquema, para que a mesma lista tenha um só valor."""
    return json.dumps([f for f in FONTES_DO_NOME if f in fontes])


def _valor_das_fontes(valor: str) -> str:
    fontes = _FONTES.validate_json(valor)
    if len(set(fontes)) != len(fontes):
        raise ValueError("fonte repetida")
    return _json_das_fontes(fontes)


def _json_do_papel_visual(ocorrencia: dict[str, Any]) -> str:
    return _json_canonico(
        {"papel": ocorrencia.get("papel"), "visual": ocorrencia.get("visual")}
    )


def _json_canonico(valor: dict[str, Any]) -> str:
    return json.dumps(valor, sort_keys=True, ensure_ascii=False)


def _json_da_aparicao(aparicao: NovaAparicao) -> str:
    return json.dumps(
        aparicao.model_dump(exclude_none=True), sort_keys=True, ensure_ascii=False
    )


def _json_do_comercial(comercial: dict[str, Any]) -> str:
    """A forma única em que o comercial acrescentado é guardado.

    Um acrescentado antes do esquema 1.2 traz `evidencia` (texto) no lugar de
    `evidencias`, e continua desfazível.
    """
    return json.dumps(
        {
            k: comercial[k]
            for k in (*CAMPOS_DO_COMERCIAL, "evidencia")
            if k in comercial
        },
        sort_keys=True,
        ensure_ascii=False,
    )


class NovaCorrecao(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/correcoes`."""

    tipo: TipoNovo
    # Só o `item.tempos` precisa: vale para pauta (o padrão) e para comercial.
    tipo_do_item: Literal["pauta", "comercial", "pessoa", "texto_na_tela"] | None = None
    # Nas correções de aparição e menção (e no `item.tempos` de pessoa).
    ocorrencia: Ocorrencia | None = None
    # Vazio só no `comercial.acrescentar` e na aparição de pessoa nova.
    item_id: Annotated[str, StringConstraints(max_length=40)] = ""
    # `item.tempos`: "<inicio_ms>-<fim_ms>"; `comercial.tipo`: um tipo do
    # esquema; `comercial.acrescentar`: o JSON do comercial; `pessoa.nao_e`:
    # "Não identificado"; `pessoa.aparicao_para_mencao`: a lista de destino;
    # `pessoa.mencao_para_aparicao`: a evidência; `pessoa.acrescentar_aparicao`:
    # o JSON da aparição; `plano.descricao`: o JSON {ambiente, acao, objetos};
    # `plano.limpo`: "true" ou "false"; `fala.texto`: o JSON {texto, locutor};
    # `pauta.tom`: o tom; `pessoa.fontes_do_nome`: a lista JSON das fontes;
    # `aparicao.papel_visual`: o JSON {papel, visual}; `texto_na_tela.texto`: o
    # JSON {tipo, texto}; `texto_na_tela.acrescentar`: o JSON {inicio_ms,
    # fim_ms, tipo, texto}.
    valor: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_JSON
        ),
    ]
    motivo: Motivo
    versao: Annotated[str, StringConstraints(min_length=1, max_length=64)]

    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)

    @model_validator(mode="after")
    def _valor_do_tipo(self) -> Self:
        entrada = TIPOS[self.tipo]
        if not self.item_id and entrada.acrescenta is None:
            raise ValueError("item_id obrigatório")
        if self.tipo_do_item is not None and entrada.tipo_do_item is not None:
            raise ValueError("tipo_do_item só vale no item.tempos")
        de_pessoa = entrada.de_ocorrencia or self.tipo_do_item == "pessoa"
        if de_pessoa != (self.ocorrencia is not None):
            raise ValueError("ocorrencia vale só para aparição e menção de pessoa")
        if not entrada.json_longo and len(self.valor) > LIMITE_DO_TEXTO:
            raise ValueError("valor longo demais")
        self.valor = entrada.canonizar(self)
        return self


class Candidato(BaseModel):
    """Item (pessoa ou pauta) da versão atual que sobrepõe o intervalo ancorado."""

    item_id: str
    nome: str
    inicio_ms: int
    fim_ms: int


class ItemDaFila(Correcao):
    candidatos: list[Candidato]
    antes_legivel: str
    depois_legivel: str


class NovaResolucao(BaseModel):
    """Corpo de `POST /v1/jobs/{id}/fila/{cid}/descartar`."""

    motivo: Motivo

    _motivo_sem_controle = field_validator("motivo")(_sem_controle_salvo_quebra)


class NovaRecusa(NovaResolucao):
    """Corpo de `POST /v1/jobs/{id}/correcoes/{cid}/recusar`."""


class NovaReaplicacao(NovaResolucao):
    """Corpo de `POST /v1/jobs/{id}/fila/{cid}/reaplicar`."""

    item_id: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class RepositorioDeAprovacao(Protocol):
    """Porta para o documento do Firestore com os tipos que exigem aprovação."""

    def tipos(self) -> frozenset[str]:
        """Vazio por padrão: nada exige aprovação."""
        ...

    def definir(self, tipos: frozenset[str]) -> None: ...


class RepositorioDeAprovacaoEmMemoria:
    def __init__(self, tipos: frozenset[str] = frozenset()) -> None:
        self._tipos = tipos

    def tipos(self) -> frozenset[str]:
        return self._tipos

    def definir(self, tipos: frozenset[str]) -> None:
        self._tipos = tipos


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
    identidade = identidade_do_nome(nome)
    if identidade is None:
        inicio, fim = _intervalo_da_pessoa(pessoa, ("na_imagem",))
        return f"{normalizar(nome)}@{inicio}-{fim}"
    return identidade


def _pessoas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("pessoas", []) if isinstance(p, dict)]


def _pautas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("pautas", []) if isinstance(p, dict)]


# Comerciais, falas e textos na tela não têm id no esquema: o id é a posição.
_PREFIXO_POSICIONAL = {
    "comerciais": "com",
    "transcricao": "fal",
    "textos_na_tela": "txt",
}


def _id_posicional(chave: str, n: int) -> str:
    return f"{_PREFIXO_POSICIONAL[chave]}{n:03d}"


def _com_ids_posicionais(modelo: dict[str, Any], chave: str) -> list[dict[str, Any]]:
    """Os itens de `chave` (cópias) com o id da posição no JSON do modelo.

    O que já traz id (decupagem entregue) o mantém.
    """
    return [
        {"id": _id_posicional(chave, n), **item}
        for n, item in enumerate(modelo.get(chave, []))
        if isinstance(item, dict)
    ]


def _comerciais(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return _com_ids_posicionais(modelo, "comerciais")


def _textos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return _com_ids_posicionais(modelo, "textos_na_tela")


def _tipo_do_item(tipo: str, escolhido: str | None = None) -> TipoDoItem:
    """O tipo do item que a correção do `tipo` corrige; no `item.tempos`, o que o
    pedido escolhe (pauta, se nada)."""
    return cast(TipoDoItem, TIPOS[tipo].tipo_do_item or escolhido or "pauta")


def _planos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("planos", []) if isinstance(p, dict)]


def _falas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return _com_ids_posicionais(modelo, "transcricao")


def _itens(modelo: dict[str, Any], tipo_do_item: str) -> list[dict[str, Any]]:
    if tipo_do_item == "pessoa":
        return _pessoas(modelo)
    if tipo_do_item == "comercial":
        return _comerciais(modelo)
    if tipo_do_item == "plano":
        return _planos(modelo)
    if tipo_do_item == "fala":
        return _falas(modelo)
    if tipo_do_item == "texto_na_tela":
        return _textos(modelo)
    return _pautas(modelo)


def _intervalo_da_pauta(pauta: dict[str, Any]) -> tuple[int, int]:
    """Pauta, comercial, plano e fala: o item tem o próprio intervalo."""
    return int(pauta["inicio_ms"]), int(pauta["fim_ms"])


def identidade_do_comercial(comercial: dict[str, Any]) -> str:
    """Marca normalizada e tipo, como a emenda da consolidação (#45)."""
    return _identidade_do_comercial(str(comercial["marca"]), str(comercial["tipo"]))


def _intervalo_do_item(item: dict[str, Any], tipo_do_item: str) -> tuple[int, int]:
    if tipo_do_item == "pessoa":
        return _intervalo_da_pessoa(item)
    return _intervalo_da_pauta(item)


def _rotulo_do_item(item: dict[str, Any], tipo_do_item: str) -> str:
    if tipo_do_item == "comercial":
        return f"{item['marca']} ({item['tipo']})"
    if tipo_do_item == "plano":
        return str(item["ambiente"])
    if tipo_do_item == "fala":
        return f"{item['locutor']}: {str(item['texto'])[:60]}"
    if tipo_do_item == "texto_na_tela":
        return f"{item['tipo']}: {str(item['texto'])[:60]}"
    return str(item["nome" if tipo_do_item == "pessoa" else "titulo"])


def _valor_do_item(item: dict[str, Any], tipo: str) -> str:
    """O valor que a correção do `tipo` troca neste item."""
    leitor = TIPOS[tipo].valor_do_item
    assert leitor is not None
    return leitor(item)


def _acha_ocorrencia(
    pessoa: dict[str, Any],
    inicio_ms: int,
    fim_ms: int,
    listas: tuple[str, ...] = LISTAS,
) -> tuple[str, dict[str, Any]] | None:
    """A ocorrência da pessoa que sobrepõe o intervalo, na lista (ou listas).

    Com várias, vence a de intervalo idêntico, depois a de maior sobreposição.
    """
    melhor = None
    for n, lista in enumerate(listas):
        for ocorrencia in pessoa.get(lista, []):
            sobreposicao = min(fim_ms, ocorrencia["fim_ms"]) - max(
                inicio_ms, ocorrencia["inicio_ms"]
            )
            instante = inicio_ms == fim_ms or (
                ocorrencia["inicio_ms"] == ocorrencia["fim_ms"]
            )
            # Só encostar na borda não é a mesma ocorrência; um instante conta
            # se cai dentro (ou na borda) do outro intervalo.
            if sobreposicao < 0 or (sobreposicao == 0 and not instante):
                continue
            exata = (ocorrencia["inicio_ms"], ocorrencia["fim_ms"]) == (
                inicio_ms,
                fim_ms,
            )
            chave = (exata, sobreposicao, -n)
            if melhor is None or chave > melhor[0]:
                melhor = (chave, lista, ocorrencia)
    return None if melhor is None else (melhor[1], melhor[2])


def _valor_da_ocorrencia(
    pessoa: dict[str, Any], tipo: str, ocorrencia: Ocorrencia | None, depois: str
) -> str:
    """Onde está hoje a ocorrência: "<lista> <inicio>-<fim>", ou só os tempos no
    `item.tempos`; vazio se a pessoa não a tem."""
    leitor = TIPOS[tipo].valor_da_ocorrencia
    assert leitor is not None
    return leitor(pessoa, ocorrencia, depois)


class TemposInvalidos(Exception):
    """Os tempos passam da duração do vídeo."""


def _confere_duracao(modelo: dict[str, Any], tipo: str, valor: str) -> None:
    """`TemposInvalidos` se os tempos de um `item.tempos` ou de um item
    acrescentado passam da duração."""
    fim_de = TIPOS[tipo].fim_ms
    if fim_de is None:
        return
    if fim_de(valor) > int(modelo.get("video", {}).get("duracao_ms", 0)):
        raise TemposInvalidos(valor)


@dataclass(frozen=True)
class Autoria:
    """Quem fez o registro e quando: a rota entrega, o módulo monta o registro."""

    uid: str
    email: str
    em: datetime


def _registro(job_id: str, autoria: Autoria, id: str, **campos: Any) -> Correcao:
    return Correcao(
        id=id,
        job_id=job_id,
        autor_uid=autoria.uid,
        autor_email=autoria.email,
        criada_em=autoria.em,
        **campos,
    )


class VersaoDesatualizada(Exception):
    """O pedido é sobre uma versão do JSON do modelo que não é mais a atual."""


class CorrecaoInexistente(Exception):
    """Nenhuma correção do Job tem o id pedido."""


def _alvo(correcoes: list[Correcao], id: str) -> Correcao:
    alvo = next((c for c in correcoes if c.id == id), None)
    if alvo is None:
        raise CorrecaoInexistente(id)
    return alvo


def corrigir(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    novo: NovaCorrecao,
    job_id: str,
    autoria: Autoria,
    *,
    exige_aprovacao: bool = False,
    catalogo: Catalogo | None = None,
) -> Correcao:
    """O registro da correção de `novo` sobre o item do JSON do modelo, com a
    âncora pronta. A ocorrência de uma pessoa tem de existir na decupagem
    entregue, que já traz as `correcoes` gravadas (aplicada aqui uma só vez).
    """
    if novo.versao != versao:
        raise VersaoDesatualizada(novo.versao)
    entregue = aplicar(modelo, versao, correcoes)
    tipo_do_item = _tipo_do_item(novo.tipo, novo.tipo_do_item)
    antes = _valor_atual(
        entregue,
        novo.tipo,
        novo.item_id,
        novo.tipo_do_item,
        novo.ocorrencia,
        novo.valor,
    )
    _confere_duracao(modelo, novo.tipo, novo.valor)
    id = uuid.uuid4().hex
    campos: dict[str, Any] = {
        "tipo": novo.tipo,
        "motivo": novo.motivo,
        "depois": novo.valor,
        "exige_aprovacao": exige_aprovacao,
    }
    acrescenta = TIPOS[novo.tipo].acrescenta
    if acrescenta is not None:
        ancora = acrescenta.ancora(novo.valor, novo.item_id, versao)
        if ancora is not None:
            return _registro(
                job_id,
                autoria,
                id,
                item_id=f"{PREFIXO_ACRESCENTADO}{id}",
                antes="",
                ancora=ancora,
                **campos,
            )
    item = next(
        (i for i in _itens(modelo, tipo_do_item) if i.get("id") == novo.item_id), None
    )
    if item is None:
        raise ItemInexistente(novo.item_id)
    if novo.ocorrencia is not None:
        pessoa = next(
            (p for p in _pessoas(entregue) if p.get("id") == novo.item_id), None
        )
        o = novo.ocorrencia
        if pessoa is None or not _acha_ocorrencia(
            pessoa, o.inicio_ms, o.fim_ms, (o.lista,)
        ):
            raise ItemInexistente(f"{novo.item_id} {o.lista}")
    return _registro(
        job_id,
        autoria,
        id,
        item_id=novo.item_id,
        antes=antes,
        ocorrencia=novo.ocorrencia,
        catalogo_id=_id_no_catalogo(novo, catalogo),
        ancora=_ancora_do_item(item, tipo_do_item, versao),
        **campos,
    )


def _id_no_catalogo(novo: NovaCorrecao, catalogo: Catalogo | None) -> str | None:
    """O id da pessoa do catálogo que tem o nome novo; vazio sem catálogo, sem
    ninguém com esse nome ou com mais de uma (a revisora não escolhe aqui)."""
    if catalogo is None or not TIPOS[novo.tipo].acha_no_catalogo:
        return None
    achadas = catalogo.achar(novo.valor)
    return achadas[0].id if len(achadas) == 1 else None


def _ancora_do_item(
    item: dict[str, Any], tipo_do_item: TipoDoItem, versao: str
) -> Ancora:
    if tipo_do_item == "pessoa":
        return _ancora_da_pessoa(item, versao)
    inicio, fim = _intervalo_da_pauta(item)
    # Plano e fala se casam pelo intervalo: a identidade é só o tipo.
    if tipo_do_item == "comercial":
        identidade = identidade_do_comercial(item)
    elif tipo_do_item in ("plano", "fala"):
        identidade = tipo_do_item
    elif tipo_do_item == "texto_na_tela":
        identidade = normalizar(str(item["texto"]))
    else:
        identidade = normalizar(str(item["titulo"]))
    return Ancora(
        versao=versao,
        tipo_do_item=tipo_do_item,
        identidade=identidade,
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


@dataclass(frozen=True)
class EstadoDasCorrecoes:
    """O estado de cada Correção de um Job, derivado uma vez dos registros.

    Histórico, fila, `aplicar`, `reconciliar` e desfazer leem daqui.
    """

    desfeitas: frozenset[str]
    reaplicadas: frozenset[str]
    descartadas: frozenset[str]
    aprovadas: frozenset[str]
    recusadas: frozenset[str]
    exigem_aprovacao: frozenset[str]

    @property
    def decididas(self) -> frozenset[str]:
        return self.aprovadas | self.recusadas

    def saiu_da_fila(self, id: str) -> bool:
        return id in self.reaplicadas or id in self.descartadas

    def espera_decisao(self, id: str) -> bool:
        return id in self.exigem_aprovacao and id not in self.decididas

    def fora_da_entrega(self, id: str) -> bool:
        """Exige aprovação e ainda não a tem: pendente ou recusada."""
        return id in self.exigem_aprovacao and id not in self.aprovadas

    def em_vigor(self, id: str) -> bool:
        """Entra na decupagem entregue: nem desfeita, nem fora da entrega."""
        return id not in self.desfeitas and not self.fora_da_entrega(id)

    def casavel(self, id: str) -> bool:
        """Em vigor e ainda na fila de revisão ou casada: `reconciliar` a considera."""
        return self.em_vigor(id) and not self.saiu_da_fila(id)

    def de(self, id: str) -> "EstadoNoHistorico":
        if id in self.desfeitas:
            return "desfeita"
        if id in self.recusadas:
            return "recusada"
        # A aprovada que depois saiu da fila mostra o que lhe aconteceu por último.
        if id in self.reaplicadas:
            return "reaplicada"
        if id in self.descartadas:
            return "descartada"
        if id in self.exigem_aprovacao:
            return "aprovada" if id in self.aprovadas else "pendente"
        return "ativa"


def estado_das(correcoes: list[Correcao]) -> EstadoDasCorrecoes:
    return EstadoDasCorrecoes(
        desfeitas=frozenset(
            c.desfaz for c in correcoes if c.tipo == "desfazer" and c.desfaz
        ),
        reaplicadas=frozenset(c.reaplica for c in correcoes if c.reaplica),
        descartadas=frozenset(c.descarta for c in correcoes if c.descarta),
        aprovadas=frozenset(c.aprova for c in correcoes if c.aprova),
        recusadas=frozenset(c.recusa for c in correcoes if c.recusa),
        exigem_aprovacao=frozenset(c.id for c in correcoes if c.exige_aprovacao),
    )


def _em_ordem_de_vigencia(
    alvos: list[Correcao], correcoes: list[Correcao]
) -> list[Correcao]:
    """Como `em_ordem`, mas a aprovada entra na data da aprovação: uma correção
    feita enquanto ela esperava o Curador não a encobre depois de aprovada."""
    aprovada_em = {c.aprova: c.criada_em for c in correcoes if c.aprova}
    return sorted(alvos, key=lambda c: (aprovada_em.get(c.id, c.criada_em), c.id))


def id_do_desfazer(alvo_id: str) -> str:
    """Fixo por alvo: dois desfazer simultâneos colidem no repositório."""
    return f"{alvo_id}-desfeita"


def _valor_do_alvo(
    modelo: dict[str, Any], entregue: dict[str, Any], alvo: Correcao
) -> str:
    """O valor entregue hoje no item do alvo (casa como `aplicar`): a pessoa
    pela identidade da âncora; a pauta pelo id, que na mesma versão é estável."""
    do_alvo = TIPOS[alvo.tipo].valor_do_alvo
    if do_alvo is not None:
        return do_alvo(modelo, entregue, alvo)
    return _valor_atual(
        entregue,
        alvo.tipo,
        alvo.item_id,
        alvo.ancora.tipo_do_item,
        alvo.ocorrencia,
        alvo.depois,
    )


def desfazer(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    alvo_id: str,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """O registro que reverte o alvo; nada é apagado. Um desfazer não se desfaz.

    Antes e depois são o nome entregue sem e com o desfazer: com uma correção
    mais nova no mesmo campo, desfazer a antiga não muda o que se vê. A de outra
    versão só se desfaz se `reconciliar` a casar; o registro aponta o item novo.
    A decupagem é aplicada com o alvo e sem ele: duas, e só.
    """
    alvo = _alvo(correcoes, alvo_id)
    if alvo.tipo not in CORRIGIVEIS or not estado_das(correcoes).casavel(alvo.id):
        raise NaoDesfazivel(alvo.id)
    restantes = [c for c in correcoes if c.id != alvo.id]
    com = aplicar(modelo, versao, correcoes)
    sem = aplicar(modelo, versao, restantes)
    if alvo.ancora.versao == versao:
        alvo_atual = alvo
        antes = _valor_do_alvo(modelo, com, alvo)
        depois = _valor_do_alvo(modelo, sem, alvo)
    else:
        casadas = reconciliar(modelo, versao, correcoes).casadas
        reapontada = next((c for c in casadas if c.id == alvo.id), None)
        if reapontada is None:
            raise NaoDesfazivel(alvo.id)
        alvo_atual = reapontada
        # A reapontada vale pelo id do item novo, como em `aplicar`.
        antes, depois = (
            _valor_atual(
                entregue,
                alvo_atual.tipo,
                alvo_atual.item_id,
                alvo_atual.ancora.tipo_do_item,
                alvo_atual.ocorrencia,
                alvo_atual.depois,
            )
            for entregue in (com, sem)
        )
    return _registro(
        job_id,
        autoria,
        id_do_desfazer(alvo.id),
        tipo="desfazer",
        desfaz=alvo.id,
        item_id=alvo_atual.item_id,
        ocorrencia=alvo_atual.ocorrencia,
        motivo=motivo,
        antes=antes,
        depois=depois,
        ancora=alvo_atual.ancora,
    )


def historico(correcoes: list[Correcao]) -> list[ItemDoHistorico]:
    """Da mais recente para a mais antiga, cada uma ativa, desfeita, fora da
    fila (reaplicada ou descartada) ou, se exige aprovação, pendente, aprovada
    ou recusada."""
    estado = estado_das(correcoes)
    tipos = {c.id: c.tipo for c in correcoes}

    def legivel(c: Correcao, valor: str) -> str:
        # Desfazer, aprovação e recusa mostram o valor do tipo que decidem.
        alvo = c.desfaz or c.aprova or c.recusa
        return valor_legivel(tipos.get(alvo) if alvo else c.tipo, valor)

    return [
        ItemDoHistorico(
            **c.model_dump(),
            estado=estado.de(c.id),
            antes_legivel=legivel(c, c.antes),
            depois_legivel=legivel(c, c.depois),
        )
        for c in reversed(em_ordem(correcoes))
    ]


def _valor_atual(
    entregue: dict[str, Any],
    tipo: str,
    item_id: str,
    tipo_do_item: str | None = None,
    ocorrencia: Ocorrencia | None = None,
    depois: str = "",
) -> str:
    """O valor que o Editor vê hoje, na decupagem `entregue`, no campo do `tipo`
    do item `item_id`.

    Vazio para o item acrescentado que não está na decupagem (ainda não existe,
    foi desfeito ou o modelo já o traz) e para a ocorrência de pessoa que a
    decupagem não tem (ou cuja pessoa saiu dela). `depois` é o valor da
    correção, de onde sai o intervalo da aparição acrescentada.
    """
    entrada = TIPOS[tipo]
    tipo_do_item = _tipo_do_item(tipo, tipo_do_item)
    if entrada.traz_o_campo is not None and not entrada.traz_o_campo(entregue):
        raise ItemInexistente(tipo)
    de_ocorrencia = tipo_do_item == "pessoa" and entrada.valor_da_ocorrencia is not None
    for item in _itens(entregue, tipo_do_item):
        if item.get("id") != item_id:
            continue
        if de_ocorrencia:
            return _valor_da_ocorrencia(item, tipo, ocorrencia, depois)
        return _valor_do_item(item, tipo)
    if entrada.acrescenta is not None or de_ocorrencia:
        return ""
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


def _sobrepoe_de_verdade(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Sobreposição positiva: trechos que só se encostam não são o mesmo.

    Um instante (duração zero) conta se cai dentro do outro intervalo.
    """
    sobreposicao = min(a[1], b[1]) - max(a[0], b[0])
    instante = a[0] == a[1] or b[0] == b[1]
    return sobreposicao > 0 or (sobreposicao == 0 and instante)


def _candidatos(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    """Itens da versão nova que a correção pode estar apontando.

    Pauta: a que sobrepõe o intervalo ancorado em pelo menos metade do menor
    dos dois. Comercial: o de mesma marca normalizada e tipo, com intervalo
    sobreposto (ou já com o "depois"). Pessoa: a com a identidade da âncora
    (ou já com o "depois"). Plano: o de início e fim a até 1 s dos ancorados.
    Fala: a que sobrepõe o intervalo ancorado (encostar na borda não conta).
    """
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    if c.ancora.tipo_do_item == "pauta":
        return [
            p
            for p in _pautas(modelo)
            if _sobrepoe_metade(ancora, _intervalo_da_pauta(p))
        ]
    if c.ancora.tipo_do_item == "plano":
        return [
            p
            for p in _planos(modelo)
            if abs(p["inicio_ms"] - ancora[0]) <= TOLERANCIA_DO_PLANO_MS
            and abs(p["fim_ms"] - ancora[1]) <= TOLERANCIA_DO_PLANO_MS
        ]
    if c.ancora.tipo_do_item == "fala":
        return [
            f
            for f in _falas(modelo)
            if _sobrepoe_de_verdade(ancora, _intervalo_da_pauta(f))
        ]
    if c.ancora.tipo_do_item == "texto_na_tela":
        identidades = TIPOS[c.tipo].identidades(c)
        return [
            t
            for t in _textos(modelo)
            if normalizar(str(t["texto"])) in identidades
            and _sobrepoe_de_verdade(ancora, _intervalo_da_pauta(t))
        ]
    if c.ancora.tipo_do_item == "comercial":
        identidades = TIPOS[c.tipo].identidades(c)
        return [
            m
            for m in _comerciais(modelo)
            if identidade_do_comercial(m) in identidades
            and _sobrepoe(ancora, _intervalo_da_pauta(m))
        ]
    return _candidatos_pessoa(modelo, c)


def _ja_traz_o_valor(c: Correcao, item: dict[str, Any]) -> bool:
    return _valor_do_item(item, c.tipo) == c.depois


def _candidatos_pessoa(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    entrada = TIPOS[c.tipo]
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    sem_nome = nao_identificado(c.ancora.identidade.split("@")[0])
    achados = []
    for pessoa in _pessoas(modelo):
        nome = str(pessoa["nome"])
        if sem_nome and nao_identificado(nome):
            # Só as aparições mostram quem é.
            intervalo = _intervalo_da_pessoa(pessoa, ("na_imagem",))
        elif (
            entrada.casa_pelo_nome_novo and normalizar(nome) == normalizar(c.depois)
        ) or (not sem_nome and normalizar(nome) == c.ancora.identidade):
            intervalo = _intervalo_da_pessoa(pessoa)
        else:
            continue
        # A aparição acrescentada pode estar longe do que a pessoa já tem.
        longe_ok = entrada.casa_longe and not sem_nome
        if longe_ok or (_sobrepoe(ancora, intervalo) and _tem_a_ocorrencia(c, pessoa)):
            achados.append(pessoa)
    return achados


def _tem_a_ocorrencia(c: Correcao, pessoa: dict[str, Any]) -> bool:
    """A pessoa ainda tem a aparição ou menção que a correção aponta."""
    o = c.ocorrencia
    if o is None:
        return True
    return _acha_ocorrencia(pessoa, o.inicio_ms, o.fim_ms, (o.lista,)) is not None


def reconciliar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> Reconciliacao:
    """Casa as correções de versões antigas com a decupagem atual do modelo.

    Casa só com exatamente um item de mesma identidade e intervalo sobreposto;
    zero ou vários candidatos não casam. Ignora as da versão atual, as
    desfeitas, as que saíram da fila, as que esperam aprovação ou foram
    recusadas e os registros que não corrigem um item.
    """
    estado = estado_das(correcoes)
    resultado = Reconciliacao(casadas=[], atendidas=[], sem_casar=[])
    for c in em_ordem(correcoes):
        if (
            c.ancora.versao == versao
            or c.tipo not in CORRIGIVEIS
            or not estado.casavel(c.id)
        ):
            continue
        candidatos = _candidatos(modelo, c)
        acrescenta = TIPOS[c.tipo].acrescenta
        if acrescenta is not None and acrescenta.acrescenta(c):
            # Não corrige item nenhum: não vai para a fila. Se o modelo já traz
            # o comercial (a aparição, o texto), a correção é atendida e não duplica.
            candidatos = acrescenta.atendentes(c, candidatos)
            nova = c.model_copy(
                update={"ancora": c.ancora.model_copy(update={"versao": versao})}
            )
            resultado.casadas.append(nova)
            if candidatos:
                resultado.atendidas.append(nova)
            continue
        if len(candidatos) != 1:
            resultado.sem_casar.append(c)
            continue
        item = candidatos[0]
        nova = c.model_copy(
            update={
                "item_id": str(item.get("id", "")),
                "ancora": _ancora_do_item(item, c.ancora.tipo_do_item, versao),
            }
        )
        resultado.casadas.append(nova)
        if TIPOS[c.tipo].ja_traz(c, item):
            resultado.atendidas.append(nova)
    return resultado


_CHAVE_DO_ITEM = {
    "pauta": "pautas",
    "comercial": "comerciais",
    "plano": "planos",
    "fala": "transcricao",
    "texto_na_tela": "textos_na_tela",
}


def _aplicar_no_item(resultado: dict[str, Any], c: Correcao) -> None:
    """Pauta, comercial, plano ou fala é achado pelo id: na versão atual o id
    do item é estável, e a reapontada já traz o id novo."""
    aplica = TIPOS[c.tipo].aplicar_no_item
    assert aplica is not None
    chave = _CHAVE_DO_ITEM[c.ancora.tipo_do_item]
    for item in resultado.get(chave, []):
        if not isinstance(item, dict) or item.get("id") != c.item_id:
            continue
        aplica(item, c)
        item["origem"] = "revisao"


def _por_inicio(ocorrencias: list[dict[str, Any]]) -> None:
    ocorrencias.sort(key=lambda o: (o["inicio_ms"], o["fim_ms"]))


def _ocorrencia_da_correcao(
    pessoa: dict[str, Any], c: Correcao
) -> tuple[Ocorrencia, dict[str, Any]] | None:
    """A ocorrência que a correção aponta, achada na lista da pessoa pela
    sobreposição; se sumiu, `None` (nada muda). Achada, a pessoa vira revisão."""
    o = c.ocorrencia
    assert o is not None
    achada = _acha_ocorrencia(pessoa, o.inicio_ms, o.fim_ms, (o.lista,))
    if achada is None:
        return None
    pessoa["origem"] = "revisao"
    return o, achada[1]


def _tempos_da_ocorrencia(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    achada = _ocorrencia_da_correcao(pessoa, c)
    if achada is None:
        return
    o, ocorrencia = achada
    ocorrencia["inicio_ms"], ocorrencia["fim_ms"] = tempos_de(c.depois)
    _por_inicio(pessoa[o.lista])


def _papel_visual_da_ocorrencia(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    achada = _ocorrencia_da_correcao(pessoa, c)
    if achada is not None:
        achada[1].update(json.loads(c.depois))


def _nao_e(resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao) -> None:
    achada = _ocorrencia_da_correcao(pessoa, c)
    if achada is None:
        return
    o, ocorrencia = achada
    pessoa[o.lista].remove(ocorrencia)
    resultado.setdefault("pessoas", []).append(
        {
            "id": f"{PREFIXO_NAO_IDENTIFICADO}{c.id}",
            "nome": NOME_NAO_IDENTIFICADO,
            "origem": "revisao",
            **{lista: [] for lista in LISTAS},
            o.lista: [ocorrencia],
        }
    )


def _aparicao_para_mencao(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    achada = _ocorrencia_da_correcao(pessoa, c)
    if achada is None:
        return
    o, ocorrencia = achada
    pessoa[o.lista].remove(ocorrencia)
    mencao = {"inicio_ms": ocorrencia["inicio_ms"], "fim_ms": ocorrencia["fim_ms"]}
    if c.depois == "citada_no_texto":
        mencao["texto"] = ocorrencia["evidencia"]
    pessoa[c.depois].append(mencao)
    _por_inicio(pessoa[c.depois])


def _mencao_para_aparicao(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    achada = _ocorrencia_da_correcao(pessoa, c)
    if achada is None:
        return
    o, ocorrencia = achada
    pessoa[o.lista].remove(ocorrencia)
    pessoa["na_imagem"].append(
        {
            "inicio_ms": ocorrencia["inicio_ms"],
            "fim_ms": ocorrencia["fim_ms"],
            "evidencia": c.depois,
        }
    )
    _por_inicio(pessoa["na_imagem"])


def _aparicao_na_pessoa(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    _acrescentar_aparicao(pessoa, json.loads(c.depois))


def _acrescentar_aparicao(pessoa: dict[str, Any], aparicao: dict[str, Any]) -> None:
    pessoa["origem"] = "revisao"
    pessoa["na_imagem"].append(
        {
            "inicio_ms": aparicao["inicio_ms"],
            "fim_ms": aparicao["fim_ms"],
            "evidencia": aparicao["evidencia"],
        }
    )
    _por_inicio(pessoa["na_imagem"])


def _acrescentar_pessoa(resultado: dict[str, Any], c: Correcao) -> None:
    """Aparição de pessoa nova; se já há uma pessoa com o nome, entra nela."""
    aparicao = json.loads(c.depois)
    existente = next(
        (
            p
            for p in _pessoas(resultado)
            if normalizar(str(p["nome"])) == c.ancora.identidade
        ),
        None,
    )
    if existente is not None:
        _acrescentar_aparicao(existente, aparicao)
        return
    nova = {
        "id": c.item_id,
        "nome": aparicao["nome"],
        "origem": "revisao",
        **{lista: [] for lista in LISTAS},
    }
    resultado.setdefault("pessoas", []).append(nova)
    _acrescentar_aparicao(nova, aparicao)


def aplicar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """Cópia do modelo com as correções da versão atual por cima.

    Item corrigido (pessoa, pauta, comercial, plano ou fala) vem com
    `origem: "revisao"`; os demais, com
    `"modelo"`.
    A atendida (o modelo já traz o "depois") deixa o nome como o modelo o
    escreveu, com `origem: "modelo"`.
    Correção desfeita não conta: o item volta ao valor que teria sem ela.
    A que exige aprovação só conta depois de aprovada.
    Correção de outra versão do JSON só vale se `reconciliar` a casar com um
    item único; as que não casam não se aplicam (e seguem no histórico).
    """
    resultado: dict[str, Any] = json.loads(json.dumps(modelo))
    pessoas = _pessoas(resultado)
    # Os ids posicionais saem da posição no modelo, antes de qualquer correção.
    posicionais = []
    for chave in _PREFIXO_POSICIONAL:
        for n, real in enumerate(resultado.get(chave, [])):
            if isinstance(real, dict):
                real["id"] = _id_posicional(chave, n)
                posicionais.append(real)
    for item in [*pessoas, *_pautas(resultado), *_planos(resultado), *posicionais]:
        # O nome confirmado pelo código (`modelo_forte`) segue como o modelo gravou.
        if item.get("origem") != "modelo_forte":
            item["origem"] = "modelo"
    # Casa pela identidade do modelo, calculada antes de qualquer renomeação.
    identidades = [identidade_da_pessoa(p) for p in pessoas]
    pessoas_do_modelo = [dict(p) for p in pessoas]
    estado = estado_das(correcoes)
    # ponytail: reconciliar a cada leitura relê as pessoas do modelo por
    # correção antiga (custo pequeno hoje); guardar o resultado quando houver
    # reprocessamentos frequentes ou muitas correções por vídeo.
    reconciliadas = reconciliar(modelo, versao, correcoes)
    esvaziadas: list[dict[str, Any]] = []
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
    # A aprovada vale a partir da aprovação, não de quando o Editor a fez.
    for c in _em_ordem_de_vigencia(da_versao + reconciliadas.casadas, correcoes):
        if not estado.em_vigor(c.id):
            continue
        entrada = TIPOS[c.tipo]
        if entrada.acrescenta is not None and entrada.acrescenta.acrescenta(c):
            if c.id not in atendidas:
                entrada.acrescenta.aplicar(resultado, c)
            continue
        if c.ancora.tipo_do_item != "pessoa":
            if c.id not in atendidas:
                _aplicar_no_item(resultado, c)
            continue
        for pessoa, identidade, do_modelo in zip(
            pessoas, identidades, pessoas_do_modelo, strict=True
        ):
            if not casa(c, pessoa, identidade):
                continue
            if c.id in atendidas:
                if entrada.atender_na_pessoa is not None:
                    entrada.atender_na_pessoa(pessoa, do_modelo, c)
                continue
            assert entrada.aplicar_na_pessoa is not None
            entrada.aplicar_na_pessoa(resultado, pessoa, c)
            if entrada.pode_esvaziar:
                esvaziadas.append(pessoa)
    # A pessoa que ficou sem nenhuma ocorrência some da decupagem, e das pautas.
    sumidas = [e for e in esvaziadas if not any(e[lista] for lista in LISTAS)]
    if sumidas:
        resultado["pessoas"] = [
            p for p in _pessoas(resultado) if not any(p is e for e in sumidas)
        ]
        ids = {e.get("id") for e in sumidas}
        for pauta in _pautas(resultado):
            if "pessoas" in pauta:
                pauta["pessoas"] = [i for i in pauta["pessoas"] if i not in ids]
    if "textos_na_tela" in resultado:
        resultado["textos_na_tela"].sort(key=lambda t: (t["inicio_ms"], t["fim_ms"]))
    if "comerciais" in resultado:
        resultado["comerciais"].sort(key=lambda m: (m["inicio_ms"], m["fim_ms"]))
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
            # Plano e fala que só encostam no ancorado não são o mesmo trecho.
            sobrepoe = (
                _sobrepoe_de_verdade
                if tipo_do_item in ("plano", "fala", "texto_na_tela")
                else _sobrepoe
            )
            # Reaplicar numa pessoa sem a aparição ou menção não mudaria nada.
            if sobrepoe(ancora, intervalo) and _tem_a_ocorrencia(c, item):
                candidatos.append(
                    Candidato(
                        item_id=str(item.get("id", "")),
                        nome=_rotulo_do_item(item, tipo_do_item),
                        inicio_ms=intervalo[0],
                        fim_ms=intervalo[1],
                    )
                )
        itens.append(
            ItemDaFila(
                **c.model_dump(),
                candidatos=candidatos,
                antes_legivel=valor_legivel(c.tipo, c.antes),
                depois_legivel=valor_legivel(c.tipo, c.depois),
            )
        )
    return itens


def _na_fila(
    modelo: dict[str, Any], versao: str, alvo: Correcao, correcoes: list[Correcao]
) -> ItemDaFila:
    item = next((i for i in fila(modelo, versao, correcoes) if i.id == alvo.id), None)
    if item is None:
        raise NaoNaFila(alvo.id)
    return item


def reaplicar(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    alvo_id: str,
    item_id: str,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """A correção nova, ancorada na versão atual no item escolhido e ligada à
    original (`reaplica`). A original sai da fila e continua no histórico.
    O item tem de ser um dos candidatos que a fila oferece."""
    alvo = _alvo(correcoes, alvo_id)
    item = _na_fila(modelo, versao, alvo, correcoes)
    if item_id not in {c.item_id for c in item.candidatos}:
        raise NaoCandidato(item_id)
    tipo_do_item = alvo.ancora.tipo_do_item
    novo = next(i for i in _itens(modelo, tipo_do_item) if i.get("id") == item_id)
    # O vídeo reprocessado pode ser mais curto que o da correção original.
    _confere_duracao(modelo, alvo.tipo, alvo.depois)
    return _registro(
        job_id,
        autoria,
        id_da_resolucao(alvo.id),
        tipo=alvo.tipo,
        reaplica=alvo.id,
        item_id=item_id,
        motivo=motivo,
        ocorrencia=alvo.ocorrencia,
        antes=_valor_atual(
            aplicar(modelo, versao, correcoes),
            alvo.tipo,
            item_id,
            tipo_do_item,
            alvo.ocorrencia,
            alvo.depois,
        ),
        depois=alvo.depois,
        ancora=_ancora_do_item(novo, tipo_do_item, versao),
    )


def descartar(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    alvo_id: str,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """O registro que tira o alvo da fila; ela não se aplica mais."""
    alvo = _alvo(correcoes, alvo_id)
    _na_fila(modelo, versao, alvo, correcoes)
    return _registro(
        job_id,
        autoria,
        id_da_resolucao(alvo.id),
        tipo="descartar",
        descarta=alvo.id,
        item_id=alvo.item_id,
        ocorrencia=alvo.ocorrencia,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
    )


class NaoPendente(Exception):
    """A correção não espera decisão: não exige aprovação ou já foi decidida."""


def id_da_decisao(alvo_id: str) -> str:
    """Fixo por alvo: aprovar e recusar simultâneos colidem no repositório."""
    return f"{alvo_id}-decidida"


def decidir(
    correcoes: list[Correcao],
    alvo_id: str,
    aprovada: bool,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """O registro em que um Curador aprova ou recusa o alvo, que tem de estar
    pendente. A recusa traz o motivo."""
    alvo = _alvo(correcoes, alvo_id)
    if not alvo.exige_aprovacao or alvo.id in estado_das(correcoes).decididas:
        raise NaoPendente(alvo.id)
    return _registro(
        job_id,
        autoria,
        id_da_decisao(alvo.id),
        tipo="aprovar" if aprovada else "recusar",
        aprova=alvo.id if aprovada else None,
        recusa=None if aprovada else alvo.id,
        item_id=alvo.item_id,
        ocorrencia=alvo.ocorrencia,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
    )


def decupagem_entregue(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """A decupagem que o Editor vê: o modelo com as correções aplicadas, e a
    versão do JSON do modelo em que elas se apoiam."""
    entregue = aplicar(modelo, versao, correcoes)
    entregue["versao_decupagem"] = versao
    return entregue


# --- Uma entrada por tipo de Correção ------------------------------------------
#
# Tudo o que muda de um tipo para outro mora numa entrada de `TIPOS`: validar o
# valor, lê-lo no item, conferir a duração e o esquema, aplicá-lo no modelo e
# reconhecê-lo na versão nova. O resto do módulo só consulta a tabela.


def _nunca(c: Correcao, item: dict[str, Any]) -> bool:
    return False


def _so_a_ancora(c: Correcao) -> set[str]:
    return {c.ancora.identidade}


@dataclass(frozen=True)
class Acrescenta:
    """O que só os tipos que criam um item (ou uma pessoa) sabem fazer."""

    # A âncora do item novo; `None` se o pedido, pelo `item_id`, corrige um existente.
    ancora: Callable[[str, str, str], Ancora | None]
    # Se este registro cria o item (a aparição num item existente não cria).
    acrescenta: Callable[[Correcao], bool]
    # Dos itens da versão nova, os que já trazem o acrescentado.
    atendentes: Callable[[Correcao, list[dict[str, Any]]], list[dict[str, Any]]]
    aplicar: Callable[[dict[str, Any], Correcao], None]


@dataclass(frozen=True)
class Tipo:
    """A entrada de um tipo de Correção."""

    # Valida o pedido e devolve o valor na forma única em que é guardado.
    canonizar: Callable[[NovaCorrecao], str]
    # O nome do tipo para quem lê.
    rotulo: str
    # O valor (`antes` ou `depois`) para quem lê; recebe o texto gravado.
    legivel: Callable[[str], str]
    # O tipo do item corrigido; `None` no que o pedido escolhe (`item.tempos`).
    tipo_do_item: TipoDoItem | None = None
    # O valor, que pode ser JSON, passa do limite do texto simples.
    json_longo: bool = False
    # Corrige uma aparição ou menção que o pedido identifica.
    de_ocorrencia: bool = False
    # O valor atual do campo, no item (ou, em `valor_da_ocorrencia`, na pessoa).
    valor_do_item: Callable[[dict[str, Any]], str] | None = None
    valor_da_ocorrencia: (
        Callable[[dict[str, Any], Ocorrencia | None, str], str] | None
    ) = None
    # O valor entregue do alvo, quando o item não é achado pelo id.
    valor_do_alvo: Callable[[dict[str, Any], dict[str, Any], Correcao], str] | None = (
        None
    )
    # O fim do vídeo que o valor pede; `None` se não traz tempos.
    fim_ms: Callable[[str], int] | None = None
    # Se a decupagem entregue traz o campo que o tipo corrige (esquema 1.2).
    traz_o_campo: Callable[[dict[str, Any]], bool] | None = None
    aplicar_no_item: Callable[[dict[str, Any], Correcao], None] | None = None
    aplicar_na_pessoa: (
        Callable[[dict[str, Any], dict[str, Any], Correcao], None] | None
    ) = None
    # Na pessoa cujo modelo (o terceiro argumento, antes das correções) já traz
    # o "depois": o que fazer, se algo.
    atender_na_pessoa: (
        Callable[[dict[str, Any], dict[str, Any], Correcao], None] | None
    ) = None
    # A pessoa pode ficar sem nenhuma ocorrência e sumir da decupagem.
    pode_esvaziar: bool = False
    # O item da versão nova já traz o "depois".
    ja_traz: Callable[[Correcao, dict[str, Any]], bool] = _nunca
    # As identidades que o item da versão nova pode ter, com o "depois".
    identidades: Callable[[Correcao], set[str]] = _so_a_ancora
    # Pessoa: casa também pelo nome novo; ou longe do que ela já tem.
    casa_pelo_nome_novo: bool = False
    # O nome novo é procurado no catálogo e, se casa com uma só pessoa, grava o id.
    acha_no_catalogo: bool = False
    casa_longe: bool = False
    acrescenta: Acrescenta | None = None


def _campo_longo(n: NovaCorrecao) -> str:
    _sem_controle(n.valor)
    if len(n.valor) > LIMITE_DO_NOME:
        raise ValueError("valor longo demais")
    return n.valor


def _canonizar_tempos(n: NovaCorrecao) -> str:
    tempos_de(n.valor)
    return n.valor


def _canonizar_resumo(n: NovaCorrecao) -> str:
    return _sem_controle_salvo_quebra(n.valor)


def _canonizar_tipo_de_comercial(n: NovaCorrecao) -> str:
    if n.valor not in TIPOS_DE_COMERCIAL:
        raise ValueError("tipo de comercial desconhecido")
    return n.valor


def _canonizar_comercial_acrescentado(n: NovaCorrecao) -> str:
    return _json_do_comercial(NovoComercial.model_validate_json(n.valor).model_dump())


def _canonizar_tom(n: NovaCorrecao) -> str:
    if n.valor not in TONS_DA_PAUTA:
        raise ValueError("tom desconhecido")
    return n.valor


def _canonizar_fontes(n: NovaCorrecao) -> str:
    return _valor_das_fontes(n.valor)


def _canonizar_limpo(n: NovaCorrecao) -> str:
    if n.valor not in ("true", "false"):
        raise ValueError("o valor de plano.limpo é true ou false")
    return n.valor


def _canonizar_descricao(n: NovaCorrecao) -> str:
    return _json_canonico(NovaDescricao.model_validate_json(n.valor).model_dump())


def _canonizar_fala(n: NovaCorrecao) -> str:
    return _json_canonico(NovoTexto.model_validate_json(n.valor).model_dump())


def _canonizar_texto_na_tela(n: NovaCorrecao) -> str:
    return _json_canonico(NovoTextoNaTela.model_validate_json(n.valor).model_dump())


def _canonizar_texto_acrescentado(n: NovaCorrecao) -> str:
    return _json_canonico(
        NovoTextoAcrescentado.model_validate_json(n.valor).model_dump()
    )


def _canonizar_aparicao_nova(n: NovaCorrecao) -> str:
    aparicao = NovaAparicao.model_validate_json(n.valor)
    if bool(n.item_id) == (aparicao.nome is not None):
        raise ValueError("informe item_id ou nome, não os dois nem nenhum")
    return _json_da_aparicao(aparicao)


def _lista_do_pedido(n: NovaCorrecao) -> str:
    assert n.ocorrencia is not None
    return n.ocorrencia.lista


def _canonizar_nao_e(n: NovaCorrecao) -> str:
    if not nao_identificado(n.valor):
        raise ValueError("o valor de pessoa.nao_e é Não identificado")
    return NOME_NAO_IDENTIFICADO


def _canonizar_aparicao_para_mencao(n: NovaCorrecao) -> str:
    if _lista_do_pedido(n) != "na_imagem" or n.valor not in MENCOES:
        raise ValueError("de aparição para citada_na_fala ou citada_no_texto")
    return n.valor


def _canonizar_papel_visual(n: NovaCorrecao) -> str:
    if _lista_do_pedido(n) != "na_imagem":
        raise ValueError("papel e visual são só da aparição")
    return _json_canonico(NovoPapelVisual.model_validate_json(n.valor).model_dump())


def _canonizar_mencao_para_aparicao(n: NovaCorrecao) -> str:
    if _lista_do_pedido(n) == "na_imagem":
        raise ValueError("a ocorrência já é uma aparição")
    _sem_controle(n.valor)
    if len(n.valor) > LIMITE_DO_NOME:
        raise ValueError("evidência longa demais")
    return n.valor


def _campo(nome: str) -> Callable[[dict[str, Any]], str]:
    return lambda item: str(item[nome])


def _tempos_do_item(item: dict[str, Any]) -> str:
    inicio, fim = _intervalo_da_pauta(item)
    return f"{inicio}-{fim}"


def _valor_da_descricao(item: dict[str, Any]) -> str:
    return _json_canonico(
        {
            "ambiente": item["ambiente"],
            "acao": item.get("acao") or None,
            "objetos": item.get("objetos", []),
        }
    )


def _valor_do_limpo(item: dict[str, Any]) -> str:
    return "true" if item["plano_limpo"] else "false"


def _valor_da_fala(item: dict[str, Any]) -> str:
    return _json_canonico({"texto": item["texto"], "locutor": item["locutor"]})


def _valor_do_tom(item: dict[str, Any]) -> str:
    return str(item.get("tom") or "")


def _valor_das_fontes_do_item(item: dict[str, Any]) -> str:
    return _json_das_fontes(item.get("fontes_do_nome", []))


def _valor_do_texto_na_tela(item: dict[str, Any]) -> str:
    return _json_canonico({"tipo": item["tipo"], "texto": item["texto"]})


def _ocorrencia_do_pedido(
    pessoa: dict[str, Any], ocorrencia: Ocorrencia | None, listas: tuple[str, ...]
) -> tuple[str, dict[str, Any]] | None:
    assert ocorrencia is not None
    return _acha_ocorrencia(pessoa, ocorrencia.inicio_ms, ocorrencia.fim_ms, listas)


def _na_lista(
    pessoa: dict[str, Any], ocorrencia: Ocorrencia | None, depois: str
) -> str:
    achada = _ocorrencia_do_pedido(pessoa, ocorrencia, LISTAS)
    if achada is None:
        return ""
    lista, o = achada
    return f"{lista} {o['inicio_ms']}-{o['fim_ms']}"


def _tempos_na_lista(
    pessoa: dict[str, Any], ocorrencia: Ocorrencia | None, depois: str
) -> str:
    assert ocorrencia is not None
    achada = _ocorrencia_do_pedido(pessoa, ocorrencia, (ocorrencia.lista,))
    if achada is None:
        return ""
    return f"{achada[1]['inicio_ms']}-{achada[1]['fim_ms']}"


def _papel_visual_na_lista(
    pessoa: dict[str, Any], ocorrencia: Ocorrencia | None, depois: str
) -> str:
    achada = _ocorrencia_do_pedido(pessoa, ocorrencia, LISTAS)
    return "" if achada is None else _json_do_papel_visual(achada[1])


def _aparicao_acrescentada_na_lista(
    pessoa: dict[str, Any], ocorrencia: Ocorrencia | None, depois: str
) -> str:
    alvo = json.loads(depois)
    achada = _acha_ocorrencia(pessoa, alvo["inicio_ms"], alvo["fim_ms"], ("na_imagem",))
    if achada is None:
        return ""
    lista, o = achada
    return f"{lista} {o['inicio_ms']}-{o['fim_ms']}"


def _nome_entregue_do_alvo(
    modelo: dict[str, Any], entregue: dict[str, Any], alvo: Correcao
) -> str:
    for original, pessoa in zip(_pessoas(modelo), _pessoas(entregue), strict=True):
        if identidade_da_pessoa(original) == alvo.ancora.identidade:
            return str(pessoa["nome"])
    raise ItemInexistente(alvo.ancora.identidade)


def _fim_dos_tempos(valor: str) -> int:
    return tempos_de(valor)[1]


def _fim_do_json(valor: str) -> int:
    return int(json.loads(valor)["fim_ms"])


def _traz_textos(entregue: dict[str, Any]) -> bool:
    return "textos_na_tela" in entregue


def _traz_tom(entregue: dict[str, Any]) -> bool:
    return any("tom" in p for p in _pautas(entregue))


def _traz_fontes(entregue: dict[str, Any]) -> bool:
    return any("fontes_do_nome" in p for p in _pessoas(entregue))


def _traz_papel_visual(entregue: dict[str, Any]) -> bool:
    return any(
        "papel" in a or "visual" in a
        for p in _pessoas(entregue)
        for a in p.get("na_imagem", [])
    )


def _no_campo(nome: str) -> Callable[[dict[str, Any], Correcao], None]:
    def aplicar_no_campo(item: dict[str, Any], c: Correcao) -> None:
        item[nome] = c.depois

    return aplicar_no_campo


def _descricao_no_plano(item: dict[str, Any], c: Correcao) -> None:
    descricao = json.loads(c.depois)
    item["ambiente"], item["objetos"] = descricao["ambiente"], descricao["objetos"]
    if descricao["acao"] is None:
        item.pop("acao", None)
    else:
        item["acao"] = descricao["acao"]


def _limpo_no_plano(item: dict[str, Any], c: Correcao) -> None:
    item["plano_limpo"] = c.depois == "true"


def _json_no_item(item: dict[str, Any], c: Correcao) -> None:
    item.update(json.loads(c.depois))


def _tempos_no_item(item: dict[str, Any], c: Correcao) -> None:
    item["inicio_ms"], item["fim_ms"] = tempos_de(c.depois)


def _renomear_pessoa(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    pessoa["nome"], pessoa["origem"] = c.depois, "revisao"
    # O nome da revisora vale sobre a conferência do código, feita no nome anterior.
    pessoa["estado_do_nome"] = "confirmado"
    _catalogo_id_na_pessoa(pessoa, c)


def _manter_o_nome_do_modelo(
    pessoa: dict[str, Any], do_modelo: dict[str, Any], c: Correcao
) -> None:
    pessoa["nome"], pessoa["origem"] = do_modelo["nome"], do_modelo["origem"]
    if "estado_do_nome" in do_modelo:
        pessoa["estado_do_nome"] = do_modelo["estado_do_nome"]
    else:
        pessoa.pop("estado_do_nome", None)
    _catalogo_id_na_pessoa(pessoa, c)


def _catalogo_id_na_pessoa(pessoa: dict[str, Any], c: Correcao) -> None:
    # O nome novo vale por inteiro: o id de um nome anterior não fica.
    if c.catalogo_id is None:
        pessoa.pop("catalogo_id", None)
    else:
        pessoa["catalogo_id"] = c.catalogo_id


def _fontes_na_pessoa(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    pessoa["fontes_do_nome"] = json.loads(c.depois)
    pessoa["origem"] = "revisao"


def _traz_o_nome(c: Correcao, item: dict[str, Any]) -> bool:
    return normalizar(str(item["nome"])) == normalizar(c.depois)


def _traz_a_marca(c: Correcao, item: dict[str, Any]) -> bool:
    return normalizar(str(item["marca"])) == normalizar(c.depois)


def _traz_o_tipo(c: Correcao, item: dict[str, Any]) -> bool:
    return str(item["tipo"]) == c.depois


def _traz_o_papel_visual(c: Correcao, item: dict[str, Any]) -> bool:
    assert c.ocorrencia is not None
    o = c.ocorrencia
    achada = _acha_ocorrencia(item, o.inicio_ms, o.fim_ms, (o.lista,))
    return achada is not None and _json_do_papel_visual(achada[1]) == c.depois


def _traz_a_aparicao(c: Correcao, item: dict[str, Any]) -> bool:
    alvo = json.loads(c.depois)
    return (
        _acha_ocorrencia(item, alvo["inicio_ms"], alvo["fim_ms"], ("na_imagem",))
        is not None
    )


def _identidades_do_texto(c: Correcao) -> set[str]:
    return {c.ancora.identidade, normalizar(json.loads(c.depois)["texto"])}


def _identidades_com_a_marca(c: Correcao) -> set[str]:
    _, tipo = c.ancora.identidade.rsplit("|", 1)
    return {c.ancora.identidade, f"{normalizar(c.depois)}|{tipo}"}


def _identidades_com_o_tipo(c: Correcao) -> set[str]:
    marca, _ = c.ancora.identidade.rsplit("|", 1)
    return {c.ancora.identidade, f"{marca}|{c.depois}"}


def _acrescentar_comercial(resultado: dict[str, Any], c: Correcao) -> None:
    resultado.setdefault("comerciais", []).append(
        {
            **json.loads(c.depois),
            "id": c.item_id,
            "origem": "revisao",
            "acrescentado": True,
        }
    )


def _acrescentar_texto_na_tela(resultado: dict[str, Any], c: Correcao) -> None:
    resultado.setdefault("textos_na_tela", []).append(
        {
            **json.loads(c.depois),
            "id": c.item_id,
            "origem": "revisao",
            "acrescentado": True,
        }
    )


def _ancora_do_comercial_novo(valor: str, item_id: str, versao: str) -> Ancora:
    return _ancora_do_item(json.loads(valor), "comercial", versao)


def _ancora_do_texto_novo(valor: str, item_id: str, versao: str) -> Ancora:
    return _ancora_do_item(json.loads(valor), "texto_na_tela", versao)


def _ancora_da_pessoa_nova(valor: str, item_id: str, versao: str) -> Ancora | None:
    if item_id:
        return None
    aparicao = json.loads(valor)
    return Ancora(
        versao=versao,
        tipo_do_item="pessoa",
        identidade=normalizar(aparicao["nome"]),
        inicio_ms=aparicao["inicio_ms"],
        fim_ms=aparicao["fim_ms"],
    )


def _todos(c: Correcao, candidatos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return candidatos


def _do_mesmo_tipo_de_texto(
    c: Correcao, candidatos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tipo = json.loads(c.depois)["tipo"]
    return [i for i in candidatos if i["tipo"] == tipo]


def _com_a_aparicao(
    c: Correcao, candidatos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [i for i in candidatos if _traz_a_aparicao(c, i)]


def _pessoa_nova(c: Correcao) -> bool:
    """Aparição de pessoa nova: não corrige item nenhum."""
    return c.item_id.startswith(PREFIXO_ACRESCENTADO)


_COMERCIAL_NOVO = Acrescenta(
    ancora=_ancora_do_comercial_novo,
    acrescenta=lambda c: True,
    atendentes=_todos,
    aplicar=_acrescentar_comercial,
)
_TEXTO_NOVO = Acrescenta(
    ancora=_ancora_do_texto_novo,
    acrescenta=lambda c: True,
    atendentes=_do_mesmo_tipo_de_texto,
    aplicar=_acrescentar_texto_na_tela,
)
_PESSOA_NOVA = Acrescenta(
    ancora=_ancora_da_pessoa_nova,
    acrescenta=_pessoa_nova,
    atendentes=_com_a_aparicao,
    aplicar=_acrescentar_pessoa,
)

TIPOS: dict[str, Tipo] = {
    "pessoa.renomear": Tipo(
        canonizar=_campo_longo,
        rotulo="Renomear pessoa",
        legivel=textos.como_veio,
        tipo_do_item="pessoa",
        valor_do_item=_campo("nome"),
        valor_do_alvo=_nome_entregue_do_alvo,
        aplicar_na_pessoa=_renomear_pessoa,
        atender_na_pessoa=_manter_o_nome_do_modelo,
        ja_traz=_traz_o_nome,
        casa_pelo_nome_novo=True,
        acha_no_catalogo=True,
    ),
    "pauta.titulo": Tipo(
        canonizar=_campo_longo,
        rotulo="Título da pauta",
        legivel=textos.como_veio,
        tipo_do_item="pauta",
        valor_do_item=_campo("titulo"),
        aplicar_no_item=_no_campo("titulo"),
    ),
    "pauta.resumo": Tipo(
        canonizar=_canonizar_resumo,
        rotulo="Resumo da pauta",
        legivel=textos.como_veio,
        tipo_do_item="pauta",
        valor_do_item=_campo("resumo"),
        aplicar_no_item=_no_campo("resumo"),
    ),
    "item.tempos": Tipo(
        canonizar=_canonizar_tempos,
        rotulo="Tempos",
        legivel=textos.tempos,
        valor_do_item=_tempos_do_item,
        valor_da_ocorrencia=_tempos_na_lista,
        fim_ms=_fim_dos_tempos,
        aplicar_no_item=_tempos_no_item,
        aplicar_na_pessoa=_tempos_da_ocorrencia,
    ),
    "comercial.marca": Tipo(
        canonizar=_campo_longo,
        rotulo="Marca do comercial",
        legivel=textos.como_veio,
        tipo_do_item="comercial",
        valor_do_item=_campo("marca"),
        aplicar_no_item=_no_campo("marca"),
        ja_traz=_traz_a_marca,
        identidades=_identidades_com_a_marca,
    ),
    "comercial.tipo": Tipo(
        canonizar=_canonizar_tipo_de_comercial,
        rotulo="Tipo do comercial",
        legivel=textos.como_veio,
        tipo_do_item="comercial",
        valor_do_item=_campo("tipo"),
        aplicar_no_item=_no_campo("tipo"),
        ja_traz=_traz_o_tipo,
        identidades=_identidades_com_o_tipo,
    ),
    "comercial.acrescentar": Tipo(
        canonizar=_canonizar_comercial_acrescentado,
        rotulo="Comercial acrescentado",
        legivel=textos.comercial_acrescentado,
        tipo_do_item="comercial",
        valor_do_item=_json_do_comercial,
        fim_ms=_fim_do_json,
        acrescenta=_COMERCIAL_NOVO,
    ),
    "pessoa.nao_e": Tipo(
        canonizar=_canonizar_nao_e,
        rotulo="Não é esta pessoa",
        legivel=textos.ocorrencia,
        tipo_do_item="pessoa",
        de_ocorrencia=True,
        valor_da_ocorrencia=_na_lista,
        aplicar_na_pessoa=_nao_e,
        pode_esvaziar=True,
    ),
    "pessoa.aparicao_para_mencao": Tipo(
        canonizar=_canonizar_aparicao_para_mencao,
        rotulo="Aparição para menção",
        legivel=textos.ocorrencia,
        tipo_do_item="pessoa",
        de_ocorrencia=True,
        valor_da_ocorrencia=_na_lista,
        aplicar_na_pessoa=_aparicao_para_mencao,
    ),
    "pessoa.mencao_para_aparicao": Tipo(
        canonizar=_canonizar_mencao_para_aparicao,
        rotulo="Menção para aparição",
        legivel=textos.ocorrencia,
        tipo_do_item="pessoa",
        de_ocorrencia=True,
        valor_da_ocorrencia=_na_lista,
        aplicar_na_pessoa=_mencao_para_aparicao,
    ),
    "pessoa.acrescentar_aparicao": Tipo(
        canonizar=_canonizar_aparicao_nova,
        rotulo="Aparição acrescentada",
        legivel=textos.aparicao_acrescentada,
        tipo_do_item="pessoa",
        valor_da_ocorrencia=_aparicao_acrescentada_na_lista,
        fim_ms=_fim_do_json,
        aplicar_na_pessoa=_aparicao_na_pessoa,
        ja_traz=_traz_a_aparicao,
        casa_longe=True,
        acrescenta=_PESSOA_NOVA,
    ),
    "plano.descricao": Tipo(
        canonizar=_canonizar_descricao,
        rotulo="Descrição do plano",
        legivel=textos.descricao_do_plano,
        tipo_do_item="plano",
        json_longo=True,
        valor_do_item=_valor_da_descricao,
        aplicar_no_item=_descricao_no_plano,
        ja_traz=_ja_traz_o_valor,
    ),
    "plano.limpo": Tipo(
        canonizar=_canonizar_limpo,
        rotulo="Plano limpo",
        legivel=textos.plano_limpo,
        tipo_do_item="plano",
        json_longo=True,
        valor_do_item=_valor_do_limpo,
        aplicar_no_item=_limpo_no_plano,
        ja_traz=_ja_traz_o_valor,
    ),
    "fala.texto": Tipo(
        canonizar=_canonizar_fala,
        rotulo="Texto da fala",
        legivel=textos.fala,
        tipo_do_item="fala",
        json_longo=True,
        valor_do_item=_valor_da_fala,
        aplicar_no_item=_json_no_item,
        ja_traz=_ja_traz_o_valor,
    ),
    "pauta.tom": Tipo(
        canonizar=_canonizar_tom,
        rotulo="Tom da pauta",
        legivel=textos.tom_da_pauta,
        tipo_do_item="pauta",
        valor_do_item=_valor_do_tom,
        traz_o_campo=_traz_tom,
        aplicar_no_item=_no_campo("tom"),
    ),
    "pessoa.fontes_do_nome": Tipo(
        canonizar=_canonizar_fontes,
        rotulo="Fontes do nome",
        legivel=textos.fontes_do_nome,
        tipo_do_item="pessoa",
        valor_do_item=_valor_das_fontes_do_item,
        traz_o_campo=_traz_fontes,
        aplicar_na_pessoa=_fontes_na_pessoa,
        ja_traz=_ja_traz_o_valor,
    ),
    "aparicao.papel_visual": Tipo(
        canonizar=_canonizar_papel_visual,
        rotulo="Papel na cena e visual",
        legivel=textos.papel_visual,
        tipo_do_item="pessoa",
        de_ocorrencia=True,
        valor_da_ocorrencia=_papel_visual_na_lista,
        traz_o_campo=_traz_papel_visual,
        aplicar_na_pessoa=_papel_visual_da_ocorrencia,
        ja_traz=_traz_o_papel_visual,
    ),
    "texto_na_tela.texto": Tipo(
        canonizar=_canonizar_texto_na_tela,
        rotulo="Texto na tela",
        legivel=textos.texto_na_tela,
        tipo_do_item="texto_na_tela",
        json_longo=True,
        valor_do_item=_valor_do_texto_na_tela,
        traz_o_campo=_traz_textos,
        aplicar_no_item=_json_no_item,
        ja_traz=_ja_traz_o_valor,
        identidades=_identidades_do_texto,
    ),
    "texto_na_tela.acrescentar": Tipo(
        canonizar=_canonizar_texto_acrescentado,
        rotulo="Texto na tela acrescentado",
        legivel=textos.texto_na_tela_acrescentado,
        tipo_do_item="texto_na_tela",
        json_longo=True,
        valor_do_item=_tempos_do_item,
        fim_ms=_fim_do_json,
        traz_o_campo=_traz_textos,
        acrescenta=_TEXTO_NOVO,
    ),
}

ROTULOS_DAS_DECISOES = {
    "desfazer": "Desfazer",
    "descartar": "Descartar da fila",
    "aprovar": "Aprovação",
    "recusar": "Recusa",
}


def rotulos_dos_tipos() -> list[textos.Opcao]:
    """Todo tipo de Correção com o rótulo: os da tabela e os das decisões."""
    rotulos = {t: e.rotulo for t, e in TIPOS.items()} | ROTULOS_DAS_DECISOES
    return [textos.Opcao(valor=t, rotulo=r) for t, r in rotulos.items()]


def valor_legivel(tipo: str | None, valor: str) -> str:
    """O valor de uma Correção para quem lê, pela entrada do tipo; o que não
    for o formato esperado sai como veio."""
    entrada = TIPOS.get(tipo or "")
    if entrada is None:
        return valor
    try:
        return entrada.legivel(valor)
    except (ValueError, KeyError, TypeError):
        return valor
