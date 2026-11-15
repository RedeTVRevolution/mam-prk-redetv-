"""Os tipos da taxa de correção que o painel lê, sem Firestore nem Storage (#653)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel


class LinhaDaTaxa(BaseModel):
    programa: str | None
    versao_pipeline: str | None
    tipo: str
    correcoes: int
    itens: int
    taxa_de_correcao: float | None


@dataclass(frozen=True)
class LinhaDiaria:
    dia: date
    job_id: str
    programa: str | None
    versao_pipeline: str | None
    tipo: str
    correcoes: int
    itens: int


class TabelaDaTaxaEmMemoria:
    def __init__(self) -> None:
        self.linhas: list[LinhaDiaria] = []

    def substituir(self, dias: Sequence[date], linhas: list[LinhaDiaria]) -> None:
        self.linhas = [x for x in self.linhas if x.dia not in dias] + linhas


@dataclass(frozen=True)
class ConfigDaTaxa:
    projeto: str
    dataset: str
    regiao: str
    tabela: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDaTaxa":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            regiao=ambiente["BIGQUERY_REGIAO"],
            tabela=ambiente["BIGQUERY_TABELA_DA_TAXA"],
        )
