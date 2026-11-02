"""O relatório de tempo de tela (#266): o cálculo, a consulta no BigQuery e a rota."""

import csv
import io
from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient

from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaEmMemoria,
    LinhaDoMomento,
    PessoaDoMomento,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tempo_de_tela import (
    ConsultaBigQuery,
    ConsultaEmMemoria,
    MomentoDaPessoa,
    relatorio,
)
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.tests.test_passadas import AUTORIZACAO

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ROTA = "/v1/relatorios/tempo-de-tela"


def _m(job: str, tipo: str, ini: int, fim: int, pessoa: str = "c1") -> MomentoDaPessoa:
    return MomentoDaPessoa(job, pessoa, pessoa.upper(), tipo, ini, fim)


def test_so_aparicoes_somam_tempo_e_mencoes_so_contam() -> None:
    linhas = relatorio(
        [
            _m("j1", "aparicao", 0, 10_000),
            _m("j1", "mencao_na_fala", 20_000, 25_000),
            _m("j1", "mencao_na_fala", 30_000, 31_000),
            _m("j1", "mencao_no_texto", 40_000, 45_000),
        ]
    )

    (c1,) = linhas
    assert c1.tempo_de_tela_ms == 10_000
    assert (c1.videos, c1.aparicoes) == (1, 1)
    assert (c1.mencoes_na_fala, c1.mencoes_no_texto) == (2, 1)


def test_a_mesma_pessoa_com_grafias_diferentes_e_uma_linha_so() -> None:
    linhas = relatorio(
        [
            MomentoDaPessoa("j1", "c1", "Sílvio Santos", "aparicao", 0, 1_000),
            MomentoDaPessoa("j2", "c1", "Silvio Santos", "aparicao", 0, 2_000),
            MomentoDaPessoa("j3", "c1", "Silvio Santos", "aparicao", 0, 3_000),
        ]
    )

    (c1,) = linhas
    assert (c1.nome, c1.tempo_de_tela_ms, c1.videos) == ("Silvio Santos", 6_000, 3)


def test_aparicoes_sobrepostas_ou_coladas_da_mesma_pessoa_nao_contam_em_dobro() -> None:
    linhas = relatorio(
        [
            _m("j1", "aparicao", 0, 10_000),
            _m("j1", "aparicao", 5_000, 12_000),  # sobrepõe
            _m("j1", "aparicao", 12_000, 15_000),  # cola
            _m("j1", "aparicao", 20_000, 21_000),
            _m("j2", "aparicao", 0, 10_000),  # outro vídeo soma
            _m("j1", "aparicao", 0, 10_000, pessoa="c2"),  # outra pessoa não se mistura
        ]
    )

    por_pessoa = {x.pessoa_id: x for x in linhas}
    c1 = por_pessoa["c1"]
    assert c1.tempo_de_tela_ms == 15_000 + 1_000 + 10_000
    assert (c1.videos, c1.aparicoes) == (2, 3)
    assert {v.job_id: v.tempo_de_tela_ms for v in c1.por_video} == {
        "j1": 16_000,
        "j2": 10_000,
    }
    assert por_pessoa["c2"].tempo_de_tela_ms == 10_000


def test_a_tabela_vem_ordenada_por_tempo_e_quem_so_foi_citado_fica_com_zero() -> None:
    linhas = relatorio(
        [
            _m("j1", "aparicao", 0, 1_000, "a"),
            _m("j1", "aparicao", 0, 9_000, "b"),
            _m("j1", "mencao_na_fala", 0, 1_000, "z"),
        ]
    )

    assert [(x.pessoa_id, x.tempo_de_tela_ms) for x in linhas] == [
        ("b", 9_000),
        ("a", 1_000),
        ("z", 0),
    ]
    assert linhas[-1].videos == 0


def _linha(
    job: str, programa: str | None, dia: date | None, tipo: str, **kw: Any
) -> LinhaDoMomento:
    return LinhaDoMomento(
        job_id=job,
        programa=programa,
        data_de_exibicao=dia,
        tipo=tipo,
        inicio_ms=kw.get("ini", 0),
        fim_ms=kw.get("fim", 1_000),
        pessoas=[PessoaDoMomento("c1", "Sabrina")],
    )


