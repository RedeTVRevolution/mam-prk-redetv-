"""O relatório de tempo de tela (#266): o cálculo, a consulta no BigQuery e a rota."""

import csv
import io
import random
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.cache_curto import CacheCurto
from api.catalogo import (
    CatalogoEmMemoria,
    EnvioParaLixeira,
    FusaoDaPessoa,
    PessoaDoCatalogo,
)
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
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.modelo_do_job import Job, agora_utc
from api.papeis import RepositorioDePapeisEmMemoria
from api.tempo_de_tela import (
    COLUNAS_DO_CSV,
    SOMA_EM_SQL,
    UNIAO_EM_SQL,
    ConsultaBigQuery,
    ConsultaDeMomentos,
    ConsultaEmMemoria,
    MomentoDaPessoa,
    PessoaNoRelatorio,
    PessoaNoVideo,
    pessoa_no_video,
    ranking_em_python,
    somar,
)
from api.tempo_de_tela import ConsultaComCache as ComCache
from api.tempo_de_tela import relatorio as relatorio_das_somas
from api.tests.sem_periodo_padrao import ClienteSemPeriodoPadrao
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.tests.test_passadas import AUTORIZACAO

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ROTA = "/v1/relatorios/tempo-de-tela"


def _nomes(momentos: list[MomentoDaPessoa]) -> dict[str, str]:
    return {m.pessoa_id: m.pessoa_id.upper() for m in momentos}


def relatorio(
    momentos: list[MomentoDaPessoa], nomes: dict[str, str] | None = None
) -> list[PessoaNoRelatorio]:
    """O relatório de hoje: a soma (que o BigQuery faz) e a montagem, com os nomes do
    catálogo (por padrão, o id em maiúsculas)."""
    return relatorio_das_somas(somar(momentos), nomes or _nomes(momentos))


def _m(job: str, tipo: str, ini: int, fim: int, pessoa: str = "c1") -> MomentoDaPessoa:
    return MomentoDaPessoa(job, pessoa, tipo, ini, fim)


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


