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
    (`programa`): o outro vem `None`. O tempo é a soma do que os vídeos concluídos levaram, e
    `videos_concluidos_com_tempo` quantos deles trazem o tempo (o fim gravado antes de o evento
    ter o campo não traz)."""

    dia: date
    quem_tipo: str | None
    quem_id: str | None
    programa: str | None
    videos_enviados: int
    videos_concluidos: int
    videos_falhos: int
    horas_concluidas: float
    segundos_de_processamento: int
    videos_concluidos_com_tempo: int
    buscas: int
    buscas_sem_resultado: int


@dataclass(frozen=True)
class CorrecaoDoDia:
    """As correções de um dia, de uma pessoa, num programa e de um tipo (`None` quando o
    evento não trouxe programa ou tipo)."""

    dia: date
    quem_tipo: str
    quem_id: str
    programa: str | None
    tipo_de_correcao: str | None
    correcoes: int


@dataclass(frozen=True)
class ChamadaDoDia:
    """As chamadas de API de um dia, de um sistema (ou pessoa), a um método e uma rota.
    Erro do cliente é o status 4xx; do servidor, o 5xx."""

    dia: date
    quem_tipo: str
    quem_id: str
    metodo: str | None
    rota: str | None
    chamadas: int
    erros_do_cliente: int
    erros_do_servidor: int


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

    def correcoes(
        self,
        desde: date | None,
        ate: date | None,
        programa: str | None,
        usuario: str | None,
    ) -> list[CorrecaoDoDia]:
        """Um dia, uma pessoa, um programa e um tipo de correção; os dois filtros se cruzam."""

    def chamadas(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[ChamadaDoDia]:
        """Um dia, um sistema (ou pessoa), um método e uma rota."""

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
        correcoes: Sequence[CorrecaoDoDia] = (),
        chamadas: Sequence[ChamadaDoDia] = (),
    ) -> None:
        self._acessos = list(acessos)
        self._programas = list(programas)
        self._uso = list(uso)
        self._correcoes = list(correcoes)
        self._chamadas = list(chamadas)

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

    def correcoes(
        self,
        desde: date | None,
        ate: date | None,
        programa: str | None,
        usuario: str | None,
    ) -> list[CorrecaoDoDia]:
        return [
            c
            for c in self._correcoes
            if (desde is None or c.dia >= desde)
            and (ate is None or c.dia <= ate)
            and (programa is None or c.programa == programa)
            and (usuario is None or c.quem_id == usuario)
        ]

    def chamadas(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[ChamadaDoDia]:
        return [
            c
            for c in self._chamadas
            if (desde is None or c.dia >= desde)
            and (ate is None or c.dia <= ate)
            and (usuario is None or c.quem_id == usuario)
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
    tabela_de_correcoes_por_dia: str
    tabela_de_chamadas_por_dia: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDosResumos":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            regiao=ambiente["BIGQUERY_REGIAO"],
            tabela_por_dia_e_usuario=ambiente["PAINEL_TABELA_POR_DIA_E_USUARIO"],
            tabela_por_dia_e_programa=ambiente["PAINEL_TABELA_POR_DIA_E_PROGRAMA"],
            tabela_de_correcoes_por_dia=ambiente["PAINEL_TABELA_CORRECOES_POR_DIA"],
            tabela_de_chamadas_por_dia=ambiente["PAINEL_TABELA_CHAMADAS_POR_DIA"],
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

    def _onde(
        self,
        desde: date | None,
        ate: date | None,
        filtros: Sequence[tuple[str, str | None]],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """O WHERE do período e dos filtros dados (os vazios não filtram), com parâmetros."""
        onde = ["TRUE"]
        parametros: list[dict[str, Any]] = []
        for nome, dia, comparacao in (("desde", desde, ">="), ("ate", ate, "<=")):
            if dia is not None:
                onde.append(f"dia {comparacao} @{nome}")
                parametros.append(_parametro(nome, dia.isoformat(), "DATE"))
        for coluna, valor in filtros:
            if valor is not None:
                onde.append(f"{coluna} = @{coluna}")
                parametros.append(_parametro(coluna, valor))
        return onde, parametros

    def correcoes(
        self,
        desde: date | None,
        ate: date | None,
        programa: str | None,
        usuario: str | None,
    ) -> list[CorrecaoDoDia]:
        onde, parametros = self._onde(
            desde, ate, [("programa", programa), ("quem_id", usuario)]
        )
        linhas = self._consultar(
            "SELECT CAST(dia AS STRING), quem_tipo, quem_id, programa, tipo_de_correcao,"
            " correcoes\n"
            f"FROM {self._tabela(self._config.tabela_de_correcoes_por_dia)}\n"
            f"WHERE {' AND '.join(onde)}",
            parametros,
        )
        return [
            CorrecaoDoDia(
                dia=date.fromisoformat(v[0]),
                quem_tipo=v[1],
                quem_id=v[2],
                programa=v[3],
                tipo_de_correcao=v[4],
                correcoes=int(v[5]),
            )
            for v in linhas
        ]

    def chamadas(
        self, desde: date | None, ate: date | None, usuario: str | None
    ) -> list[ChamadaDoDia]:
        onde, parametros = self._onde(desde, ate, [("quem_id", usuario)])
        linhas = self._consultar(
            "SELECT CAST(dia AS STRING), quem_tipo, quem_id, metodo, rota, chamadas,"
            " erros_do_cliente, erros_do_servidor\n"
            f"FROM {self._tabela(self._config.tabela_de_chamadas_por_dia)}\n"
            f"WHERE {' AND '.join(onde)}",
            parametros,
        )
        return [
            ChamadaDoDia(
                dia=date.fromisoformat(v[0]),
                quem_tipo=v[1],
                quem_id=v[2],
                metodo=v[3],
                rota=v[4],
                chamadas=int(v[5]),
                erros_do_cliente=int(v[6]),
                erros_do_servidor=int(v[7]),
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
        onde, parametros = self._onde(desde, ate, [filtro])
        linhas = self._consultar(
            f"SELECT CAST(dia AS STRING), {chaves}, videos_enviados, videos_concluidos,"
            " videos_falhos, horas_concluidas, segundos_de_processamento,"
            " videos_concluidos_com_tempo, buscas, buscas_sem_resultado\n"
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
                videos_concluidos_com_tempo=int(v[9]),
                buscas=int(v[10]),
                buscas_sem_resultado=int(v[11]),
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
