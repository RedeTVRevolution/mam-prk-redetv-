"""Catálogo de pessoas (E1): dado vivo no Firestore, não configuração.

Cada pessoa tem um id estável, gerado uma vez e nunca reaproveitado; o id é o
dono dos objetos da busca. Os rostos `origem=web` são legado da busca de fotos na
web, retirada no #327: só a migração `apagar_referencias_web` ainda os lê.
"""

import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, Self

from fastapi import HTTPException
from pydantic import BaseModel

from api.texto import normalizar


class Rosto(BaseModel):
    """Uma referência de rosto ligada à pessoa e de onde ela veio. `referencia` é o
    objeto da foto no bucket. `origem="web"` e os campos da busca na web (página, imagem,
    busca e data) só servem para ler os rostos gravados antes do #327, até a migração
    `make apagar-referencias-web` apagá-los (ADR 0012)."""

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


class RenomeacaoDaPessoa(BaseModel):
    """A última renomeação em todos os vídeos (#263): de onde veio o nome e o andamento.
    Desde o #417 nasce `concluida`, sem `pendentes`: o índice não guarda o
    nome. `nomes_anteriores` guarda todos os nomes que a pessoa já teve."""

    nome_antigo: str
    nome_novo: str
    nomes_anteriores: list[str]
    em: datetime
    por_uid: str
    por_email: str
    total: int
    pendentes: list[str]
    estado: Literal["em_andamento", "concluida", "falhou"]


class AndamentoDaRenomeacao(BaseModel):
    estado: Literal["em_andamento", "concluida", "falhou"]
    feitos: int
    total: int
    nome_antigo: str
    nome_novo: str


class _Renomeacao(Protocol):
    """O que a renomeação de uma pessoa e a de um programa têm em comum."""

    @property
    def estado(self) -> str: ...
    @property
    def total(self) -> int: ...
    @property
    def pendentes(self) -> list[str]: ...
    @property
    def nome_antigo(self) -> str: ...
    @property
    def nome_novo(self) -> str: ...


def andamento_da_renomeacao(
    r: _Renomeacao, confirmando_conta_como_em_andamento: bool = False
) -> AndamentoDaRenomeacao:
    """Para quem lê, a troca de programa que espera a auditoria (`confirmando`) já está em andamento."""
    estado = r.estado
    if confirmando_conta_como_em_andamento and estado == "confirmando":
        estado = "em_andamento"
    dados: dict[str, Any] = {
        "estado": estado,
        "feitos": r.total - len(r.pendentes),
        "total": r.total,
        "nome_antigo": r.nome_antigo,
        "nome_novo": r.nome_novo,
    }
    return AndamentoDaRenomeacao.model_validate(dados)


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
    # Renomeada em todos os vídeos (#263): a leitura troca os nomes antigos pelo atual.
    renomeacao: RenomeacaoDaPessoa | None = None


class PessoaInexistente(Exception):
    """Nenhuma pessoa do catálogo tem o id pedido."""


def visivel(pessoa: PessoaDoCatalogo) -> bool:
    """Entra nas buscas e no autocompletar: fora da lixeira e não fundida em outra."""
    return pessoa.lixeira is None and pessoa.fundida is None


class EntradaDoCatalogo(Protocol):
    """O que pessoa e marca têm em comum: o que a implementação única do catálogo (em
    memória aqui, no Firestore em `api/nuvem.py`) lê e grava."""

    id: str
    nome: str
    apelidos: list[str]
    lixeira: EnvioParaLixeira | None

    def model_copy(self, *, update: Mapping[str, Any]) -> Self: ...

    def model_dump(self, *, exclude: set[str]) -> dict[str, Any]: ...


def sem_lixeira(entrada: EntradaDoCatalogo) -> bool:
    return entrada.lixeira is None


def existente_para_acrescentar[T: EntradaDoCatalogo](achadas: list[T]) -> T | None:
    """Para o POST que evita duplicata: o registro que já existe (fora da lixeira), ou
    `None` se o nome é novo. Nome na lixeira é 409: restaurar é o caminho, não criar."""
    if not achadas:
        return None
    if achadas[0].lixeira is not None:
        raise HTTPException(409, "Esse nome está na lixeira e pode ser restaurado")
    return achadas[0]


def qualquer(_: object) -> bool:
    return True


def sem_fusao(pessoa: PessoaDoCatalogo) -> bool:
    """O que `achar(com_lixeira=True)` ainda esconde: a fundida, que o destino já cobre."""
    return pessoa.fundida is None


def nomes_de_busca(entrada: EntradaDoCatalogo) -> list[str]:
    """Nome e apelidos normalizados (de pessoa ou marca): o que `achar` compara."""
    return sorted({normalizar(n) for n in [entrada.nome, *entrada.apelidos]})


VALIDADE_DA_COPIA = timedelta(seconds=30)