def _copia() -> CopiaEmMemoria:
    copia = CopiaEmMemoria()
    copia.gravar(
        "j1",
        [
            _linha("j1", "Jornal", date(2026, 10, 1), "aparicao"),
            _linha("j1", "Jornal", date(2026, 10, 1), "plano"),
            _linha("j1", "Jornal", date(2026, 10, 1), "fala"),
        ],
    )
    copia.gravar("j2", [_linha("j2", "Fama", date(2026, 10, 15), "aparicao")])
    copia.gravar("j3", [_linha("j3", "Jornal", date(2026, 11, 1), "mencao_na_fala")])
    copia.gravar("j4", [_linha("j4", "Jornal", None, "aparicao")])
    return copia


def _jobs(consulta: ConsultaEmMemoria) -> set[str]:
    return {m.job_id for m in consulta.momentos(None, None, None)}


def test_a_consulta_em_memoria_so_traz_os_tipos_do_relatorio() -> None:
    consulta = ConsultaEmMemoria(_copia())

    momentos = consulta.momentos(None, None, None)

    assert {m.tipo for m in momentos} == {"aparicao", "mencao_na_fala"}
    assert _jobs(consulta) == {"j1", "j2", "j3", "j4"}


def test_a_consulta_filtra_por_programa_e_por_periodo_inclusive() -> None:
    consulta = ConsultaEmMemoria(_copia())

    assert {m.job_id for m in consulta.momentos("Fama", None, None)} == {"j2"}
    assert {
        m.job_id for m in consulta.momentos(None, date(2026, 10, 15), date(2026, 11, 1))
    } == {"j2", "j3"}
    # Sem data de exibição não cabe num período pedido.
    assert "j4" not in {
        m.job_id for m in consulta.momentos(None, date(2020, 1, 1), None)
    }


class Transporte:
    def __init__(self, resposta: dict[str, Any]) -> None:
        self.resposta = resposta
        self.corpos: list[dict[str, Any]] = []

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return self.resposta


def _linha_do_bq(*valores: str) -> dict[str, Any]:
    return {"f": [{"v": v} for v in valores]}


CONFIG = ConfigDoBigQuery("proj", "ds", "tab", "regiao")


def test_bigquery_pede_so_os_tipos_do_relatorio_com_os_filtros_como_parametros() -> (
    None
):
    transporte = Transporte(
        {
            "jobComplete": True,
            "rows": [
                _linha_do_bq("j1", "c1", "Sabrina", "aparicao", "0", "5000"),
                _linha_do_bq("j1", "c1", "Sabrina", "mencao_na_fala", "7000", "8000"),
            ],
        }
    )

    momentos = ConsultaBigQuery(CONFIG, transporte).momentos(
        "Jornal", date(2026, 10, 1), date(2026, 10, 31)
    )

    assert momentos == [
        MomentoDaPessoa("j1", "c1", "Sabrina", "aparicao", 0, 5000),
        MomentoDaPessoa("j1", "c1", "Sabrina", "mencao_na_fala", 7000, 8000),
    ]
    (corpo,) = transporte.corpos
    consulta = corpo["query"]
    assert "`proj.ds.tab`" in consulta
    assert "'aparicao'" in consulta and "'mencao_na_fala'" in consulta
    assert "'plano'" not in consulta
    assert corpo["location"] == "regiao"
    parametros = {
        p["name"]: (p["parameterType"]["type"], p["parameterValue"]["value"])
        for p in corpo["queryParameters"]
    }
    assert parametros == {
        "programa": ("STRING", "Jornal"),
        "desde": ("DATE", "2026-10-01"),
        "ate": ("DATE", "2026-10-31"),
    }
    assert "Jornal" not in consulta  # o valor vai como parâmetro, nunca no texto


def test_bigquery_sem_filtros_nao_leva_parametros_e_sem_linhas_devolve_vazio() -> None:
    transporte = Transporte({"jobComplete": True})

    assert ConsultaBigQuery(CONFIG, transporte).momentos(None, None, None) == []
    assert transporte.corpos[0]["queryParameters"] == []


