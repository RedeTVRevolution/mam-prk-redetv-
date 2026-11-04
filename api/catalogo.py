"""Catálogo de pessoas (E1): dado vivo no Firestore, não configuração.

Cada pessoa tem um id estável, gerado uma vez e nunca reaproveitado. A
identificação automática (#82) grava nele as referências de rosto e usa o id
como dono dos objetos da busca.
"""

import hashlib
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from api.comparador import normalizar


class Rosto(BaseModel):
    """Uma referência de rosto ligada à pessoa e de onde ela veio. `referencia` é o
    objeto da foto no bucket; da busca na web guardam-se também a página, a imagem, a
    busca e a data (de onde sai a validade)."""

    origem: Literal["web", "acervo"]
    referencia: str
    pagina_url: str = ""
    imagem_url: str = ""
    busca: str = ""
    obtida_em: datetime | None = None


class EnvioParaLixeira(BaseModel):
    """Quando, por quem e por quê o item foi para a lixeira (E8, #144, #151)."""

    em: datetime
    por_uid: str
    por_email: str
    motivo: str


class FusaoDaPessoa(BaseModel):
    """A pessoa fundida em outra (#209): quando, por quem, por quê e para quem aponta."""

    destino_id: str
    em: datetime
    por_uid: str
    por_email: str
    motivo: str


class PessoaDoCatalogo(BaseModel):
    id: str
    nome: str
    papel: str
    apelidos: list[str] = []
    rostos: list[Rosto] = []
    # Nome acrescentado por quem corrige (#150): o Curador confere depois.
    a_revisar: bool = False
    acrescentada_por: str | None = None
    # Na lixeira (#151): some do autocompletar e da busca por nome; fica até a purga.
    lixeira: EnvioParaLixeira | None = None
    # Fundida em outra (#209): aponta para o destino e sai das buscas e do autocompletar.
    fundida: FusaoDaPessoa | None = None


class PessoaInexistente(Exception):
    """Nenhuma pessoa do catálogo tem o id pedido."""


def visivel(pessoa: PessoaDoCatalogo) -> bool:
    """Entra nas buscas e no autocompletar: fora da lixeira e não fundida em outra."""
    return pessoa.lixeira is None and pessoa.fundida is None


def nomes_de_busca(pessoa: PessoaDoCatalogo) -> list[str]:
    """Nome e apelidos normalizados: o que `achar` compara."""
    return sorted({normalizar(n) for n in [pessoa.nome, *pessoa.apelidos]})