def test_a_pessoa_em_varios_videos_e_uma_linha_so_com_o_nome_do_catalogo() -> None:
    linhas = relatorio(
        [
            MomentoDaPessoa("j1", "c1", "aparicao", 0, 1_000),
            MomentoDaPessoa("j2", "c1", "aparicao", 0, 2_000),
            MomentoDaPessoa("j3", "c1", "aparicao", 0, 3_000),
        ],
        {"c1": "Silvio Santos"},
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
    return {m.job_id for m in consulta.momentos((), None, None)}


def test_a_consulta_em_memoria_so_traz_os_tipos_do_relatorio() -> None:
    consulta = ConsultaEmMemoria(_copia())

    momentos = consulta.momentos((), None, None)

    assert {m.tipo for m in momentos} == {"aparicao", "mencao_na_fala"}
    assert _jobs(consulta) == {"j1", "j2", "j3", "j4"}


def test_a_consulta_filtra_por_programa_e_por_periodo_inclusive() -> None:
    consulta = ConsultaEmMemoria(_copia())

    assert {m.job_id for m in consulta.momentos(("Fama",), None, None)} == {"j2"}
    assert {
        m.job_id for m in consulta.momentos((), date(2026, 10, 15), date(2026, 11, 1))
    } == {"j2", "j3"}
    # Sem data de exibição não cabe num período pedido.
    assert "j4" not in {m.job_id for m in consulta.momentos((), date(2020, 1, 1), None)}


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


def test_bigquery_pede_a_soma_so_dos_tipos_do_relatorio_com_os_filtros_como_parametros() -> (
    None
):
    transporte = Transporte(
        {
            "jobComplete": True,
            "rows": [
                _linha_do_bq("j1", "c1", "5000", "1", "2", "0"),
                _linha_do_bq("j2", "c1", "0", "0", "0", "1"),
            ],
        }
    )

    somas = ConsultaBigQuery(CONFIG, transporte).somas(
        ("Jornal",), date(2026, 10, 1), date(2026, 10, 31)
    )

    assert somas == [
        PessoaNoVideo("j1", "c1", 5000, 1, 2, 0),
        PessoaNoVideo("j2", "c1", 0, 0, 0, 1),
    ]
    (corpo,) = transporte.corpos
    consulta = corpo["query"]
    assert "`proj.ds.tab`" in consulta
    assert "'aparicao'" in consulta and "'mencao_na_fala'" in consulta
    assert "'plano'" not in consulta
    assert "GROUP BY" in consulta  # a soma é do BigQuery
    assert corpo["location"] == "regiao"
    parametros = {
        p["name"]: (p["parameterType"]["type"], p["parameterValue"].get("value"))
        for p in corpo["queryParameters"]
    }
    assert parametros == {
        "programas": ("ARRAY", None),
        "desde": ("DATE", "2026-10-01"),
        "ate": ("DATE", "2026-10-31"),
    }
    assert "Jornal" not in consulta  # o valor vai como parâmetro, nunca no texto


def test_bigquery_sem_filtros_nao_leva_parametros_e_sem_linhas_devolve_vazio() -> None:
    transporte = Transporte({"jobComplete": True})

    assert ConsultaBigQuery(CONFIG, transporte).somas((), None, None) == []
    assert transporte.corpos[0]["queryParameters"] == []


def test_bigquery_resposta_incompleta_falha_alto() -> None:
    import pytest

    with pytest.raises(RuntimeError):
        ConsultaBigQuery(CONFIG, Transporte({"jobComplete": False})).somas(
            (), None, None
        )


def _sqlite_com(momentos: list[MomentoDaPessoa]) -> sqlite3.Connection:
    banco = sqlite3.connect(":memory:")
    banco.execute(
        "CREATE TABLE base (job_id, pessoa_id, tipo, inicio_ms, fim_ms)"
    )
    banco.executemany(
        "INSERT INTO base VALUES (?, ?, ?, ?, ?)",
        [
            (m.job_id, m.pessoa_id, m.tipo, m.inicio_ms, m.fim_ms)
            for m in momentos
        ],
    )
    return banco


def test_a_uniao_em_sql_da_os_mesmos_numeros_que_a_de_python() -> None:
    # O texto de UNIAO_EM_SQL é o que vai ao BigQuery; só usa SQL que o SQLite também
    # roda, então o mesmo texto confere a soma contra `somar` em vários conjuntos.
    sorteio = random.Random(363)
    for _ in range(200):
        momentos = [
            MomentoDaPessoa(
                job_id=sorteio.choice(["j1", "j2"]),
                pessoa_id=sorteio.choice(["c1", "c2"]),
                tipo=sorteio.choice(["aparicao", "aparicao", "mencao_na_fala"]),
                inicio_ms=(inicio := sorteio.randrange(0, 50)),
                fim_ms=inicio
                + sorteio.randrange(0, 15),  # inclui duração zero e colados
            )
            for _ in range(sorteio.randrange(1, 25))
        ]
        banco = _sqlite_com(momentos)

        do_sql = {
            (j, p): (int(tempo), int(n))
            for j, p, tempo, n in banco.execute(
                f"WITH {UNIAO_EM_SQL}\n"
                "SELECT job_id, pessoa_id, SUM(fim_ms - inicio_ms), COUNT(*) "
                "FROM unidas GROUP BY job_id, pessoa_id"
            )
        }

        em_python = {
            (s.job_id, s.pessoa_id): (s.tempo_de_tela_ms, s.aparicoes)
            for s in somar(momentos)
            if s.aparicoes
        }
        assert do_sql == em_python


def test_a_soma_em_sql_inteira_da_os_mesmos_numeros_que_a_de_python() -> None:
    # O SOMA_EM_SQL que vai ao BigQuery roda num SQLite, e cada linha passa pela mesma
    # leitura da consulta real: confere a união, as contagens e a ordem das colunas.
    sql = "WITH base AS (SELECT * FROM linhas)\n" + SOMA_EM_SQL
    sorteio = random.Random(363)
    for _ in range(200):
        momentos = [
            MomentoDaPessoa(
                job_id=sorteio.choice(["j1", "j2"]),
                pessoa_id=sorteio.choice(["c1", "c2"]),
                tipo=sorteio.choice(
                    ["aparicao", "aparicao", "mencao_na_fala", "mencao_no_texto"]
                ),
                inicio_ms=(inicio := sorteio.randrange(0, 50)),
                fim_ms=inicio + sorteio.randrange(0, 15),
            )
            for _ in range(sorteio.randrange(1, 25))
        ]
        banco = _sqlite_com(momentos)
        banco.execute("ALTER TABLE base RENAME TO linhas")

        do_sql = [pessoa_no_video(v) for v in banco.execute(sql)]

        assert sorted(do_sql, key=repr) == sorted(somar(momentos), key=repr)
        assert relatorio_das_somas(do_sql, _nomes(momentos)) == relatorio(momentos)


def test_a_uniao_em_sql_cola_o_que_se_toca_e_une_o_que_se_sobrepoe() -> None:
    banco = _sqlite_com(
        [
            _m("j1", "aparicao", 0, 10_000),
            _m("j1", "aparicao", 5_000, 12_000),  # sobrepõe
            _m("j1", "aparicao", 12_000, 15_000),  # cola
            _m("j1", "aparicao", 20_000, 21_000),
            _m("j1", "aparicao", 1_000, 2_000),  # dentro de outro
            _m("j2", "aparicao", 0, 10_000),
        ]
    )

    unidas = banco.execute(
        f"WITH {UNIAO_EM_SQL}\nSELECT job_id, inicio_ms, fim_ms FROM unidas "
        "ORDER BY job_id, inicio_ms"
    ).fetchall()

    assert unidas == [
        ("j1", 0, 15_000),
        ("j1", 20_000, 21_000),
        ("j2", 0, 10_000),
    ]


def test_a_soma_em_memoria_e_a_que_o_relatorio_monta() -> None:
    somas = ConsultaEmMemoria(_copia()).somas((), None, None)

    por_par = {(s.job_id, s.pessoa_id): s for s in somas}
    assert por_par[("j1", "c1")] == PessoaNoVideo(
        "j1", "c1", 1_000, 1, 0, 0
    )
    assert por_par[("j3", "c1")].mencoes_na_fala == 1
    assert len(somas) == 4


def _catalogo_da_copia(consulta: Any) -> CatalogoEmMemoria:
    """O catálogo com cada pessoa que a cópia por trás da consulta traz, com o nome da
    cópia: o relatório só conta quem existe no catálogo (#591)."""
    while not hasattr(consulta, "_copia"):
        consulta = consulta._consulta
    catalogo = CatalogoEmMemoria()
    for linhas in consulta._copia.por_job.values():
        for linha in linhas:
            for p in linha.pessoas:
                catalogo._itens.setdefault(
                    p.id, PessoaDoCatalogo(id=p.id, nome=p.nome or p.id, papel="")
                )
    return catalogo


def _cliente(
    papel: str = "consulta",
    consulta: ConsultaDeMomentos | None = None,
    relogio: Callable[[], datetime] | None = None,
    catalogo: CatalogoEmMemoria | None = None,
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
    app = criar_app(
        VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@redetv.com.br")}),
        jobs,
        papeis=papeis,
        tempo_de_tela=consulta,
        catalogo=catalogo or (_catalogo_da_copia(consulta) if consulta else None),
        relogio=relogio or agora_utc,
    )
    # Com relógio, o teste é do período padrão: o cliente comum não pede o histórico inteiro.
    return TestClient(app) if relogio else ClienteSemPeriodoPadrao(app)


def test_rota_devolve_a_tabela_com_os_videos_de_cada_pessoa() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_copia()))

    resposta = cliente.get(ROTA, params={"programa": "Jornal"}, headers=AUTORIZACAO)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["programas"] == ["Jornal"]
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

    assert vazio["programas"] == []
    assert vazio["pessoas"] == todos["pessoas"] != []


