"""A aba Custo do painel (#285): o cruzamento das linhas do faturamento com os Jobs, a rota
`/v1/painel/custo` e a consulta à exportação do faturamento."""

import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from api.auditoria import FiltroDeAuditoria
from api.custo_do_painel import (
    BaseDeCusto,
    ConfigDoFaturamento,
    CustoDaEtapa,
    CustoDoDia,
    CustoDosJobs,
    CustoEmMemoria,
    CustoSemDono,
    FaturamentoBigQuery,
    FiltroDeCusto,
    relatorio_de_custo,
)
from api.jobs import Estado, Job, RepositorioEmMemoria
from api.tests.test_rotas_do_painel import Mundo


def _job(
    id: str,
    quando: datetime,
    *,
    programa: str | None = "Hoje",
    quem: str = "bia",
    sistema: str | None = None,
    duracao_s: float | None = 3600,
    estado: Estado = "concluido",
) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        estado=estado,
        criado_por=quem,
        sistema=sistema,
        programa=programa,
        duracao_s=duracao_s,
        criado_em=quando,
        atualizado_em=quando,
    )


def _linha(
    dia: date,
    job_id: str | None,
    custo: float,
    etapa: str | None = None,
    servico: str = "Vertex AI",
    moeda: str = "BRL",
) -> CustoDoDia:
    return CustoDoDia(dia, job_id, etapa, servico, custo, moeda)


# 15h UTC é 12h em São Paulo: o dia é o mesmo nos dois.
J1 = _job("j1", datetime(2026, 11, 1, 15, tzinfo=UTC))
J2 = _job(
    "j2",
    datetime(2026, 11, 2, 15, tzinfo=UTC),
    quem="chave",
    sistema="Playout",
    duracao_s=1800,
)
J3 = _job(
    "j3",
    datetime(2026, 11, 3, 15, tzinfo=UTC),
    programa="Fala",
    duracao_s=600,
    estado="falhou",
)
# Outro mês; a criação à 1h UTC de 1º de dezembro é 22h de 30 de novembro em São Paulo.
J4 = _job("j4", datetime(2026, 12, 1, 1, tzinfo=UTC), duracao_s=7200)
JOBS = [J1, J2, J3, J4]

LINHAS = [
    _linha(date(2026, 11, 1), "j1", 1.0),
    _linha(date(2026, 11, 1), "j1", 0.5, "referencias"),
    # O custo do Job vem em dias depois do dia em que ele foi criado.
    _linha(date(2026, 11, 2), "j1", 0.25),
    _linha(date(2026, 11, 2), "j2", 2.0),
    _linha(date(2026, 11, 3), "j3", 0.5),
    _linha(date(2026, 12, 1), "j4", 3.0),
    # Sem dono: o fixo, o que não tem rótulo, a busca e o Job que não existe mais.
    _linha(date(2026, 11, 1), None, 10.0, servico="Vertex AI Search"),
    _linha(date(2026, 11, 2), "busca", 0.1, "entendimento_da_consulta"),
    _linha(date(2026, 11, 1), "sumiu", 0.2),
    _linha(date(2026, 12, 1), None, 5.0, servico="Vertex AI Search"),
]


def _mundo(
    papeis: list[str] | None = None, linhas: list[CustoDoDia] | None = None
) -> Mundo:
    return Mundo(
        papeis or ["diretoria"],
        faturamento=CustoEmMemoria(LINHAS if linhas is None else linhas, JOBS),
        jobs=_JobsSemListar(),
    )


class _JobsSemListar(RepositorioEmMemoria):
    """O Custo não lê a coleção `jobs` (#466): quem chamar `listar` falha o teste."""

    def listar(self) -> Any:
        raise AssertionError("o Custo não pode ler a coleção jobs")


