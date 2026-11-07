"""As abas Revisão e API do painel (#284): correções, taxa de correção e tempo de revisão;
chamadas por sistema e rota, erros e vídeos enviados pela API."""

import csv
import io
from datetime import date

from api.auditoria import FiltroDeAuditoria
from api.qualidade_do_painel import QualidadeEmMemoria
from api.resumos_de_uso import ChamadaDoDia, CorrecaoDoDia, ResumosEmMemoria
from api.revisao_do_painel import RevisaoNoVideo
from api.taxa_de_correcao import LinhaDaTaxa
from api.tests.test_rotas_do_painel import USO, Mundo


def _correcao(
    dia: int, quem: str, programa: str | None, tipo: str | None, n: int
) -> CorrecaoDoDia:
    return CorrecaoDoDia(date(2026, 11, dia), "usuario", quem, programa, tipo, n)


CORRECOES = [
    _correcao(1, "bia", "Hoje", "fala.texto", 3),
    _correcao(1, "caio", "Hoje", "pessoa.renomear", 1),
    _correcao(3, "bia", "Fala", "fala.texto", 2),
    _correcao(3, "bia", None, None, 1),
]


def _taxa(
    programa: str, versao: str, tipo: str, correcoes: int, itens: int
) -> LinhaDaTaxa:
    return LinhaDaTaxa(
        programa=programa,
        versao_pipeline=versao,
        tipo=tipo,
        correcoes=correcoes,
        itens=itens,
        taxa_de_correcao=correcoes / itens,
    )


TAXA = [
    _taxa("Hoje", "v1", "pessoa.renomear", 1, 10),
    _taxa("Hoje", "v2", "pessoa.renomear", 1, 10),
    _taxa("Hoje", "v1", "fala.texto", 3, 30),
    _taxa("Fala", "v1", "fala.texto", 2, 10),
]

TEMPOS = [
    RevisaoNoVideo("v1", "bia", "bia@redetv.com.br", "Hoje", 600, 3600),
    RevisaoNoVideo("v2", "bia", "bia@redetv.com.br", "Fala", 1200, 1800),
    RevisaoNoVideo("v1", "caio", "caio@redetv.com.br", "Hoje", 300, 3600),
    # Sem a duração do vídeo: os minutos contam, mas não entram na taxa por hora.
    RevisaoNoVideo("v3", "caio", "caio@redetv.com.br", "Fala", 120, None),
]


def _revisao(resumos: ResumosEmMemoria | None = None) -> Mundo:
    return Mundo(
        ["diretoria"],
        resumos=resumos or ResumosEmMemoria(uso=USO, correcoes=CORRECOES),
        qualidade=QualidadeEmMemoria(TAXA, TEMPOS),
    )


def test_correcoes_por_dia_tipo_e_usuario() -> None:
    r = _revisao().get("/revisao").json()["correcoes"]

    assert r["total"] == 7
    assert [(d["dia"], d["correcoes"]) for d in r["por_dia"]] == [
        ("2026-11-01", 4),
        ("2026-11-02", 0),  # sem correção no meio do período vem com zero
        ("2026-11-03", 3),
    ]
    assert [(t["tipo"], t["correcoes"]) for t in r["por_tipo"]] == [
        ("fala.texto", 5),
        ("pessoa.renomear", 1),
        (None, 1),  # o evento sem tipo
    ]
    assert [(u["quem_id"], u["email"], u["correcoes"]) for u in r["por_usuario"]] == [
        ("bia", "bia@redetv.com.br", 6),
        ("caio", "caio@redetv.com.br", 1),
    ]


def test_correcoes_filtram_por_periodo_programa_e_usuario_juntos() -> None:
    mundo = _revisao()

    r = mundo.get("/revisao", desde="2026-11-02").json()["correcoes"]
    assert r["total"] == 3

    r = mundo.get("/revisao", programa="Hoje", usuario="bia").json()["correcoes"]
    assert r["total"] == 3
    assert [t["tipo"] for t in r["por_tipo"]] == ["fala.texto"]