def test_chave_de_sistema_nao_consulta_o_relatorio() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave("Playout", frozenset({"ler"}), MAC, chaves, BASE)
    cliente = ClienteSemPeriodoPadrao(
        criar_app(
            VerificadorFalso({}),
            RepositorioEmMemoria(),
            chaves=VerificadorDeChaveDeApi(chaves, MAC),
            tempo_de_tela=ConsultaEmMemoria(_copia()),
        )
    )

    resposta = cliente.get(ROTA, headers={"X-API-Key": emitida.chave})

    assert resposta.status_code == 403
    videos = cliente.get(
        f"{ROTA}/videos",
        params={"pessoa_id": "c1"},
        headers={"X-API-Key": emitida.chave},
    )
    assert videos.status_code == 403


# Com `limite` (ADR 0014): o ranking paginado, os totais e os vídeos de uma pessoa.


def _varias_pessoas() -> CopiaEmMemoria:
    """c1 com 3 s em dois vídeos; c2 e c3 empatadas com 2 s; c4 só citada."""
    copia = CopiaEmMemoria()

    def linha(job: str, pessoa: str, tipo: str, fim: int) -> LinhaDoMomento:
        return LinhaDoMomento(
            job_id=job,
            programa="Jornal",
            data_de_exibicao=date(2026, 10, 1),
            tipo=tipo,
            inicio_ms=0,
            fim_ms=fim,
            pessoas=[PessoaDoMomento(pessoa, pessoa.upper())],
        )

    copia.gravar(
        "j1",
        [
            linha("j1", "c1", "aparicao", 1_000),
            linha("j1", "c3", "aparicao", 2_000),
            linha("j1", "c4", "mencao_na_fala", 0),
        ],
    )
    copia.gravar(
        "j2",
        [linha("j2", "c1", "aparicao", 2_000), linha("j2", "c2", "aparicao", 2_000)],
    )
    return copia


def test_sem_limite_a_resposta_e_a_de_antes() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_varias_pessoas()))

    resposta = cliente.get(ROTA, params={"cursor": "lixo"}, headers=AUTORIZACAO)

    assert resposta.status_code == 200  # sem `limite`, o cursor não conta
    assert "X-Proximo-Cursor" not in resposta.headers
    corpo = resposta.json()
    assert set(corpo) == {"programas", "desde", "ate", "pessoas"}
    assert all("por_video" in p for p in corpo["pessoas"])
    # A ordem de sempre: tempo, nome, id.
    assert [p["pessoa_id"] for p in corpo["pessoas"]] == ["c1", "c2", "c3", "c4"]


