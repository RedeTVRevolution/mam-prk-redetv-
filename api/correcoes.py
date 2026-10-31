"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

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
# Corrigem uma ocorrência (aparição ou menção) que o pedido identifica.
DE_OCORRENCIA = (
    "pessoa.nao_e",
    "pessoa.aparicao_para_mencao",
    "pessoa.mencao_para_aparicao",
    "aparicao.papel_visual",
)
# Corrigem a pessoa inteira, não uma ocorrência.
DE_PESSOA = ("pessoa.renomear", "pessoa.fontes_do_nome")
ACRESCENTAR_APARICAO = "pessoa.acrescentar_aparicao"
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
DE_PLANO_OU_FALA = ("plano.descricao", "plano.limpo", "fala.texto")
ACRESCENTAR_TEXTO = "texto_na_tela.acrescentar"
# Valores em JSON, que podem passar do limite do texto simples.
DE_JSON_LONGO = (*DE_PLANO_OU_FALA, "texto_na_tela.texto", ACRESCENTAR_TEXTO)
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


def _valor_de_plano_ou_fala(tipo: str, valor: str) -> str:
    """A forma única em que a correção de plano ou fala é guardada."""
    if tipo == "plano.limpo":
        if valor not in ("true", "false"):
            raise ValueError("o valor de plano.limpo é true ou false")
        return valor
    if tipo == "plano.descricao":
        return _json_canonico(NovaDescricao.model_validate_json(valor).model_dump())
    return _json_canonico(NovoTexto.model_validate_json(valor).model_dump())


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
        if not self.item_id and self.tipo not in (
            "comercial.acrescentar",
            ACRESCENTAR_APARICAO,
            ACRESCENTAR_TEXTO,
        ):
            raise ValueError("item_id obrigatório")
        if self.tipo_do_item is not None and self.tipo != "item.tempos":
            raise ValueError("tipo_do_item só vale no item.tempos")
        de_pessoa = self.tipo in DE_OCORRENCIA or self.tipo_do_item == "pessoa"
        if de_pessoa != (self.ocorrencia is not None):
            raise ValueError("ocorrencia vale só para aparição e menção de pessoa")
        if self.tipo not in DE_JSON_LONGO and len(self.valor) > LIMITE_DO_TEXTO:
            raise ValueError("valor longo demais")
        if self.tipo == "item.tempos":
            tempos_de(self.valor)
        elif self.tipo in DE_PLANO_OU_FALA:
            self.valor = _valor_de_plano_ou_fala(self.tipo, self.valor)
        elif self.tipo in DE_OCORRENCIA:
            self.valor = self._valor_da_ocorrencia()
        elif self.tipo == ACRESCENTAR_APARICAO:
            aparicao = NovaAparicao.model_validate_json(self.valor)
            if bool(self.item_id) == (aparicao.nome is not None):
                raise ValueError("informe item_id ou nome, não os dois nem nenhum")
            self.valor = _json_da_aparicao(aparicao)
        elif self.tipo == "comercial.tipo":
            if self.valor not in TIPOS_DE_COMERCIAL:
                raise ValueError("tipo de comercial desconhecido")
        elif self.tipo == "comercial.acrescentar":
            self.valor = _json_do_comercial(
                NovoComercial.model_validate_json(self.valor).model_dump()
            )
        elif self.tipo == "pauta.resumo":
            self.valor = _sem_controle_salvo_quebra(self.valor)
        elif self.tipo == "pauta.tom":
            if self.valor not in TONS_DA_PAUTA:
                raise ValueError("tom desconhecido")
        elif self.tipo == "pessoa.fontes_do_nome":
            self.valor = _valor_das_fontes(self.valor)
        elif self.tipo == "texto_na_tela.texto":
            self.valor = _json_canonico(
                NovoTextoNaTela.model_validate_json(self.valor).model_dump()
            )
        elif self.tipo == ACRESCENTAR_TEXTO:
            self.valor = _json_canonico(
                NovoTextoAcrescentado.model_validate_json(self.valor).model_dump()
            )
        else:
            _sem_controle(self.valor)
            if len(self.valor) > LIMITE_DO_NOME:
                raise ValueError("valor longo demais")
        return self

    def _valor_da_ocorrencia(self) -> str:
        assert self.ocorrencia is not None
        lista = self.ocorrencia.lista
        if self.tipo == "pessoa.nao_e":
            if not nao_identificado(self.valor):
                raise ValueError("o valor de pessoa.nao_e é Não identificado")
            return NOME_NAO_IDENTIFICADO
        if self.tipo == "pessoa.aparicao_para_mencao":
            if lista != "na_imagem" or self.valor not in MENCOES:
                raise ValueError("de aparição para citada_na_fala ou citada_no_texto")
            return self.valor
        if self.tipo == "aparicao.papel_visual":
            if lista != "na_imagem":
                raise ValueError("papel e visual são só da aparição")
            return _json_canonico(
                NovoPapelVisual.model_validate_json(self.valor).model_dump()
            )
        if lista == "na_imagem":
            raise ValueError("a ocorrência já é uma aparição")
        _sem_controle(self.valor)
        if len(self.valor) > LIMITE_DO_NOME:
            raise ValueError("evidência longa demais")
        return self.valor


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