def test_bigquery_resposta_incompleta_ou_cortada_falha_alto() -> None:
    import pytest

    for resposta in ({"jobComplete": False}, {"jobComplete": True, "pageToken": "x"}):
        with pytest.raises(RuntimeError):
            ConsultaBigQuery(CONFIG, Transporte(resposta)).momentos(None, None, None)


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
            tempo_de_tela=consulta,
        )
    )


def test_rota_devolve_a_tabela_com_os_videos_de_cada_pessoa() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    resposta = cliente.get(ROTA, params={"programa": "Jornal"}, headers=AUTORIZACAO)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["programa"] == "Jornal"
    (sabrina,) = corpo["pessoas"]
    assert sabrina["pessoa_id"] == "c1"
    assert sabrina["tempo_de_tela_ms"] == 2_000  # j1 e j4 (sem data) com 1 s cada
    assert sabrina["mencoes_na_fala"] == 1
    por_video = {v["job_id"]: v for v in sabrina["por_video"]}
    assert por_video["j1"]["nome"] == "jornal-01.mp4"
    assert por_video["j4"]["nome"] is None


def test_rota_filtra_pelo_periodo() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    corpo = cliente.get(
        ROTA, params={"desde": "2026-10-10", "ate": "2026-10-20"}, headers=AUTORIZACAO
    ).json()

    assert [v["job_id"] for v in corpo["pessoas"][0]["por_video"]] == ["j2"]


def test_rota_em_csv_tem_uma_linha_por_pessoa() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    resposta = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/csv")
    assert "attachment" in resposta.headers["content-disposition"]
    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    assert linhas == [
        {
            "pessoa_id": "c1",
            "nome": "Sabrina",
            "tempo_de_tela_ms": "3000",
            "videos": "3",
            "aparicoes": "3",
            "mencoes_na_fala": "1",
            "mencoes_no_texto": "0",
        }
    ]


def test_csv_nao_deixa_o_nome_virar_formula() -> None:
    copia = CopiaEmMemoria()
    copia.gravar(
        "j1",
        [
            LinhaDoMomento(
                job_id="j1",
                programa="Jornal",
                data_de_exibicao=date(2026, 10, 1),
                tipo="aparicao",
                inicio_ms=0,
                fim_ms=1000,
                pessoas=[PessoaDoMomento("c9", "=HYPERLINK(1)")],
            )
        ],
    )
    cliente = _cliente(consulta=ConsultaEmMemoria(copia))

    texto = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO).text

    assert "'=HYPERLINK(1)" in texto


def test_rota_exige_login_e_o_bigquery_configurado() -> None:
    assert _cliente(consulta=ConsultaEmMemoria(_copia())).get(ROTA).status_code == 401
    assert _cliente().get(ROTA, headers=AUTORIZACAO).status_code == 503


def test_rota_nega_periodo_invertido_e_formato_desconhecido() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    assert (
        cliente.get(
            ROTA,
            params={"desde": "2026-11-01", "ate": "2026-10-01"},
            headers=AUTORIZACAO,
        ).status_code
        == 422
    )
    assert (
        cliente.get(ROTA, params={"formato": "xml"}, headers=AUTORIZACAO).status_code
        == 422
    )


def test_programa_vazio_e_todos_os_programas() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    vazio = cliente.get(ROTA, params={"programa": ""}, headers=AUTORIZACAO).json()
    todos = cliente.get(ROTA, headers=AUTORIZACAO).json()

    assert vazio["programa"] is None
    assert vazio["pessoas"] == todos["pessoas"] != []


def test_chave_de_sistema_nao_consulta_o_relatorio() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave("Playout", frozenset({"ler"}), MAC, chaves, BASE)
    cliente = TestClient(
        criar_app(
            VerificadorFalso({}),
            RepositorioEmMemoria(),
            chaves=VerificadorDeChaveDeApi(chaves, MAC),
            tempo_de_tela=ConsultaEmMemoria(_copia()),
        )
    )

    resposta = cliente.get(ROTA, headers={"X-API-Key": emitida.chave})

    assert resposta.status_code == 403