def test_o_resultado_e_o_mesmo_do_calculo_antigo_que_lia_todos_os_jobs() -> None:
    """`custo_antes_do_bigquery.json` guarda o que o cálculo de antes (`jobs.listar()` e o
    cruzamento em Python) dava para estes Jobs e linhas, com seis filtros."""
    casos = json.loads(
        (Path(__file__).parent / "custo_antes_do_bigquery.json").read_text()
    )
    fonte = CustoEmMemoria(LINHAS, JOBS)

    for caso in casos:
        d, a, programa, usuario = caso["filtro"]
        desde = date.fromisoformat(d) if d else None
        ate = date.fromisoformat(a) if a else None
        base = fonte.custos(FiltroDeCusto(desde, ate, programa, usuario))
        relatorio = relatorio_de_custo(
            base, {"bia": "bia@redetv.com.br"}, desde, ate, programa, usuario
        )
        atual = relatorio.model_dump(mode="json")
        atual.pop("faturamento_ate")  # o JSON é de antes deste campo (#523)
        assert atual == caso["relatorio"], caso["filtro"]


def test_devolve_o_dia_da_ultima_linha_do_faturamento_no_periodo() -> None:
    assert _mundo().get("/custo").json()["faturamento_ate"] == "2026-12-01"
    r = _mundo().get("/custo", ate="2026-11-30").json()
    assert r["faturamento_ate"] == "2026-11-03"
    assert _mundo(linhas=[]).get("/custo").json()["faturamento_ate"] is None


def test_o_total_junta_os_jobs_e_o_custo_sem_dono() -> None:
    r = _mundo().get("/custo").json()

    assert r["moeda"] == "BRL"
    total = r["total"]
    assert total["custo_dos_jobs"] == 7.25
    assert total["custo_sem_dono"] == 15.3
    assert total["custo"] == 22.55
    # Só os concluídos contam nas horas: j1 (1 h), j2 (0,5 h) e j4 (2 h); o custo do j3, que
    # falhou, entra no custo.
    assert total["videos"] == 3
    assert total["horas_de_video"] == 3.5
    assert total["custo_por_hora"] == round(7.25 / 3.5, 4)


def test_por_mes_o_custo_do_job_conta_no_mes_em_que_ele_foi_criado() -> None:
    meses = _mundo().get("/custo").json()["por_mes"]

    # O j4 foi criado às 22h de 30 de novembro em São Paulo (e cobrado em dezembro): é de
    # novembro. Em dezembro só fica o custo sem dono do dia 1º.
    assert [(m["mes"], m["custo_dos_jobs"], m["custo_sem_dono"]) for m in meses] == [
        ("2026-11", 7.25, 10.3),
        ("2026-12", 0.0, 5.0),
    ]
    assert meses[0]["custo_por_hora"] == round(7.25 / 3.5, 4)
    assert meses[1]["custo_por_hora"] is None


def test_por_usuario_ou_sistema_com_o_custo_por_hora() -> None:
    quem = _mundo().get("/custo").json()["por_quem"]

    assert [
        (q["quem_tipo"], q["quem_id"], q["email"], q["custo"], q["custo_por_hora"])
        for q in quem
    ] == [
        ("usuario", "bia", "bia@redetv.com.br", 5.25, round(5.25 / 3.0, 4)),
        ("sistema", "Playout", None, 2.0, 4.0),
    ]


def test_por_etapa_e_o_custo_sem_dono_por_servico() -> None:
    r = _mundo().get("/custo").json()

    assert r["por_etapa"] == [
        {"etapa": "analise", "custo": 6.75},
        {"etapa": "referencias", "custo": 0.5},
    ]
    assert r["sem_dono_por_servico"] == [
        {"servico": "Vertex AI Search", "custo": 15.0},
        {"servico": "Vertex AI", "custo": 0.3},
    ]