def _comerciais(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    """Os comerciais não têm id no esquema: o id é a posição no JSON do modelo.

    São cópias; o que já traz id (decupagem entregue) o mantém.
    """
    return [
        {"id": f"com{n:03d}", **c}
        for n, c in enumerate(modelo.get("comerciais", []))
        if isinstance(c, dict)
    ]


def _textos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    """Os textos na tela não têm id no esquema: o id é a posição (`txt000`)."""
    return [
        {"id": f"txt{n:03d}", **t}
        for n, t in enumerate(modelo.get("textos_na_tela", []))
        if isinstance(t, dict)
    ]


def _tipo_do_item(tipo: str, escolhido: str | None = None) -> TipoDoItem:
    if tipo.startswith(("pessoa.", "aparicao.")) or escolhido == "pessoa":
        return "pessoa"
    if tipo.startswith("texto_na_tela.") or escolhido == "texto_na_tela":
        return "texto_na_tela"
    if tipo.startswith("comercial.") or escolhido == "comercial":
        return "comercial"
    if tipo.startswith("plano."):
        return "plano"
    if tipo.startswith("fala."):
        return "fala"
    return "pauta"


def _planos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("planos", []) if isinstance(p, dict)]


def _falas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    """As falas não têm id no esquema: o id é a posição, como nos comerciais."""
    return [
        {"id": f"fal{n:03d}", **f}
        for n, f in enumerate(modelo.get("transcricao", []))
        if isinstance(f, dict)
    ]


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
    if tipo == "pessoa.renomear":
        return str(item["nome"])
    if tipo == "pauta.titulo":
        return str(item["titulo"])
    if tipo == "pauta.resumo":
        return str(item["resumo"])
    if tipo == "comercial.marca":
        return str(item["marca"])
    if tipo == "comercial.tipo":
        return str(item["tipo"])
    if tipo == "comercial.acrescentar":
        return _json_do_comercial(item)
    if tipo == "plano.descricao":
        return _json_canonico(
            {
                "ambiente": item["ambiente"],
                "acao": item.get("acao") or None,
                "objetos": item.get("objetos", []),
            }
        )
    if tipo == "plano.limpo":
        return "true" if item["plano_limpo"] else "false"
    if tipo == "fala.texto":
        return _json_canonico({"texto": item["texto"], "locutor": item["locutor"]})
    if tipo == "pauta.tom":
        return str(item.get("tom") or "")
    if tipo == "pessoa.fontes_do_nome":
        return _json_das_fontes(item.get("fontes_do_nome", []))
    if tipo == "texto_na_tela.texto":
        return _json_canonico({"tipo": item["tipo"], "texto": item["texto"]})
    inicio, fim = _intervalo_da_pauta(item)
    return f"{inicio}-{fim}"


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
    if tipo == ACRESCENTAR_APARICAO:
        alvo = json.loads(depois)
        achada = _acha_ocorrencia(
            pessoa, alvo["inicio_ms"], alvo["fim_ms"], ("na_imagem",)
        )
    else:
        assert ocorrencia is not None
        listas = (ocorrencia.lista,) if tipo == "item.tempos" else LISTAS
        achada = _acha_ocorrencia(
            pessoa, ocorrencia.inicio_ms, ocorrencia.fim_ms, listas
        )
    if achada is None:
        return ""
    lista, o = achada
    if tipo == "aparicao.papel_visual":
        return _json_do_papel_visual(o)
    tempos = f"{o['inicio_ms']}-{o['fim_ms']}"
    return tempos if tipo == "item.tempos" else f"{lista} {tempos}"


