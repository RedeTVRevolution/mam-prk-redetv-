"""O tempo de revisão da aba Revisão do painel (#467), agregado no BigQuery.

As medidas (uma por pessoa e vídeo, `api/revisao.py`) moram no Firestore e crescem com o uso;
a aba as lia todas e cruzava com `jobs.listar()` em Python. Agora cada medida também vai para a
tabela `revisao_do_painel` (a web grava a cada pulso; `make preencher-revisao-do-painel` traz
as que já existiam) e uma consulta só junta essa tabela com a dos Jobs (#454) e devolve as
linhas já agrupadas: o que a API carrega depende do número de pessoas e programas, não de
Jobs nem de medidas.
"""

import json
import logging
import os
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from google.cloud import firestore

from api.copia_bigquery import Transporte, _parametro, transporte_http
from api.jobs import RepositorioDeJobs
from api.nuvem import RepositorioDeRevisaoFirestore
from api.relatorios import linhas_da_consulta
from api.revisao import Medida, Pulso, RepositorioDeRevisao

log = logging.getLogger(__name__)

MEDIDAS_POR_MERGE = 500


@dataclass(frozen=True)
class RevisaoNoVideo:
    """O tempo ativo de uma pessoa num vídeo (o acumulado dela nele, não só o do período: a
    medida guarda só o total), o programa do Job e a duração do vídeo (a do Job, como no
    `GET /v1/jobs/{id}/revisao`; sem ela, a que a medida trouxe)."""

    job_id: str
    uid: str
    email: str
    programa: str | None
    ativo_s: float
    duracao_s: float | None


@dataclass(frozen=True)
class NumerosAgregados:
    """Os vídeos de um grupo: o tempo ativo, o que cabe nos vídeos com duração, quantos
    vídeos e as horas deles (a duração conta uma vez por vídeo, mesmo revisado por duas
    pessoas)."""

    ativo_s: float
    ativo_com_duracao_s: float
    videos: int
    horas: float


@dataclass(frozen=True)
class RevisaoAgregada:
    total: NumerosAgregados
    por_pessoa: dict[tuple[str, str], NumerosAgregados]
    por_programa: dict[str | None, NumerosAgregados]
    por_pessoa_e_programa: dict[tuple[str, str, str], NumerosAgregados]


SEM_REVISAO = NumerosAgregados(0.0, 0.0, 0, 0.0)


class TempoDeRevisao(Protocol):
    def tempo(
        self,
        inicio: datetime | None,
        fim: datetime | None,
        programa: str | None,
        usuario: str | None,
    ) -> RevisaoAgregada:
        """As medidas cujo último pulso está em `[inicio, fim)`, agrupadas."""


def _numeros(medidas: list[RevisaoNoVideo]) -> NumerosAgregados:
    duracao: dict[str, float] = {}
    for m in medidas:
        if m.duracao_s:
            duracao[m.job_id] = max(duracao.get(m.job_id, 0), m.duracao_s)
    return NumerosAgregados(
        ativo_s=sum(m.ativo_s for m in medidas),
        ativo_com_duracao_s=sum(m.ativo_s for m in medidas if m.job_id in duracao),
        videos=len({m.job_id for m in medidas}),
        horas=sum(duracao.values()) / 3600,
    )


def agregar(medidas: list[RevisaoNoVideo]) -> RevisaoAgregada:
    """O agrupamento que o BigQuery faz, em memória (o dublê e a conferência da consulta)."""
    pessoas: dict[tuple[str, str], list[RevisaoNoVideo]] = defaultdict(list)
    programas: dict[str | None, list[RevisaoNoVideo]] = defaultdict(list)
    pessoas_e_programas: dict[tuple[str, str, str], list[RevisaoNoVideo]] = defaultdict(
        list
    )
    for m in medidas:
        pessoas[(m.uid, m.email)].append(m)
        programas[m.programa].append(m)
        pessoas_e_programas[(m.uid, m.email, m.programa or "")].append(m)
    return RevisaoAgregada(
        total=_numeros(medidas),
        por_pessoa={k: _numeros(v) for k, v in pessoas.items()},
        por_programa={k: _numeros(v) for k, v in programas.items()},
        por_pessoa_e_programa={k: _numeros(v) for k, v in pessoas_e_programas.items()},
    )


