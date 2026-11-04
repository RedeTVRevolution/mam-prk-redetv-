"""A leitura das tabelas resumidas do painel da diretoria (#280, #282, #283).

O painel lê só `uso_por_dia_e_usuario` e `uso_por_dia_e_programa`, nunca a tabela de eventos.
Os nomes das tabelas vêm do ambiente (o Terraform os monta). Uma consulta que não termina ou
não cabe numa resposta falha alto com `RuntimeError` (`linhas_da_consulta`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from api.copia_bigquery import Transporte, _parametro, transporte_http
from api.relatorios import linhas_da_consulta


@dataclass(frozen=True)
class AcessoDoDia:
    """Uma pessoa num dia: quantos logins, se agiu, e o último login do dia."""

    dia: date
    uid: str
    acessos: int
    ativo: bool
    ultimo_acesso: datetime | None


@dataclass(frozen=True)
class UsoDoDia:
    """Vídeos e buscas de um dia, de uma pessoa ou sistema (`quem_id`) ou de um programa
    (`programa`): o outro vem `None`. O tempo é a soma do que os vídeos concluídos levaram."""

    dia: date
    quem_tipo: str | None
    quem_id: str | None
    programa: str | None
    videos_enviados: int
    videos_concluidos: int
    videos_falhos: int
    horas_concluidas: float
    segundos_de_processamento: int
    buscas: int
    buscas_sem_resultado: int


class ResumosDeUso(Protocol):
    def acessos(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[AcessoDoDia]:
        """Só pessoas (sistema não faz login); `desde` e `ate` são dias de São Paulo, inclusive."""

    def uso_por_quem(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[UsoDoDia]:
        """Um dia, uma pessoa ou sistema (`usuario` é o uid ou o nome do sistema)."""

    def uso_por_programa(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[UsoDoDia]:
        """Um dia, um programa."""

    def programas(self) -> list[str]:
        """Os programas que já têm algum evento, em ordem."""

    def usuarios(self) -> list[str]:
        """Os uids de quem já agiu, em ordem."""


class ResumosEmMemoria:
    """Dublê: as linhas dadas, com os mesmos filtros da consulta."""

    def __init__(
        self,
        acessos: Sequence[AcessoDoDia] = (),
        programas: Sequence[str] = (),
        uso: Sequence[UsoDoDia] = (),
    ) -> None:
        self._acessos = list(acessos)
        self._programas = list(programas)
        self._uso = list(uso)

    def _do_periodo(self, desde: date | None, ate: date | None) -> list[UsoDoDia]:
        return [
            u
            for u in self._uso
            if (desde is None or u.dia >= desde) and (ate is None or u.dia <= ate)
        ]

    def uso_por_quem(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[UsoDoDia]:
        return [
            u
            for u in self._do_periodo(desde, ate)
            if u.quem_id is not None and (usuario is None or u.quem_id == usuario)
        ]

    def uso_por_programa(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[UsoDoDia]:
        return [
            u
            for u in self._do_periodo(desde, ate)
            if u.programa is not None and (programa is None or u.programa == programa)
        ]

    def acessos(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[AcessoDoDia]:
        return [
            a
            for a in self._acessos
            if (desde is None or a.dia >= desde)
            and (ate is None or a.dia <= ate)
            and (usuario is None or a.uid == usuario)
        ]

    def programas(self) -> list[str]:
        return sorted(set(self._programas))

    def usuarios(self) -> list[str]:
        return sorted({a.uid for a in self._acessos if a.ativo})


@dataclass(frozen=True)
class ConfigDosResumos:
    projeto: str
    dataset: str
    regiao: str
    tabela_por_dia_e_usuario: str
    tabela_por_dia_e_programa: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDosResumos":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            regiao=ambiente["BIGQUERY_REGIAO"],
            tabela_por_dia_e_usuario=ambiente["PAINEL_TABELA_POR_DIA_E_USUARIO"],
            tabela_por_dia_e_programa=ambiente["PAINEL_TABELA_POR_DIA_E_PROGRAMA"],
        )


class ResumosBigQuery:
    """A leitura real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDosResumos, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def _consultar(
        self, sql: str, parametros: Sequence[dict[str, Any]] = ()
    ) -> list[list[Any]]:
        return linhas_da_consulta(
            self._transporte, self._config.regiao, sql, parametros, "painel"
        )

    def _tabela(self, nome: str) -> str:
        c = self._config
        return f"`{c.projeto}.{c.dataset}.{nome}`"

    def acessos(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[AcessoDoDia]:
        onde = ["quem_tipo = 'usuario'"]
        parametros: list[dict[str, Any]] = []
        for nome, dia, comparacao in (("desde", desde, ">="), ("ate", ate, "<=")):
            if dia is not None:
                onde.append(f"dia {comparacao} @{nome}")
                parametros.append(_parametro(nome, dia.isoformat(), "DATE"))
        if usuario is not None:
            onde.append("quem_id = @usuario")
            parametros.append(_parametro("usuario", usuario))
        linhas = self._consultar(
            "SELECT CAST(dia AS STRING), quem_id, acessos, ativo,"
            " FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', ultimo_acesso)\n"
            f"FROM {self._tabela(self._config.tabela_por_dia_e_usuario)}\n"
            f"WHERE {' AND '.join(onde)}",
            parametros,
        )
        return [
            AcessoDoDia(
                dia=date.fromisoformat(v[0]),
                uid=v[1],
                acessos=int(v[2]),
                ativo=v[3] in ("true", True),
                ultimo_acesso=(
                    datetime.fromisoformat(v[4]).astimezone(UTC) if v[4] else None
                ),
            )
            for v in linhas
        ]

    def _uso(
        self,
        tabela: str,
        chaves: str,
        desde: date | None,
        ate: date | None,
        filtro: tuple[str, str | None],
    ) -> list[UsoDoDia]:
        onde = ["TRUE"]
        parametros: list[dict[str, Any]] = []
        for nome, dia, comparacao in (("desde", desde, ">="), ("ate", ate, "<=")):
            if dia is not None:
                onde.append(f"dia {comparacao} @{nome}")
                parametros.append(_parametro(nome, dia.isoformat(), "DATE"))
        coluna, valor = filtro
        if valor is not None:
            onde.append(f"{coluna} = @{coluna}")
            parametros.append(_parametro(coluna, valor))
        linhas = self._consultar(
            f"SELECT CAST(dia AS STRING), {chaves}, videos_enviados, videos_concluidos,"
            " videos_falhos, horas_concluidas, segundos_de_processamento, buscas,"
            " buscas_sem_resultado\n"
            f"FROM {self._tabela(tabela)}\n"
            f"WHERE {' AND '.join(onde)}",
            parametros,
        )
        return [
            UsoDoDia(
                dia=date.fromisoformat(v[0]),
                quem_tipo=v[1],
                quem_id=v[2],
                programa=v[3],
                videos_enviados=int(v[4]),
                videos_concluidos=int(v[5]),
                videos_falhos=int(v[6]),
                horas_concluidas=float(v[7]),
                segundos_de_processamento=int(v[8]),
                buscas=int(v[9]),
                buscas_sem_resultado=int(v[10]),
            )
            for v in linhas
        ]

    def uso_por_quem(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[UsoDoDia]:
        return self._uso(
            self._config.tabela_por_dia_e_usuario,
            "quem_tipo, quem_id, CAST(NULL AS STRING)",
            desde,
            ate,
            ("quem_id", usuario),
        )

    def uso_por_programa(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[UsoDoDia]:
        return self._uso(
            self._config.tabela_por_dia_e_programa,
            "CAST(NULL AS STRING), CAST(NULL AS STRING), programa",
            desde,
            ate,
            ("programa", programa),
        )

    def programas(self) -> list[str]:
        linhas = self._consultar(
            f"SELECT DISTINCT programa FROM {self._tabela(self._config.tabela_por_dia_e_programa)}"
            " ORDER BY programa"
        )
        return [v[0] for v in linhas if v[0]]

    def usuarios(self) -> list[str]:
        linhas = self._consultar(
            f"SELECT DISTINCT quem_id FROM {self._tabela(self._config.tabela_por_dia_e_usuario)}"
            " WHERE quem_tipo = 'usuario' AND ativo ORDER BY quem_id"
        )
        return [v[0] for v in linhas]


def resumos_do_ambiente(ambiente: Any) -> ResumosBigQuery | None:
    """A leitura configurada, ou `None` se o ambiente não diz onde as tabelas moram."""
    if "PAINEL_TABELA_POR_DIA_E_USUARIO" not in ambiente:
        return None
    config = ConfigDosResumos.do_ambiente(ambiente)
    return ResumosBigQuery(config, transporte_http(config.projeto))
