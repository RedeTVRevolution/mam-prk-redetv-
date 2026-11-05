"""O relatório por marca e tipo de inserção (#267): o cálculo, a consulta e a rota."""

import csv
import io
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.copia_bigquery import ConfigDoBigQuery, CopiaEmMemoria, LinhaDoMomento
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.relatorio_de_marcas import (
    TIPOS_DE_INSERCAO,
    ConsultaBigQuery,
    ConsultaEmMemoria,
    Insercao,
    InsercoesDaMarca,
    MarcaNoRelatorio,
    somar,
)
from api.relatorio_de_marcas import relatorio as relatorio_das_somas
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.tests.test_passadas import AUTORIZACAO

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ROTA = "/v1/relatorios/marcas"


def relatorio(insercoes: list[Insercao]) -> list[MarcaNoRelatorio]:
    """O relatório de hoje: a soma (que o BigQuery faz) e a montagem."""
    return relatorio_das_somas(somar(insercoes))


def _i(job: str, marca: str, tipo: str, ini: int, fim: int) -> Insercao:
    return Insercao(job, marca, tipo, ini, fim)


def test_por_marca_soma_insercoes_tempo_e_videos_com_o_detalhe_por_tipo() -> None:
    marcas = relatorio(
        [
            _i("j1", "Ambev", "merchan_apresentador", 0, 30_000),
            _i("j1", "Ambev", "sobreposicao_grafica", 10_000, 15_000),
            _i("j2", "Ambev", "merchan_apresentador", 0, 20_000),
            _i("j2", "Natura", "intervalo", 0, 5_000),
        ]
    )

    assert [m.marca for m in marcas] == ["Ambev", "Natura"]  # do maior tempo ao menor
    ambev = marcas[0]
    assert (ambev.insercoes, ambev.tempo_ms, ambev.videos) == (3, 55_000, 2)
    assert [(t.tipo, t.insercoes, t.tempo_ms, t.videos) for t in ambev.por_tipo] == [
        ("merchan_apresentador", 2, 50_000, 2),
        ("sobreposicao_grafica", 1, 5_000, 1),
    ]
    assert [(i.job_id, i.inicio_ms) for i in ambev.lista] == [
        ("j1", 0),
        ("j1", 10_000),
        ("j2", 0),
    ]


def _linha(
    job: str, programa: str, dia: date | None, marca: str | None, tipo: str | None
) -> LinhaDoMomento:
    return LinhaDoMomento(
        job_id=job,
        programa=programa,
        data_de_exibicao=dia,
        tipo="comercial",
        inicio_ms=0,
        fim_ms=1_000,
        marca=marca,
        tipo_de_insercao=tipo,
    )


def _copia() -> CopiaEmMemoria:
    copia = CopiaEmMemoria()
    copia.gravar(
        "j1",
        [
            _linha("j1", "Jornal", date(2026, 10, 1), "Ambev", "intervalo"),
            _linha("j1", "Jornal", date(2026, 10, 1), "Natura", "marca_incidental"),
            LinhaDoMomento(
                job_id="j1",
                programa="Jornal",
                data_de_exibicao=date(2026, 10, 1),
                tipo="plano",
                inicio_ms=0,
                fim_ms=5_000,
                marca="Ambev",
            ),
        ],
    )
    copia.gravar(
        "j2",
        [_linha("j2", "Fama", date(2026, 10, 15), "Ambev", "merchan_apresentador")],
    )
    copia.gravar(
        "j3",
        [
            _linha("j3", "Jornal", None, "Ambev", "intervalo"),
            _linha("j3", "Jornal", None, "", "intervalo"),  # marca vazia fica de fora
        ],
    )
    return copia


def test_a_consulta_em_memoria_traz_so_comerciais_e_filtra_por_tipo_programa_e_periodo() -> (
    None
):
    consulta = ConsultaEmMemoria(_copia())

    def jobs(*filtros: Any) -> set[str]:
        return {i.job_id for i in consulta.insercoes(*filtros)}

    assert len(consulta.insercoes(None, None, None, None)) == 4  # o plano fica de fora
    assert jobs("Fama", None, None, None) == {"j2"}
    assert jobs(None, date(2026, 10, 10), date(2026, 10, 20), None) == {"j2"}
    assert jobs(None, date(2020, 1, 1), None, None) == {"j1", "j2"}  # sem data sai
    assert jobs(None, None, None, "intervalo") == {"j1", "j3"}