class RevisaoEmMemoria:
    """Dublê da consulta: as medidas do repositório cruzadas com os Jobs, pela mesma regra
    (Job desconhecido fica de fora; a duração é a do Job, senão a da medida)."""

    def __init__(self, revisao: RepositorioDeRevisao, jobs: RepositorioDeJobs) -> None:
        self._revisao = revisao
        self._jobs = jobs

    def tempo(
        self,
        inicio: datetime | None,
        fim: datetime | None,
        programa: str | None,
        usuario: str | None,
    ) -> RevisaoAgregada:
        medidas: list[RevisaoNoVideo] = []
        for m in self._revisao.todas(inicio):
            job = self._jobs.obter(m.job_id)
            if (
                job is not None
                and (fim is None or m.ultimo_pulso < fim)
                and (programa is None or job.programa == programa)
                and (usuario is None or m.uid == usuario)
            ):
                medidas.append(
                    RevisaoNoVideo(
                        m.job_id,
                        m.uid,
                        m.email,
                        job.programa,
                        m.ativo_s,
                        job.duracao_s or m.duracao_s,
                    )
                )
        return agregar(medidas)


@dataclass(frozen=True)
class ConfigDaRevisao:
    projeto: str
    dataset: str
    regiao: str
    tabela_da_revisao: str
    tabela_dos_jobs: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDaRevisao":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            regiao=ambiente["BIGQUERY_REGIAO"],
            tabela_da_revisao=ambiente["BIGQUERY_TABELA_DE_REVISAO"],
            tabela_dos_jobs=ambiente["BIGQUERY_TABELA_DE_JOBS"],
        )


def _grao(chaves: list[str]) -> str:
    """Um nível de agrupamento: primeiro por vídeo (para a duração contar uma vez), depois
    pelas `chaves`. As colunas são sempre as mesmas, as chaves que faltam vão como NULL."""
    todas = ["uid", "email", "programa"]
    nome = "_".join(chaves) or "total"
    vazias = ", ".join(f"CAST(NULL AS STRING) AS {c}" for c in todas if c not in chaves)
    colunas = ", ".join(chaves)
    return (
        f"SELECT '{nome}' AS grao, {colunas + ', ' if chaves else ''}{vazias + ', ' if vazias else ''}"
        # Sem GROUP BY, o total volta uma linha mesmo sem medida no período, com as somas
        # NULL: o IFNULL as faz 0, como no agregado em memória.
        "IFNULL(SUM(ativo_s), 0) AS ativo_s,"
        " IFNULL(SUM(IF(duracao_s IS NOT NULL, ativo_s, 0)), 0) AS ativo_com_duracao_s,"
        " COUNT(*) AS videos, IFNULL(SUM(duracao_s), 0) / 3600 AS horas\n"
        "FROM (SELECT job_id"
        f"{', ' + colunas if chaves else ''}, SUM(ativo_s) AS ativo_s,"
        " MAX(duracao_s) AS duracao_s FROM por_video"
        f" GROUP BY job_id{', ' + colunas if chaves else ''})"
        + (f"\nGROUP BY {colunas}" if chaves else "")
    )


GRAOS = {
    "total": [],
    "uid_email": ["uid", "email"],
    "programa": ["programa"],
    "uid_email_programa": ["uid", "email", "programa"],
}