def test_o_periodo_filtra_pelo_dia_do_job_e_pelo_dia_do_custo_sem_dono() -> None:
    r = _mundo().get("/custo", desde="2026-11-02", ate="2026-11-02").json()

    # O j1 foi criado dia 1º e sai, com os 0,25 do dia 2; o j2 fica.
    assert r["total"]["custo_dos_jobs"] == 2.0
    assert r["total"]["custo_sem_dono"] == 0.1


def test_filtro_de_programa_ou_de_usuario_deixa_o_custo_sem_dono_de_fora() -> None:
    mundo = _mundo()

    por_programa = mundo.get("/custo", programa="Fala").json()
    assert por_programa["total"]["custo"] == 0.5
    assert por_programa["total"]["custo_sem_dono"] == 0
    assert por_programa["total"]["videos"] == 0
    assert por_programa["total"]["custo_por_hora"] is None

    por_sistema = mundo.get("/custo", usuario="Playout").json()
    assert por_sistema["total"]["custo"] == 2.0
    assert [q["quem_id"] for q in por_sistema["por_quem"]] == ["Playout"]


def test_programa_e_usuario_se_cruzam() -> None:
    r = _mundo().get("/custo", programa="Hoje", usuario="bia").json()

    assert r["total"]["custo"] == 4.75


def test_periodo_invertido_e_422() -> None:
    resposta = _mundo().get("/custo", desde="2026-11-03", ate="2026-11-01")

    assert resposta.status_code == 422


def test_sem_faturamento_configurado_e_503() -> None:
    assert Mundo(["diretoria"], faturamento=None).get("/custo").status_code == 503


def test_duas_moedas_na_exportacao_e_503() -> None:
    linhas = [
        _linha(date(2026, 11, 1), "j1", 1.0),
        _linha(date(2026, 11, 1), "j1", 1, moeda="USD"),
    ]

    resposta = _mundo(linhas=linhas).get("/custo")

    assert resposta.status_code == 503
    assert "moeda" in resposta.json()["detail"]


def test_sem_nenhuma_linha_o_relatorio_vem_vazio() -> None:
    r = _mundo(linhas=[]).get("/custo").json()

    assert r["moeda"] is None
    assert r["por_mes"] == [] and r["por_quem"] == []
    assert r["total"]["custo"] == 0
    assert r["total"]["custo_por_hora"] is None


def test_o_csv_traz_uma_linha_por_mes_programa_e_dono_e_uma_por_mes_e_servico_sem_dono() -> (
    None
):
    resposta = _mundo().get("/custo", formato="csv")

    assert resposta.status_code == 200
    assert "custo.csv" in resposta.headers["content-disposition"]
    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    jobs = [
        (r["mes"], r["programa"], r["quem_id"], r["horas_de_video"], r["custo"])
        for r in linhas
        if r["quem_tipo"] != "sem_dono"
    ]
    assert jobs == [
        ("2026-11", "Fala", "bia", "0.0", "0.5"),
        ("2026-11", "Hoje", "Playout", "0.5", "2.0"),
        ("2026-11", "Hoje", "bia", "3.0", "4.75"),
    ]
    assert [
        (r["mes"], r["detalhe"], r["custo"])
        for r in linhas
        if r["quem_tipo"] == "sem_dono"
    ] == [
        ("2026-11", "Vertex AI", "0.3"),
        ("2026-11", "Vertex AI Search", "10.0"),
        ("2026-12", "Vertex AI Search", "5.0"),
    ]