class Transporte:
    def __init__(self, resposta: dict[str, Any]) -> None:
        self.resposta = resposta
        self.corpos: list[dict[str, Any]] = []

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return self.resposta


CONFIG = ConfigDoBigQuery("proj", "ds", "tab", "regiao")


def test_bigquery_pede_so_comerciais_com_marca_e_os_filtros_como_parametros() -> None:
    transporte = Transporte(
        {
            "jobComplete": True,
            "rows": [
                {
                    "f": [
                        {"v": v}
                        for v in (
                            "Ambev",
                            "intervalo",
                            "j1",
                            "2",
                            "35000",
                            '[{"inicio_ms":0,"fim_ms":30000},{"inicio_ms":40000,"fim_ms":45000}]',
                        )
                    ]
                }
            ],
        }
    )

    achadas = ConsultaBigQuery(CONFIG, transporte).somas(
        "Jornal", date(2026, 10, 1), date(2026, 10, 31), "intervalo"
    )

    assert achadas == [
        InsercoesDaMarca(
            "Ambev", "intervalo", "j1", 2, 35_000, [(0, 30_000), (40_000, 45_000)]
        )
    ]
    (corpo,) = transporte.corpos
    consulta = corpo["query"]
    assert "`proj.ds.tab`" in consulta and "'comercial'" in consulta
    assert "NULLIF(t.marca, '') IS NOT NULL" in consulta
    assert "GROUP BY marca, tipo, job_id" in consulta  # a soma é do BigQuery
    parametros = {
        p["name"]: (p["parameterType"]["type"], p["parameterValue"]["value"])
        for p in corpo["queryParameters"]
    }
    assert parametros == {
        "tipo_de_insercao": ("STRING", "intervalo"),
        "programa": ("STRING", "Jornal"),
        "desde": ("DATE", "2026-10-01"),
        "ate": ("DATE", "2026-10-31"),
    }
    assert "Jornal" not in consulta and "Ambev" not in consulta


def test_bigquery_sem_filtros_nao_leva_parametros_e_resposta_cortada_falha_alto() -> (
    None
):
    transporte = Transporte({"jobComplete": True})
    assert ConsultaBigQuery(CONFIG, transporte).somas(None, None, None, None) == []
    assert transporte.corpos[0]["queryParameters"] == []
    for resposta in ({"jobComplete": False}, {"jobComplete": True, "pageToken": "x"}):
        with pytest.raises(RuntimeError):
            ConsultaBigQuery(CONFIG, Transporte(resposta)).somas(None, None, None, None)


def _cliente(
    papel: str = "consulta", consulta: ConsultaEmMemoria | None = None
) -> TestClient:
    jobs = RepositorioEmMemoria()
    jobs.salvar(
        Job(
            id="j1",
            nome="jornal-01.mp4",
            tamanho_bytes=1,
            estado="concluido",
            criado_por="u1",
            programa="Jornal",
            data_exibicao=date(2026, 10, 1),
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("u1", [papel])  # type: ignore[list-item]
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@redetv.com.br")}),
            jobs,
            papeis=papeis,
            relatorio_de_marcas=consulta,
        )
    )


def test_rota_devolve_a_tabela_por_marca_com_as_insercoes_e_o_nome_do_video() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    resposta = cliente.get(ROTA, params={"programa": "Jornal"}, headers=AUTORIZACAO)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert (corpo["programa"], corpo["tipo"]) == ("Jornal", None)
    assert [m["marca"] for m in corpo["marcas"]] == ["Ambev", "Natura"]
    ambev = corpo["marcas"][0]
    assert (ambev["insercoes"], ambev["videos"]) == (2, 2)  # j1 e j3 (sem data)
    nomes = {i["job_id"]: i["nome"] for i in ambev["lista"]}
    assert nomes == {"j1": "jornal-01.mp4", "j3": None}