class RevisaoBigQuery:
    """A leitura real: uma consulta junta as medidas com a tabela dos Jobs do painel e devolve
    os quatro agrupamentos que a aba usa (total, pessoa, programa e pessoa × programa)."""

    def __init__(self, config: ConfigDaRevisao, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def consulta(
        self,
        inicio: datetime | None,
        fim: datetime | None,
        programa: str | None,
        usuario: str | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        c = self._config
        onde = ["TRUE"]
        parametros: list[dict[str, Any]] = []
        if inicio is not None:
            parametros.append(_parametro("inicio", inicio.isoformat(), "TIMESTAMP"))
            onde.append("r.ultimo_pulso >= @inicio")
        if fim is not None:
            parametros.append(_parametro("fim", fim.isoformat(), "TIMESTAMP"))
            onde.append("r.ultimo_pulso < @fim")
        if programa is not None:
            parametros.append(_parametro("programa", programa))
            onde.append("j.programa = @programa")
        if usuario is not None:
            parametros.append(_parametro("usuario", usuario))
            onde.append("r.uid = @usuario")
        revisao = f"`{c.projeto}.{c.dataset}.{c.tabela_da_revisao}`"
        jobs = f"`{c.projeto}.{c.dataset}.{c.tabela_dos_jobs}`"
        sql = (
            "WITH por_video AS (\n"
            "  SELECT r.job_id, r.uid, IFNULL(r.email, '') AS email, j.programa, r.ativo_s,\n"
            "    IF(IFNULL(j.duracao_ms, 0) > 0, j.duracao_ms / 1000,"
            " NULLIF(IFNULL(r.duracao_s, 0), 0)) AS duracao_s\n"
            f"  FROM {revisao} AS r JOIN {jobs} AS j ON j.id = r.job_id\n"
            f"  WHERE {' AND '.join(onde)}\n"
            ")\n" + "\nUNION ALL\n".join(_grao(g) for g in GRAOS.values())
        )
        return sql, parametros

    def tempo(
        self,
        inicio: datetime | None,
        fim: datetime | None,
        programa: str | None,
        usuario: str | None,
    ) -> RevisaoAgregada:
        sql, parametros = self.consulta(inicio, fim, programa, usuario)
        linhas = linhas_da_consulta(
            self._transporte, self._config.regiao, sql, parametros, "tempo de revisão"
        )
        total = SEM_REVISAO
        pessoas: dict[tuple[str, str], NumerosAgregados] = {}
        programas: dict[str | None, NumerosAgregados] = {}
        pessoas_e_programas: dict[tuple[str, str, str], NumerosAgregados] = {}
        for grao, uid, email, prog, ativo, com_duracao, videos, horas in linhas:
            numeros = NumerosAgregados(
                float(ativo), float(com_duracao), int(videos), float(horas)
            )
            if grao == "total":
                total = numeros
            elif grao == "uid_email":
                pessoas[(uid, email)] = numeros
            elif grao == "programa":
                programas[prog] = numeros
            else:
                pessoas_e_programas[(uid, email, prog or "")] = numeros
        return RevisaoAgregada(total, pessoas, programas, pessoas_e_programas)


class TabelaDaRevisao(Protocol):
    def gravar(self, medidas: list[Medida]) -> None:
        """Insere as medidas; a de (vídeo, pessoa) que já havia é trocada se a nova não
        for mais antiga."""


class TabelaDaRevisaoEmMemoria:
    def __init__(self) -> None:
        self.por_chave: dict[tuple[str, str], Medida] = {}

    def gravar(self, medidas: list[Medida]) -> None:
        for m in medidas:
            antiga = self.por_chave.get((m.job_id, m.uid))
            if antiga is None or m.ultimo_pulso >= antiga.ultimo_pulso:
                self.por_chave[(m.job_id, m.uid)] = m


def _json_da_medida(m: Medida) -> dict[str, Any]:
    return {
        "job_id": m.job_id,
        "uid": m.uid,
        "email": m.email,
        "ativo_s": m.ativo_s,
        "duracao_s": m.duracao_s,
        "ultimo_pulso": m.ultimo_pulso.isoformat(),
    }


class TabelaDaRevisaoBigQuery:
    """A tabela real: um MERGE por lote troca a linha de cada (vídeo, pessoa)."""

    def __init__(self, config: ConfigDaRevisao, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def gravar(self, medidas: list[Medida]) -> None:
        c = self._config
        tabela = f"`{c.projeto}.{c.dataset}.{c.tabela_da_revisao}`"
        consulta = f"""
MERGE {tabela} AS t
USING (
  SELECT
    JSON_VALUE(l, '$.job_id') AS job_id,
    JSON_VALUE(l, '$.uid') AS uid,
    JSON_VALUE(l, '$.email') AS email,
    CAST(JSON_VALUE(l, '$.ativo_s') AS FLOAT64) AS ativo_s,
    CAST(JSON_VALUE(l, '$.duracao_s') AS FLOAT64) AS duracao_s,
    TIMESTAMP(JSON_VALUE(l, '$.ultimo_pulso')) AS ultimo_pulso
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@linhas))) AS l
) AS s
ON t.job_id = s.job_id AND t.uid = s.uid
WHEN MATCHED AND s.ultimo_pulso >= t.ultimo_pulso THEN UPDATE SET
  email = s.email, ativo_s = s.ativo_s, duracao_s = s.duracao_s,
  ultimo_pulso = s.ultimo_pulso
WHEN NOT MATCHED THEN INSERT
  (job_id, uid, email, ativo_s, duracao_s, ultimo_pulso)
VALUES
  (s.job_id, s.uid, s.email, s.ativo_s, s.duracao_s, s.ultimo_pulso)
"""
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 120_000,
                "queryParameters": [
                    _parametro(
                        "linhas",
                        json.dumps(
                            [_json_da_medida(m) for m in medidas], ensure_ascii=False
                        ),
                    )
                ],
            }
        )
        if not resposta.get("jobComplete", False):
            raise RuntimeError(f"carga de {len(medidas)} medidas não terminou no prazo")


class RepositorioDeRevisaoEspelhado:
    """O repositório do Firestore com cada medida copiada para a tabela do painel. O
    Firestore continua sendo a verdade: se a cópia falha, o pulso vale do mesmo jeito (a
    próxima medida do mesmo vídeo e pessoa ou o `make preencher-revisao-do-painel` a
    refaz)."""

    def __init__(self, revisao: RepositorioDeRevisao, tabela: TabelaDaRevisao) -> None:
        self._revisao = revisao
        self._tabela = tabela

    def aplicar(self, pulso: Pulso, limite_s: float) -> Medida:
        medida = self._revisao.aplicar(pulso, limite_s)
        try:
            self._tabela.gravar([medida])
        except Exception:
            log.exception(
                "cópia da medida de %s em %s para o painel falhou",
                pulso.uid,
                pulso.job_id,
            )
        return medida

    def do_video(self, job_id: str) -> list[Medida]:
        return self._revisao.do_video(job_id)

    def todas(self, desde: datetime | None = None) -> list[Medida]:
        return self._revisao.todas(desde)


def _em_lotes(medidas: Iterable[Medida], tamanho: int) -> Iterator[list[Medida]]:
    lote: list[Medida] = []
    for m in medidas:
        lote.append(m)
        if len(lote) == tamanho:
            yield lote
            lote = []
    if lote:
        yield lote


def preencher(
    revisao: RepositorioDeRevisao,
    tabela: TabelaDaRevisao,
    por_lote: int = MEDIDAS_POR_MERGE,
) -> int:
    """Grava as medidas do repositório e devolve quantas. Passada única de linha de comando;
    o MERGE por (vídeo, pessoa) faz repetir dar o mesmo resultado."""
    total = 0
    for lote in _em_lotes(revisao.todas(), por_lote):
        tabela.gravar(lote)
        total += len(lote)
    return total


def tabela_do_ambiente(ambiente: Any) -> TabelaDaRevisaoBigQuery | None:
    """A tabela configurada, ou `None` se o ambiente não diz onde ela mora."""
    if "BIGQUERY_TABELA_DE_REVISAO" not in ambiente:
        return None
    config = ConfigDaRevisao.do_ambiente(ambiente)
    return TabelaDaRevisaoBigQuery(config, transporte_http(config.projeto))


def revisao_do_ambiente(ambiente: Any) -> RevisaoBigQuery | None:
    """A leitura configurada, ou `None` se o ambiente não diz onde a tabela mora."""
    if "BIGQUERY_TABELA_DE_REVISAO" not in ambiente:
        return None
    config = ConfigDaRevisao.do_ambiente(ambiente)
    return RevisaoBigQuery(config, transporte_http(config.projeto))


def main() -> int:
    config = ConfigDaRevisao.do_ambiente(os.environ)
    total = preencher(
        RepositorioDeRevisaoFirestore(firestore.Client(project=config.projeto)),
        TabelaDaRevisaoBigQuery(config, transporte_http(config.projeto)),
    )
    print(f"{total} medidas gravadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
