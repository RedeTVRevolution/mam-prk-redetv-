"""Esquema 1.3 da decupagem (aceita as anteriores: 1.2 continua válido).

Um modelo só: dele saem a saída estruturada pedida ao Gemini
(`esquema_do_modelo()`), a validação da resposta e o tipo do OpenAPI.

O modelo escreve os tempos em MM:SS (`inicio`/`fim`), o formato em que ele pensa;
`tempos_em_ms()` os converte nos `inicio_ms`/`fim_ms` guardados. Pedidos em ms,
os tempos saíam como 124 para 01:24 (clipe3).
"""

import re
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VersaoEsquema = Literal["1.2", "1.3"]
VERSAO_ESQUEMA: VersaoEsquema = "1.3"  # o mypy cobra se o tipo mudar sozinho

Texto = Annotated[str, Field(max_length=2000)]
Rotulo = Annotated[str, Field(max_length=200)]
Id = Annotated[str, Field(max_length=40)]

TomDaPauta = Literal[
    "informativo",
    "polemico",
    "descontraido",
    "exclusivo",
    "homenagem",
    "analise",
    "comercial",
]


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Intervalo(_Estrito):
    inicio_ms: int = Field(ge=0)
    fim_ms: int = Field(ge=0)
    # Tempos do modelo, guardados só quando a regra de tempos os mudou.
    inicio_modelo_ms: int | None = Field(default=None, ge=0)
    fim_modelo_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _inicio_antes_do_fim(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self

    @property
    def duracao_ms(self) -> int:
        return self.fim_ms - self.inicio_ms


class Video(_Estrito):
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    duracao_ms: int = Field(gt=0)
    fps: float | None = None
    timecode_origem: Rotulo | None = None


class Bloco(_Intervalo):
    titulo: Rotulo


class Programa(_Estrito):
    resumo: Texto
    blocos: list[Bloco]


class Pauta(_Intervalo):
    id: Id
    titulo: Rotulo
    resumo: Texto = Field(description="Resumo jornalístico fiel ao mostrado e dito.")
    pessoas: list[Id] = Field(default=[], description="Ids das pessoas envolvidas.")
    locais: list[Rotulo] = []
    tom: TomDaPauta | None = Field(
        default=None,
        description="Tom da pauta. `comercial` é a pauta que é ação comercial ou "
        "merchandising, não reportagem.",
    )


class Aparicao(_Intervalo):
    evidencia: Rotulo = Field(description="O que mostra que é essa pessoa.")
    papel: Rotulo | None = Field(
        default=None,
        description="Papel no trecho: apresentador, repórter, entrevistado, "
        "assunto da pauta ou flagrante.",
    )
    visual: Rotulo | None = Field(
        default=None,
        description="Visual de destaque, se relevante (ex.: vestido de gala vermelho).",
    )
    quadro: str | None = None  # vazio na E0


class MencaoNaFala(_Intervalo):
    pass


class MencaoNoTexto(_Intervalo):
    texto: Texto = Field(description="O texto na tela que cita a pessoa.")


# `contexto` não é prova (ADR 0005): as versões anteriores a gravaram, e o
# validador de `Pessoa` a descarta ao ler.
FonteDoNome = Literal["rosto", "gc", "fala", "referencia"]
FONTES_ANTIGAS = frozenset({"contexto"})
EstadoDoNome = Literal["confirmado", "palpite"]


class Pessoa(_Estrito):
    id: Id
    nome: Rotulo = Field(
        description='Nome próprio; "não identificado" com uma descrição curta '
        "quando não há segurança."
    )
    fontes_do_nome: list[FonteDoNome] = Field(
        default=[],
        description="O que sustenta o nome: rosto, GC ou tarja, fala, referência. "
        'Vazia para "não identificado".',
    )
    origem: Literal["modelo", "modelo_forte", "revisao"] = "modelo"
    # O servidor grava: `confirmado` com a prova conferida pelo código, `palpite`
    # sem ela. Vazio onde a identificação não rodou.
    estado_do_nome: EstadoDoNome | None = None
    # A pessoa do catálogo (#108); o servidor grava, o modelo não conhece.
    catalogo_id: Id | None = None
    na_imagem: list[Aparicao] = Field(
        description="Aparições: a pessoa visível na imagem. Foto num gráfico, logo "
        "ou QR code não é aparição."
    )
    citada_na_fala: list[MencaoNaFala] = Field(
        description="Nome dito na fala sem a pessoa aparecer."
    )
    citada_no_texto: list[MencaoNoTexto] = Field(
        description="Nome em texto na tela sem a pessoa aparecer."
    )

    @field_validator("fontes_do_nome", mode="before")
    @classmethod
    def _sem_fontes_antigas(cls, fontes: Any) -> Any:
        if isinstance(fontes, list):
            return [f for f in fontes if f not in FONTES_ANTIGAS]
        return fontes


CategoriaDeObjeto = Literal[
    "roupa", "calcado", "acessorio", "na_mao", "em_cena", "veiculo", "outro"
]
CorBase = Literal[
    "vermelho",
    "laranja",
    "amarelo",
    "verde",
    "azul",
    "roxo",
    "rosa",
    "marrom",
    "bege",
    "preto",
    "branco",
    "cinza",
    "dourado",
    "prateado",
    "estampado",
]
RelacaoDoObjeto = Literal["veste", "calca", "usa", "segura"]
# As listas fechadas num lugar só: o entendimento da consulta da busca as usa.
CATEGORIAS_DE_OBJETO = get_args(CategoriaDeObjeto)
CORES_BASE = get_args(CorBase)
RELACOES_DO_OBJETO = get_args(RelacaoDoObjeto)


class Objeto(_Estrito):
    id: Id
    categoria: CategoriaDeObjeto
    tipo: Rotulo = Field(
        description='Texto curto e no singular: "sandália", "vestido".'
    )
    cor_base: list[CorBase] = Field(
        max_length=2, description="Até 2 cores da lista: é o que a busca filtra."
    )
    cor: Rotulo | None = Field(
        default=None, description='O tom como você vê: "vinho", "azul-marinho".'
    )
    detalhe: Rotulo | None = None
    marca: Rotulo | None = Field(
        default=None, description="Só se o logo ou o nome estiver legível na imagem."
    )
    pessoa: Id | None = Field(
        default=None,
        description="Id de uma pessoa da lista `pessoas`; nulo para objeto em cena.",
    )
    relacao: RelacaoDoObjeto | None = Field(
        default=None,
        description="Como a pessoa se liga ao objeto; nulo sem `pessoa`.",
    )
    ocorrencias: list[_Intervalo] = Field(
        min_length=1, description="Intervalos em que o objeto está visível."
    )

    @model_validator(mode="after")
    def _dono_e_relacao_juntos(self) -> Self:
        if (self.pessoa is None) != (self.relacao is None):
            raise ValueError("`pessoa` e `relacao` vêm juntas ou nenhuma")
        return self


class Plano(_Intervalo):
    id: Id
    ambiente: Rotulo = Field(description="Local: estúdio, aeroporto, estádio, rua…")
    plano_limpo: bool = Field(
        description="Sem texto na tela e sem ninguém falando para a câmera."
    )
    objetos: list[Rotulo] = Field(
        default=[],
        description="Objetos de destaque: carro de luxo, joia, troféu, produto…",
    )
    acao: Texto | None = None
    enquadramento: Rotulo | None = None
    movimento_camera: Rotulo | None = None
    externa: bool | None = None
    periodo: Literal["dia", "noite"] | None = None


EvidenciaDoComercial = Literal["fala", "logo", "texto_na_tela", "produto"]


class Comercial(_Intervalo):
    marca: Rotulo
    tipo: Literal[
        "intervalo",
        "merchan_apresentador",
        "testemunhal",
        "produto_em_cena",
        "patrocinio_vinheta",
        "sobreposicao_grafica",
        "marca_incidental",
        "mencao_editorial",
    ] = Field(
        description="Banner, bug, QR code e chamada de site são "
        "sobreposicao_grafica; mencao_editorial é a marca citada sem ação comercial."
    )
    evidencias: list[EvidenciaDoComercial] = Field(
        min_length=1, description="O que mostra a ação comercial."
    )


class Fala(_Intervalo):
    locutor: Rotulo = Field(description="Quem fala: nome ou papel.")
    texto: Texto
    # O texto do Whisper, sem as correções do Gemini; só quando há transcrição.
    texto_original: Texto | None = None


class CorrecaoDaTranscricao(_Intervalo):
    """Uma palavra do Whisper que o Gemini corrigiu, com a prova.

    `inicio`/`fim` são o momento da palavra; `original` é o que o Whisper
    escreveu e `prova` é um texto da tela, já registrado na análise naquele
    momento, que contém a palavra corrigida.
    """

    original: Rotulo = Field(description="A palavra como a transcrição a escreveu.")
    corrigida: Rotulo = Field(
        description="A palavra corrigida, parecida com a original."
    )
    prova: Texto = Field(
        description="Texto da tela (GC, tarja, logo, legenda) já registrado em "
        "textos_na_tela naquele momento, que contém a palavra corrigida."
    )


MotivoDaRecusa = Literal["original_ausente", "sem_prova", "semelhanca_abaixo_do_limiar"]


class CorrecaoDescartada(CorrecaoDaTranscricao):
    motivo: MotivoDaRecusa


class TextoNaTela(_Intervalo):
    """Cada vez que um texto fica visível é um item, com o início e o fim em que
    ele está na tela; um GC que sai e volta são dois itens. Nunca estenda o texto
    até o fim do bloco ou do plano."""

    tipo: Literal[
        "gc", "tarja", "legenda", "placar", "chamada", "logo", "qr_code", "outro"
    ]
    texto: Texto = Field(description="O texto lido, como aparece.")
    # Preenchido pelo servidor: `True` se os tempos foram medidos nos quadros,
    # `False` se o OCR não achou o texto (ficam os tempos do modelo).
    medido: bool | None = None


class Decupagem(_Estrito):
    versao_esquema: VersaoEsquema
    video: Video
    programa: Programa
    pautas: list[Pauta]
    pessoas: list[Pessoa]
    objetos: list[Objeto] = Field(
        default=[],
        description="Roupas, calçados, acessórios e objetos em cena, cada um com os "
        "atributos, o dono (uma pessoa da lista `pessoas`) e os intervalos visíveis.",
    )
    planos: list[Plano]
    comerciais: list[Comercial]
    transcricao: list[Fala] = Field(
        description="As falas em trechos curtos, um por frase ou troca de quem fala."
    )
    textos_na_tela: list[TextoNaTela] = Field(
        default=[],
        description="GCs, tarjas, legendas, placares, chamadas, logos e QR codes. "
        "Cada vez que um texto fica visível é um item, com o início e o fim em que "
        "ele está na tela; um GC que sai e volta são dois itens. Nunca estenda o "
        "texto até o fim do bloco ou do plano.",
    )
    correcoes_da_transcricao: list[CorrecaoDaTranscricao] = Field(
        default=[],
        description="Só quando a instrução traz a transcrição: palavras dela que "
        "você corrige, cada uma com a prova de um texto da tela. Sem prova, deixe "
        "como está. Nunca troque uma palavra por outra de som diferente.",
    )
    correcoes_descartadas: list[CorrecaoDescartada] = []

    def _intervalos(self) -> list[_Intervalo]:
        achados: list[_Intervalo] = [*self.programa.blocos, *self.pautas]
        for p in self.pessoas:
            achados += [*p.na_imagem, *p.citada_na_fala, *p.citada_no_texto]
        achados += [o for objeto in self.objetos for o in objeto.ocorrencias]
        return [
            *achados,
            *self.planos,
            *self.comerciais,
            *self.transcricao,
            *self.textos_na_tela,
            *self.correcoes_da_transcricao,
            *self.correcoes_descartadas,
        ]

    @model_validator(mode="after")
    def _tempos_dentro_da_duracao(self) -> Self:
        if any(i.fim_ms > self.video.duracao_ms for i in self._intervalos()):
            raise ValueError("tempo além da duração do vídeo")
        return self

    @model_validator(mode="after")
    def _dono_do_objeto_existe(self) -> Self:
        ids = {p.id for p in self.pessoas}
        if any(o.pessoa is not None and o.pessoa not in ids for o in self.objetos):
            raise ValueError("objeto de uma pessoa que não está na decupagem")
        return self


# Campos que o servidor preenche; o modelo não tem como sabê-los. A versão é
# nossa; o SHA-256 e a duração (`video`) vêm da quarentena; os tempos originais
# são escritos pela regra de tempos; `origem` só muda na revisão; `quadro` é a
# imagem que nós extraímos; os ms saem dos tempos em MM:SS. Vale pelo nome da
# chave em qualquer nível: um campo do modelo com um desses nomes sumiria do
# esquema e toda resposta seria recusada.
CAMPOS_DO_SERVIDOR = frozenset(
    {
        "versao_esquema",
        "video",
        "inicio_ms",
        "fim_ms",
        "inicio_modelo_ms",
        "fim_modelo_ms",
        "origem",
        "estado_do_nome",
        "catalogo_id",
        "quadro",
        "texto_original",
        "medido",
        "motivo",
        "correcoes_descartadas",
    }
)

# Minutos passam de 59 e nunca há horas: é o formato estável do modelo depois de
# 1 h (`62:30`); pedido em HH:MM:SS, o 3.5 Flash-Lite perdia a hora (`00:02:30`).
FORMATO_DO_TEMPO = r"^\d{2,}:[0-5]\d$"
_TEMPO = re.compile(FORMATO_DO_TEMPO)
TEMPO_DO_MODELO = {
    "type": "string",
    "pattern": FORMATO_DO_TEMPO,
    "description": "MM:SS contado do início do arquivo de vídeo, mesmo num trecho. "
    "Minutos passam de 59 (1 h 2 min 30 s = 62:30); nunca use horas.",
}


def _ms(tempo: Any, duracao_ms: int) -> int:
    if not isinstance(tempo, str) or not _TEMPO.match(tempo):
        raise ValueError(f"tempo fora de MM:SS: {tempo!r}")
    minutos, segundos = tempo.split(":")
    ms = (int(minutos) * 60 + int(segundos)) * 1000
    # O modelo só escreve segundos: até 1 s além do fim é o fim do vídeo.
    return duracao_ms if duracao_ms < ms <= duracao_ms + 1000 else ms


def tempos_em_ms(dados: Any, duracao_ms: int) -> Any:
    """Troca, em qualquer nível, `inicio`/`fim` em MM:SS por `inicio_ms`/`fim_ms`.

    Levanta `ValueError` se um tempo não estiver em MM:SS.
    """
    if isinstance(dados, list):
        return [tempos_em_ms(d, duracao_ms) for d in dados]
    if not isinstance(dados, dict):
        return dados
    convertido = {k: tempos_em_ms(v, duracao_ms) for k, v in dados.items()}
    if "inicio" in convertido or "fim" in convertido:
        convertido["inicio_ms"] = _ms(convertido.pop("inicio", None), duracao_ms)
        convertido["fim_ms"] = _ms(convertido.pop("fim", None), duracao_ms)
    return convertido


def esquema_do_modelo() -> dict[str, Any]:
    """Saída estruturada pedida ao Gemini: a decupagem sem `CAMPOS_DO_SERVIDOR`,
    com tempos em MM:SS e todo campo obrigatório (o opcional vem como null ou
    lista vazia), para o modelo não pular nenhum."""
    esquema = Decupagem.model_json_schema()
    del esquema["$defs"]["Video"], esquema["$defs"]["CorrecaoDescartada"]
    for definicao in [esquema, *esquema["$defs"].values()]:
        propriedades = definicao.get("properties", {})
        intervalo = "inicio_ms" in propriedades
        for campo in CAMPOS_DO_SERVIDOR:
            propriedades.pop(campo, None)
        if intervalo:
            definicao["properties"] = {
                "inicio": TEMPO_DO_MODELO,
                "fim": TEMPO_DO_MODELO,
                **propriedades,
            }
        if "properties" in definicao:
            definicao["required"] = list(definicao["properties"])
    return esquema