def test_com_limite_pagina_o_ranking_com_os_totais_e_sem_os_videos() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_varias_pessoas()))

    primeira = cliente.get(ROTA, params={"limite": 3}, headers=AUTORIZACAO)
    corpo = primeira.json()
    segunda = cliente.get(
        ROTA,
        params={"limite": 3, "cursor": primeira.headers["X-Proximo-Cursor"]},
        headers=AUTORIZACAO,
    )

    assert corpo["total"] == {
        "pessoas": 4,
        "tempo_de_tela_ms": 7_000,
        "videos": 2,
        "aparicoes": 4,
        "mencoes_na_fala": 1,
        "mencoes_no_texto": 0,
    }
    assert corpo["pessoas"][0] == {
        "pessoa_id": "c1",
        "nome": "C1",
        "tempo_de_tela_ms": 3_000,
        "videos": 2,
        "aparicoes": 2,
        "mencoes_na_fala": 0,
        "mencoes_no_texto": 0,
    }
    assert "X-Proximo-Cursor" not in segunda.headers
    assert segunda.json()["total"] == corpo["total"]
    vistas = [p["pessoa_id"] for r in (corpo, segunda.json()) for p in r["pessoas"]]
    assert vistas == ["c1", "c2", "c3", "c4"]  # no empate, o id desempata


def test_com_limite_o_csv_vem_inteiro_e_cursor_invalido_e_422() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_varias_pessoas()))

    texto = cliente.get(
        ROTA, params={"limite": 1, "formato": "csv"}, headers=AUTORIZACAO
    ).text

    assert len(list(csv.DictReader(io.StringIO(texto)))) == 4
    ruins: list[dict[str, Any]] = [
        {"limite": 1, "cursor": "lixo"},
        {"limite": 1, "cursor": "LTE"},  # "-1"
        {"limite": 1, "cursor": "wrI"},  # "²", dígito fora do ASCII
        {"limite": 1, "cursor": "OTk5OTk5OTk5OQ"},  # "9999999999", 10 dígitos
        {"limite": 0},
        {"limite": 101},
    ]
    for params in ruins:
        assert cliente.get(ROTA, params=params, headers=AUTORIZACAO).status_code == 422


def test_os_videos_de_uma_pessoa_vem_paginados_e_com_o_nome() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(_varias_pessoas()))
    rota = f"{ROTA}/videos"

    primeira = cliente.get(
        rota, params={"pessoa_id": "c1", "limite": 1}, headers=AUTORIZACAO
    )
    segunda = cliente.get(
        rota,
        params={
            "pessoa_id": "c1",
            "limite": 1,
            "cursor": primeira.headers["X-Proximo-Cursor"],
        },
        headers=AUTORIZACAO,
    )

    assert [v["job_id"] for v in primeira.json()] == ["j2"]  # o maior tempo primeiro
    assert segunda.json() == [
        {
            "job_id": "j1",
            "nome": "jornal-01.mp4",
            "tempo_de_tela_ms": 1_000,
            "aparicoes": 1,
            "mencoes_na_fala": 0,
            "mencoes_no_texto": 0,
        }
    ]
    assert "X-Proximo-Cursor" not in segunda.headers
    vazia = cliente.get(rota, params={"pessoa_id": "c9"}, headers=AUTORIZACAO)
    assert vazia.json() == []
    assert cliente.get(rota, headers=AUTORIZACAO).status_code == 422  # sem a pessoa
    sem_bigquery = _cliente().get(rota, params={"pessoa_id": "c1"}, headers=AUTORIZACAO)
    assert sem_bigquery.status_code == 503


def test_o_nome_do_relatorio_vem_do_catalogo_inclusive_depois_de_renomear() -> None:
    catalogo = CatalogoEmMemoria()
    ana = catalogo.acrescentar("Ana Souza", "apresentadora", [])
    bia = catalogo.acrescentar("Bia Lima", "", [])
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
                fim_ms=fim,
                pessoas=[PessoaDoMomento(quem.id)],  # a cópia não grava o nome
            )
            for quem, fim in ((ana, 2_000), (bia, 1_000))
        ],
    )
    cliente = _cliente(consulta=ConsultaEmMemoria(copia), catalogo=catalogo)

    def nomes(**params: Any) -> list[str]:
        corpo = cliente.get(ROTA, params=params, headers=AUTORIZACAO).json()
        return [p["nome"] for p in corpo["pessoas"]]

    assert nomes() == ["Ana Souza", "Bia Lima"]
    assert nomes(limite=10) == ["Ana Souza", "Bia Lima"]

    catalogo.corrigir(ana.id, nome="Ana Souza Pereira", apelidos=[])

    assert nomes() == ["Ana Souza Pereira", "Bia Lima"]
    assert nomes(limite=10) == ["Ana Souza Pereira", "Bia Lima"]
    csv_ = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO).text
    assert "Ana Souza Pereira" in csv_