class TemposInvalidos(Exception):
    """Os tempos passam da duração do vídeo."""


def _confere_duracao(modelo: dict[str, Any], tipo: str, valor: str) -> None:
    """`TemposInvalidos` se os tempos de um `item.tempos` ou de um comercial
    acrescentado passam da duração."""
    if tipo == "item.tempos":
        fim = tempos_de(valor)[1]
    elif tipo in ("comercial.acrescentar", ACRESCENTAR_APARICAO, ACRESCENTAR_TEXTO):
        fim = int(json.loads(valor)["fim_ms"])
    else:
        return
    if fim > int(modelo.get("video", {}).get("duracao_ms", 0)):
        raise TemposInvalidos(valor)


def montar_correcao(
    modelo: dict[str, Any],
    versao: str,
    novo: NovaCorrecao,
    antes: str,
    *,
    anteriores: list[Correcao] | None = None,
    **registro: Any,
) -> Correcao:
    """A correção de `novo` sobre o item do JSON do modelo, com a âncora pronta.

    `anteriores` são as correções já gravadas: a ocorrência de uma pessoa tem de
    existir na decupagem entregue, que já as traz.
    """
    tipo_do_item = _tipo_do_item(novo.tipo, novo.tipo_do_item)
    _confere_duracao(modelo, novo.tipo, novo.valor)
    if novo.tipo == ACRESCENTAR_APARICAO and not novo.item_id:
        aparicao = json.loads(novo.valor)
        return Correcao(
            tipo=novo.tipo,
            item_id=f"{PREFIXO_ACRESCENTADO}{registro['id']}",
            motivo=novo.motivo,
            antes="",
            depois=novo.valor,
            ancora=Ancora(
                versao=versao,
                tipo_do_item="pessoa",
                identidade=normalizar(aparicao["nome"]),
                inicio_ms=aparicao["inicio_ms"],
                fim_ms=aparicao["fim_ms"],
            ),
            **registro,
        )
    if novo.tipo == ACRESCENTAR_TEXTO:
        texto = json.loads(novo.valor)
        return Correcao(
            tipo=novo.tipo,
            item_id=f"{PREFIXO_ACRESCENTADO}{registro['id']}",
            motivo=novo.motivo,
            antes="",
            depois=novo.valor,
            ancora=_ancora_do_item(texto, "texto_na_tela", versao),
            **registro,
        )
    if novo.tipo == "comercial.acrescentar":
        comercial = json.loads(novo.valor)
        return Correcao(
            tipo=novo.tipo,
            item_id=f"acr-{registro['id']}",
            motivo=novo.motivo,
            antes="",
            depois=novo.valor,
            ancora=_ancora_do_item(comercial, "comercial", versao),
            **registro,
        )
    item = next(
        (i for i in _itens(modelo, tipo_do_item) if i.get("id") == novo.item_id), None
    )
    if item is None:
        raise ItemInexistente(novo.item_id)
    if novo.ocorrencia is not None:
        entregue = _itens(aplicar(modelo, versao, anteriores or []), "pessoa")
        pessoa = next((p for p in entregue if p.get("id") == novo.item_id), None)
        o = novo.ocorrencia
        if pessoa is None or not _acha_ocorrencia(
            pessoa, o.inicio_ms, o.fim_ms, (o.lista,)
        ):
            raise ItemInexistente(f"{novo.item_id} {o.lista}")
    return Correcao(
        tipo=novo.tipo,
        item_id=novo.item_id,
        motivo=novo.motivo,
        antes=antes,
        depois=novo.valor,
        ocorrencia=novo.ocorrencia,
        ancora=_ancora_do_item(item, tipo_do_item, versao),
        **registro,
    )