class CopiaCurta[T]:
    """A lista de um catálogo lida há pouco, para todos que a pedem (o autocompletar e o
    busca por nome). Um nome acrescentado a descarta. Quando expira, uma thread
    só relê; as outras usam a cópia anterior, e só esperam se não há cópia (a primeira
    leitura, ou depois de `descartar`)."""

    def __init__(self, ler: Callable[[], list[T]], relogio: Callable[[], datetime]):
        self._ler, self._relogio = ler, relogio
        self._lida_em: datetime | None = None
        self._itens: list[T] = []
        self._geracao = 0
        self._recarga = threading.Lock()

    def _vale(self) -> bool:
        lida_em = self._lida_em
        return lida_em is not None and self._relogio() - lida_em < VALIDADE_DA_COPIA

    def itens(self) -> list[T]:
        if self._vale():
            return self._itens
        # Expirada, mas ainda boa para quem não vai recarregar; descartada, não.
        if not self._recarga.acquire(blocking=self._lida_em is None):
            return self._itens
        try:
            if not self._vale():
                geracao, agora = self._geracao, self._relogio()
                itens = self._ler()
                # Um `descartar` durante a leitura a deixa velha: lê de novo na próxima.
                self._itens = itens
                self._lida_em = agora if geracao == self._geracao else None
            return self._itens
        finally:
            self._recarga.release()

    def descartar(self) -> None:
        self._geracao += 1
        self._lida_em = None


class Catalogo(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def obter(self, id: str) -> PessoaDoCatalogo | None: ...

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        """As pessoas que existem entre os `ids`, numa leitura em lote."""
        ...

    def achar(self, nome: str, *, com_lixeira: bool = False) -> list[PessoaDoCatalogo]:
        """As pessoas (fora da lixeira e não fundidas) cujo nome ou apelido é `nome`, sem
        maiúsculas nem acentos; com `com_lixeira`, as da lixeira também (as fundidas
        continuam de fora)."""
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

    def definir_renomeacao(
        self, id: str, renomeacao: RenomeacaoDaPessoa | None
    ) -> PessoaDoCatalogo:
        """Grava o andamento da renomeação (ou, com `None`, limpa); `PessoaInexistente` se o id não existe."""
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


class CatalogoGenericoEmMemoria[T: EntradaDoCatalogo]:
    """A parte do catálogo em memória que pessoas e marcas dividem; cada uma só diz o
    modelo (nos `acrescentar`), a exceção de inexistente e o que é "visível"."""

    _inexistente: type[Exception]
    _visivel: Callable[[T], bool] = staticmethod(sem_lixeira)
    _achavel_na_lixeira: Callable[[T], bool] = staticmethod(qualquer)

    def __init__(self) -> None:
        self._itens: dict[str, T] = {}

    def _existente(self, id: str) -> T:
        if id not in self._itens:
            raise self._inexistente(id)
        return self._itens[id]

    def _alterar(self, id: str, update: Mapping[str, Any]) -> T:
        self._itens[id] = self._existente(id).model_copy(update=update)
        return self._itens[id]

    def _achar(self, nome: str, com_lixeira: bool = False) -> list[T]:
        chave = normalizar(nome)
        ok = self._achavel_na_lixeira if com_lixeira else self._visivel
        return [i for i in self._itens.values() if ok(i) and chave in nomes_de_busca(i)]

    def obter(self, id: str) -> T | None:
        return self._itens.get(id)

    def obter_varios(self, ids: Iterable[str]) -> dict[str, T]:
        return {i: self._itens[i] for i in dict.fromkeys(ids) if i in self._itens}

    def todas(self) -> list[T]:
        return [i for i in self._itens.values() if self._visivel(i)]

    def na_lixeira(self) -> list[T]:
        return [i for i in self._itens.values() if i.lixeira is not None]

    def definir_lixeira(self, id: str, envio: EnvioParaLixeira | None) -> T:
        return self._alterar(id, {"lixeira": envio})

    def apagar(self, id: str) -> None:
        if self._itens.pop(id, None) is None:
            raise self._inexistente(id)


class CatalogoEmMemoria(CatalogoGenericoEmMemoria[PessoaDoCatalogo]):
    _inexistente = PessoaInexistente
    _visivel = staticmethod(visivel)
    _achavel_na_lixeira = staticmethod(sem_fusao)
    # Os testes mexem direto nesse dicionário.
    _pessoas = property(lambda self: self._itens)

    @classmethod
    def copia_de(cls, catalogo: Catalogo) -> "CatalogoEmMemoria":
        """Uma cópia solta: o que se acrescenta nela não chega ao catálogo de origem."""
        copia = cls()
        copia._itens = {p.id: p for p in catalogo.todas()}
        return copia

    def achar(self, nome: str, *, com_lixeira: bool = False) -> list[PessoaDoCatalogo]:
        return self._achar(nome, com_lixeira)

    def definir_fusao(self, id: str, fusao: FusaoDaPessoa | None) -> PessoaDoCatalogo:
        return self._alterar(id, {"fundida": fusao})

    def definir_renomeacao(
        self, id: str, renomeacao: RenomeacaoDaPessoa | None
    ) -> PessoaDoCatalogo:
        return self._alterar(id, {"renomeacao": renomeacao})

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
        self._itens[pessoa.id] = pessoa
        return pessoa

    def corrigir(
        self,
        id: str,
        *,
        nome: str | None = None,
        papel: str | None = None,
        apelidos: list[str] | None = None,
    ) -> PessoaDoCatalogo:
        self._itens[id] = corrigida(self._existente(id), nome, papel, apelidos)
        return self._itens[id]

    def definir_rostos(self, id: str, rostos: list[Rosto]) -> PessoaDoCatalogo:
        return self._alterar(id, {"rostos": list(rostos)})