def test_o_nome_do_catalogo_nao_suja_o_ranking_guardado_no_cache() -> None:
    catalogo = CatalogoEmMemoria()
    ana = catalogo.acrescentar("Ana", "", [])
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
                fim_ms=1_000,
                pessoas=[PessoaDoMomento(ana.id, "Antigo")],
            )
        ],
    )
    cache = CacheCurto()
    cliente = _cliente(
        consulta=ComCache(ConsultaEmMemoria(copia), cache), catalogo=catalogo
    )

    def nome() -> str:
        corpo = cliente.get(ROTA, params={"limite": 5}, headers=AUTORIZACAO).json()
        return str(corpo["pessoas"][0]["nome"])

    assert nome() == "Ana"
    catalogo.corrigir(ana.id, nome="Ana Maria", apelidos=[])
    assert nome() == "Ana Maria"


class CatalogoQueConta(CatalogoEmMemoria):
    """O catálogo em memória que anota quantas leituras em lote recebeu."""

    def __init__(self) -> None:
        super().__init__()
        self.leituras = 0

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        self.leituras += 1
        return super().obter_varios(ids)


def _empate_com_nome_atual() -> tuple[CatalogoQueConta, CopiaEmMemoria]:
    """Quatro pessoas empatadas em 2 s, com o id na ordem contrária à dos nomes atuais.
    p1 se chama "Zélia" no catálogo e "Ana" (o mais frequente) na cópia; p3 foi fundida em
    p4 ("Carla"), e o nome dela mesma ("Zzz Velho") não vale; as duas somam numa linha (#784)."""
    catalogo = CatalogoQueConta()
    for id_, nome in (
        ("p1", "Zélia"),
        ("p2", "Bia"),
        ("p3", "Zzz Velho"),
        ("p4", "Carla"),
    ):
        catalogo._itens[id_] = PessoaDoCatalogo(id=id_, nome=nome, papel="")
    catalogo.definir_fusao(
        "p3",
        FusaoDaPessoa(
            destino_id="p4",
            em=agora_utc(),
            por_uid="u",
            por_email="u@r.com",
            motivo="x",
        ),
    )
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
                fim_ms=2_000,
                pessoas=[PessoaDoMomento(id_, "Ana" if id_ == "p1" else id_)],
            )
            for id_ in ("p1", "p2", "p3", "p4")
        ],
    )
    return catalogo, copia


def test_tela_e_csv_saem_na_mesma_ordem_no_empate_pelo_nome_atual() -> None:
    catalogo, copia = _empate_com_nome_atual()
    cliente = _cliente(consulta=ConsultaEmMemoria(copia), catalogo=catalogo)
    esperado = [("p2", "Bia"), ("p4", "Carla"), ("p1", "Zélia")]  # p3 soma em p4

    completo = cliente.get(ROTA, headers=AUTORIZACAO).json()["pessoas"]
    csv_ = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO).text
    paginas: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limite": 1}
        if cursor:
            params["cursor"] = cursor
        pagina = cliente.get(ROTA, params=params, headers=AUTORIZACAO)
        paginas += [(p["pessoa_id"], p["nome"]) for p in pagina.json()["pessoas"]]
        if cursor is None:
            assert (
                pagina.headers["X-Proximo-Cursor"] == "MQ"
            )  # a posição 1, como sempre
        cursor = pagina.headers.get("X-Proximo-Cursor")
        if not cursor:
            break

    assert [(p["pessoa_id"], p["nome"]) for p in completo] == esperado
    linhas = list(csv.DictReader(io.StringIO(csv_)))
    assert [(r["pessoa_id"], r["nome"]) for r in linhas] == esperado
    assert paginas == esperado  # o empate cortado entre páginas não troca a ordem


def test_o_catalogo_e_lido_uma_vez_por_pedido() -> None:
    catalogo, copia = _empate_com_nome_atual()
    cliente = _cliente(consulta=ConsultaEmMemoria(copia), catalogo=catalogo)

    for params in ({"limite": 2}, {}, {"formato": "csv"}):
        catalogo.leituras = 0
        cliente.get(ROTA, params=params, headers=AUTORIZACAO)
        assert catalogo.leituras == 1


def test_o_ranking_usa_o_nome_do_catalogo_no_empate() -> None:
    somas = somar(
        [
            MomentoDaPessoa("j1", "p1", 0, 1_000),
            MomentoDaPessoa("j1", "p2", 0, 1_000),
        ]
    )

    pagina, _ = ranking_em_python(somas, 0, 10, {"p1": "Zeca", "p2": "Ana"})

    assert [(p.pessoa_id, p.nome) for p in pagina] == [("p2", "Ana"), ("p1", "Zeca")]


def test_video_so_de_mencoes_nao_entra_no_total_de_videos() -> None:
    somas = somar(
        [
            MomentoDaPessoa("j1", "p1", "aparicao", 0, 1_000),
            MomentoDaPessoa("j2", "p1", "mencao_na_fala", 0, 500),
            MomentoDaPessoa("j2", "p2", "mencao_no_texto", 0, 500),
        ]
    )

    pagina, total = ranking_em_python(somas, 0, 10, {"p1": "Ana", "p2": "Bia"})

    assert total.videos == 1  # j2 só tem menções
    assert total.mencoes_na_fala == 1 and total.mencoes_no_texto == 1
    assert [(p.pessoa_id, p.videos) for p in pagina] == [("p1", 1), ("p2", 0)]