class Catalogo(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def obter(self, id: str) -> PessoaDoCatalogo | None: ...

    def achar(self, nome: str) -> list[PessoaDoCatalogo]:
        """As pessoas (fora da lixeira e não fundidas) cujo nome ou apelido é `nome`, sem maiúsculas nem acentos."""
        ...

    def todas(self) -> list[PessoaDoCatalogo]:
        """As pessoas que não estão na lixeira nem foram fundidas em outra."""
        ...

    def na_lixeira(self) -> list[PessoaDoCatalogo]: ...

    def definir_lixeira(
        self, id: str, envio: EnvioParaLixeira | None
    ) -> PessoaDoCatalogo:
        """Manda para a lixeira (ou, com `None`, tira); `PessoaInexistente` se o id não existe."""
        ...

    def definir_fusao(self, id: str, fusao: FusaoDaPessoa | None) -> PessoaDoCatalogo:
        """Marca a pessoa como fundida no destino (ou, com `None`, desfaz); `PessoaInexistente` se o id não existe."""
        ...

    def acrescentar(
        self,
        nome: str,
        papel: str,
        apelidos: list[str],
        *,
        a_revisar: bool = False,
        autor: str | None = None,
    ) -> PessoaDoCatalogo: ...

    def corrigir(
        self,
        id: str,
        *,
        nome: str | None = None,
        papel: str | None = None,
        apelidos: list[str] | None = None,
    ) -> PessoaDoCatalogo:
        """Troca só o que veio; `PessoaInexistente` se o id não existe."""
        ...

    def definir_rostos(self, id: str, rostos: list[Rosto]) -> PessoaDoCatalogo:
        """Troca as referências de rosto; `PessoaInexistente` se o id não existe."""
        ...

    def apagar(self, id: str) -> None:
        """`PessoaInexistente` se o id não existe."""
        ...


def prefixo_das_fotos(pessoa_id: str) -> str:
    """A pasta das fotos de referência de uma pessoa do catálogo no bucket."""
    return f"referencias/{pessoa_id}/"


def objeto_da_foto(pessoa_id: str, jpeg: bytes) -> str:
    """Onde a foto de referência de uma pessoa do catálogo fica no bucket."""
    return f"{prefixo_das_fotos(pessoa_id)}{hashlib.sha256(jpeg).hexdigest()[:24]}.jpg"


def novo_id() -> str:
    return uuid.uuid4().hex


def corrigida(
    pessoa: PessoaDoCatalogo,
    nome: str | None,
    papel: str | None,
    apelidos: list[str] | None,
) -> PessoaDoCatalogo:
    return pessoa.model_copy(
        update={
            "nome": pessoa.nome if nome is None else nome,
            "papel": pessoa.papel if papel is None else papel,
            "apelidos": pessoa.apelidos if apelidos is None else list(apelidos),
        }
    )


def rostos_que_valem(
    rostos: Iterable[Rosto],
    agora: datetime,
    validade: timedelta,
    *,
    com_acervo: bool = False,
) -> list[Rosto]:
    """As referências que ainda valem, conferidas na hora de usar: as da web só
    até `validade` depois da data em que foram obtidas (sem data, não valem); as do
    acervo só com `com_acervo`, desligado por configuração."""
    return [
        r
        for r in rostos
        if (r.origem == "acervo" and com_acervo)
        or (
            r.origem == "web"
            and r.obtida_em is not None
            and agora - r.obtida_em <= validade
        )
    ]


def rostos_validos(
    pessoa: PessoaDoCatalogo,
    agora: datetime,
    validade: timedelta,
    *,
    com_acervo: bool = False,
) -> list[Rosto]:
    """As referências da pessoa que ainda valem (veja `rostos_que_valem`)."""
    return rostos_que_valem(pessoa.rostos, agora, validade, com_acervo=com_acervo)


class CatalogoEmMemoria:
    def __init__(self) -> None:
        self._pessoas: dict[str, PessoaDoCatalogo] = {}

    @classmethod
    def copia_de(cls, catalogo: Catalogo) -> "CatalogoEmMemoria":
        """Uma cópia solta: o que se acrescenta nela não chega ao catálogo de origem."""
        copia = cls()
        copia._pessoas = {p.id: p for p in catalogo.todas()}
        return copia

    def obter(self, id: str) -> PessoaDoCatalogo | None:
        return self._pessoas.get(id)

    def achar(self, nome: str) -> list[PessoaDoCatalogo]:
        chave = normalizar(nome)
        return [p for p in self.todas() if chave in nomes_de_busca(p)]

    def todas(self) -> list[PessoaDoCatalogo]:
        return [p for p in self._pessoas.values() if visivel(p)]

    def na_lixeira(self) -> list[PessoaDoCatalogo]:
        return [p for p in self._pessoas.values() if p.lixeira is not None]

    def definir_lixeira(
        self, id: str, envio: EnvioParaLixeira | None
    ) -> PessoaDoCatalogo:
        atual = self._pessoas.get(id)
        if atual is None:
            raise PessoaInexistente(id)
        self._pessoas[id] = atual.model_copy(update={"lixeira": envio})
        return self._pessoas[id]

    def definir_fusao(self, id: str, fusao: FusaoDaPessoa | None) -> PessoaDoCatalogo:
        atual = self._pessoas.get(id)
        if atual is None:
            raise PessoaInexistente(id)
        self._pessoas[id] = atual.model_copy(update={"fundida": fusao})
        return self._pessoas[id]

    def acrescentar(
        self,
        nome: str,
        papel: str,
        apelidos: list[str],
        *,
        a_revisar: bool = False,
        autor: str | None = None,
    ) -> PessoaDoCatalogo:
        pessoa = PessoaDoCatalogo(
            id=novo_id(),
            nome=nome,
            papel=papel,
            apelidos=list(apelidos),
            a_revisar=a_revisar,
            acrescentada_por=autor,
        )
        self._pessoas[pessoa.id] = pessoa
        return pessoa

    def corrigir(
        self,
        id: str,
        *,
        nome: str | None = None,
        papel: str | None = None,
        apelidos: list[str] | None = None,
    ) -> PessoaDoCatalogo:
        atual = self._pessoas.get(id)
        if atual is None:
            raise PessoaInexistente(id)
        self._pessoas[id] = corrigida(atual, nome, papel, apelidos)
        return self._pessoas[id]

    def definir_rostos(self, id: str, rostos: list[Rosto]) -> PessoaDoCatalogo:
        atual = self._pessoas.get(id)
        if atual is None:
            raise PessoaInexistente(id)
        self._pessoas[id] = atual.model_copy(update={"rostos": list(rostos)})
        return self._pessoas[id]

    def apagar(self, id: str) -> None:
        if self._pessoas.pop(id, None) is None:
            raise PessoaInexistente(id)


def _pessoas_dos_programas(
    programas: Mapping[str, Mapping[str, Any]],
) -> Iterable[Mapping[str, Any]]:
    for dados in programas.values():
        yield from dados.get("pessoas", [])


def carregar_programas(
    catalogo: Catalogo, programas: Mapping[str, Mapping[str, Any]]
) -> int:
    """Acrescenta ao catálogo as pessoas do `programas.toml` que ainda não estão
    nele (pelo nome ou apelido). Idempotente; devolve quantas entraram."""
    entraram = 0
    for p in _pessoas_dos_programas(programas):
        if catalogo.achar(p["nome"]):
            continue
        catalogo.acrescentar(p["nome"], p["papel"], list(p.get("apelidos", [])))
        entraram += 1
    return entraram