def _ancora_do_item(item: dict[str, Any], tipo_do_item: str, versao: str) -> Ancora:
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
        tipo_do_item=_tipo_do_item(f"{tipo_do_item}."),
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


def _desfeitas(correcoes: list[Correcao]) -> set[str]:
    return {c.desfaz for c in correcoes if c.tipo == "desfazer" and c.desfaz}


def _resolvidas(correcoes: list[Correcao]) -> set[str]:
    """As que saíram da fila: reaplicadas ou descartadas."""
    return {c.reaplica for c in correcoes if c.reaplica} | {
        c.descarta for c in correcoes if c.descarta
    }


def _aprovadas(correcoes: list[Correcao]) -> set[str]:
    return {c.aprova for c in correcoes if c.aprova}


def _recusadas(correcoes: list[Correcao]) -> set[str]:
    return {c.recusa for c in correcoes if c.recusa}


def _fora_da_entrega(correcoes: list[Correcao]) -> set[str]:
    """As que exigem aprovação e ainda não a têm: pendentes ou recusadas."""
    return {c.id for c in correcoes if c.exige_aprovacao} - _aprovadas(correcoes)


def _em_ordem_de_vigencia(
    alvos: list[Correcao], correcoes: list[Correcao]
) -> list[Correcao]:
    """Como `em_ordem`, mas a aprovada entra na data da aprovação: uma correção
    feita enquanto ela esperava o Curador não a encobre depois de aprovada."""
    aprovada_em = {c.aprova: c.criada_em for c in correcoes if c.aprova}
    return sorted(alvos, key=lambda c: (aprovada_em.get(c.id, c.criada_em), c.id))


def _decididas(correcoes: list[Correcao]) -> set[str]:
    return _aprovadas(correcoes) | _recusadas(correcoes)


def id_do_desfazer(alvo_id: str) -> str:
    """Fixo por alvo: dois desfazer simultâneos colidem no repositório."""
    return f"{alvo_id}-desfeita"


def _valor_do_alvo(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao], alvo: Correcao
) -> str:
    """O valor entregue hoje no item do alvo (casa como `aplicar`): a pessoa
    pela identidade da âncora; a pauta pelo id, que na mesma versão é estável."""
    if alvo.tipo != "pessoa.renomear":
        return valor_atual(
            modelo,
            versao,
            correcoes,
            alvo.tipo,
            alvo.item_id,
            alvo.ancora.tipo_do_item,
            alvo.ocorrencia,
            alvo.depois,
        )
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
        or alvo.id in _fora_da_entrega(correcoes)
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
        tipo_do_item = alvo_atual.ancora.tipo_do_item
        antes, depois = (
            valor_atual(
                modelo,
                versao,
                lista,
                alvo_atual.tipo,
                alvo_atual.item_id,
                tipo_do_item,
                alvo_atual.ocorrencia,
                alvo_atual.depois,
            )
            for lista in (correcoes, restantes)
        )
    return Correcao(
        tipo="desfazer",
        desfaz=alvo.id,
        item_id=alvo_atual.item_id,
        ocorrencia=alvo_atual.ocorrencia,
        motivo=motivo,
        antes=antes,
        depois=depois,
        ancora=alvo_atual.ancora,
        **registro,
    )