class ConsultaQueEstoura(ConsultaEmMemoria):
    def __init__(self) -> None:
        super().__init__(CopiaEmMemoria())

    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        raise RuntimeError("a consulta do BigQuery não terminou a tempo")


@pytest.mark.parametrize("params", [{}, {"formato": "csv"}])
def test_consulta_que_nao_termina_vira_503_em_json_e_em_csv(
    params: dict[str, str],
) -> None:
    cliente = _cliente(consulta=ConsultaQueEstoura())

    resposta = cliente.get(ROTA, params=params, headers=AUTORIZACAO)

    assert resposta.status_code == 503
    assert "não terminou" in resposta.json()["detail"]


def test_sem_resultados_o_json_vem_vazio_e_o_csv_so_com_o_cabecalho() -> None:
    cliente = _cliente(consulta=ConsultaEmMemoria(CopiaEmMemoria()))

    json_ = cliente.get(ROTA, headers=AUTORIZACAO)
    csv_ = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO)

    assert json_.status_code == 200 and json_.json()["pessoas"] == []
    assert csv_.status_code == 200
    assert csv_.text.splitlines() == [",".join(COLUNAS_DO_CSV)]


class SoSomas:
    """Uma fonte nova das somas: `somas` de verdade e a consulta de intervalos que falha
    (sem fusão no período, ninguém pode pedi-la, #784)."""

    def __init__(self, copia: CopiaEmMemoria) -> None:
        self._em_memoria = ConsultaEmMemoria(copia)

    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        return self._em_memoria.somas(programas, desde, ate)

    def aparicoes_unidas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        pessoas: Sequence[str],
    ) -> list[tuple[str, str, int, int]]:
        raise AssertionError("sem fusão no período não há consulta de intervalos")


def test_uma_fonte_so_com_somas_serve_ao_ranking_e_aos_videos_da_pessoa() -> None:
    copia = _varias_pessoas()
    catalogo = _catalogo_da_copia(ConsultaEmMemoria(copia))
    nova = _cliente(consulta=SoSomas(copia), catalogo=catalogo)
    velha = _cliente(consulta=ConsultaEmMemoria(copia), catalogo=catalogo)

    casos: list[tuple[str, dict[str, Any]]] = [
        (ROTA, {"limite": 2}),
        (ROTA, {}),
        (f"{ROTA}/videos", {"pessoa_id": "c1"}),
    ]
    for url, params in casos:
        resposta = nova.get(url, params=params, headers=AUTORIZACAO)
        assert resposta.status_code == 200
        assert resposta.text == velha.get(url, params=params, headers=AUTORIZACAO).text


# --- a pessoa fundida numa linha só (#784) ------------------------------------------------


def _fusao() -> FusaoDaPessoa:
    return FusaoDaPessoa(
        destino_id="p4", em=agora_utc(), por_uid="u", por_email="u@r.com", motivo="x"
    )


def _aparicao(job: str, pessoa: str, ini: int, fim: int, tipo: str = "aparicao") -> Any:
    return LinhaDoMomento(
        job_id=job,
        programa="Jornal",
        data_de_exibicao=date(2026, 10, 1),
        tipo=tipo,
        inicio_ms=ini,
        fim_ms=fim,
        pessoas=[PessoaDoMomento(pessoa, pessoa)],
    )


class FonteQueContaIntervalos(ConsultaEmMemoria):
    def __init__(self, copia: CopiaEmMemoria) -> None:
        super().__init__(copia)
        self.pedidos: list[Sequence[str]] = []

    def aparicoes_unidas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        pessoas: Sequence[str],
    ) -> list[tuple[str, str, int, int]]:
        self.pedidos.append(pessoas)
        return super().aparicoes_unidas(programas, desde, ate, pessoas)


def _mundo_da_fusao() -> tuple[CatalogoQueConta, FonteQueContaIntervalos]:
    """p3 foi fundida em p4 ("Carla"). Em j1 as duas aparecem com intervalos que se
    sobrepõem (p3 0-2 s, p4 1-3 s: 3 s unidos, não 4 s somados) e p3 cita Carla na fala;
    j2 só tem p3 (1 s); j3 só tem p4 (0,5 s); p1 ("Ana") tem 1,5 s em j3."""
    catalogo = CatalogoQueConta()
    for id_, nome in (("p1", "Ana"), ("p3", "Carla Velha"), ("p4", "Carla")):
        catalogo._itens[id_] = PessoaDoCatalogo(id=id_, nome=nome, papel="")
    catalogo.definir_fusao("p3", _fusao())
    copia = CopiaEmMemoria()
    copia.gravar(
        "j1",
        [
            _aparicao("j1", "p3", 0, 2_000),
            _aparicao("j1", "p4", 1_000, 3_000),
            _aparicao("j1", "p3", 0, 0, "mencao_na_fala"),
        ],
    )
    copia.gravar("j2", [_aparicao("j2", "p3", 0, 1_000)])
    copia.gravar("j3", [_aparicao("j3", "p4", 0, 500), _aparicao("j3", "p1", 0, 1_500)])
    return catalogo, FonteQueContaIntervalos(copia)