def test_taxa_de_correcao_por_tipo_e_por_programa_soma_as_versoes() -> None:
    r = _revisao().get("/revisao").json()["taxa_de_correcao"]

    assert [
        (t["tipo"], t["correcoes"], t["itens"], t["taxa"]) for t in r["por_tipo"]
    ] == [
        ("fala.texto", 5, 40, 0.125),
        ("pessoa.renomear", 2, 20, 0.1),
    ]
    assert [
        (p["programa"], p["correcoes"], p["itens"], p["taxa"])
        for p in r["por_programa"]
    ] == [
        ("Fala", 2, 10, 0.2),
        ("Hoje", 5, 50, 0.1),
    ]


def test_taxa_com_denominador_zero_e_vazia() -> None:
    sem_itens = QualidadeEmMemoria(
        [
            LinhaDaTaxa(
                programa="Hoje",
                versao_pipeline=None,
                tipo="fala.texto",
                correcoes=0,
                itens=0,
                taxa_de_correcao=None,
            )
        ],
        [],
    )

    r = Mundo(["diretoria"], qualidade=sem_itens).get("/revisao").json()

    assert r["taxa_de_correcao"]["por_tipo"][0]["taxa"] is None


def test_a_taxa_filtra_por_programa_e_nao_tem_pessoa() -> None:
    mundo = _revisao()

    por_programa = mundo.get("/revisao", programa="Fala").json()["taxa_de_correcao"]
    assert [p["programa"] for p in por_programa["por_programa"]] == ["Fala"]

    por_pessoa = mundo.get("/revisao", usuario="bia").json()["taxa_de_correcao"]
    assert por_pessoa == {"por_tipo": [], "por_programa": []}


def test_minutos_de_revisao_por_hora_de_video_por_pessoa_e_programa() -> None:
    r = _revisao().get("/revisao").json()["tempo_de_revisao"]

    assert r["total"] == {
        "minutos": 37.0,
        "videos": 3,
        "horas_de_video": 1.5,  # v1 uma vez só, mesmo revisado por duas pessoas
        # 35 min dos que têm duração / 1,5 h
        "minutos_por_hora_de_video": 23.33,
    }
    assert [
        (
            p["email"],
            p["minutos"],
            p["videos"],
            p["horas_de_video"],
            p["minutos_por_hora_de_video"],
        )
        for p in r["por_pessoa"]
    ] == [
        ("bia@redetv.com.br", 30.0, 2, 1.5, 20.0),
        ("caio@redetv.com.br", 7.0, 2, 1.0, 5.0),
    ]
    assert [
        (
            p["programa"],
            p["minutos"],
            p["horas_de_video"],
            p["minutos_por_hora_de_video"],
        )
        for p in r["por_programa"]
    ] == [
        ("Fala", 22.0, 0.5, 40.0),
        ("Hoje", 15.0, 1.0, 15.0),
    ]


def test_tempo_de_revisao_filtra_por_usuario_e_programa() -> None:
    mundo = _revisao()

    r = mundo.get("/revisao", usuario="caio", programa="Hoje").json()[
        "tempo_de_revisao"
    ]

    assert r["total"]["minutos"] == 5.0
    assert [p["email"] for p in r["por_pessoa"]] == ["caio@redetv.com.br"]


def test_sem_revisao_nem_correcao_vem_tudo_vazio() -> None:
    r = (
        Mundo(
            ["diretoria"],
            resumos=ResumosEmMemoria(),
            qualidade=QualidadeEmMemoria([], []),
        )
        .get("/revisao")
        .json()
    )

    assert r["correcoes"]["total"] == 0 and r["correcoes"]["por_dia"] == []
    assert r["tempo_de_revisao"]["total"]["minutos_por_hora_de_video"] is None
    assert r["tempo_de_revisao"]["por_pessoa"] == []


