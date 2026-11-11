"""A aba Custo do painel da diretoria (#285): o custo da exportação do faturamento, cruzado
com os Jobs pelos rótulos de custo. O cruzamento e a soma rodam dentro do BigQuery (#466): a
exportação do faturamento junta com a tabela dos Jobs do painel (#454) e a API recebe só as
linhas já agregadas (mês × programa × dono), sem ler a coleção `jobs`.

Cada chamada ao Gemini leva o rótulo `job_id` (e, fora a análise principal, `etapa`); é por ele
que o custo vira custo de um Job. O que não tem rótulo, ou tem um `job_id` que não é de nenhum
Job do painel (a busca usa `busca`; o Job criado há poucos minutos, que a tabela dos Jobs
ainda não tem), e o custo fixo (a réplica do índice, os
serviços de rede) entram como custo **sem dono**, no mês em que foram cobrados. Os Jobs do
Cloud Run não levam o id do Job: o Cloud Run não deixa rotular cada execução, então o custo
deles cai aqui também, e o dos embeddings, que vão sem rótulo.

O custo de um Job conta no mês em que o Job foi criado (dia de São Paulo), e o filtro de
período compara esse dia; o custo sem dono conta no dia em que foi cobrado. Com filtro de
programa ou de usuário só entra o custo dos Jobs: o sem dono não tem nem um nem outro. O custo
é o líquido dos créditos da exportação (`cost` mais `credits.amount`). As horas de vídeo e o
custo por hora são dos Jobs concluídos, mas o custo de um Job que falhou entra no total: ele foi
pago.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from api.copia_bigquery import Transporte, _parametro, transporte_http
from api.eventos_de_uso import Quem
from api.jobs import Job
from api.qualidade_do_painel import SAO_PAULO
from api.relatorios import linhas_da_consulta

# A chamada da análise principal só leva o `job_id`; as outras etapas levam `etapa`.
ETAPA_DA_ANALISE = "analise"


@dataclass(frozen=True)
class CustoDoDia:
    """O custo de um dia (de São Paulo) de um serviço, com os rótulos de custo da exportação:
    `job_id` e `etapa` são `None` onde a cobrança não os tem."""

    dia: date
    job_id: str | None
    etapa: str | None
    servico: str | None
    custo: float
    moeda: str


@dataclass(frozen=True)
class FiltroDeCusto:
    desde: date | None
    ate: date | None
    programa: str | None
    usuario: str | None

    @property
    def com_dono(self) -> bool:
        """Com programa ou usuário só entra o custo dos Jobs: o sem dono não tem nem um nem outro."""
        return self.programa is not None or self.usuario is not None


@dataclass(frozen=True)
class CustoDosJobs:
    """O custo dos Jobs de um mês de criação (de São Paulo), programa e dono. `videos` e
    `horas` são dos Jobs concluídos com custo."""

    mes: str
    programa: str | None
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    custo: float
    videos: int
    horas: float


@dataclass(frozen=True)
class CustoDaEtapa:
    etapa: str
    custo: float


@dataclass(frozen=True)
class CustoSemDono:
    mes: str
    servico: str | None
    custo: float


@dataclass(frozen=True)
class BaseDeCusto:
    """O que a fonte devolve, já filtrado e somado: os Jobs do período (com programa e usuário
    pedidos), o custo por etapa desses Jobs e o custo sem dono do período (só sem filtro de
    programa ou de usuário). `moedas` são todas as da exportação: mais de uma é erro."""

    dos_jobs: list[CustoDosJobs]
    por_etapa: list[CustoDaEtapa]
    sem_dono: list[CustoSemDono]
    moedas: frozenset[str]
    # O dia da última linha do faturamento no período: a exportação atrasa de 1 a 2 dias.
    faturamento_ate: date | None = None

    @property
    def moeda(self) -> str | None:
        return next(iter(self.moedas), None)


class FonteDeCusto(Protocol):
    def custos(self, filtro: FiltroDeCusto) -> BaseDeCusto:
        """O custo do `filtro`, agregado. O custo de um Job conta no mês de criação dele; a
        exportação lida começa em `filtro.desde` (o custo de um Job vem até depois do dia em
        que ele foi criado, então o fim do período não corta a exportação)."""


def _dia_do_job(job: Job) -> date:
    return job.criado_em.astimezone(SAO_PAULO).date()


def _mes(dia: date) -> str:
    return f"{dia.year:04d}-{dia.month:02d}"


def _quem(job: Job) -> Quem:
    """Quem enviou: o sistema, ou a pessoa (o uid), como nas tabelas de uso."""
    return ("sistema", job.sistema) if job.sistema else ("usuario", job.criado_por)


class CustoEmMemoria:
    """Dublê do BigQuery: as linhas do faturamento e os Jobs dados, agregados em Python com a
    mesma regra da consulta."""

    def __init__(
        self, linhas: Sequence[CustoDoDia] = (), jobs: Iterable[Job] = ()
    ) -> None:
        self._linhas = list(linhas)
        self._jobs = {j.id: j for j in jobs}

    def custos(self, filtro: FiltroDeCusto) -> BaseDeCusto:
        desde, ate = filtro.desde, filtro.ate
        linhas = [c for c in self._linhas if desde is None or c.dia >= desde]

        def no_periodo(dia: date) -> bool:
            return (desde is None or dia >= desde) and (ate is None or dia <= ate)

        por_job: dict[str, dict[str | None, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        sem_dono: dict[tuple[str, str | None], float] = defaultdict(float)
        for linha in linhas:
            job = self._jobs.get(linha.job_id) if linha.job_id else None
            if job is None:
                if not filtro.com_dono and no_periodo(linha.dia):
                    sem_dono[(_mes(linha.dia), linha.servico)] += linha.custo
            else:
                por_job[job.id][linha.etapa] += linha.custo
        dos_jobs: dict[tuple[str, str | None, Quem], list[float]] = {}
        por_etapa: dict[str, float] = defaultdict(float)
        for id, etapas in por_job.items():
            job = self._jobs[id]
            quem = _quem(job)
            if (
                not no_periodo(_dia_do_job(job))
                or (filtro.programa is not None and job.programa != filtro.programa)
                or (filtro.usuario is not None and quem[1] != filtro.usuario)
            ):
                continue
            concluido = job.estado == "concluido"
            soma = dos_jobs.setdefault(
                (_mes(_dia_do_job(job)), job.programa, quem), [0.0, 0, 0.0]
            )
            soma[0] += sum(etapas.values())
            soma[1] += 1 if concluido else 0
            soma[2] += (job.duracao_s or 0) / 3600 if concluido else 0.0
            for etapa, custo in etapas.items():
                por_etapa[etapa or ETAPA_DA_ANALISE] += custo
        return BaseDeCusto(
            dos_jobs=[
                CustoDosJobs(mes, programa, tipo, quem_id, *soma)  # type: ignore[arg-type]
                for (mes, programa, (tipo, quem_id)), soma in dos_jobs.items()
            ],
            por_etapa=[CustoDaEtapa(e, c) for e, c in por_etapa.items()],
            sem_dono=[CustoSemDono(m, s, c) for (m, s), c in sem_dono.items()],
            moedas=frozenset(c.moeda for c in linhas),
            faturamento_ate=max(
                (c.dia for c in linhas if no_periodo(c.dia)), default=None
            ),
        )


@dataclass(frozen=True)
class ConfigDoFaturamento:
    projeto: str
    dataset: str
    tabela: str
    regiao: str
    dataset_dos_jobs: str
    tabela_dos_jobs: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDoFaturamento":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["FATURAMENTO_DATASET"],
            tabela=ambiente["FATURAMENTO_TABELA"],
            regiao=ambiente["BIGQUERY_REGIAO"],
            dataset_dos_jobs=ambiente["BIGQUERY_DATASET"],
            tabela_dos_jobs=ambiente["BIGQUERY_TABELA_DE_JOBS"],
        )


def _rotulo(chave: str) -> str:
    return f"(SELECT value FROM UNNEST(labels) WHERE key = '{chave}' LIMIT 1)"


def _texto(valor: Any) -> str | None:
    return valor or None


class FaturamentoBigQuery:
    """A leitura real: uma consulta junta a exportação do faturamento (custo detalhado) com a
    tabela dos Jobs do painel e devolve só as linhas agregadas. REST com o mesmo transporte da
    cópia."""

    def __init__(self, config: ConfigDoFaturamento, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def consulta(self, filtro: FiltroDeCusto) -> tuple[str, list[dict[str, Any]]]:
        c = self._config
        fuso = f"'{SAO_PAULO.key}'"
        dia = f"DATE(usage_start_time, {fuso})"
        parametros: list[dict[str, Any]] = []
        onde_do_faturamento = "TRUE"
        # O período do Job vem do instante de criação, que é a partição da tabela dos Jobs.
        onde_do_job = ["TRUE"]
        onde_do_custo_sem_dono = ["TRUE"]
        if filtro.desde is not None:
            parametros.append(_parametro("desde", filtro.desde.isoformat(), "DATE"))
            # A partição vem do instante do uso, em UTC: sem folga, pois o dia de SP começa
            # às 03:00Z. O `ate` não limita a partição (o uso do último dia chega no seguinte).
            onde_do_faturamento = f"{dia} >= @desde AND _PARTITIONTIME >= TIMESTAMP(@desde)"
            onde_do_job.append(f"j.criado_em >= TIMESTAMP(@desde, {fuso})")
            onde_do_custo_sem_dono.append("l.dia >= @desde")
        if filtro.ate is not None:
            parametros.append(_parametro("ate", filtro.ate.isoformat(), "DATE"))
            onde_do_job.append(
                f"j.criado_em < TIMESTAMP(DATE_ADD(@ate, INTERVAL 1 DAY), {fuso})"
            )
            onde_do_custo_sem_dono.append("l.dia <= @ate")
        if filtro.programa is not None:
            parametros.append(_parametro("programa", filtro.programa, "STRING"))
            onde_do_job.append("j.programa = @programa")
        if filtro.usuario is not None:
            parametros.append(_parametro("usuario", filtro.usuario, "STRING"))
            onde_do_job.append("j.quem_id = @usuario")
        jobs = f"`{c.projeto}.{c.dataset_dos_jobs}.{c.tabela_dos_jobs}`"
        mes = "FORMAT_DATE('%Y-%m', {})"
        data_do_job = f"DATE(j.criado_em, {fuso})"
        # As colunas das quatro partes são as mesmas: tipo, mes, programa, quem_tipo, quem_id,
        # rotulo (etapa ou serviço), custo, videos, horas, moeda.
        partes = [
            (
                "SELECT 'jobs' AS tipo, mes, programa, quem_tipo, quem_id,"
                " CAST(NULL AS STRING) AS rotulo, SUM(custo) AS custo,"
                " COUNTIF(estado = 'concluido') AS videos,"
                " SUM(IF(estado = 'concluido', IFNULL(duracao_ms, 0), 0)) / 3600000"
                " AS horas, moeda\n"
                "FROM por_job GROUP BY mes, programa, quem_tipo, quem_id, moeda"
            ),
            (
                "SELECT 'etapa', NULL, NULL, NULL, NULL, IFNULL(NULLIF(etapa, ''),"
                f" '{ETAPA_DA_ANALISE}')"
                " AS rotulo, SUM(custo), 0, 0.0, moeda\n"
                "FROM dos_jobs GROUP BY rotulo, moeda"
            ),
            (
                "SELECT 'moeda', NULL, NULL, NULL, NULL, NULL, 0.0, 0, 0.0, moeda\n"
                "FROM linhas GROUP BY moeda"
            ),
            # O dia vai em `rotulo`, como texto, na coluna que as outras partes já têm.
            (
                "SELECT 'ate', NULL, NULL, NULL, NULL, CAST(MAX(l.dia) AS STRING),"
                " 0.0, 0, 0.0, l.moeda\n"
                "FROM linhas AS l\n"
                f"WHERE {' AND '.join(onde_do_custo_sem_dono)}\n"
                "GROUP BY l.moeda"
            ),
        ]
        if not filtro.com_dono:
            partes.append(
                f"SELECT 'sem_dono', {mes.format('l.dia')}, NULL, NULL, NULL,"
                " l.servico AS rotulo, SUM(l.custo), 0, 0.0, l.moeda\n"
                "FROM linhas AS l\n"
                f"WHERE {' AND '.join(onde_do_custo_sem_dono)}\n"
                f"  AND (l.job_id IS NULL OR l.job_id NOT IN (SELECT id FROM {jobs}))\n"
                f"GROUP BY {mes.format('l.dia')}, rotulo, l.moeda"
            )
        return (
            "WITH linhas AS (\n"
            f"  SELECT {dia} AS dia, {_rotulo('job_id')} AS job_id,"
            f" {_rotulo('etapa')} AS etapa, service.description AS servico,"
            " SUM(cost + IFNULL((SELECT SUM(cr.amount) FROM UNNEST(credits) cr), 0))"
            " AS custo, currency AS moeda\n"
            f"  FROM `{c.projeto}.{c.dataset}.{c.tabela}`\n"
            f"  WHERE {onde_do_faturamento}\n"
            "  GROUP BY dia, job_id, etapa, servico, moeda\n"
            "),\n"
            "dos_jobs AS (\n"
            "  SELECT l.etapa, l.custo, l.moeda, j.id, j.programa, j.quem_tipo, j.quem_id,"
            " j.estado, j.duracao_ms,"
            f" {mes.format(data_do_job)} AS mes\n"
            f"  FROM linhas AS l JOIN {jobs} AS j ON j.id = l.job_id\n"
            f"  WHERE {' AND '.join(onde_do_job)}\n"
            "),\n"
            "por_job AS (\n"
            "  SELECT id, mes, programa, quem_tipo, quem_id, estado, duracao_ms, moeda,"
            " SUM(custo) AS custo\n"
            "  FROM dos_jobs\n"
            "  GROUP BY id, mes, programa, quem_tipo, quem_id, estado, duracao_ms, moeda\n"
            ")\n" + "\nUNION ALL\n".join(partes),
            parametros,
        )

    def custos(self, filtro: FiltroDeCusto) -> BaseDeCusto:
        sql, parametros = self.consulta(filtro)
        linhas = linhas_da_consulta(
            self._transporte, self._config.regiao, sql, parametros, "faturamento"
        )
        dos_jobs: list[CustoDosJobs] = []
        por_etapa: dict[str, float] = defaultdict(float)
        sem_dono: list[CustoSemDono] = []
        moedas: set[str] = set()
        faturamento_ate: date | None = None
        for (
            tipo,
            mes,
            programa,
            quem_tipo,
            quem_id,
            rotulo,
            custo,
            videos,
            horas,
            moeda,
        ) in linhas:
            moedas.add(moeda)
            if tipo == "jobs":
                dos_jobs.append(
                    CustoDosJobs(
                        mes,
                        _texto(programa),
                        quem_tipo,
                        quem_id,
                        float(custo),
                        int(videos),
                        float(horas),
                    )
                )
            elif tipo == "etapa":
                por_etapa[rotulo] += float(custo)
            elif tipo == "ate" and rotulo:
                dia = date.fromisoformat(rotulo)
                faturamento_ate = max(faturamento_ate or dia, dia)
            elif tipo == "sem_dono":
                sem_dono.append(CustoSemDono(mes, _texto(rotulo), float(custo)))
        return BaseDeCusto(
            dos_jobs=dos_jobs,
            por_etapa=[CustoDaEtapa(e, c) for e, c in por_etapa.items()],
            sem_dono=sem_dono,
            moedas=frozenset(moedas),
            faturamento_ate=faturamento_ate,
        )


def faturamento_do_ambiente(ambiente: Any) -> FaturamentoBigQuery | None:
    """A leitura configurada, ou `None` se o ambiente não diz onde o faturamento mora."""
    if "FATURAMENTO_DATASET" not in ambiente:
        return None
    config = ConfigDoFaturamento.do_ambiente(ambiente)
    return FaturamentoBigQuery(config, transporte_http(config.projeto))


class NumerosDeCusto(BaseModel):
    custo: float
    videos: int
    horas_de_video: float
    custo_por_hora: float | None


class TotalDeCusto(NumerosDeCusto):
    custo_dos_jobs: float
    custo_sem_dono: float


class MesDeCusto(TotalDeCusto):
    mes: str


class QuemDeCusto(NumerosDeCusto):
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    email: str | None


class EtapaDeCusto(BaseModel):
    etapa: str
    custo: float


class ServicoSemDono(BaseModel):
    servico: str | None
    custo: float


class RelatorioDeCusto(BaseModel):
    """`custo` é o líquido dos créditos, na `moeda` da exportação (`None` sem nenhuma linha).
    `por_quem` e `por_etapa` são só dos Jobs; o que não tem dono vem em `sem_dono_por_servico`."""

    desde: date | None
    ate: date | None
    programa: str | None
    usuario: str | None
    moeda: str | None
    faturamento_ate: date | None
    total: TotalDeCusto
    por_mes: list[MesDeCusto]
    por_quem: list[QuemDeCusto]
    por_etapa: list[EtapaDeCusto]
    sem_dono_por_servico: list[ServicoSemDono]


COLUNAS_DO_CSV_DE_CUSTO = (
    "mes",
    "quem_tipo",
    "quem_id",
    "email",
    "programa",
    "detalhe",
    "videos",
    "horas_de_video",
    "custo",
)


def centavos(valor: float) -> float:
    """O custo em centavos, sem sinal no zero: o líquido dos créditos pode ser um negativo de fração
    de centavo, e `round(-0.0003, 2)` dá `-0.0`, que o painel escreveria "-R$ 0,00". Todo custo que
    sai daqui (relatório e CSV) passa por esta função."""
    return round(valor, 2) + 0.0


def _por_hora(custo: float, horas: float) -> float | None:
    return round(custo / horas, 4) + 0.0 if horas > 0 else None


def _numeros(linhas: Sequence[CustoDosJobs]) -> dict[str, Any]:
    custo = sum(c.custo for c in linhas)
    horas = sum(c.horas for c in linhas)
    return {
        "custo": centavos(custo),
        "videos": sum(c.videos for c in linhas),
        "horas_de_video": round(horas, 4),
        "custo_por_hora": _por_hora(custo, horas),
    }


def confere_a_moeda(base: BaseDeCusto) -> BaseDeCusto:
    if len(base.moedas) > 1:
        raise RuntimeError(
            f"o faturamento tem mais de uma moeda ({', '.join(sorted(base.moedas))})"
        )
    return base


def relatorio_de_custo(
    base: BaseDeCusto,
    emails: dict[str, str],
    desde: date | None,
    ate: date | None,
    programa: str | None,
    usuario: str | None,
) -> RelatorioDeCusto:
    jobs_do_mes: dict[str, list[CustoDosJobs]] = defaultdict(list)
    for c in base.dos_jobs:
        jobs_do_mes[c.mes].append(c)
    sem_dono_do_mes: dict[str, list[CustoSemDono]] = defaultdict(list)
    for s in base.sem_dono:
        sem_dono_do_mes[s.mes].append(s)

    def total(
        jobs: Sequence[CustoDosJobs], sem_dono: Sequence[CustoSemDono]
    ) -> dict[str, Any]:
        # O custo por hora é o dos Jobs: o custo sem dono não tem vídeo.
        numeros = _numeros(jobs)
        dos_jobs = sum(c.custo for c in jobs)
        sem = sum(s.custo for s in sem_dono)
        return numeros | {
            "custo": centavos(dos_jobs + sem),
            "custo_dos_jobs": centavos(dos_jobs),
            "custo_sem_dono": centavos(sem),
        }

    do_quem: dict[Quem, list[CustoDosJobs]] = defaultdict(list)
    for c in base.dos_jobs:
        do_quem[(c.quem_tipo, c.quem_id)].append(c)
    por_servico: dict[str | None, float] = defaultdict(float)
    for s in base.sem_dono:
        por_servico[s.servico] += s.custo

    return RelatorioDeCusto(
        desde=desde,
        ate=ate,
        programa=programa,
        usuario=usuario,
        moeda=base.moeda,
        faturamento_ate=base.faturamento_ate,
        total=TotalDeCusto(**total(base.dos_jobs, base.sem_dono)),
        por_mes=[
            MesDeCusto(
                mes=mes, **total(jobs_do_mes.get(mes, []), sem_dono_do_mes.get(mes, []))
            )
            for mes in sorted(set(jobs_do_mes) | set(sem_dono_do_mes))
        ],
        por_quem=[
            QuemDeCusto(
                quem_tipo=tipo,
                quem_id=quem_id,
                email=emails.get(quem_id) if tipo == "usuario" else None,
                **_numeros(cs),
            )
            for (tipo, quem_id), cs in sorted(
                do_quem.items(),
                key=lambda i: (-sum(c.custo for c in i[1]), i[0][1]),
            )
        ],
        por_etapa=[
            EtapaDeCusto(etapa=e.etapa, custo=centavos(e.custo))
            for e in sorted(base.por_etapa, key=lambda e: (-e.custo, e.etapa))
        ],
        sem_dono_por_servico=[
            ServicoSemDono(servico=s, custo=centavos(v))
            for s, v in sorted(por_servico.items(), key=lambda i: (-i[1], i[0] or ""))
        ],
    )


def linhas_do_csv_de_custo(
    base: BaseDeCusto, emails: dict[str, str]
) -> list[list[object]]:
    """Uma linha por mês, programa e dono dos Jobs com custo (`detalhe` vazio) e uma por mês e
    serviço do custo sem dono (`quem_tipo` `sem_dono`, o serviço em `detalhe`)."""
    linhas: list[list[object]] = []
    for c in sorted(
        base.dos_jobs, key=lambda c: (c.mes, c.programa or "", c.quem_tipo, c.quem_id)
    ):
        linhas.append(
            [
                c.mes,
                c.quem_tipo,
                c.quem_id,
                emails.get(c.quem_id, "") if c.quem_tipo == "usuario" else "",
                c.programa or "",
                "",
                c.videos,
                round(c.horas, 4),
                centavos(c.custo),
            ]
        )
    por_mes_e_servico: dict[tuple[str, str], float] = defaultdict(float)
    for s in base.sem_dono:
        por_mes_e_servico[(s.mes, s.servico or "")] += s.custo
    for (mes, servico), custo in sorted(por_mes_e_servico.items()):
        linhas.append([mes, "sem_dono", "", "", "", servico, "", "", centavos(custo)])
    return linhas