def historico(correcoes: list[Correcao]) -> list[ItemDoHistorico]:
    """Da mais recente para a mais antiga, cada uma ativa, desfeita, fora da
    fila (reaplicada ou descartada) ou, se exige aprovação, pendente, aprovada
    ou recusada."""
    desfeitas = _desfeitas(correcoes)
    reaplicadas = {c.reaplica for c in correcoes if c.reaplica}
    descartadas = {c.descarta for c in correcoes if c.descarta}
    aprovadas, recusadas = _aprovadas(correcoes), _recusadas(correcoes)

    def estado(c: Correcao) -> EstadoNoHistorico:
        if c.id in desfeitas:
            return "desfeita"
        if c.id in recusadas:
            return "recusada"
        # A aprovada que depois saiu da fila mostra o que lhe aconteceu por último.
        if c.id in reaplicadas:
            return "reaplicada"
        if c.id in descartadas:
            return "descartada"
        if c.exige_aprovacao:
            return "aprovada" if c.id in aprovadas else "pendente"
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
    tipo_do_item: str | None = None,
    ocorrencia: Ocorrencia | None = None,
    depois: str = "",
) -> str:
    """O valor que o Editor vê hoje no campo do `tipo` do item `item_id`.

    Vazio para o comercial acrescentado que não está na decupagem (ainda não
    existe, foi desfeito ou o modelo já o traz) e para a ocorrência de pessoa
    que a decupagem não tem (ou cuja pessoa saiu dela). `depois` é o valor da
    correção, de onde sai o intervalo da aparição acrescentada.
    """
    tipo_do_item = _tipo_do_item(tipo, tipo_do_item)
    entregue = aplicar(modelo, versao, correcoes)
    _confere_campo_do_esquema(entregue, tipo)
    for item in _itens(entregue, tipo_do_item):
        if item.get("id") != item_id:
            continue
        if tipo_do_item == "pessoa" and tipo not in DE_PESSOA:
            return _valor_da_ocorrencia(item, tipo, ocorrencia, depois)
        return _valor_do_item(item, tipo)
    if tipo in ("comercial.acrescentar", ACRESCENTAR_TEXTO) or (
        tipo_do_item == "pessoa" and tipo not in DE_PESSOA
    ):
        return ""
    raise ItemInexistente(item_id)


def _confere_campo_do_esquema(entregue: dict[str, Any], tipo: str) -> None:
    """`ItemInexistente` se a decupagem não traz o campo que o `tipo` corrige.

    Uma decupagem anterior ao esquema 1.2 não tem tom, fontes do nome, papel e
    visual, nem a lista de textos na tela: a correção seria sobre o que não
    existe. O campo conta como presente se algum item o traz (o item criado
    pela revisão não o tem).
    """
    pessoas = _pessoas(entregue)
    if tipo.startswith("texto_na_tela."):
        traz = "textos_na_tela" in entregue
    elif tipo == "pauta.tom":
        traz = any("tom" in p for p in _pautas(entregue))
    elif tipo == "pessoa.fontes_do_nome":
        traz = any("fontes_do_nome" in p for p in pessoas)
    elif tipo == "aparicao.papel_visual":
        traz = any(
            "papel" in a or "visual" in a
            for p in pessoas
            for a in p.get("na_imagem", [])
        )
    else:
        return
    if not traz:
        raise ItemInexistente(tipo)


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
        identidades = {c.ancora.identidade}
        if c.tipo == "texto_na_tela.texto":
            identidades.add(normalizar(json.loads(c.depois)["texto"]))
        return [
            t
            for t in _textos(modelo)
            if normalizar(str(t["texto"])) in identidades
            and _sobrepoe_de_verdade(ancora, _intervalo_da_pauta(t))
        ]
    if c.ancora.tipo_do_item == "comercial":
        identidades = {c.ancora.identidade, _identidade_com_o_depois(c)}
        return [
            m
            for m in _comerciais(modelo)
            if identidade_do_comercial(m) in identidades
            and _sobrepoe(ancora, _intervalo_da_pauta(m))
        ]
    return _candidatos_pessoa(modelo, c)