def test_periodo_invertido_na_revisao_e_422() -> None:
    r = _revisao().get("/revisao", desde="2026-11-03", ate="2026-11-01")

    assert r.status_code == 422


def test_csv_da_revisao_traz_as_tres_medidas_numa_tabela() -> None:
    mundo = _revisao()

    resposta = mundo.get("/revisao", formato="csv")

    assert "revisao.csv" in resposta.headers["content-disposition"]
    linhas = list(csv.DictReader(io.StringIO(resposta.text)))
    assert list(linhas[0]) == [
        "indicador",
        "dia",
        "quem_id",
        "email",
        "programa",
        "tipo",
        "correcoes",
        "itens",
        "taxa_de_correcao",
        "minutos",
        "horas_de_video",
        "minutos_por_hora_de_video",
    ]
    por: dict[str, list[dict[str, str]]] = {}
    for linha in linhas:
        por.setdefault(linha["indicador"], []).append(linha)
    assert len(por["correcoes"]) == 4
    assert {
        k: por["correcoes"][0][k]
        for k in ("dia", "quem_id", "programa", "tipo", "correcoes")
    } == {
        "dia": "2026-11-01",
        "quem_id": "bia",
        "programa": "Hoje",
        "tipo": "fala.texto",
        "correcoes": "3",
    }
    # A taxa por programa e tipo (as versões somadas).
    hoje = next(
        l for l in por["taxa"] if l["programa"] == "Hoje" and l["tipo"] == "fala.texto"
    )
    assert (hoje["correcoes"], hoje["itens"], hoje["taxa_de_correcao"]) == (
        "3",
        "30",
        "0.1",
    )
    # O tempo por pessoa e programa.
    bia = next(
        l for l in por["tempo"] if l["quem_id"] == "bia" and l["programa"] == "Fala"
    )
    assert (
        bia["email"],
        bia["minutos"],
        bia["horas_de_video"],
        bia["minutos_por_hora_de_video"],
    ) == (
        "bia@redetv.com.br",
        "20.0",
        "0.5",
        "40.0",
    )


def test_abrir_e_baixar_a_revisao_gravam_a_aba_na_auditoria() -> None:
    mundo = _revisao()

    mundo.get("/revisao", programa="Hoje")
    mundo.get("/revisao", programa="Hoje", formato="csv")

    [aberto] = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.aberto")
    ).registros
    [baixado] = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.exportado")
    ).registros
    assert aberto.detalhes == {"aba": "revisao", "filtro": {"programa": "Hoje"}}
    assert baixado.detalhes == {"aba": "revisao", "filtro": {"programa": "Hoje"}}


def _chamada(
    dia: int,
    sistema: str,
    metodo: str,
    rota: str,
    chamadas: int,
    cliente: int = 0,
    servidor: int = 0,
) -> ChamadaDoDia:
    return ChamadaDoDia(
        date(2026, 11, dia),
        "sistema",
        sistema,
        metodo,
        rota,
        chamadas,
        cliente,
        servidor,
    )


CHAMADAS = [
    _chamada(1, "cms", "POST", "/v1/jobs", 5, 1, 1),
    _chamada(1, "cms", "GET", "/v1/jobs/{job_id}", 20),
    _chamada(1, "playout", "GET", "/v1/jobs/{job_id}", 10, 2, 0),
    _chamada(3, "cms", "POST", "/v1/jobs", 3),
]


def _api() -> Mundo:
    return Mundo(["diretoria"], resumos=ResumosEmMemoria(uso=USO, chamadas=CHAMADAS))


