"""A taxa de correção da aba Revisão do painel, lida da tabela diária (#468, parte 2 de 2).

O painel soma `correcoes` e `itens` das linhas diárias do período (`api/taxa_diaria.py`, #455)
e divide uma pela outra: não baixa decupagem nem lê as correções vídeo a vídeo. O cálculo
antigo (`api/taxa_de_correcao.calcular`) segue como referência nos testes e na rota
`GET /v1/qualidade/taxa-de-correcao`.

`desde` e `ate` são dias de São Paulo, os dois inclusive, como a coluna `dia`. Um período de
5 anos lê só as linhas diárias dele (a tabela é particionada por dia): poucas por dia (programa
× versão × tipo), então a consulta devolve um grupo por programa, versão e tipo.

Diferença do cálculo antigo: um vídeo revisado em dois dias do período tem os itens contados
nos dois (a tabela não guarda o vídeo). As correções somam igual; os itens podem passar, e a
taxa do período de mais de um dia sai um pouco menor. Num dia só, o número é o mesmo.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol

from api.copia_bigquery import Transporte, _parametro, transporte_http
from api.relatorios import linhas_da_consulta
from api.taxa_de_correcao import LinhaDaTaxa
from api.taxa_diaria import ConfigDaTaxa, LinhaDiaria, TabelaDaTaxaEmMemoria

__all__ = [
    "LeitorDaTaxa",
    "TaxaBigQuery",
    "TaxaEmMemoria",
    "somar_dias",
    "taxa_do_ambiente",
]


class LeitorDaTaxa(Protocol):
    def somar(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[LinhaDaTaxa]:
        """Uma linha por programa, versão do pipeline e tipo, em ordem; os dias de `desde`
        a `ate` inclusive (sem limite se faltam)."""


def _linha(
    programa: str | None,
    versao: str | None,
    tipo: str,
    correcoes: int,
    itens: int,
) -> LinhaDaTaxa:
    return LinhaDaTaxa(
        programa=programa,
        versao_pipeline=versao,
        tipo=tipo,
        correcoes=correcoes,
        itens=itens,
        taxa_de_correcao=round(correcoes / itens, 4) if itens else None,
    )


def somar_dias(
    linhas: Iterable[LinhaDiaria],
    desde: date | None,
    ate: date | None,
    programa: str | None,
) -> list[LinhaDaTaxa]:
    """A soma que a consulta do BigQuery faz, em memória (o dublê e a conferência dela)."""
    somas: dict[tuple[str | None, str | None, str], list[int]] = defaultdict(
        lambda: [0, 0]
    )
    for x in linhas:
        if (
            (desde is None or x.dia >= desde)
            and (ate is None or x.dia <= ate)
            and (programa is None or x.programa == programa)
        ):
            soma = somas[(x.programa, x.versao_pipeline, x.tipo)]
            soma[0] += x.correcoes
            soma[1] += x.itens
    return [
        _linha(p, v, t, n, itens)
        for (p, v, t), (n, itens) in sorted(
            somas.items(), key=lambda kv: tuple(x or "" for x in kv[0])
        )
    ]


class TaxaEmMemoria:
    """Dublê: soma as linhas da tabela em memória."""

    def __init__(self, tabela: TabelaDaTaxaEmMemoria | None = None) -> None:
        self.tabela = tabela or TabelaDaTaxaEmMemoria()

    def somar(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[LinhaDaTaxa]:
        return somar_dias(self.tabela.linhas, desde, ate, programa)


class TaxaBigQuery:
    """A leitura real: uma consulta soma as linhas diárias do período."""

    def __init__(self, config: ConfigDaTaxa, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def consulta(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> tuple[str, list[dict[str, Any]]]:
        c = self._config
        onde = ["TRUE"]
        parametros: list[dict[str, Any]] = []
        if desde is not None:
            parametros.append(_parametro("desde", desde.isoformat(), "DATE"))
            onde.append("dia >= @desde")
        if ate is not None:
            parametros.append(_parametro("ate", ate.isoformat(), "DATE"))
            onde.append("dia <= @ate")
        if programa is not None:
            parametros.append(_parametro("programa", programa))
            onde.append("programa = @programa")
        sql = (
            "SELECT programa, versao_pipeline, tipo,"
            " SUM(correcoes) AS correcoes, SUM(itens) AS itens\n"
            f"FROM `{c.projeto}.{c.dataset}.{c.tabela}`\n"
            f"WHERE {' AND '.join(onde)}\n"
            "GROUP BY programa, versao_pipeline, tipo"
        )
        return sql, parametros

    def somar(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[LinhaDaTaxa]:
        sql, parametros = self.consulta(desde, ate, programa)
        linhas = linhas_da_consulta(
            self._transporte, self._config.regiao, sql, parametros, "taxa de correção"
        )
        return [
            _linha(p, v, t, int(n), int(itens))
            for p, v, t, n, itens in sorted(
                linhas, key=lambda r: tuple(x or "" for x in r[:3])
            )
        ]


def taxa_do_ambiente(ambiente: Any) -> TaxaBigQuery | None:
    """A leitura configurada, ou `None` se o ambiente não diz onde a tabela mora."""
    if "BIGQUERY_TABELA_DA_TAXA" not in ambiente:
        return None
    config = ConfigDaTaxa.do_ambiente(ambiente)
    return TaxaBigQuery(config, transporte_http(config.projeto))
