"""Esquema 1.1 da decupagem.

Um modelo só: dele saem a saída estruturada pedida ao Gemini
(`Decupagem.model_json_schema()`), a validação da resposta e o tipo do OpenAPI.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

Texto = Annotated[str, Field(max_length=2000)]
Rotulo = Annotated[str, Field(max_length=200)]
Id = Annotated[str, Field(max_length=40)]


class _Estrito(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Intervalo(_Estrito):
    inicio_ms: int = Field(ge=0)
    fim_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _inicio_antes_do_fim(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self


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
    resumo: Texto
    pessoas: list[Id] = []
    locais: list[Rotulo] = []


class Aparicao(_Intervalo):
    evidencia: Rotulo
    quadro: str | None = None  # vazio na E0


class CitacaoNaFala(_Intervalo):
    pass


class CitacaoNoTexto(_Intervalo):
    texto: Texto


class Pessoa(_Estrito):
    id: Id
    nome: Rotulo  # "não identificado" quando o modelo não reconhece
    origem: Literal["modelo", "revisao"] = "modelo"
    na_imagem: list[Aparicao]
    citada_na_fala: list[CitacaoNaFala]
    citada_no_texto: list[CitacaoNoTexto]


class Plano(_Intervalo):
    id: Id
    ambiente: Rotulo
    plano_limpo: bool
    objetos: list[Rotulo] = []
    acao: Texto | None = None
    enquadramento: Rotulo | None = None
    movimento_camera: Rotulo | None = None
    externa: bool | None = None
    periodo: Literal["dia", "noite"] | None = None


class Comercial(_Intervalo):
    marca: Rotulo
    tipo: Literal[
        "intervalo",
        "merchan_apresentador",
        "patrocinio_vinheta",
        "sobreposicao_grafica",
        "marca_incidental",
        "mencao_editorial",
    ]
    evidencia: Rotulo


class Fala(_Intervalo):
    locutor: Rotulo
    texto: Texto


class Decupagem(_Estrito):
    versao_esquema: Literal["1.1"]
    video: Video
    programa: Programa
    pautas: list[Pauta]
    pessoas: list[Pessoa]
    planos: list[Plano]
    comerciais: list[Comercial]
    transcricao: list[Fala]

    def _intervalos(self) -> list[_Intervalo]:
        achados: list[_Intervalo] = [*self.programa.blocos, *self.pautas]
        for p in self.pessoas:
            achados += [*p.na_imagem, *p.citada_na_fala, *p.citada_no_texto]
        return [*achados, *self.planos, *self.comerciais, *self.transcricao]

    @model_validator(mode="after")
    def _tempos_dentro_da_duracao(self, info: ValidationInfo) -> Self:
        """Vale a duração do contexto (confiável); a do modelo é só o plano B."""
        contexto = info.context or {}
        duracao = contexto.get("duracao_ms", self.video.duracao_ms)
        if self.video.duracao_ms != duracao:
            raise ValueError("duração declarada difere da duração do vídeo")
        if any(i.fim_ms > duracao for i in self._intervalos()):
            raise ValueError("tempo além da duração do vídeo")
        return self