def test_custo_liquido_de_fracao_de_centavo_vira_zero_sem_sinal_no_relatorio_e_no_csv() -> (
    None
):
    # O crédito supera o custo por arredondamento: o líquido do mês é negativo de fração de centavo.
    linhas = [
        _linha(date(2026, 11, 1), "j1", -0.0003, "referencias"),
        _linha(date(2026, 11, 1), None, -0.0001, servico="Vertex AI Search"),
    ]
    mundo = _mundo(linhas=linhas)

    resposta = mundo.get("/custo")
    r = resposta.json()

    assert r["por_mes"][0]["custo"] == 0
    assert r["por_mes"][0]["custo_dos_jobs"] == 0
    assert r["por_mes"][0]["custo_sem_dono"] == 0
    assert r["total"]["custo"] == 0
    assert r["por_etapa"][0]["custo"] == 0
    assert r["sem_dono_por_servico"][0]["custo"] == 0
    # O custo por hora segue em quatro casas (a tela o arredonda para centavos ao escrever): fica fora.
    for campo in ("custo", "custo_dos_jobs", "custo_sem_dono"):
        assert f'"{campo}":-0' not in resposta.text
    texto = mundo.get("/custo", formato="csv").text
    assert "-0" not in texto
    assert [x["custo"] for x in csv.DictReader(io.StringIO(texto))] == ["0.0", "0.0"]


def test_o_custo_e_arredondado_para_centavos() -> None:
    linhas = [_linha(date(2026, 11, 1), None, 1.2349, servico="Vertex AI Search")]

    r = _mundo(linhas=linhas).get("/custo").json()

    assert r["total"]["custo"] == 1.23


def test_o_csv_respeita_os_filtros_e_vai_para_a_auditoria() -> None:
    mundo = _mundo()

    resposta = mundo.get("/custo", programa="Fala", formato="csv")

    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    assert [(r["programa"], r["custo"]) for r in linhas] == [("Fala", "0.5")]
    registro = mundo.auditoria.consultar(FiltroDeAuditoria()).registros[0]
    assert registro.acao == "painel.exportado"
    assert registro.detalhes == {"aba": "custo", "filtro": {"programa": "Fala"}}


def test_abrir_a_aba_vai_para_a_auditoria() -> None:
    mundo = _mundo()

    mundo.get("/custo")

    registro = mundo.auditoria.consultar(FiltroDeAuditoria()).registros[0]
    assert registro.acao == "painel.aberto"
    assert registro.detalhes["aba"] == "custo"


class _Transporte:
    def __init__(self, linhas: list[list[Any]]) -> None:
        self.corpos: list[dict[str, Any]] = []
        self._linhas = linhas

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return {
            "jobComplete": True,
            "rows": [{"f": [{"v": v} for v in linha]} for linha in self._linhas],
        }


# tipo, mes, programa, quem_tipo, quem_id, rotulo, custo, videos, horas, moeda
def _fonte(linhas: list[list[Any]]) -> tuple[FaturamentoBigQuery, _Transporte]:
    transporte = _Transporte(linhas)
    config = ConfigDoFaturamento(
        "proj",
        "fat",
        "gcp_billing_export_resource_v1_*",
        "regiao-x",
        "decupagens",
        "tabela_de_jobs",
    )
    return FaturamentoBigQuery(config, transporte), transporte


