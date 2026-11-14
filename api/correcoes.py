"""Correções (E3): registros à parte, que nunca alteram o JSON do modelo.

Cada correção guarda o antes e o depois e uma âncora que permite casar o item
com o JSON do modelo depois. A decupagem entregue é o JSON do modelo com as
correções aplicadas por cima, em memória.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Sequence
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

from api import catalogo_de_correcoes as textos
from api.comparador import normalizar
from api.decupagem import (
    CategoriaDeObjeto,
    Comercial,
    CorBase,
    EvidenciaDoComercial,
    FonteDoNome,
    Id,
    RelacaoDoObjeto,
    TextoNaTela,
    TomDaPauta,
)
from api.identidade import (
    identidade_do_comercial as _identidade_do_comercial,
)
from api.identidade import identidade_do_nome, nao_identificado
from api.pessoas import LISTAS
from api.texto_como_dado import ID_SEGURO, Linha, Texto

TipoNovo = Literal[
    "pessoa.renomear",
    "pauta.titulo",
    "pauta.resumo",
    "item.tempos",
    "comercial.marca",
    "comercial.tipo",
    "comercial.acrescentar",
    "pessoa.nao_e",
    "pessoa.separar",
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
    "pauta.acrescentar",
    "pauta.juntar",
    "pauta.dividir",
    "objeto.atributos",
    "objeto.dono",
    "objeto.nao_existe",
    "objeto.acrescentar",
]
TipoDeCorrecao = Literal[TipoNovo, "desfazer", "descartar", "aprovar", "recusar"]
TipoDoItem = Literal[
    "pessoa", "pauta", "comercial", "plano", "fala", "texto_na_tela", "objeto"
]
CORRIGIVEIS = get_args(TipoNovo)
Lista = Literal["na_imagem", "citada_na_fala", "citada_no_texto"]
MENCOES = ("citada_na_fala", "citada_no_texto")
# Prefixo do id da pessoa ou do comercial que a revisão cria.
PREFIXO_ACRESCENTADO = "acr-"
PREFIXO_NAO_IDENTIFICADO = "nid-"
PREFIXO_SEPARADA = "sep-"  # a pessoa que a separação devolve (#547)
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
    # No `pessoa.renomear` e no `comercial.marca` cujo nome é de uma pessoa ou marca do
    # catálogo, escolhida pela revisora (`NovaCorrecao.catalogo_id`) ou, na pessoa, a
    # única que casa com o nome.
    catalogo_id: str | None = None
    antes: str
    depois: str
    ancora: Ancora


Motivo = Annotated[
    str,
    Texto(LIMITE_DO_MOTIVO, min_length=1, strip=True),
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


EstadoNaBusca = Literal["salva", "indexando", "na_busca"]


class ItemDoHistorico(Correcao):
    estado: EstadoNoHistorico
    antes_legivel: str
    depois_legivel: str
    # Onde a correção está no índice da busca; `historico` não sabe, quem lê o Job preenche.
    na_busca: EstadoNaBusca = "salva"


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


_Rotulo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME),
]


class _AtributosDoObjeto(BaseModel):
    """O valor de um `objeto.atributos`: tipo, cores base, tom, detalhe e marca."""

    model_config = ConfigDict(extra="forbid")

    tipo: _Rotulo
    cor_base: list[CorBase] = Field(max_length=2)
    cor: _Rotulo | None = None
    detalhe: _Rotulo | None = None
    marca: _Rotulo | None = None

    @field_validator("tipo", "cor", "detalhe", "marca")
    @classmethod
    def _sem_controle_nos_rotulos(cls, valor: str | None) -> str | None:
        return None if valor is None else _sem_controle(valor)

    @field_validator("cor_base")
    @classmethod
    def _sem_repetir(cls, valor: list[str]) -> list[str]:
        if len(set(valor)) != len(valor):
            raise ValueError("cor base repetida")
        return valor


class NovoObjeto(_AtributosDoObjeto):
    """O objeto de um `objeto.acrescentar`: categoria, atributos, dono e trecho."""

    categoria: CategoriaDeObjeto
    pessoa: Id | None = None
    relacao: RelacaoDoObjeto | None = None
    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if (self.pessoa is None) != (self.relacao is None):
            raise ValueError("pessoa e relação vêm juntas ou nenhuma das duas")
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


class _DonoDoObjeto(BaseModel):
    """O valor de um `objeto.dono`: a pessoa e a relação, os dois ou nenhum (sem dono)."""

    model_config = ConfigDict(extra="forbid")

    pessoa: Id | None
    relacao: RelacaoDoObjeto | None

    @model_validator(mode="after")
    def _os_dois_ou_nenhum(self) -> Self:
        if (self.pessoa is None) != (self.relacao is None):
            raise ValueError("pessoa e relação vêm juntas ou nenhuma das duas")
        return self


class NovoTextoAcrescentado(NovoTextoNaTela):
    """O texto na tela de um `texto_na_tela.acrescentar`: tempos, tipo e texto."""

    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


class NovaPauta(BaseModel):
    """A pauta de um `pauta.acrescentar`: título, resumo opcional, tom e tempos."""

    model_config = ConfigDict(extra="forbid")

    titulo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
        ),
    ]
    resumo: (
        Annotated[
            str,
            StringConstraints(
                strip_whitespace=True, min_length=1, max_length=LIMITE_DO_TEXTO
            ),
        ]
        | None
    ) = None
    tom: TomDaPauta
    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, valor: str) -> str:
        return _sem_controle(valor)

    @field_validator("resumo")
    @classmethod
    def _resumo(cls, valor: str | None) -> str | None:
        return None if valor is None else _sem_controle_salvo_quebra(valor)

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


class NovaJuncao(BaseModel):
    """O valor de um `pauta.juntar`: os ids das pautas seguidas e o título escolhido."""

    model_config = ConfigDict(extra="forbid")

    ids: Annotated[
        list[Annotated[str, StringConstraints(max_length=40)]], Field(min_length=2)
    ]
    titulo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
        ),
    ]

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, valor: str) -> str:
        return _sem_controle(valor)

    @model_validator(mode="after")
    def _sem_repetir(self) -> Self:
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("pauta repetida")
        return self


class NovaDivisao(BaseModel):
    """O valor de um `pauta.dividir`: o tempo do corte e o título de cada metade."""

    model_config = ConfigDict(extra="forbid")

    em_ms: Annotated[int, Field(gt=0)]
    titulos: Annotated[
        list[
            Annotated[
                str,
                StringConstraints(
                    strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
                ),
            ]
        ],
        Field(min_length=2, max_length=2),
    ]

    @field_validator("titulos")
    @classmethod
    def _titulos(cls, valor: list[str]) -> list[str]:
        for titulo in valor:
            _sem_controle(titulo)
        return valor


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
    # O id da pessoa ou da marca do catálogo que o nome novo é (`pessoa.renomear` e
    # `comercial.marca`); o servidor confere que existe e que o nome é o dela.
    catalogo_id: Annotated[str, Linha(64, min_length=1), ID_SEGURO] | None = None
    # Vazio só no `comercial.acrescentar` e na aparição de pessoa nova.
    item_id: Annotated[str, Linha(40)] = ""
    # `item.tempos`: "<inicio_ms>-<fim_ms>"; `comercial.tipo`: um tipo do
    # esquema; `comercial.acrescentar`: o JSON do comercial; `pessoa.nao_e`:
    # "Não identificado"; `pessoa.aparicao_para_mencao`: a lista de destino;
    # `pessoa.mencao_para_aparicao`: a evidência; `pessoa.acrescentar_aparicao`:
    # o JSON da aparição; `plano.descricao`: o JSON {ambiente, acao, objetos};
    # `plano.limpo`: "true" ou "false"; `fala.texto`: o JSON {texto, locutor};
    # `pauta.tom`: o tom; `pessoa.fontes_do_nome`: a lista JSON das fontes;
    # `aparicao.papel_visual`: o JSON {papel, visual}; `texto_na_tela.texto`: o
    # JSON {tipo, texto}; `texto_na_tela.acrescentar`: o JSON {inicio_ms,
    # fim_ms, tipo, texto}; `pauta.acrescentar`: o JSON {titulo, resumo?, tom,
    # inicio_ms, fim_ms}; `pauta.juntar`: o JSON {ids, titulo}, com o `item_id` da
    # primeira; `pauta.dividir`: o JSON {em_ms, titulos: [primeira, segunda]}.
    valor: Annotated[str, Texto(LIMITE_DO_JSON, min_length=1, strip=True)]
    motivo: Motivo
    versao: Annotated[str, Linha(64, min_length=1)]

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
        if self.catalogo_id is not None and entrada.catalogo_de is None:
            raise ValueError("catalogo_id vale só no nome de pessoa ou de marca")
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

    item_id: Annotated[str, Linha(40, min_length=1)]


class RepositorioDeAprovacao(Protocol):
    """Porta para o documento do Firestore com os tipos que exigem aprovação."""

    def tipos(self) -> frozenset[str]:
        """Vazio por padrão: nada exige aprovação."""
        ...

    def definir(self, tipos: frozenset[str]) -> None: ...

    def mudar(self, tipo: str, exige_aprovacao: bool) -> None:
        """Liga ou desliga um tipo só, sem regravar os outros: duas mudanças ao
        mesmo tempo em tipos diferentes não se apagam."""
        ...


class RepositorioDeAprovacaoEmMemoria:
    def __init__(self, tipos: frozenset[str] = frozenset()) -> None:
        self._tipos = tipos

    def tipos(self) -> frozenset[str]:
        return self._tipos

    def definir(self, tipos: frozenset[str]) -> None:
        self._tipos = tipos

    def mudar(self, tipo: str, exige_aprovacao: bool) -> None:
        self._tipos = self._tipos | {tipo} if exige_aprovacao else self._tipos - {tipo}


class ItemInexistente(Exception):
    """O item da correção não existe no JSON do modelo."""


class EstruturaInvalida(Exception):
    """Juntar ou dividir pautas que a decupagem entregue não permite: pautas que não
    são seguidas, ou um corte fora da pauta."""


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

    def jobs_com_correcao(
        self, desde: datetime | None = None, ate: datetime | None = None
    ) -> set[str]:
        """Os `job_id` com alguma correção criada em `[desde, ate)`; sem limite, de
        qualquer data. Sem ler as correções de vídeo nenhum além do necessário."""
        ...

    def purgar(self, job_id: str) -> None:
        """Apaga todas as correções do vídeo. Único caminho que apaga, e só a purga
        (`api.purga`, ADR 0010) o chama."""
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

    def jobs_com_correcao(
        self, desde: datetime | None = None, ate: datetime | None = None
    ) -> set[str]:
        return {
            c.job_id
            for c in self._correcoes
            if (desde is None or c.criada_em >= desde)
            and (ate is None or c.criada_em < ate)
        }

    def purgar(self, job_id: str) -> None:
        self._correcoes = [c for c in self._correcoes if c.job_id != job_id]


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


def _ids_das_pessoas(modelo: dict[str, Any]) -> set[Any]:
    return {p.get("id") for p in _pessoas(modelo)}


def _pautas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("pautas", []) if isinstance(p, dict)]


def _objetos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in modelo.get("objetos", []) if isinstance(o, dict)]


def _intervalo_da_pauta(pauta: dict[str, Any]) -> tuple[int, int]:
    """Pauta, comercial, plano e fala: o item tem o próprio intervalo."""
    return int(pauta["inicio_ms"]), int(pauta["fim_ms"])


def _intervalo_do_objeto(objeto: dict[str, Any]) -> tuple[int, int]:
    """Do menor início ao maior fim das ocorrências: o objeto não tem intervalo próprio."""
    ocorrencias = objeto["ocorrencias"]
    return (
        min(o["inicio_ms"] for o in ocorrencias),
        max(o["fim_ms"] for o in ocorrencias),
    )


def identidade_do_comercial(comercial: dict[str, Any]) -> str:
    """Marca normalizada e tipo, como a emenda da consolidação (#45)."""
    return _identidade_do_comercial(str(comercial["marca"]), str(comercial["tipo"]))


def _intervalo_do_item(item: dict[str, Any], tipo_do_item: str) -> tuple[int, int]:
    if tipo_do_item == "pessoa":
        return _intervalo_da_pessoa(item)
    if tipo_do_item == "objeto":
        return _intervalo_do_objeto(item)
    return _intervalo_da_pauta(item)


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


class TemposInvalidos(Exception):
    """Os tempos passam da duração do vídeo."""


@dataclass(frozen=True)
class Autoria:
    """Quem fez o registro e quando: a rota entrega, o módulo monta o registro."""

    uid: str
    email: str
    em: datetime


class VersaoDesatualizada(Exception):
    """O pedido é sobre uma versão do JSON do modelo que não é mais a atual."""


class CorrecaoInexistente(Exception):
    """Nenhuma correção do Job tem o id pedido."""


class CatalogoIdInvalido(Exception):
    """O `catalogo_id` não existe no catálogo ou é de outro nome."""


def _ancora_do_item(
    item: dict[str, Any], tipo_do_item: TipoDoItem, versao: str
) -> Ancora:
    if tipo_do_item == "pessoa":
        return _ancora_da_pessoa(item, versao)
    inicio, fim = _intervalo_do_item(item, tipo_do_item)
    # Plano e fala se casam pelo intervalo: a identidade é só o tipo.
    if tipo_do_item == "comercial":
        identidade = identidade_do_comercial(item)
    elif tipo_do_item in ("plano", "fala"):
        identidade = tipo_do_item
    elif tipo_do_item == "texto_na_tela":
        identidade = normalizar(str(item["texto"]))
    elif tipo_do_item == "objeto":
        identidade = normalizar(str(item["tipo"]))
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


def _ja_traz_o_valor(c: Correcao, item: dict[str, Any]) -> bool:
    return _valor_do_item(item, c.tipo) == c.depois


_CHAVE_DO_ITEM = {
    "pauta": "pautas",
    "comercial": "comerciais",
    "plano": "planos",
    "fala": "transcricao",
    "texto_na_tela": "textos_na_tela",
    "objeto": "objetos",
}


def _itens_com_o_id(resultado: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    chave = _CHAVE_DO_ITEM[c.ancora.tipo_do_item]
    return [
        item
        for item in resultado.get(chave, [])
        if isinstance(item, dict) and item.get("id") == c.item_id
    ]


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
    novo_id = f"{PREFIXO_NAO_IDENTIFICADO}{c.id}"
    if o.lista == "na_imagem":
        _leva_os_objetos(resultado, pessoa, ocorrencia, novo_id)
    resultado.setdefault("pessoas", []).append(
        {
            "id": novo_id,
            "nome": NOME_NAO_IDENTIFICADO,
            "origem": "revisao",
            **{lista: [] for lista in LISTAS},
            o.lista: [ocorrencia],
        }
    )


def _chaves_das_origens(pessoa: dict[str, Any]) -> str:
    """As origens da junção (`antes` da separação): o resto fica em `pares_proibidos`."""
    return json.dumps(
        [o["chave"] for o in pessoa.get("origens", [])], ensure_ascii=False
    )


def _separar(resultado: dict[str, Any], pessoa: dict[str, Any], c: Correcao) -> None:
    """Devolve a origem `c.depois` da pessoa juntada: as aparições, a citação nas
    pautas e o dono dos objetos que eram dela (guardados na junção). As menções
    ficam com a base (a junção não as guardou por origem)."""
    origens = pessoa.get("origens", [])
    origem = next((o for o in origens if o["chave"] == c.depois), None)
    if origem is None or len(origens) < 2:
        return
    novo_id = f"{PREFIXO_SEPARADA}{c.id}"
    for aparicao in origem["na_imagem"]:
        if aparicao in pessoa["na_imagem"]:
            pessoa["na_imagem"].remove(aparicao)
    restantes = [o for o in origens if o is not origem]
    pessoa["origens"] = restantes if len(restantes) > 1 else []
    resultado.setdefault("pessoas", []).append(
        {
            "id": novo_id,
            "nome": origem["nome"],
            "origem": "revisao",
            "janela": origem.get("janela"),
            "origens": [],
            **{lista: [] for lista in LISTAS},
            "na_imagem": list(origem["na_imagem"]),
        }
    )
    ainda = {i for o in restantes for i in o["pautas"]}
    for pauta in _pautas(resultado):
        if pauta.get("id") in origem["pautas"]:
            ids = [
                i
                for i in pauta.get("pessoas", [])
                if i != pessoa["id"] or pauta["id"] in ainda
            ]
            pauta["pessoas"] = list(dict.fromkeys([*ids, novo_id]))
    for objeto in _objetos(resultado):
        if (
            objeto.get("id") in origem["objetos"]
            and objeto.get("pessoa") == pessoa["id"]
        ):
            objeto["pessoa"] = novo_id
    resultado.setdefault("_separadas", []).append((pessoa["id"], novo_id))


def _origem_ja_separada(c: Correcao, item: dict[str, Any]) -> bool:
    return not any(o["chave"] == c.depois for o in item.get("origens", []))


def _confere_a_origem(decupagem: dict[str, Any], valor: str) -> None:
    if not any(
        o["chave"] == valor for p in _pessoas(decupagem) for o in p.get("origens", [])
    ):
        raise ItemInexistente(valor)


def _leva_os_objetos(
    resultado: dict[str, Any],
    pessoa: dict[str, Any],
    aparicao: dict[str, Any],
    novo_id: str,
) -> None:
    """O objeto da pessoa visto só na aparição trocada passa à pessoa nova; o
    visto também noutra aparição dela fica com ela."""
    trocada = _intervalo_da_pauta(aparicao)
    restantes = [_intervalo_da_pauta(a) for a in pessoa["na_imagem"]]
    for objeto in _objetos(resultado):
        if objeto.get("pessoa") != pessoa.get("id"):
            continue
        tempos = [_intervalo_da_pauta(t) for t in objeto.get("ocorrencias", [])]
        if (
            tempos
            and all(_sobrepoe(t, trocada) for t in tempos)
            and not any(_sobrepoe_de_verdade(t, r) for t in tempos for r in restantes)
        ):
            objeto["pessoa"] = novo_id


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


class NaoNaFila(Exception):
    """A correção não está na fila de revisão (casou, saiu da fila ou é de outro tipo)."""


class NaoCandidato(Exception):
    """O item escolhido para reaplicar não é candidato do item da fila."""


class NaoPendente(Exception):
    """A correção não espera decisão: não exige aprovação ou já foi decidida."""


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
class Reestrutura:
    """O que só os tipos que mexem no conjunto de pautas (juntar, dividir) sabem fazer."""

    # Do pedido e da decupagem entregue: o valor guardado e a âncora; `ItemInexistente`
    # ou `EstruturaInvalida` se o pedido não cabe nela.
    preparar: Callable[[dict[str, Any], NovaCorrecao, str], tuple[str, Ancora]]
    aplicar: Callable[[dict[str, Any], Correcao], None]
    # A correção apontada para as pautas do JSON novo e se o modelo já traz o resultado;
    # `None` se não há pauta correspondente.
    reapontar: Callable[[dict[str, Any], Correcao, str], tuple[Correcao, bool] | None]


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
    # No item cujo modelo já traz o "depois": o que fazer, se algo.
    atender_no_item: Callable[[dict[str, Any], Correcao], None] | None = None
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
    # O catálogo cujo id a correção pode trazer (`NovaCorrecao.catalogo_id`).
    catalogo_de: Literal["pessoas", "marcas"] | None = None
    casa_longe: bool = False
    acrescenta: Acrescenta | None = None
    reestrutura: Reestrutura | None = None
    # Confere o valor do pedido (já canonizado) com a decupagem entregue; levanta
    # `ItemInexistente` se ele aponta para o que ela não tem. Também decide se a
    # correção se reaplica.
    confere: Callable[[dict[str, Any], str], None] | None = None


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


def _canonizar_atributos_do_objeto(n: NovaCorrecao) -> str:
    return _json_canonico(_AtributosDoObjeto.model_validate_json(n.valor).model_dump())


def _canonizar_objeto_acrescentado(n: NovaCorrecao) -> str:
    return _json_canonico(NovoObjeto.model_validate_json(n.valor).model_dump())


def _canonizar_dono_do_objeto(n: NovaCorrecao) -> str:
    return _json_canonico(_DonoDoObjeto.model_validate_json(n.valor).model_dump())


def _canonizar_texto_acrescentado(n: NovaCorrecao) -> str:
    return _json_canonico(
        NovoTextoAcrescentado.model_validate_json(n.valor).model_dump()
    )


def _canonizar_pauta_acrescentada(n: NovaCorrecao) -> str:
    return _json_canonico(NovaPauta.model_validate_json(n.valor).model_dump())


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


def _canonizar_separar(n: NovaCorrecao) -> str:
    return _sem_controle(n.valor)


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


def _valor_do_objeto(item: dict[str, Any]) -> str:
    return _json_canonico(
        {
            "tipo": item["tipo"],
            "cor_base": item["cor_base"],
            "cor": item.get("cor"),
            "detalhe": item.get("detalhe"),
            "marca": item.get("marca"),
        }
    )


def _valor_do_dono(item: dict[str, Any]) -> str:
    return _json_canonico(
        {"pessoa": item.get("pessoa"), "relacao": item.get("relacao")}
    )


def _confere_o_dono(entregue: dict[str, Any], valor: str) -> None:
    pessoa = json.loads(valor)["pessoa"]
    if pessoa is not None and pessoa not in _ids_das_pessoas(entregue):
        raise ItemInexistente(pessoa)


def _valor_do_existe(item: dict[str, Any]) -> str:
    return "existe"


def _canonizar_nao_existe(n: NovaCorrecao) -> str:
    if n.valor != "nao_existe":
        raise ValueError("o valor de objeto.nao_existe é nao_existe")
    return n.valor


def _marca_o_objeto_removido(item: dict[str, Any], c: Correcao) -> None:
    item["_removido"] = True


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
    # Pelo id, não pela posição: junção e `nao_e` tiram pessoas só da lista entregue.
    # A pessoa absorvida já não está nela (item inexistente, 422).
    for original in _pessoas(modelo):
        if identidade_da_pessoa(original) == alvo.ancora.identidade:
            for pessoa in _pessoas(entregue):
                if pessoa.get("id") == original.get("id"):
                    return str(pessoa["nome"])
            break
    raise ItemInexistente(alvo.ancora.identidade)


def _fim_dos_tempos(valor: str) -> int:
    return tempos_de(valor)[1]


def _fim_do_json(valor: str) -> int:
    return int(json.loads(valor)["fim_ms"])


def _traz_textos(entregue: dict[str, Any]) -> bool:
    return "textos_na_tela" in entregue


def _traz_objetos(entregue: dict[str, Any]) -> bool:
    return "objetos" in entregue


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


def _marca_no_comercial(item: dict[str, Any], c: Correcao) -> None:
    item["marca"] = c.depois
    _catalogo_id_no_comercial(item, c)


def _catalogo_id_no_comercial(item: dict[str, Any], c: Correcao) -> None:
    # A marca nova vale por inteiro: o id da marca anterior não fica. O modelo que já
    # escreve a marca não conhece o id, que vem da correção.
    if c.catalogo_id is None:
        item.pop("catalogo_id", None)
    else:
        item["catalogo_id"] = c.catalogo_id


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
    anterior = identidade_do_nome(str(pessoa["nome"]))
    pessoa["nome"], pessoa["origem"] = c.depois, "revisao"
    # A fala não aponta para a pessoa: o locutor acompanha o nome que ela tinha
    # agora (não o `c.antes`), para a segunda troca achar o que a primeira deixou.
    # "Não identificado" é de várias pessoas, então não leva nada.
    if anterior is not None:
        for fala in resultado.get("transcricao", []):
            if (
                isinstance(fala, dict)
                and identidade_do_nome(str(fala.get("locutor", ""))) == anterior
            ):
                fala["locutor"] = c.depois
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


def _identidades_do_objeto(c: Correcao) -> set[str]:
    return {c.ancora.identidade, normalizar(json.loads(c.depois)["tipo"])}


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


def _acrescentar_pauta(resultado: dict[str, Any], c: Correcao) -> None:
    pauta = json.loads(c.depois)
    resultado.setdefault("pautas", []).append(
        {
            **pauta,
            "resumo": pauta.get("resumo") or "",
            "id": c.item_id,
            "origem": "revisao",
            "acrescentado": True,
        }
    )


def _acrescentar_objeto(resultado: dict[str, Any], c: Correcao) -> None:
    novo = json.loads(c.depois)
    inicio, fim = novo.pop("inicio_ms"), novo.pop("fim_ms")
    resultado.setdefault("objetos", []).append(
        {
            **novo,
            "id": c.item_id,
            "ocorrencias": [{"inicio_ms": inicio, "fim_ms": fim}],
            "origem": "revisao",
            "acrescentado": True,
        }
    )


def _ancora_do_objeto_novo(valor: str, item_id: str, versao: str) -> Ancora:
    novo = json.loads(valor)
    item = {
        "tipo": novo["tipo"],
        "ocorrencias": [{"inicio_ms": novo["inicio_ms"], "fim_ms": novo["fim_ms"]}],
    }
    return _ancora_do_item(item, "objeto", versao)


def _do_mesmo_tipo_de_objeto(
    c: Correcao, candidatos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    tipo = normalizar(json.loads(c.depois)["tipo"])
    return [i for i in candidatos if normalizar(str(i["tipo"])) == tipo]


def _tempos_do_objeto(item: dict[str, Any]) -> str:
    inicio, fim = _intervalo_do_objeto(item)
    return f"{inicio}-{fim}"


def _ancora_do_comercial_novo(valor: str, item_id: str, versao: str) -> Ancora:
    return _ancora_do_item(json.loads(valor), "comercial", versao)


def _ancora_do_texto_novo(valor: str, item_id: str, versao: str) -> Ancora:
    return _ancora_do_item(json.loads(valor), "texto_na_tela", versao)


def _ancora_da_pauta_nova(valor: str, item_id: str, versao: str) -> Ancora:
    return _ancora_do_item(json.loads(valor), "pauta", versao)


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


def _com_o_mesmo_titulo(
    c: Correcao, candidatos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    titulo = normalizar(json.loads(c.depois)["titulo"])
    return [i for i in candidatos if normalizar(str(i["titulo"])) == titulo]


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
_PAUTA_NOVA = Acrescenta(
    ancora=_ancora_da_pauta_nova,
    acrescenta=lambda c: True,
    atendentes=_com_o_mesmo_titulo,
    aplicar=_acrescentar_pauta,
)
_OBJETO_NOVO = Acrescenta(
    ancora=_ancora_do_objeto_novo,
    acrescenta=lambda c: True,
    atendentes=_do_mesmo_tipo_de_objeto,
    aplicar=_acrescentar_objeto,
)
_PESSOA_NOVA = Acrescenta(
    ancora=_ancora_da_pessoa_nova,
    acrescenta=_pessoa_nova,
    atendentes=_com_a_aparicao,
    aplicar=_acrescentar_pessoa,
)


def _titulo_e_tempos(item: dict[str, Any]) -> str:
    return _json_canonico(
        {
            "titulo": item["titulo"],
            "inicio_ms": item["inicio_ms"],
            "fim_ms": item["fim_ms"],
        }
    )


def _canonizar_juncao(n: NovaCorrecao) -> str:
    juncao = NovaJuncao.model_validate_json(n.valor)
    if n.item_id != juncao.ids[0]:
        raise ValueError("item_id é o da primeira pauta")
    return _json_canonico(juncao.model_dump())


def _canonizar_divisao(n: NovaCorrecao) -> str:
    return _json_canonico(NovaDivisao.model_validate_json(n.valor).model_dump())


def _pautas_em_ordem(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(_pautas(modelo), key=lambda p: (p["inicio_ms"], p["fim_ms"]))


def _preparar_juncao(
    entregue: dict[str, Any], novo: NovaCorrecao, versao: str
) -> tuple[str, Ancora]:
    juncao = NovaJuncao.model_validate_json(novo.valor)
    pautas = _pautas_em_ordem(entregue)
    ids = [p.get("id") for p in pautas]
    if any(i not in ids for i in juncao.ids):
        raise ItemInexistente(" ".join(juncao.ids))
    primeira = ids.index(juncao.ids[0])
    if ids[primeira : primeira + len(juncao.ids)] != juncao.ids:
        raise EstruturaInvalida("as pautas não são seguidas")
    juntas = pautas[primeira : primeira + len(juncao.ids)]
    inicio, fim = juntas[0]["inicio_ms"], max(p["fim_ms"] for p in juntas)
    depois = _json_canonico(
        {"titulo": juncao.titulo, "inicio_ms": inicio, "fim_ms": fim}
    )
    ancora = Ancora(
        versao=versao,
        tipo_do_item="pauta",
        identidade=normalizar(str(juntas[0]["titulo"])),
        inicio_ms=inicio,
        fim_ms=fim,
    )
    return depois, ancora


def _aplicar_juncao(resultado: dict[str, Any], c: Correcao) -> None:
    """Junta as pautas que estão no intervalo da âncora na primeira delas (a que
    mantém o id), com o título escolhido; a mesma regra de sobreposição serve à
    versão em que a correção foi feita e à reaplicação. Com uma pauta só (o modelo
    já juntou, com outro título), só o título muda."""
    intervalo = (c.ancora.inicio_ms, c.ancora.fim_ms)
    juntas = [
        p
        for p in _pautas_em_ordem(resultado)
        if _sobrepoe_metade(intervalo, _intervalo_da_pauta(p))
    ]
    if not juntas:
        return
    primeira, *outras = juntas
    primeira["titulo"] = json.loads(c.depois)["titulo"]
    primeira["inicio_ms"] = min(p["inicio_ms"] for p in juntas)
    primeira["fim_ms"] = max(p["fim_ms"] for p in juntas)
    primeira["resumo"] = "\n".join(p["resumo"] for p in juntas if p.get("resumo"))
    for campo in ("pessoas", "locais"):
        if campo in primeira:
            reunidos = [x for p in juntas for x in p.get(campo, [])]
            primeira[campo] = list(dict.fromkeys(reunidos))
    primeira["origem"] = "revisao"
    resultado["pautas"] = [
        p for p in resultado["pautas"] if not any(p is o for o in outras)
    ]


def _reapontar_juncao(
    modelo: dict[str, Any], c: Correcao, versao: str
) -> tuple[Correcao, bool] | None:
    intervalo = (c.ancora.inicio_ms, c.ancora.fim_ms)
    achadas = [
        p
        for p in _pautas_em_ordem(modelo)
        if _sobrepoe_metade(intervalo, _intervalo_da_pauta(p))
    ]
    if not achadas:
        return None
    if len(achadas) == 1:
        # Uma pauta só: o modelo já a trouxe junta se ela cobre ao menos metade do trecho.
        inicio, fim = _intervalo_da_pauta(achadas[0])
        sobreposicao = min(fim, intervalo[1]) - max(inicio, intervalo[0])
        if sobreposicao * 2 <= intervalo[1] - intervalo[0]:
            return None
    inicio = achadas[0]["inicio_ms"]
    fim = max(p["fim_ms"] for p in achadas)
    ancora = Ancora(
        versao=versao,
        tipo_do_item="pauta",
        identidade=normalizar(str(achadas[0]["titulo"])),
        inicio_ms=inicio,
        fim_ms=fim,
    )
    titulo = json.loads(c.depois)["titulo"]
    depois = _json_canonico({"titulo": titulo, "inicio_ms": inicio, "fim_ms": fim})
    nova = c.model_copy(
        update={
            "item_id": str(achadas[0].get("id", "")),
            "ancora": ancora,
            "depois": depois,
        }
    )
    # Atendida só se o modelo já juntou e com o mesmo título: senão o título se perde.
    atendida = len(achadas) == 1 and normalizar(achadas[0]["titulo"]) == normalizar(
        titulo
    )
    return nova, atendida


def _preparar_divisao(
    entregue: dict[str, Any], novo: NovaCorrecao, versao: str
) -> tuple[str, Ancora]:
    divisao = NovaDivisao.model_validate_json(novo.valor)
    item = next((p for p in _pautas(entregue) if p.get("id") == novo.item_id), None)
    if item is None:
        raise ItemInexistente(novo.item_id)
    if not item["inicio_ms"] < divisao.em_ms < item["fim_ms"]:
        raise EstruturaInvalida("o corte cai fora da pauta")
    return novo.valor, _ancora_do_item(item, "pauta", versao)


def _aplicar_divisao(resultado: dict[str, Any], c: Correcao) -> None:
    """Corta a pauta em duas; se o modelo já cortou ali (a pauta acaba no corte),
    só dá a cada metade o seu título."""
    divisao = json.loads(c.depois)
    em = divisao["em_ms"]
    for pauta in _itens_com_o_id(resultado, c):
        if abs(pauta["fim_ms"] - em) <= TOLERANCIA_DO_PLANO_MS:
            seguinte = next(
                (
                    p
                    for p in _pautas_em_ordem(resultado)
                    if p is not pauta
                    and abs(p["inicio_ms"] - em) <= TOLERANCIA_DO_PLANO_MS
                ),
                None,
            )
            if seguinte is not None:
                for metade, titulo in zip(
                    (pauta, seguinte), divisao["titulos"], strict=True
                ):
                    metade["titulo"], metade["origem"] = titulo, "revisao"
            continue
        if not pauta["inicio_ms"] < em < pauta["fim_ms"]:
            continue
        segunda = {
            **json.loads(json.dumps(pauta)),
            "id": f"{PREFIXO_ACRESCENTADO}{c.id}",
            "titulo": divisao["titulos"][1],
            "resumo": "",
            "inicio_ms": em,
            "origem": "revisao",
        }
        pauta["titulo"], pauta["fim_ms"] = divisao["titulos"][0], em
        pauta["origem"] = "revisao"
        resultado["pautas"].insert(resultado["pautas"].index(pauta) + 1, segunda)


def _reapontar_divisao(
    modelo: dict[str, Any], c: Correcao, versao: str
) -> tuple[Correcao, bool] | None:
    divisao = json.loads(c.depois)
    em = divisao["em_ms"]
    intervalo = (c.ancora.inicio_ms, c.ancora.fim_ms)
    achadas = [
        p
        for p in _pautas_em_ordem(modelo)
        if _sobrepoe_metade(intervalo, _intervalo_da_pauta(p))
    ]
    antes = [p for p in achadas if abs(p["fim_ms"] - em) <= TOLERANCIA_DO_PLANO_MS]
    depois = [p for p in achadas if abs(p["inicio_ms"] - em) <= TOLERANCIA_DO_PLANO_MS]
    com_o_corte = [p for p in achadas if p["inicio_ms"] < em < p["fim_ms"]]
    if antes and depois:
        # O modelo já cortou aqui; atendida só se os títulos também são os escolhidos.
        trazidos = [normalizar(p["titulo"]) for p in (antes[0], depois[0])]
        item = antes[0]
        atendida = trazidos == [normalizar(t) for t in divisao["titulos"]]
    elif len(com_o_corte) == 1:
        item, atendida = com_o_corte[0], False
    else:
        return None
    nova = c.model_copy(
        update={
            "item_id": str(item.get("id", "")),
            "ancora": _ancora_do_item(item, "pauta", versao),
        }
    )
    return nova, atendida


_JUNTAR = Reestrutura(
    preparar=_preparar_juncao, aplicar=_aplicar_juncao, reapontar=_reapontar_juncao
)
_DIVIDIR = Reestrutura(
    preparar=_preparar_divisao, aplicar=_aplicar_divisao, reapontar=_reapontar_divisao
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
        catalogo_de="pessoas",
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
        aplicar_no_item=_marca_no_comercial,
        atender_no_item=_catalogo_id_no_comercial,
        catalogo_de="marcas",
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
    "pessoa.separar": Tipo(
        canonizar=_canonizar_separar,
        rotulo="Separar pessoa",
        legivel=textos.separacao,
        tipo_do_item="pessoa",
        valor_do_item=_chaves_das_origens,
        aplicar_na_pessoa=_separar,
        ja_traz=_origem_ja_separada,
        confere=_confere_a_origem,
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
    "pauta.acrescentar": Tipo(
        canonizar=_canonizar_pauta_acrescentada,
        rotulo="Pauta acrescentada",
        legivel=textos.pauta_acrescentada,
        tipo_do_item="pauta",
        json_longo=True,
        valor_do_item=_tempos_do_item,
        fim_ms=_fim_do_json,
        acrescenta=_PAUTA_NOVA,
    ),
    "pauta.juntar": Tipo(
        canonizar=_canonizar_juncao,
        rotulo="Juntar pautas",
        legivel=textos.pauta_estrutural,
        tipo_do_item="pauta",
        json_longo=True,
        valor_do_item=_titulo_e_tempos,
        reestrutura=_JUNTAR,
    ),
    "pauta.dividir": Tipo(
        canonizar=_canonizar_divisao,
        rotulo="Dividir pauta",
        legivel=textos.pauta_estrutural,
        tipo_do_item="pauta",
        json_longo=True,
        valor_do_item=_titulo_e_tempos,
        reestrutura=_DIVIDIR,
    ),
    "objeto.atributos": Tipo(
        canonizar=_canonizar_atributos_do_objeto,
        rotulo="Atributos do objeto",
        legivel=textos.atributos_do_objeto,
        tipo_do_item="objeto",
        json_longo=True,
        valor_do_item=_valor_do_objeto,
        aplicar_no_item=_json_no_item,
        ja_traz=_ja_traz_o_valor,
        identidades=_identidades_do_objeto,
    ),
    "objeto.dono": Tipo(
        canonizar=_canonizar_dono_do_objeto,
        rotulo="Dono do objeto",
        legivel=textos.dono_do_objeto,
        tipo_do_item="objeto",
        json_longo=True,
        valor_do_item=_valor_do_dono,
        aplicar_no_item=_json_no_item,
        ja_traz=_ja_traz_o_valor,
        confere=_confere_o_dono,
    ),
    "objeto.nao_existe": Tipo(
        canonizar=_canonizar_nao_existe,
        rotulo="Objeto na imagem",
        legivel=textos.objeto_na_imagem,
        tipo_do_item="objeto",
        valor_do_item=_valor_do_existe,
        aplicar_no_item=_marca_o_objeto_removido,
    ),
    "objeto.acrescentar": Tipo(
        canonizar=_canonizar_objeto_acrescentado,
        rotulo="Objeto acrescentado",
        legivel=textos.objeto_acrescentado,
        tipo_do_item="objeto",
        json_longo=True,
        valor_do_item=_tempos_do_objeto,
        fim_ms=_fim_do_json,
        traz_o_campo=_traz_objetos,
        acrescenta=_OBJETO_NOVO,
        confere=_confere_o_dono,
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