def _producao(
    catalogo: CatalogoEmMemoria, fonte: ConsultaDeMomentos, cache: CacheCurto
) -> TestClient:
    """Como em `api/main.py`: o cache entre a consulta e `SoComQuemConta`."""
    return _cliente(consulta=ComCache(fonte, cache), catalogo=catalogo)


def test_pessoa_fundida_soma_na_linha_do_destino_com_o_tempo_unido() -> None:
    catalogo, fonte = _mundo_da_fusao()
    cliente = _producao(catalogo, fonte, CacheCurto())

    corpo = cliente.get(ROTA, headers=AUTORIZACAO).json()

    carla = next(p for p in corpo["pessoas"] if p["pessoa_id"] == "p4")
    assert [p["pessoa_id"] for p in corpo["pessoas"]] == ["p4", "p1"]
    assert carla["nome"] == "Carla"  # o nome atual do destino
    assert carla["tempo_de_tela_ms"] == 3_000 + 1_000 + 500  # j1 unido + j2 + j3
    assert carla["aparicoes"] == 3 and carla["videos"] == 3
    assert carla["mencoes_na_fala"] == 1
    por_video = {v["job_id"]: v["tempo_de_tela_ms"] for v in carla["por_video"]}
    assert por_video == {"j1": 3_000, "j2": 1_000, "j3": 500}
    total = cliente.get(ROTA, params={"limite": 5}, headers=AUTORIZACAO).json()["total"]
    assert total["pessoas"] == 2
    assert total["tempo_de_tela_ms"] == 4_500 + 1_500
    assert total["aparicoes"] == 4


def test_pessoa_fundida_sai_numa_linha_so_no_csv_e_nas_paginas() -> None:
    catalogo, fonte = _mundo_da_fusao()
    cliente = _producao(catalogo, fonte, CacheCurto())

    csv_ = cliente.get(ROTA, params={"formato": "csv"}, headers=AUTORIZACAO).text
    pagina = cliente.get(ROTA, params={"limite": 1}, headers=AUTORIZACAO).json()

    linhas = list(csv.DictReader(io.StringIO(csv_)))
    assert [(r["pessoa_id"], r["tempo_de_tela_ms"]) for r in linhas] == [
        ("p4", "4500"),
        ("p1", "1500"),
    ]
    assert [p["pessoa_id"] for p in pagina["pessoas"]] == ["p4"]
    assert pagina["total"]["pessoas"] == 2


def test_os_videos_do_destino_trazem_um_item_por_video_com_os_das_origens() -> None:
    catalogo, fonte = _mundo_da_fusao()
    cliente = _producao(catalogo, fonte, CacheCurto())

    videos = cliente.get(
        f"{ROTA}/videos", params={"pessoa_id": "p4"}, headers=AUTORIZACAO
    ).json()
    da_origem = cliente.get(
        f"{ROTA}/videos", params={"pessoa_id": "p3"}, headers=AUTORIZACAO
    ).json()

    assert [
        (
            v["job_id"],
            v["tempo_de_tela_ms"],
            v["aparicoes"],
            v["mencoes_na_fala"],
            v["mencoes_no_texto"],
        )
        for v in videos
    ] == [("j1", 3_000, 1, 1, 0), ("j2", 1_000, 1, 0, 0), ("j3", 500, 1, 0, 0)]
    assert da_origem == []  # a origem não é linha do ranking


def test_origem_sozinha_no_video_so_troca_o_id_e_nao_consulta_intervalos() -> None:
    catalogo, fonte = _mundo_da_fusao()
    fonte._copia.por_job.pop("j1")  # sem o vídeo em que as duas aparecem
    cliente = _producao(catalogo, fonte, CacheCurto())

    corpo = cliente.get(ROTA, headers=AUTORIZACAO).json()

    carla = next(p for p in corpo["pessoas"] if p["pessoa_id"] == "p4")
    assert carla["tempo_de_tela_ms"] == 1_500  # j2 (de p3) e j3 (de p4)
    assert fonte.pedidos == []