def _identidade_com_o_depois(c: Correcao) -> str:
    """A identidade do comercial já com a marca ou o tipo corrigidos: o modelo
    pode passar a trazer o "depois"."""
    marca, tipo = c.ancora.identidade.rsplit("|", 1)
    if c.tipo == "comercial.marca":
        marca = normalizar(c.depois)
    elif c.tipo == "comercial.tipo":
        tipo = c.depois
    return f"{marca}|{tipo}"


def _aparicao_acrescentada(c: Correcao) -> tuple[int, int]:
    alvo = json.loads(c.depois)
    return alvo["inicio_ms"], alvo["fim_ms"]


def _pessoa_acrescentada(c: Correcao) -> bool:
    """Aparição de pessoa nova: não corrige item nenhum."""
    return c.tipo == ACRESCENTAR_APARICAO and c.item_id.startswith(PREFIXO_ACRESCENTADO)


def _ja_traz_o_depois(c: Correcao, item: dict[str, Any]) -> bool:
    if c.tipo == ACRESCENTAR_APARICAO:
        return (
            _acha_ocorrencia(item, *_aparicao_acrescentada(c), ("na_imagem",))
            is not None
        )
    if c.tipo == "pessoa.renomear":
        return normalizar(str(item["nome"])) == normalizar(c.depois)
    if c.tipo == "comercial.marca":
        return normalizar(str(item["marca"])) == normalizar(c.depois)
    if c.tipo == "comercial.tipo":
        return str(item["tipo"]) == c.depois
    if c.tipo in (*DE_PLANO_OU_FALA, "texto_na_tela.texto", "pessoa.fontes_do_nome"):
        return _valor_do_item(item, c.tipo) == c.depois
    if c.tipo == "aparicao.papel_visual":
        assert c.ocorrencia is not None
        o = c.ocorrencia
        achada = _acha_ocorrencia(item, o.inicio_ms, o.fim_ms, (o.lista,))
        return achada is not None and _json_do_papel_visual(achada[1]) == c.depois
    return False


