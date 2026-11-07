"""Os tipos de objeto já vistos nas Decupagens (#308), para o autocompletar da correção."""

from collections.abc import Mapping
from typing import Annotated, Protocol, TypedDict

from fastapi import APIRouter, Depends, Query

from api.auth import Chamador
from api.comparador import normalizar
from api.jobs import _exige

LIMITE_PADRAO = 10


class TipoDeObjeto(TypedDict):
    tipo: str
    ocorrencias: int


class TiposDeObjeto(Protocol):
    def registrar(self, job_id: str, contagens: Mapping[str, int]) -> None:
        """Troca a contribuição do job (tipo → ocorrências): registrar de novo não dobra."""

    def buscar(self, q: str, limite: int = LIMITE_PADRAO) -> list[TipoDeObjeto]:
        """Os tipos cuja chave `normalizar(tipo)` começa por `normalizar(q)`, dos mais
        ocorridos para os menos."""


def somar_por_chave(contagens: Mapping[str, int]) -> dict[str, tuple[str, int]]:
    """chave normalizada → (tipo como escrito da primeira vez, ocorrências)."""
    somadas: dict[str, tuple[str, int]] = {}
    for tipo, n in contagens.items():
        chave = normalizar(tipo)
        if not chave:
            continue
        escrito, antes = somadas.get(chave, (tipo, 0))
        somadas[chave] = (escrito, antes + n)
    return somadas


class TiposDeObjetoEmMemoria:
    def __init__(self) -> None:
        self._por_job: dict[str, dict[str, tuple[str, int]]] = {}

    def registrar(self, job_id: str, contagens: Mapping[str, int]) -> None:
        self._por_job[job_id] = somar_por_chave(contagens)

    def buscar(self, q: str, limite: int = LIMITE_PADRAO) -> list[TipoDeObjeto]:
        prefixo = normalizar(q)
        totais: dict[str, tuple[str, int]] = {}
        for contribuicao in self._por_job.values():
            for chave, (tipo, n) in contribuicao.items():
                if chave.startswith(prefixo):
                    escrito, antes = totais.get(chave, (tipo, 0))
                    totais[chave] = (escrito, antes + n)
        ordenados = sorted(totais.items(), key=lambda kv: (-kv[1][1], kv[0]))
        return [{"tipo": t, "ocorrencias": n} for _, (t, n) in ordenados[:limite]]


def criar_rotas_dos_tipos_de_objeto(tipos: TiposDeObjeto) -> APIRouter:
    rotas = APIRouter()

    @rotas.get("/objetos/tipos")
    def buscar(
        _chamador: Annotated[Chamador, Depends(_exige("ler"))],
        q: Annotated[str, Query(max_length=100)] = "",
    ) -> list[TipoDeObjeto]:
        return tipos.buscar(q, LIMITE_PADRAO)

    return rotas