def test_duas_origens_no_mesmo_destino_somam_uma_linha() -> None:
    catalogo, fonte = _mundo_da_fusao()
    catalogo._itens["p5"] = PessoaDoCatalogo(id="p5", nome="Carla Outra", papel="")
    catalogo.definir_fusao("p5", _fusao())
    fonte._copia.gravar(
        "j4",
        [
            _aparicao("j4", "p3", 0, 1_000),
            _aparicao("j4", "p5", 500, 1_500),
            _aparicao("j4", "p4", 5_000, 6_000),
        ],
    )
    cliente = _producao(catalogo, fonte, CacheCurto())

    corpo = cliente.get(ROTA, headers=AUTORIZACAO).json()

    carla = corpo["pessoas"][0]
    por_video = {v["job_id"]: v["tempo_de_tela_ms"] for v in carla["por_video"]}
    assert por_video["j4"] == 1_500 + 1_000  # 0-1,5 s unido e 5-6 s
    assert next(v for v in carla["por_video"] if v["job_id"] == "j4")["aparicoes"] == 2
    assert [p["pessoa_id"] for p in corpo["pessoas"]] == ["p4", "p1"]
    assert fonte.pedidos and set(fonte.pedidos[0]) == {"p3", "p4", "p5"}


def test_sem_fusao_no_periodo_nao_ha_segunda_consulta() -> None:
    copia = _varias_pessoas()
    catalogo = _catalogo_da_copia(ConsultaEmMemoria(copia))
    cliente = _producao(catalogo, SoSomas(copia), CacheCurto())

    assert cliente.get(ROTA, headers=AUTORIZACAO).status_code == 200
    assert (
        cliente.get(
            f"{ROTA}/videos", params={"pessoa_id": "c1"}, headers=AUTORIZACAO
        ).status_code
        == 200
    )


def test_fundida_na_lixeira_ou_com_destino_purgado_continua_fora() -> None:
    catalogo, fonte = _mundo_da_fusao()
    cliente = _producao(catalogo, fonte, CacheCurto())
    # destino na lixeira: a origem também não conta (o elo do caminho está nela)
    catalogo.definir_lixeira(
        "p4",
        EnvioParaLixeira(em=agora_utc(), por_uid="u", por_email="u@r.com", motivo="x"),
    )

    na_lixeira = cliente.get(ROTA, params={"limite": 5}, headers=AUTORIZACAO).json()
    assert [p["pessoa_id"] for p in na_lixeira["pessoas"]] == ["p1"]
    assert na_lixeira["total"]["pessoas"] == 1

    catalogo.definir_lixeira("p4", None)
    catalogo.apagar("p4")  # destino purgado
    purgado = cliente.get(ROTA, headers=AUTORIZACAO).json()
    assert [p["pessoa_id"] for p in purgado["pessoas"]] == ["p1"]
    assert (
        cliente.get(
            f"{ROTA}/videos", params={"pessoa_id": "p4"}, headers=AUTORIZACAO
        ).json()
        == []
    )


def test_o_cache_das_somas_guarda_as_somas_sem_fusao_na_mesma_chave() -> None:
    catalogo, fonte = _mundo_da_fusao()
    cache = CacheCurto()
    cliente = _producao(catalogo, fonte, cache)
    cliente.get(ROTA, headers=AUTORIZACAO)

    guardadas: list[PessoaNoVideo] = cache.obter(
        ("tempo-de-tela", (), None, None), lambda: pytest.fail()
    )

    assert guardadas == fonte.somas((), None, None)
    assert {s.pessoa_id for s in guardadas} == {"p1", "p3", "p4"}  # ids originais


def test_bigquery_pede_os_intervalos_so_das_pessoas_com_os_filtros_da_soma() -> None:
    transporte = Transporte(
        {"jobComplete": True, "rows": [_linha_do_bq("j1", "p3", "0", "2000")]}
    )

    intervalos = ConsultaBigQuery(CONFIG, transporte).aparicoes_unidas(
        ("Jornal",), date(2026, 10, 1), date(2026, 10, 31), ["p3", "p4"]
    )

    assert intervalos == [("j1", "p3", 0, 2_000)]
    (corpo,) = transporte.corpos
    consulta = corpo["query"]
    assert "`proj.ds.tab`" in consulta
    assert "p.id IN UNNEST(@pessoas)" in consulta
    assert "t.programa IN UNNEST(@programas)" in consulta
    assert "t.data_de_exibicao >= @desde" in consulta
    assert "t.data_de_exibicao <= @ate" in consulta
    assert "p3" not in consulta  # os ids vão como parâmetro
    por_nome = {p["name"]: p["parameterValue"] for p in corpo["queryParameters"]}
    assert [v["value"] for v in por_nome["pessoas"]["arrayValues"]] == ["p3", "p4"]
    assert set(por_nome) == {"pessoas", "programas", "desde", "ate"}


def test_videos_de_quem_nao_esta_em_fusao_nao_consultam_intervalos() -> None:
    catalogo, fonte = _mundo_da_fusao()
    cliente = _producao(catalogo, fonte, CacheCurto())

    resposta = cliente.get(
        f"{ROTA}/videos", params={"pessoa_id": "p1"}, headers=AUTORIZACAO
    )

    assert [v["job_id"] for v in resposta.json()] == ["j3"]
    assert fonte.pedidos == []  # a fusão p3 -> p4 não é da p1