def test_rota_filtra_por_tipo_e_por_periodo() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    por_tipo = cliente.get(
        ROTA, params={"tipo": "marca_incidental"}, headers=AUTORIZACAO
    ).json()
    por_periodo = cliente.get(
        ROTA, params={"desde": "2026-10-10", "ate": "2026-10-20"}, headers=AUTORIZACAO
    ).json()

    assert [m["marca"] for m in por_tipo["marcas"]] == ["Natura"]
    assert [m["marca"] for m in por_periodo["marcas"]] == ["Ambev"]
    assert por_periodo["marcas"][0]["por_tipo"][0]["tipo"] == "merchan_apresentador"


def test_rota_em_csv_tem_o_total_e_uma_linha_por_tipo_de_cada_marca() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    resposta = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO)

    assert resposta.headers["content-type"].startswith("text/csv")
    assert "attachment" in resposta.headers["content-disposition"]
    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    assert [(x["marca"], x["tipo"], x["insercoes"], x["videos"]) for x in linhas] == [
        ("Ambev", "todos", "3", "3"),
        ("Ambev", "intervalo", "2", "2"),
        ("Ambev", "merchan_apresentador", "1", "1"),
        ("Natura", "todos", "1", "1"),
        ("Natura", "marca_incidental", "1", "1"),
    ]


def test_csv_nao_deixa_a_marca_virar_formula() -> None:
    copia = CopiaEmMemoria()
    copia.gravar("j1", [_linha("j1", "Jornal", None, "=HYPERLINK(1)", "intervalo")])
    cliente = _cliente(consulta=ConsultaEmMemoria(copia))

    texto = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO).text

    assert "'=HYPERLINK(1)" in texto


def test_rota_exige_login_e_o_bigquery_configurado() -> None:
    assert _cliente(consulta=ConsultaEmMemoria(_copia())).get(ROTA).status_code == 401
    assert _cliente().get(ROTA, headers=AUTORIZACAO).status_code == 503


def test_rota_nega_periodo_invertido_tipo_e_formato_desconhecidos() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    for params in (
        {"desde": "2026-11-01", "ate": "2026-10-01"},
        {"tipo": "outdoor"},
        {"formato": "xml"},
    ):
        assert cliente.get(ROTA, params=params, headers=AUTORIZACAO).status_code == 422


def test_programa_e_tipo_vazios_sao_todos() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    vazio = cliente.get(
        ROTA, params={"programa": "", "tipo": ""}, headers=AUTORIZACAO
    ).json()
    todos = cliente.get(ROTA, headers=AUTORIZACAO).json()

    assert vazio["programa"] is None and vazio["tipo"] is None
    assert vazio["marcas"] == todos["marcas"] != []


def test_chave_de_sistema_nao_consulta_o_relatorio() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave("Playout", frozenset({"ler"}), MAC, chaves, BASE)
    cliente = TestClient(
        criar_app(
            VerificadorFalso({}),
            RepositorioEmMemoria(),
            chaves=VerificadorDeChaveDeApi(chaves, MAC),
            relatorio_de_marcas=ConsultaEmMemoria(_copia()),
        )
    )

    assert cliente.get(ROTA, headers={"X-API-Key": emitida.chave}).status_code == 403


def test_os_tipos_de_insercao_vem_do_modelo_da_decupagem() -> None:
    assert "merchan_apresentador" in TIPOS_DE_INSERCAO
    assert "mencao_editorial" in TIPOS_DE_INSERCAO


def test_a_tela_conhece_os_mesmos_tipos_de_insercao() -> None:
    # web/src/marcas.ts dá o nome de cada tipo na tela; um tipo novo na decupagem entra lá
    # também, ou o filtro da tela não o oferece.
    fonte = (Path(__file__).parents[2] / "web" / "src" / "marcas.ts").read_text()
    depois = fonte.split("TIPOS_DE_INSERCAO: Record<string, string> = {")[1]
    bloco = depois.split("}")[0]
    assert re.findall(r"^\s*(\w+):", bloco, re.MULTILINE) == list(TIPOS_DE_INSERCAO)


def test_tipo_que_a_decupagem_nao_tem_mais_entra_no_detalhe_e_fecha_o_total() -> None:
    (ambev,) = relatorio(
        [
            _i("j1", "Ambev", "tipo_antigo", 0, 1_000),
            _i("j1", "Ambev", "intervalo", 0, 2_000),
        ]
    )

    assert [t.tipo for t in ambev.por_tipo] == ["intervalo", "tipo_antigo"]
    assert sum(t.tempo_ms for t in ambev.por_tipo) == ambev.tempo_ms
