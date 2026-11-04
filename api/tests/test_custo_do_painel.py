"""A aba Custo do painel (#285): o cruzamento das linhas do faturamento com os Jobs, a rota
`/v1/painel/custo` e a consulta à exportação do faturamento."""

import csv
import io
from datetime import UTC, date, datetime
from typing import Any

from api.auditoria import FiltroDeAuditoria
from api.custo_do_painel import (
    ConfigDoFaturamento,
    CustoDoDia,
    CustoEmMemoria,
    FaturamentoBigQuery,
    cruzar_com_os_jobs,
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
    repositorio = RepositorioEmMemoria()
    for j in JOBS:
        repositorio.salvar(j)
    return Mundo(
        papeis or ["diretoria"],
        faturamento=CustoEmMemoria(LINHAS if linhas is None else linhas),
        jobs=repositorio,
    )


def test_o_cruzamento_poe_cada_linha_no_job_do_rotulo() -> None:
    cruzado = cruzar_com_os_jobs(LINHAS, JOBS)

    assert {i: c.por_etapa for i, c in cruzado.dos_jobs.items()} == {
        "j1": {"analise": 1.25, "referencias": 0.5},
        "j2": {"analise": 2.0},
        "j3": {"analise": 0.5},
        "j4": {"analise": 3.0},
    }
    assert [(s.job_id, s.custo) for s in cruzado.sem_dono] == [
        (None, 10.0),
        ("busca", 0.1),
        ("sumiu", 0.2),
        (None, 5.0),
    ]


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


def test_o_csv_traz_uma_linha_por_job_e_uma_por_mes_e_servico_sem_dono() -> None:
    resposta = _mundo().get("/custo", formato="csv")

    assert resposta.status_code == 200
    assert "custo.csv" in resposta.headers["content-disposition"]
    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    jobs = [
        (r["job_id"], r["quem_id"], r["horas_de_video"], r["custo"])
        for r in linhas
        if r["job_id"]
    ]
    assert jobs == [
        ("j1", "bia", "1.0", "1.75"),
        ("j2", "Playout", "0.5", "2.0"),
        ("j3", "bia", "0.0", "0.5"),
        ("j4", "bia", "2.0", "3.0"),
    ]
    assert [
        (r["mes"], r["quem_tipo"], r["detalhe"], r["custo"])
        for r in linhas
        if not r["job_id"]
    ] == [
        ("2026-11", "sem_dono", "Vertex AI", "0.3"),
        ("2026-11", "sem_dono", "Vertex AI Search", "10.0"),
        ("2026-12", "sem_dono", "Vertex AI Search", "5.0"),
    ]


def test_o_csv_respeita_os_filtros_e_vai_para_a_auditoria() -> None:
    mundo = _mundo()

    resposta = mundo.get("/custo", programa="Fala", formato="csv")

    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    assert [r["job_id"] for r in linhas] == ["j3"]
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


def test_a_consulta_le_o_faturamento_na_regiao_do_painel() -> None:
    transporte = _Transporte(
        [
            ["2026-11-01", "j1", "referencias", "Vertex AI", "1.5", "BRL"],
            ["2026-11-01", None, None, None, "10", "BRL"],
        ]
    )
    fonte = FaturamentoBigQuery(
        ConfigDoFaturamento(
            "proj", "fat", "gcp_billing_export_resource_v1_*", "regiao-x"
        ),
        transporte,
    )

    linhas = fonte.custos(date(2026, 11, 1))

    assert linhas == [
        CustoDoDia(date(2026, 11, 1), "j1", "referencias", "Vertex AI", 1.5, "BRL"),
        CustoDoDia(date(2026, 11, 1), None, None, None, 10.0, "BRL"),
    ]
    corpo = transporte.corpos[0]
    assert corpo["location"] == "regiao-x"
    assert "`proj.fat.gcp_billing_export_resource_v1_*`" in corpo["query"]
    assert "key = 'job_id'" in corpo["query"] and "key = 'etapa'" in corpo["query"]
    # O custo é o líquido dos créditos e o dia é o de São Paulo.
    assert "credits" in corpo["query"] and "America/Sao_Paulo" in corpo["query"]
    assert corpo["queryParameters"][0]["parameterValue"] == {"value": "2026-11-01"}


def test_sem_desde_a_consulta_nao_filtra_o_dia() -> None:
    transporte = _Transporte([])
    fonte = FaturamentoBigQuery(ConfigDoFaturamento("p", "d", "t", "r"), transporte)

    assert fonte.custos(None) == []
    assert transporte.corpos[0]["queryParameters"] == []
