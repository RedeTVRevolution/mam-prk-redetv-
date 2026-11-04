"""A aba Custo do painel da diretoria (#285): o custo da exportação do faturamento, cruzado
com os Jobs pelos rótulos de custo.

Cada chamada ao Gemini leva o rótulo `job_id` (e, fora a análise principal, `etapa`); é por ele
que o custo vira custo de um Job. O que não tem rótulo, ou tem um `job_id` que não é de nenhum
Job (a busca usa `busca`; o vídeo purgado some), e o custo fixo (a réplica do índice, os
serviços de rede) entram como custo **sem dono**, no mês em que foram cobrados. Os Jobs do
Cloud Run não levam o id do Job: o Cloud Run não deixa rotular cada execução, então o custo
deles cai aqui também, e o dos embeddings (quadros-chave e busca visual), que vão sem rótulo.

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


class FonteDeCusto(Protocol):
    def custos(self, desde: date | None) -> list[CustoDoDia]:
        """As linhas do faturamento de `desde` (dia de São Paulo, inclusive) em diante, uma por
        dia, job, etapa e serviço. O fim do período não corta: o custo de um Job vem até depois
        do dia em que ele foi criado."""


class CustoEmMemoria:
    """Dublê: as linhas dadas, com o mesmo corte de `desde`."""

    def __init__(self, linhas: Sequence[CustoDoDia] = ()) -> None:
        self._linhas = list(linhas)

    def custos(self, desde: date | None) -> list[CustoDoDia]:
        return [c for c in self._linhas if desde is None or c.dia >= desde]


@dataclass(frozen=True)
class ConfigDoFaturamento:
    projeto: str
    dataset: str
    tabela: str
    regiao: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDoFaturamento":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["FATURAMENTO_DATASET"],
            tabela=ambiente["FATURAMENTO_TABELA"],
            regiao=ambiente["BIGQUERY_REGIAO"],
        )


def _rotulo(chave: str) -> str:
    return f"(SELECT value FROM UNNEST(labels) WHERE key = '{chave}' LIMIT 1)"


class FaturamentoBigQuery:
    """A leitura real da exportação do faturamento (custo detalhado): REST com o mesmo
    transporte da cópia."""

    def __init__(self, config: ConfigDoFaturamento, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def custos(self, desde: date | None) -> list[CustoDoDia]:
        c = self._config
        dia = "DATE(usage_start_time, 'America/Sao_Paulo')"
        onde = "TRUE"
        parametros: list[dict[str, Any]] = []
        if desde is not None:
            onde = f"{dia} >= @desde"
            parametros.append(_parametro("desde", desde.isoformat(), "DATE"))
        linhas = linhas_da_consulta(
            self._transporte,
            c.regiao,
            f"SELECT CAST({dia} AS STRING) AS dia, {_rotulo('job_id')} AS job_id,"
            f" {_rotulo('etapa')} AS etapa, service.description AS servico,"
            " SUM(cost + IFNULL((SELECT SUM(cr.amount) FROM UNNEST(credits) cr), 0)),"
            " currency\n"
            f"FROM `{c.projeto}.{c.dataset}.{c.tabela}`\n"
            f"WHERE {onde}\n"
            "GROUP BY dia, job_id, etapa, servico, currency",
            parametros,
            "faturamento",
        )
        return [
            CustoDoDia(
                dia=date.fromisoformat(v[0]),
                job_id=v[1] or None,
                etapa=v[2] or None,
                servico=v[3] or None,
                custo=float(v[4]),
                moeda=v[5],
            )
            for v in linhas
        ]


def faturamento_do_ambiente(ambiente: Any) -> FaturamentoBigQuery | None:
    """A leitura configurada, ou `None` se o ambiente não diz onde o faturamento mora."""
    if "FATURAMENTO_DATASET" not in ambiente:
        return None
    config = ConfigDoFaturamento.do_ambiente(ambiente)
    return FaturamentoBigQuery(config, transporte_http(config.projeto))


@dataclass
class CustoDeUmJob:
    """O custo de um Job, por etapa."""

    job: Job
    por_etapa: dict[str, float]

    @property
    def custo(self) -> float:
        return sum(self.por_etapa.values())


@dataclass(frozen=True)
class CustoCruzado:
    """O que o cruzamento devolve: o custo de cada Job com cobrança, e as linhas sem dono."""

    dos_jobs: dict[str, CustoDeUmJob]
    sem_dono: list[CustoDoDia]


def cruzar_com_os_jobs(
    linhas: Iterable[CustoDoDia], jobs: Iterable[Job]
) -> CustoCruzado:
    """A linha com `job_id` de um Job conhecido é do Job; as outras são sem dono."""
    por_id = {j.id: j for j in jobs}
    dos_jobs: dict[str, CustoDeUmJob] = {}
    sem_dono: list[CustoDoDia] = []
    for linha in linhas:
        job = por_id.get(linha.job_id) if linha.job_id else None
        if job is None:
            sem_dono.append(linha)
            continue
        do_job = dos_jobs.setdefault(job.id, CustoDeUmJob(job, defaultdict(float)))
        do_job.por_etapa[linha.etapa or ETAPA_DA_ANALISE] += linha.custo
    return CustoCruzado(dos_jobs, sem_dono)


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
    total: TotalDeCusto
    por_mes: list[MesDeCusto]
    por_quem: list[QuemDeCusto]
    por_etapa: list[EtapaDeCusto]
    sem_dono_por_servico: list[ServicoSemDono]


COLUNAS_DO_CSV_DE_CUSTO = (
    "mes",
    "job_id",
    "quem_tipo",
    "quem_id",
    "email",
    "programa",
    "detalhe",
    "horas_de_video",
    "custo",
)


def _dia_do_job(job: Job) -> date:
    return job.criado_em.astimezone(SAO_PAULO).date()


def _mes(dia: date) -> str:
    return f"{dia.year:04d}-{dia.month:02d}"


def _quem(job: Job) -> Quem:
    """Quem enviou: o sistema, ou a pessoa (o uid), como nas tabelas de uso."""
    return ("sistema", job.sistema) if job.sistema else ("usuario", job.criado_por)


def _horas(job: Job) -> float:
    """As horas de vídeo contam só do Job concluído."""
    return (job.duracao_s or 0) / 3600 if job.estado == "concluido" else 0.0


def _por_hora(custo: float, horas: float) -> float | None:
    return round(custo / horas, 4) if horas > 0 else None


def _numeros(custo: float, jobs: Sequence[Job]) -> dict[str, Any]:
    horas = sum(_horas(j) for j in jobs)
    return {
        "custo": round(custo, 4),
        "videos": sum(1 for j in jobs if j.estado == "concluido"),
        "horas_de_video": round(horas, 4),
        "custo_por_hora": _por_hora(custo, horas),
    }


@dataclass(frozen=True)
class BaseDeCusto:
    """O custo já filtrado: os Jobs do período (com programa e usuário pedidos) e as linhas sem
    dono do período (só sem filtro de programa ou de usuário)."""

    jobs: list[CustoDeUmJob]
    sem_dono: list[CustoDoDia]
    moeda: str | None


def base_de_custo(
    linhas: Sequence[CustoDoDia],
    jobs: Iterable[Job],
    desde: date | None,
    ate: date | None,
    programa: str | None,
    usuario: str | None,
) -> BaseDeCusto:
    moedas = {c.moeda for c in linhas}
    if len(moedas) > 1:
        raise RuntimeError(
            f"o faturamento tem mais de uma moeda ({', '.join(sorted(moedas))})"
        )

    def no_periodo(dia: date) -> bool:
        return (desde is None or dia >= desde) and (ate is None or dia <= ate)

    cruzado = cruzar_com_os_jobs(linhas, jobs)
    dos_jobs = [
        c
        for c in cruzado.dos_jobs.values()
        if no_periodo(_dia_do_job(c.job))
        and (programa is None or c.job.programa == programa)
        and (usuario is None or _quem(c.job)[1] == usuario)
    ]
    sem_dono = (
        [c for c in cruzado.sem_dono if no_periodo(c.dia)]
        if programa is None and usuario is None
        else []
    )
    return BaseDeCusto(dos_jobs, sem_dono, next(iter(moedas), None))


def relatorio_de_custo(
    base: BaseDeCusto,
    emails: dict[str, str],
    desde: date | None,
    ate: date | None,
    programa: str | None,
    usuario: str | None,
) -> RelatorioDeCusto:
    jobs_do_mes: dict[str, list[CustoDeUmJob]] = defaultdict(list)
    for c in base.jobs:
        jobs_do_mes[_mes(_dia_do_job(c.job))].append(c)
    sem_dono_do_mes: dict[str, list[CustoDoDia]] = defaultdict(list)
    for s in base.sem_dono:
        sem_dono_do_mes[_mes(s.dia)].append(s)

    def total(
        jobs: Sequence[CustoDeUmJob], sem_dono: Sequence[CustoDoDia]
    ) -> dict[str, Any]:
        dos_jobs = sum(c.custo for c in jobs)
        sem = sum(s.custo for s in sem_dono)
        # O custo por hora é o dos Jobs: o custo sem dono não tem vídeo.
        numeros = _numeros(dos_jobs, [c.job for c in jobs])
        return numeros | {
            "custo": round(dos_jobs + sem, 4),
            "custo_dos_jobs": round(dos_jobs, 4),
            "custo_sem_dono": round(sem, 4),
        }

    do_quem: dict[Quem, list[CustoDeUmJob]] = defaultdict(list)
    por_etapa: dict[str, float] = defaultdict(float)
    for c in base.jobs:
        do_quem[_quem(c.job)].append(c)
        for etapa, custo in c.por_etapa.items():
            por_etapa[etapa] += custo
    por_servico: dict[str | None, float] = defaultdict(float)
    for s in base.sem_dono:
        por_servico[s.servico] += s.custo

    return RelatorioDeCusto(
        desde=desde,
        ate=ate,
        programa=programa,
        usuario=usuario,
        moeda=base.moeda,
        total=TotalDeCusto(**total(base.jobs, base.sem_dono)),
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
                **_numeros(sum(c.custo for c in cs), [c.job for c in cs]),
            )
            for (tipo, quem_id), cs in sorted(
                do_quem.items(),
                key=lambda i: (-sum(c.custo for c in i[1]), i[0][1]),
            )
        ],
        por_etapa=[
            EtapaDeCusto(etapa=e, custo=round(v, 4))
            for e, v in sorted(por_etapa.items(), key=lambda i: (-i[1], i[0]))
        ],
        sem_dono_por_servico=[
            ServicoSemDono(servico=s, custo=round(v, 4))
            for s, v in sorted(por_servico.items(), key=lambda i: (-i[1], i[0] or ""))
        ],
    )


def linhas_do_csv_de_custo(
    base: BaseDeCusto, emails: dict[str, str]
) -> list[list[object]]:
    """Uma linha por Job com custo (`detalhe` vazio) e uma por mês e serviço do custo sem dono
    (`quem_tipo` `sem_dono`, o serviço em `detalhe`)."""
    linhas: list[list[object]] = []
    for c in sorted(
        base.jobs, key=lambda c: (_dia_do_job(c.job), c.job.programa or "", c.job.id)
    ):
        tipo, quem_id = _quem(c.job)
        linhas.append(
            [
                _mes(_dia_do_job(c.job)),
                c.job.id,
                tipo,
                quem_id,
                emails.get(quem_id, "") if tipo == "usuario" else "",
                c.job.programa or "",
                "",
                round(_horas(c.job), 4),
                round(c.custo, 4),
            ]
        )
    por_mes_e_servico: dict[tuple[str, str], float] = defaultdict(float)
    for s in base.sem_dono:
        por_mes_e_servico[(_mes(s.dia), s.servico or "")] += s.custo
    for (mes, servico), custo in sorted(por_mes_e_servico.items()):
        linhas.append([mes, "", "sem_dono", "", "", "", servico, "", round(custo, 4)])
    return linhas