def test_a_consulta_junta_o_faturamento_com_os_jobs_dentro_do_bigquery() -> None:
    fonte, transporte = _fonte(
        [
            [
                "jobs",
                "2026-11",
                "Hoje",
                "usuario",
                "bia",
                None,
                "1.75",
                "1",
                "1.0",
                "BRL",
            ],
            [
                "jobs",
                "2026-11",
                None,
                "sistema",
                "Playout",
                None,
                "2",
                "1",
                "0.5",
                "BRL",
            ],
            ["etapa", None, None, None, None, "analise", "3.25", "0", "0", "BRL"],
            ["etapa", None, None, None, None, "referencias", "0.5", "0", "0", "BRL"],
            [
                "sem_dono",
                "2026-11",
                None,
                None,
                None,
                "Vertex AI",
                "10",
                "0",
                "0",
                "BRL",
            ],
            ["sem_dono", "2026-11", None, None, None, None, "1", "0", "0", "BRL"],
            ["moeda", None, None, None, None, None, "0", "0", "0", "BRL"],
            ["ate", None, None, None, None, "2026-11-04", "0", "0", "0", "BRL"],
        ]
    )

    base = fonte.custos(FiltroDeCusto(date(2026, 11, 1), None, None, None))

    assert base.dos_jobs == [
        CustoDosJobs("2026-11", "Hoje", "usuario", "bia", 1.75, 1, 1.0),
        CustoDosJobs("2026-11", None, "sistema", "Playout", 2.0, 1, 0.5),
    ]
    assert base.por_etapa == [
        CustoDaEtapa("analise", 3.25),
        CustoDaEtapa("referencias", 0.5),
    ]
    assert base.sem_dono == [
        CustoSemDono("2026-11", "Vertex AI", 10.0),
        CustoSemDono("2026-11", None, 1.0),
    ]
    assert base.moedas == {"BRL"}
    assert base.faturamento_ate == date(2026, 11, 4)
    # Uma consulta só, na região do painel, sobre as duas tabelas: a soma não passa pela API.
    assert len(transporte.corpos) == 1
    corpo = transporte.corpos[0]
    assert corpo["location"] == "regiao-x"
    sql = corpo["query"]
    assert "`proj.fat.gcp_billing_export_resource_v1_*`" in sql
    assert "JOIN `proj.decupagens.tabela_de_jobs` AS j ON j.id = l.job_id" in sql
    assert "GROUP BY" in sql and "SUM(" in sql
    assert "key = 'job_id'" in sql and "key = 'etapa'" in sql
    # A etapa vazia é a análise principal, como a sem rótulo.
    assert "IFNULL(NULLIF(etapa, ''), 'analise')" in sql
    # O custo é o líquido dos créditos e o dia é o de São Paulo.
    assert "credits" in sql and "America/Sao_Paulo" in sql
    assert [p["name"] for p in corpo["queryParameters"]] == ["desde"]
    assert corpo["queryParameters"][0]["parameterValue"] == {"value": "2026-11-01"}
    # O "até quando há faturamento" é o MAX do dia, dentro dos limites do período.
    assert "CAST(MAX(l.dia) AS STRING)" in sql and "MIN(l.dia)" not in sql
    parte_ate = sql[sql.index("SELECT 'ate'") :]
    assert "WHERE TRUE AND l.dia >= @desde\n" in parte_ate


def test_os_filtros_vao_como_parametros_e_o_sem_dono_so_vem_sem_programa_nem_usuario() -> (
    None
):
    fonte, transporte = _fonte([])

    fonte.custos(FiltroDeCusto(date(2026, 11, 1), date(2026, 11, 30), None, None))
    fonte.custos(
        FiltroDeCusto(date(2026, 11, 1), date(2026, 11, 30), "Hoje' OR 1=1", "bia")
    )

    sem_filtro, com_filtro = transporte.corpos
    assert [p["name"] for p in sem_filtro["queryParameters"]] == ["desde", "ate"]
    assert "'sem_dono'" in sem_filtro["query"]
    # O MAX do dia só olha o período pedido, nos dois limites.
    parte_ate = sem_filtro["query"][sem_filtro["query"].index("SELECT 'ate'") :]
    assert "WHERE TRUE AND l.dia >= @desde AND l.dia <= @ate\n" in parte_ate
    assert [p["name"] for p in com_filtro["queryParameters"]] == [
        "desde",
        "ate",
        "programa",
        "usuario",
    ]
    assert "j.programa = @programa" in com_filtro["query"]
    assert "j.quem_id = @usuario" in com_filtro["query"]
    assert "OR 1=1" not in com_filtro["query"]
    assert "'sem_dono'" not in com_filtro["query"]


def test_sem_periodo_a_consulta_nao_filtra_o_dia() -> None:
    fonte, transporte = _fonte([])

    base = fonte.custos(FiltroDeCusto(None, None, None, None))

    assert base == BaseDeCusto([], [], [], frozenset())
    assert transporte.corpos[0]["queryParameters"] == []
