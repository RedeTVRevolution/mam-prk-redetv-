"""Fotos de referência de um nome fora do catálogo (#222, ADR 0005).

O palpite do modelo forte que o catálogo não conhece também ganha as 3 fotos, mas elas
ficam sob `palpites/` no bucket das referências, pelo nome normalizado, com os dados de
cada uma num `rostos.json` ao lado. Uma regra de ciclo de vida do bucket apaga esse
prefixo sozinha (rosto é dado sensível). Só o nome que se confirma entra no catálogo, e
aí as fotos que o confirmaram passam para o lugar das fotos do catálogo, fora do prefixo.
"""

import hashlib
import re
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ValidationError

from api.catalogo import (
    Catalogo,
    PessoaDoCatalogo,
    Rosto,
    objeto_da_foto,
)
from api.comparador import normalizar

PREFIXO_DOS_PALPITES = "palpites/"
ARQUIVO_DOS_DADOS = "rostos.json"


class FotoAusente(Exception):
    """A foto de referência não está no bucket."""


class Objetos(Protocol):
    """O bucket das referências."""

    def gravar(self, objeto: str, conteudo: bytes) -> None: ...

    def ler(self, objeto: str) -> bytes:
        """O objeto guardado; `FotoAusente` se não existe."""
        ...

    def apagar(self, objeto: str) -> None:
        """Sem erro se o objeto já não existe."""
        ...


class _Dados(BaseModel):
    rostos: list[Rosto]


def pasta_do_palpite(nome: str) -> str:
    """`palpites/<nome-normalizado>/`; um nome sem letras nem números (outra escrita)
    vira o início do hash do nome."""
    chave = normalizar(nome)
    pasta = "-".join(re.findall(r"[a-z0-9]+", chave))
    if not pasta:
        pasta = hashlib.sha256(chave.encode()).hexdigest()[:16]
    return f"{PREFIXO_DOS_PALPITES}{pasta}/"


def objeto_da_foto_do_palpite(nome: str, jpeg: bytes) -> str:
    return f"{pasta_do_palpite(nome)}{hashlib.sha256(jpeg).hexdigest()[:24]}.jpg"


class Palpites:
    def __init__(self, objetos: Objetos) -> None:
        self._objetos = objetos

    def rostos(self, nome: str) -> list[Rosto]:
        """As referências guardadas para o nome; vazio se não há (ou se o arquivo
        dos dados não se lê)."""
        try:
            bruto = self._objetos.ler(pasta_do_palpite(nome) + ARQUIVO_DOS_DADOS)
            return _Dados.model_validate_json(bruto).rostos
        except (FotoAusente, ValidationError):
            return []

    def guardar(self, nome: str, fotos: Sequence[tuple[bytes, Rosto]]) -> list[Rosto]:
        """Grava cada JPEG sob o prefixo e os dados deles; troca os de antes."""
        novos = []
        for jpeg, rosto in fotos:
            objeto = objeto_da_foto_do_palpite(nome, jpeg)
            self._objetos.gravar(objeto, jpeg)
            novos.append(rosto.model_copy(update={"referencia": objeto}))
        self._objetos.gravar(
            pasta_do_palpite(nome) + ARQUIVO_DOS_DADOS,
            _Dados(rostos=novos).model_dump_json().encode(),
        )
        return novos

    def promover(
        self,
        nome: str,
        rostos: Sequence[Rosto],
        jpegs: Sequence[bytes],
        papel: str,
        catalogo: Catalogo,
    ) -> tuple[PessoaDoCatalogo, tuple[Rosto, ...]]:
        """O nome confirmado entra no catálogo (a pessoa de mesmo nome, se já existe
        uma só; senão uma nova) e as fotos que o confirmaram passam para o lugar das
        fotos do catálogo, ligadas a ela; as de antes, sob o prefixo, são apagadas."""
        achadas = catalogo.achar(nome)
        pessoa = (
            achadas[0] if len(achadas) == 1 else catalogo.acrescentar(nome, papel, [])
        )
        novos = []
        for rosto, jpeg in zip(rostos, jpegs, strict=True):
            objeto = objeto_da_foto(pessoa.id, jpeg)
            self._objetos.gravar(objeto, jpeg)
            novos.append(rosto.model_copy(update={"referencia": objeto}))
        do_acervo = [r for r in pessoa.rostos if r.origem == "acervo"]
        pessoa = catalogo.definir_rostos(pessoa.id, [*do_acervo, *novos])
        for rosto in rostos:
            self._objetos.apagar(rosto.referencia)
        self._objetos.apagar(pasta_do_palpite(nome) + ARQUIVO_DOS_DADOS)
        return pessoa, tuple(novos)