def _candidatos_pessoa(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    sem_nome = nao_identificado(c.ancora.identidade.split("@")[0])
    achados = []
    for pessoa in _pessoas(modelo):
        nome = str(pessoa["nome"])
        if sem_nome and nao_identificado(nome):
            # Só as aparições mostram quem é.
            intervalo = _intervalo_da_pessoa(pessoa, ("na_imagem",))
        elif (
            c.tipo == "pessoa.renomear" and normalizar(nome) == normalizar(c.depois)
        ) or (not sem_nome and normalizar(nome) == c.ancora.identidade):
            intervalo = _intervalo_da_pessoa(pessoa)
        else:
            continue
        # A aparição acrescentada pode estar longe do que a pessoa já tem.
        longe_ok = c.tipo == ACRESCENTAR_APARICAO and not sem_nome
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
    fora = _desfeitas(correcoes) | _resolvidas(correcoes) | _fora_da_entrega(correcoes)
    resultado = Reconciliacao(casadas=[], atendidas=[], sem_casar=[])
    for c in em_ordem(correcoes):
        if c.ancora.versao == versao or c.tipo not in CORRIGIVEIS or c.id in fora:
            continue
        candidatos = _candidatos(modelo, c)
        if c.tipo in ("comercial.acrescentar", ACRESCENTAR_TEXTO) or (
            _pessoa_acrescentada(c)
        ):
            # Não corrige item nenhum: não vai para a fila. Se o modelo já traz
            # o comercial (a aparição, o texto), a correção é atendida e não duplica.
            if _pessoa_acrescentada(c):
                candidatos = [i for i in candidatos if _ja_traz_o_depois(c, i)]
            elif c.tipo == ACRESCENTAR_TEXTO:
                tipo = json.loads(c.depois)["tipo"]
                candidatos = [i for i in candidatos if i["tipo"] == tipo]
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
        if _ja_traz_o_depois(c, item):
            resultado.atendidas.append(nova)
    return resultado


_CHAVE_DO_ITEM = {
    "pauta": "pautas",
    "comercial": "comerciais",
    "plano": "planos",
    "fala": "transcricao",
    "texto_na_tela": "textos_na_tela",
}
_CAMPO_DO_TIPO = {
    "pauta.titulo": "titulo",
    "pauta.resumo": "resumo",
    "comercial.marca": "marca",
    "comercial.tipo": "tipo",
    "pauta.tom": "tom",
}


def _aplicar_no_item(resultado: dict[str, Any], c: Correcao) -> None:
    """Pauta, comercial, plano ou fala é achado pelo id: na versão atual o id
    do item é estável, e a reapontada já traz o id novo."""
    chave = _CHAVE_DO_ITEM[c.ancora.tipo_do_item]
    for item in resultado.get(chave, []):
        if not isinstance(item, dict) or item.get("id") != c.item_id:
            continue
        if c.tipo == "plano.descricao":
            descricao = json.loads(c.depois)
            item["ambiente"], item["objetos"] = (
                descricao["ambiente"],
                descricao["objetos"],
            )
            if descricao["acao"] is None:
                item.pop("acao", None)
            else:
                item["acao"] = descricao["acao"]
        elif c.tipo == "plano.limpo":
            item["plano_limpo"] = c.depois == "true"
        elif c.tipo in ("fala.texto", "texto_na_tela.texto"):
            item.update(json.loads(c.depois))
        elif c.tipo == "item.tempos":
            item["inicio_ms"], item["fim_ms"] = tempos_de(c.depois)
        else:
            item[_CAMPO_DO_TIPO[c.tipo]] = c.depois
        item["origem"] = "revisao"


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


def _por_inicio(ocorrencias: list[dict[str, Any]]) -> None:
    ocorrencias.sort(key=lambda o: (o["inicio_ms"], o["fim_ms"]))


def _aplicar_na_pessoa(
    resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao
) -> None:
    """Uma correção de aparição ou menção sobre a pessoa que ela casou.

    A ocorrência é achada na lista dela pela sobreposição; se sumiu, nada muda.
    """
    if c.tipo == ACRESCENTAR_APARICAO:
        _acrescentar_aparicao(pessoa, json.loads(c.depois))
        return
    o = c.ocorrencia
    assert o is not None
    achada = _acha_ocorrencia(pessoa, o.inicio_ms, o.fim_ms, (o.lista,))
    if achada is None:
        return
    ocorrencia = achada[1]
    pessoa["origem"] = "revisao"
    if c.tipo == "item.tempos":
        ocorrencia["inicio_ms"], ocorrencia["fim_ms"] = tempos_de(c.depois)
        _por_inicio(pessoa[o.lista])
        return
    if c.tipo == "aparicao.papel_visual":
        ocorrencia.update(json.loads(c.depois))
        return
    pessoa[o.lista].remove(ocorrencia)
    if c.tipo == "pessoa.nao_e":
        resultado.setdefault("pessoas", []).append(
            {
                "id": f"{PREFIXO_NAO_IDENTIFICADO}{c.id}",
                "nome": NOME_NAO_IDENTIFICADO,
                "origem": "revisao",
                **{lista: [] for lista in LISTAS},
                o.lista: [ocorrencia],
            }
        )
    elif c.tipo == "pessoa.aparicao_para_mencao":
        mencao = {"inicio_ms": ocorrencia["inicio_ms"], "fim_ms": ocorrencia["fim_ms"]}
        if c.depois == "citada_no_texto":
            mencao["texto"] = ocorrencia["evidencia"]
        pessoa[c.depois].append(mencao)
        _por_inicio(pessoa[c.depois])
    else:
        pessoa["na_imagem"].append(
            {
                "inicio_ms": ocorrencia["inicio_ms"],
                "fim_ms": ocorrencia["fim_ms"],
                "evidencia": c.depois,
            }
        )
        _por_inicio(pessoa["na_imagem"])


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
    comerciais = [c for c in resultado.get("comerciais", []) if isinstance(c, dict)]
    for n, comercial in enumerate(comerciais):
        comercial["id"] = f"com{n:03d}"
    falas = []
    for n, fala in enumerate(resultado.get("transcricao", [])):
        if isinstance(fala, dict):
            fala["id"] = f"fal{n:03d}"
            falas.append(fala)
    textos = []
    for n, texto in enumerate(resultado.get("textos_na_tela", [])):
        if isinstance(texto, dict):
            texto["id"] = f"txt{n:03d}"
            textos.append(texto)
    for item in [
        *pessoas,
        *_pautas(resultado),
        *comerciais,
        *_planos(resultado),
        *falas,
        *textos,
    ]:
        item["origem"] = "modelo"
    # Casa pela identidade do modelo, calculada antes de qualquer renomeação.
    identidades = [identidade_da_pessoa(p) for p in pessoas]
    nomes_do_modelo = [p["nome"] for p in pessoas]
    desfeitas = _desfeitas(correcoes) | _fora_da_entrega(correcoes)
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
        if c.id in desfeitas:
            continue
        if c.tipo == "comercial.acrescentar":
            if c.id not in atendidas:
                _acrescentar_comercial(resultado, c)
            continue
        if c.tipo == ACRESCENTAR_TEXTO:
            if c.id not in atendidas:
                _acrescentar_texto_na_tela(resultado, c)
            continue
        if _pessoa_acrescentada(c):
            if c.id not in atendidas:
                _acrescentar_pessoa(resultado, c)
            continue
        if c.ancora.tipo_do_item != "pessoa":
            if c.id not in atendidas:
                _aplicar_no_item(resultado, c)
            continue
        for pessoa, identidade, nome in zip(
            pessoas, identidades, nomes_do_modelo, strict=True
        ):
            if not casa(c, pessoa, identidade):
                continue
            if c.tipo == "pessoa.fontes_do_nome":
                if c.id not in atendidas:
                    pessoa["fontes_do_nome"] = json.loads(c.depois)
                    pessoa["origem"] = "revisao"
            elif c.tipo != "pessoa.renomear":
                if c.id not in atendidas:
                    _aplicar_na_pessoa(resultado, pessoa, c)
                    if c.tipo == "pessoa.nao_e":
                        esvaziadas.append(pessoa)
            elif c.id in atendidas:
                pessoa["nome"], pessoa["origem"] = nome, "modelo"
            else:
                pessoa["nome"], pessoa["origem"] = c.depois, "revisao"
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
        ocorrencia=alvo.ocorrencia,
        antes=valor_atual(
            modelo,
            versao,
            correcoes,
            alvo.tipo,
            item_id,
            tipo_do_item,
            alvo.ocorrencia,
            alvo.depois,
        ),
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
        ocorrencia=alvo.ocorrencia,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
        **registro,
    )


class NaoPendente(Exception):
    """A correção não espera decisão: não exige aprovação ou já foi decidida."""


def id_da_decisao(alvo_id: str) -> str:
    """Fixo por alvo: aprovar e recusar simultâneos colidem no repositório."""
    return f"{alvo_id}-decidida"


def montar_decisao(
    alvo: Correcao,
    correcoes: list[Correcao],
    aprovada: bool,
    motivo: str = "",
    **registro: Any,
) -> Correcao:
    """O registro em que um Curador aprova (autor e data, os do registro) ou
    recusa `alvo`, que tem de estar pendente. A recusa traz o motivo."""
    if not alvo.exige_aprovacao or alvo.id in _decididas(correcoes):
        raise NaoPendente(alvo.id)
    return Correcao(
        tipo="aprovar" if aprovada else "recusar",
        aprova=alvo.id if aprovada else None,
        recusa=None if aprovada else alvo.id,
        item_id=alvo.item_id,
        ocorrencia=alvo.ocorrencia,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
        **registro,
    )