def test_api_por_dia_sistema_e_rota_com_erros_e_videos_enviados() -> None:
    r = _api().get("/api").json()

    assert r["total"] == {
        "chamadas": 38,
        "erros_do_cliente": 3,
        "erros_do_servidor": 1,
        "sistemas": 2,
        "videos_enviados": 1,  # só o do sistema `cms`; as pessoas não contam
    }
    assert [
        (d["dia"], d["chamadas"], d["erros_do_cliente"], d["videos_enviados"])
        for d in r["por_dia"]
    ] == [
        ("2026-11-01", 35, 3, 1),
        ("2026-11-02", 0, 0, 0),
        ("2026-11-03", 3, 0, 0),
    ]
    assert [
        (s["quem_id"], s["chamadas"], s["erros_do_servidor"], s["videos_enviados"])
        for s in r["por_sistema"]
    ] == [("cms", 28, 1, 1), ("playout", 10, 0, 0)]
    assert [(x["metodo"], x["rota"], x["chamadas"]) for x in r["por_rota"]] == [
        ("GET", "/v1/jobs/{job_id}", 30),
        ("POST", "/v1/jobs", 8),
    ]


def test_api_filtra_por_periodo_e_sistema() -> None:
    mundo = _api()

    r = mundo.get("/api", desde="2026-11-02").json()
    assert r["total"]["chamadas"] == 3

    r = mundo.get("/api", usuario="playout").json()
    assert r["total"]["chamadas"] == 10
    assert [s["quem_id"] for s in r["por_sistema"]] == ["playout"]


def test_revisao_e_api_agrupam_os_dias() -> None:
    # 01/11 é domingo: a semana de 26/10; o dia 3 já é da semana de 02/11.
    revisao = _revisao().get("/revisao", agrupar="semana")
    api = _api().get("/api", agrupar="semana")

    assert revisao.headers["X-Agrupamento"] == api.headers["X-Agrupamento"] == "semana"
    assert [
        (d["dia"], d["correcoes"]) for d in revisao.json()["correcoes"]["por_dia"]
    ] == [
        ("2026-10-26", 4),
        ("2026-11-02", 3),
    ]
    assert [
        (d["dia"], d["chamadas"], d["videos_enviados"]) for d in api.json()["por_dia"]
    ] == [("2026-10-26", 35, 1), ("2026-11-02", 3, 0)]
    # Sem `agrupar`, o mesmo de antes.
    assert len(_api().get("/api").json()["por_dia"]) == 3


def test_api_com_programa_e_422() -> None:
    assert _api().get("/api", programa="Hoje").status_code == 422


def test_api_sem_nenhuma_chamada_vem_vazia() -> None:
    r = Mundo(["diretoria"], resumos=ResumosEmMemoria()).get("/api").json()

    assert r["total"]["chamadas"] == 0
    assert r["por_dia"] == [] and r["por_sistema"] == [] and r["por_rota"] == []


def test_csv_da_api_traz_chamadas_e_envios_por_dia_e_sistema() -> None:
    resposta = _api().get("/api", formato="csv")

    assert "api.csv" in resposta.headers["content-disposition"]
    linhas = list(csv.reader(io.StringIO(resposta.text)))
    assert linhas[0] == [
        "dia",
        "quem_tipo",
        "quem_id",
        "metodo",
        "rota",
        "chamadas",
        "erros_do_cliente",
        "erros_do_servidor",
        "videos_enviados",
    ]
    assert [
        "2026-11-01",
        "sistema",
        "cms",
        "POST",
        "/v1/jobs",
        "5",
        "1",
        "1",
        "",
    ] in linhas
    # Os envios, numa linha por dia e sistema, sem método nem rota.
    assert ["2026-11-01", "sistema", "cms", "", "", "", "", "", "1"] in linhas
    assert len(linhas) == 1 + 4 + 1


def test_abrir_e_baixar_a_api_gravam_a_aba_na_auditoria() -> None:
    mundo = _api()

    mundo.get("/api", usuario="cms")
    mundo.get("/api", usuario="cms", formato="csv")

    [aberto] = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.aberto")
    ).registros
    assert aberto.detalhes == {"aba": "api", "filtro": {"usuario": "cms"}}
    assert mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.exportado")
    ).registros
