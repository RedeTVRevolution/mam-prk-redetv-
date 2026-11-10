"""As rotas `/v1/painel/...` (#282): quem vê, os filtros, os números dos acessos e o CSV."""

import csv
import io
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.copia_bigquery import _parametro
from api.jobs import Estado, Job, RepositorioEmMemoria, agora_utc
from api.main import criar_app
from api.painel import escolhe_o_grupo, inicio_do_grupo
from api.papeis import RepositorioDePapeisEmMemoria
from api.resumos_de_uso import (
    AcessoDoDia,
    ChamadaDoDia,
    ConfigDosResumos,
    CorrecaoDoDia,
    ResumosBigQuery,
    ResumosEmMemoria,
    UsoDoDia,
)
from api.tests.sem_periodo_padrao import ClienteSemPeriodoPadrao
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.usuarios import ContaDoIdentityPlatform, ContasDeUsuarioEmMemoria

ANA = Usuario(uid="ana", email="ana@redetv.com.br")
CABECALHO = {"Authorization": "Bearer ana"}


def _acesso(dia: int, uid: str, acessos: int, ativo: bool = True) -> AcessoDoDia:
    return AcessoDoDia(
        dia=date(2026, 11, dia),
        uid=uid,
        acessos=acessos,
        ativo=ativo,
        ultimo_acesso=datetime(2026, 11, dia, 15, 0, tzinfo=UTC),
    )


LINHAS = [
    _acesso(1, "bia", 2),
    _acesso(1, "caio", 1),
    _acesso(2, "bia", 1),
    # Só o fim do processamento do vídeo dele: sem login nem ação, não é ativo.
    _acesso(2, "caio", 0, ativo=False),
    _acesso(3, "bia", 3),
]


def _uso(
    dia: int,
    *,
    quem: tuple[str, str] | None = None,
    programa: str | None = None,
    enviados: int = 0,
    concluidos: int = 0,
    falhos: int = 0,
    horas: float = 0,
    segundos: int = 0,
    com_tempo: int | None = None,
    buscas: int = 0,
    sem_resultado: int = 0,
) -> UsoDoDia:
    return UsoDoDia(
        dia=date(2026, 11, dia),
        quem_tipo=quem[0] if quem else None,
        quem_id=quem[1] if quem else None,
        programa=programa,
        videos_enviados=enviados,
        videos_concluidos=concluidos,
        videos_falhos=falhos,
        horas_concluidas=horas,
        segundos_de_processamento=segundos,
        videos_concluidos_com_tempo=concluidos if com_tempo is None else com_tempo,
        buscas=buscas,
        buscas_sem_resultado=sem_resultado,
    )


BIA = ("usuario", "bia")
CAIO = ("usuario", "caio")
CMS = ("sistema", "cms")
USO = [
    _uso(1, quem=BIA, enviados=2, concluidos=1, falhos=1, horas=2, segundos=600),
    _uso(1, quem=CMS, enviados=1, concluidos=1, horas=1, segundos=1800),
    _uso(1, quem=CAIO, buscas=3, sem_resultado=1),
    _uso(3, quem=BIA, concluidos=1, horas=0.5, segundos=300, buscas=2, sem_resultado=2),
    # Sem vídeo nem busca (só login): fica de fora dos dois relatórios.
    _uso(2, quem=CAIO),
    _uso(1, programa="Hoje", enviados=2, concluidos=1, falhos=1, horas=2, segundos=600),
    _uso(1, programa="Fala", enviados=1, concluidos=1, horas=1, segundos=1800),
    _uso(3, programa="Hoje", concluidos=1, horas=0.5, segundos=300),
    _uso(3, programa="Hoje", buscas=2, sem_resultado=2),
]


class Mundo:
    def __init__(
        self,
        papeis: list[str],
        resumos: Any = "padrao",
        qualidade: Any = None,
        faturamento: Any = None,
        jobs: Any = None,
        relogio: Callable[[], datetime] = agora_utc,
        periodo_padrao: bool = False,
        cache_do_painel: Any = None,
        revisao: Any = None,
        tempo_de_revisao: Any = None,
        armazenamento: Any = None,
        correcoes: Any = None,
        taxa_de_correcao: Any = None,
    ) -> None:
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        repo = RepositorioDePapeisEmMemoria()
        repo.salvar("ana", papeis)  # type: ignore[arg-type]
        self.resumos = (
            ResumosEmMemoria(LINHAS, ["Hoje", "Fofocalizando"], USO)
            if resumos == "padrao"
            else resumos
        )
        self.contas = ContasDeUsuarioEmMemoria(
            [
                ContaDoIdentityPlatform(uid="bia", email="bia@redetv.com.br"),
                ContaDoIdentityPlatform(uid="caio", email="caio@redetv.com.br"),
            ]
        )
        # `periodo_padrao`: o teste é do período padrão, então o cliente não pede o histórico inteiro.
        classe = TestClient if periodo_padrao else ClienteSemPeriodoPadrao
        self.cliente = classe(
            criar_app(
                verificador=VerificadorFalso({"ana": ANA}),
                papeis=repo,
                auditoria=self.auditoria,
                resumos_de_uso=self.resumos,
                qualidade_do_painel=qualidade,
                faturamento=faturamento,
                repositorio=jobs,
                relogio=relogio,
                contas=self.contas,
                cache_do_painel=cache_do_painel,
                revisao=revisao,
                tempo_de_revisao=tempo_de_revisao,
                armazenamento=armazenamento,
                correcoes=correcoes,
                taxa_de_correcao=taxa_de_correcao,
            )
        )

    def get(self, rota: str, **params: str) -> Any:
        return self.cliente.get(f"/v1/painel{rota}", params=params, headers=CABECALHO)


def _diretoria() -> Mundo:
    return Mundo(["diretoria"])


@pytest.mark.parametrize(
    "rota",
    [
        "/acessos",
        "/videos",
        "/buscas",
        "/revisao",
        "/api",
        "/custo",
        "/filtros",
        "/fila",
    ],
)
@pytest.mark.parametrize("papel", ["consulta", "operador", "editor", "curador"])
def test_sem_painel_ver_e_403(rota: str, papel: str) -> None:
    mundo = Mundo([papel])

    assert mundo.get(rota).status_code == 403
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_chave_de_sistema_e_403() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave(
        "Playout", frozenset({"ler"}), MAC, chaves, datetime(2026, 11, 4, tzinfo=UTC)
    )
    app = criar_app(
        verificador=VerificadorFalso({}),
        chaves=VerificadorDeChaveDeApi(chaves, MAC),
        resumos_de_uso=ResumosEmMemoria(),
    )

    resposta = TestClient(app).get(
        "/v1/painel/acessos", headers={"X-API-Key": emitida.chave}
    )

    assert resposta.status_code == 403


def test_sem_bigquery_e_503() -> None:
    assert Mundo(["diretoria"], resumos=None).get("/acessos").status_code == 503


def test_acessos_por_dia_por_usuario_e_no_total() -> None:
    resposta = _diretoria().get("/acessos")

    assert resposta.status_code == 200
    r = resposta.json()
    assert r["total"] == {"acessos": 7, "usuarios_ativos": 2}
    assert r["por_dia"] == [
        {"dia": "2026-11-01", "acessos": 3, "usuarios_ativos": 2},
        {"dia": "2026-11-02", "acessos": 1, "usuarios_ativos": 1},
        {"dia": "2026-11-03", "acessos": 3, "usuarios_ativos": 1},
    ]
    assert [
        (u["uid"], u["email"], u["acessos"], u["dias_ativos"]) for u in r["por_usuario"]
    ] == [
        ("bia", "bia@redetv.com.br", 6, 3),
        ("caio", "caio@redetv.com.br", 1, 1),
    ]
    assert r["por_usuario"][0]["ultimo_acesso"] == "2026-11-03T15:00:00Z"


def test_ativos_por_semana_e_por_mes_contam_cada_pessoa_uma_vez() -> None:
    resumos = ResumosEmMemoria(
        [
            AcessoDoDia(date(2026, 10, 30), "bia", 1, True, None),  # sexta
            _acesso(1, "caio", 1),  # domingo, ainda a semana de 26/10
            _acesso(2, "bia", 1),  # segunda
            _acesso(3, "bia", 2),
            _acesso(3, "caio", 1),
        ]
    )

    r = Mundo(["diretoria"], resumos=resumos).get("/acessos").json()

    assert r["por_semana"] == [
        {"inicio": "2026-10-26", "usuarios_ativos": 2},
        {"inicio": "2026-11-02", "usuarios_ativos": 2},
    ]
    assert r["por_mes"] == [
        {"inicio": "2026-10-01", "usuarios_ativos": 1},
        {"inicio": "2026-11-01", "usuarios_ativos": 2},
    ]


def test_dias_sem_login_no_meio_do_periodo_vem_com_zero() -> None:
    resumos = ResumosEmMemoria([_acesso(1, "bia", 2), _acesso(4, "caio", 1)])

    r = Mundo(["diretoria"], resumos=resumos).get("/acessos").json()

    assert r["por_dia"] == [
        {"dia": "2026-11-01", "acessos": 2, "usuarios_ativos": 1},
        {"dia": "2026-11-02", "acessos": 0, "usuarios_ativos": 0},
        {"dia": "2026-11-03", "acessos": 0, "usuarios_ativos": 0},
        {"dia": "2026-11-04", "acessos": 1, "usuarios_ativos": 1},
    ]


def test_o_grafico_comeca_no_dia_inicial_do_filtro_mesmo_sem_dados_nele() -> None:
    resumos = ResumosEmMemoria([_acesso(3, "bia", 1), _acesso(4, "bia", 2)])

    r = (
        Mundo(["diretoria"], resumos=resumos)
        .get("/acessos", desde="2026-11-01", ate="2026-11-04")
        .json()
    )

    assert [d["dia"] for d in r["por_dia"]] == [
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
    ]


def test_desde_muito_antigo_vale_para_o_teto_de_pontos_e_para_o_auto() -> None:
    mundo = Mundo(["diretoria"], resumos=ResumosEmMemoria([_acesso(3, "bia", 1)]))

    por_dia = mundo.get("/acessos", desde="0001-01-01", agrupar="dia")
    auto = mundo.get("/acessos", desde="0001-01-01", agrupar="auto")
    sem_agrupar = mundo.get("/acessos", desde="0001-01-01").json()

    assert por_dia.status_code == 422
    assert auto.status_code == 200
    assert auto.headers["X-Agrupamento"] == "trimestre"
    assert len(sem_agrupar["por_dia"]) <= 401  # os dados (1 dia) + o teto antes deles


def test_o_teto_de_pontos_corta_o_desde_antigo_sem_andar_dia_a_dia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api import painel

    tamanhos: list[int] = []
    original = painel._dias_do_intervalo

    def espiao(*args: Any, **kwargs: Any) -> list[date]:
        r = original(*args, **kwargs)
        tamanhos.append(len(r))
        return r

    monkeypatch.setattr(painel, "_dias_do_intervalo", espiao)

    with pytest.raises(HTTPException) as erro:
        escolhe_o_grupo("dia", [date(2026, 1, 1)], date(1, 1, 1))

    assert erro.value.status_code == 422
    assert max(tamanhos) <= 401


def test_linha_sem_login_nem_acao_nao_vira_dia_nem_pessoa() -> None:
    # Só o fim do processamento do vídeo do caio caiu no dia 4.
    resumos = ResumosEmMemoria([_acesso(3, "bia", 1), _acesso(4, "caio", 0, False)])
    mundo = Mundo(["diretoria"], resumos=resumos)

    r = mundo.get("/acessos").json()
    linhas = list(csv.reader(io.StringIO(mundo.get("/acessos", formato="csv").text)))

    assert [d["dia"] for d in r["por_dia"]] == ["2026-11-03"]
    assert [u["uid"] for u in r["por_usuario"]] == ["bia"]
    assert [linha[1] for linha in linhas[1:]] == ["bia"]


def test_filtra_pelo_periodo_e_pelo_usuario() -> None:
    mundo = _diretoria()

    r = mundo.get("/acessos", desde="2026-11-02", ate="2026-11-02").json()
    assert (r["total"]["acessos"], len(r["por_dia"])) == (1, 1)
    r = mundo.get("/acessos", usuario="caio").json()
    assert [u["uid"] for u in r["por_usuario"]] == ["caio"]
    assert r["total"]["acessos"] == 1


def test_periodo_invertido_e_422() -> None:
    resposta = _diretoria().get("/acessos", desde="2026-11-03", ate="2026-11-01")

    assert resposta.status_code == 422


def test_acessos_com_programa_e_422_e_vazio_vale_todos() -> None:
    mundo = _diretoria()

    assert mundo.get("/acessos", programa="Hoje").status_code == 422
    assert mundo.get("/acessos", programa="").status_code == 200


def test_filtros_oferecem_programas_e_usuarios_ativos() -> None:
    r = _diretoria().get("/filtros").json()

    assert r["programas"] == ["Fofocalizando", "Hoje"]
    assert r["usuarios"] == [
        {"uid": "bia", "email": "bia@redetv.com.br"},
        {"uid": "caio", "email": "caio@redetv.com.br"},
    ]


def test_filtros_oferecem_os_sistemas_que_tem_eventos() -> None:
    r = _diretoria().get("/filtros").json()

    assert r["sistemas"] == ["cms"]


def test_csv_tem_uma_linha_por_dia_e_pessoa() -> None:
    resposta = _diretoria().get("/acessos", formato="csv", usuario="bia")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/csv")
    assert "acessos.csv" in resposta.headers["content-disposition"]
    linhas = list(csv.reader(io.StringIO(resposta.text)))
    assert linhas[0] == ["dia", "uid", "email", "acessos", "ativo", "ultimo_acesso"]
    assert linhas[1] == [
        "2026-11-01",
        "bia",
        "bia@redetv.com.br",
        "2",
        "sim",
        "2026-11-01T12:00:00-03:00",
    ]
    assert len(linhas) == 4


def test_csv_traz_dia_e_ultimo_acesso_no_mesmo_dia_de_sao_paulo() -> None:
    # 23h30 em São Paulo já é dia 5 em UTC.
    tarde = AcessoDoDia(
        dia=date(2026, 11, 4),
        uid="bia",
        acessos=1,
        ativo=True,
        ultimo_acesso=datetime(2026, 11, 5, 2, 30, tzinfo=UTC),
    )
    mundo = Mundo(["diretoria"], ResumosEmMemoria([tarde], [], []))
    linha = list(csv.reader(io.StringIO(mundo.get("/acessos", formato="csv").text)))[1]

    assert linha[0] == "2026-11-04"
    assert linha[5] == "2026-11-04T23:30:00-03:00"


def test_abrir_e_baixar_gravam_a_auditoria_com_o_filtro() -> None:
    mundo = _diretoria()

    mundo.get("/acessos", desde="2026-11-01")
    mundo.get("/acessos", desde="2026-11-01")  # recarga: não grava de novo
    mundo.get("/acessos", desde="2026-11-01", formato="csv")
    mundo.get("/filtros")  # só os nomes dos filtros: sem registro

    abertos = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.aberto")
    ).registros
    exportados = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.exportado")
    ).registros
    assert [r.detalhes for r in abertos] == [
        {"aba": "acessos", "filtro": {"desde": "2026-11-01"}}
    ]
    assert [r.uid for r in exportados] == ["ana"]


def test_consulta_do_bigquery_filtra_com_parametros_e_converte_as_linhas() -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        return {
            "jobComplete": True,
            "rows": [
                {
                    "f": [
                        {"v": "2026-11-01"},
                        {"v": "bia"},
                        {"v": "2"},
                        {"v": "true"},
                        {"v": "2026-11-01T15:00:00Z"},
                    ]
                },
                {
                    "f": [
                        {"v": "2026-11-02"},
                        {"v": "bia"},
                        {"v": "0"},
                        {"v": "false"},
                        {"v": None},
                    ]
                },
            ],
        }

    resumos = ResumosBigQuery(
        ConfigDosResumos(
            "proj",
            "ds",
            "regiao",
            "por_usuario",
            "por_programa",
            "correcoes",
            "chamadas",
        ),
        transporte,
    )

    linhas = resumos.acessos(date(2026, 11, 1), None, "bia'; DROP TABLE x")

    assert linhas == [
        AcessoDoDia(
            date(2026, 11, 1), "bia", 2, True, datetime(2026, 11, 1, 15, tzinfo=UTC)
        ),
        AcessoDoDia(date(2026, 11, 2), "bia", 0, False, None),
    ]
    [pedido] = pedidos
    assert "`proj.ds.por_usuario`" in pedido["query"]
    assert "DROP" not in pedido["query"]
    assert pedido["queryParameters"] == [
        _parametro("desde", "2026-11-01", "DATE"),
        _parametro("usuario", "bia'; DROP TABLE x"),
    ]


def test_consulta_que_nao_termina_ou_nao_cabe_falha_alto() -> None:
    resumos = ResumosBigQuery(
        ConfigDosResumos("p", "d", "r", "a", "b", "c", "d"),
        lambda corpo: {"jobComplete": False},
    )

    with pytest.raises(RuntimeError):
        resumos.acessos(None, None, None)


def test_videos_por_dia_programa_e_usuario_com_o_tempo_medio() -> None:
    r = _diretoria().get("/videos").json()

    assert r["total"] == {
        "enviados": 3,
        "concluidos": 3,
        "falhos": 1,
        "horas_concluidas": 3.5,
        "tempo_medio_s": 900.0,  # (600 + 1800 + 300) / 3 concluídos
    }
    assert [(d["dia"], d["enviados"], d["concluidos"]) for d in r["por_dia"]] == [
        ("2026-11-01", 3, 2),
        ("2026-11-02", 0, 0),  # sem vídeo no meio do período vem com zero
        ("2026-11-03", 0, 1),
    ]
    assert r["por_dia"][1]["tempo_medio_s"] is None
    assert [
        (p["programa"], p["enviados"], p["horas_concluidas"]) for p in r["por_programa"]
    ] == [
        ("Fala", 1, 1.0),
        ("Hoje", 2, 2.5),
    ]
    assert [
        (u["quem_tipo"], u["quem_id"], u["email"], u["enviados"])
        for u in r["por_usuario"]
    ] == [
        ("usuario", "bia", "bia@redetv.com.br", 2),
        ("sistema", "cms", None, 1),
    ]


def test_a_soma_por_programa_bate_com_os_enviados_com_a_linha_sem_programa() -> None:
    # O resumo por programa descarta o vídeo sem programa; o total (por pessoa) o tem.
    uso = [
        *USO,
        _uso(1, quem=BIA, enviados=4, concluidos=2, horas=1.5, segundos=100),
    ]
    r = Mundo(["diretoria"], ResumosEmMemoria(uso=uso)).get("/videos").json()

    assert sum(p["enviados"] for p in r["por_programa"]) == r["total"]["enviados"]
    assert r["por_programa"][-1]["programa"] is None
    assert (
        r["por_programa"][-1]["enviados"],
        r["por_programa"][-1]["horas_concluidas"],
    ) == (4, 1.5)


def test_csv_de_videos_traz_a_quebra_por_programa_com_a_linha_sem_programa() -> None:
    uso = [
        *USO,
        _uso(1, quem=BIA, enviados=4, concluidos=2, horas=1.5, segundos=100),
    ]
    mundo = Mundo(["diretoria"], ResumosEmMemoria(uso=uso))

    linhas = list(csv.reader(io.StringIO(mundo.get("/videos", formato="csv").text)))

    por_programa = [l for l in linhas[1:] if l[4]]
    assert [(l[0], l[1], l[2], l[4], l[5]) for l in por_programa] == [
        ("2026-11-01", "", "", "Fala", "1"),
        ("2026-11-01", "", "", "Hoje", "2"),
        ("2026-11-01", "", "", "Sem programa", "4"),
        ("2026-11-03", "", "", "Hoje", "0"),
    ]
    assert por_programa[2][6:] == ["2", "0", "1.5", "100"]
    # A soma da quebra bate com os enviados do relatório.
    enviados = mundo.get("/videos").json()["total"]["enviados"]
    assert sum(int(l[5]) for l in por_programa) == enviados
    # Com filtro de usuário não há quebra por programa.
    de_usuario = mundo.get("/videos", formato="csv", usuario="bia").text
    assert "Sem programa" not in de_usuario


def test_o_concluido_sem_tempo_fica_fora_do_tempo_medio() -> None:
    # O fim gravado antes de o evento trazer o tempo: 2 concluídos, só 1 com tempo.
    resumos = ResumosEmMemoria(
        uso=[_uso(1, quem=BIA, concluidos=2, segundos=600, com_tempo=1)]
    )

    r = Mundo(["diretoria"], resumos).get("/videos").json()

    assert (r["total"]["concluidos"], r["total"]["tempo_medio_s"]) == (2, 600.0)


def test_videos_filtrados_por_programa_ou_por_usuario() -> None:
    mundo = _diretoria()

    r = mundo.get("/videos", programa="Hoje").json()
    assert r["total"]["enviados"] == 2 and r["total"]["concluidos"] == 2
    assert [p["programa"] for p in r["por_programa"]] == ["Hoje"]
    assert r["por_usuario"] == []

    r = mundo.get("/videos", usuario="cms").json()
    assert (r["total"]["enviados"], r["total"]["horas_concluidas"]) == (1, 1.0)
    assert r["por_programa"] == []
    assert [u["quem_id"] for u in r["por_usuario"]] == ["cms"]

    r = mundo.get("/videos", desde="2026-11-03").json()
    assert r["total"]["concluidos"] == 1


def test_videos_e_buscas_com_programa_e_usuario_juntos_e_422() -> None:
    mundo = _diretoria()

    assert mundo.get("/videos", programa="Hoje", usuario="bia").status_code == 422
    assert mundo.get("/buscas", programa="Hoje", usuario="bia").status_code == 422
    assert mundo.get("/videos", desde="2026-11-03", ate="2026-11-01").status_code == 422


def test_buscas_contam_sem_resultado_e_quem_busca() -> None:
    r = _diretoria().get("/buscas").json()

    assert r["total"] == {"buscas": 5, "sem_resultado": 3, "usuarios_que_buscam": 2}
    assert r["por_dia"] == [
        {
            "dia": "2026-11-01",
            "buscas": 3,
            "sem_resultado": 1,
            "usuarios_que_buscam": 1,
        },
        {
            "dia": "2026-11-02",
            "buscas": 0,
            "sem_resultado": 0,
            "usuarios_que_buscam": 0,
        },
        {
            "dia": "2026-11-03",
            "buscas": 2,
            "sem_resultado": 2,
            "usuarios_que_buscam": 1,
        },
    ]
    assert [
        (u["quem_id"], u["email"], u["buscas"], u["sem_resultado"])
        for u in r["por_usuario"]
    ] == [
        ("caio", "caio@redetv.com.br", 3, 1),
        ("bia", "bia@redetv.com.br", 2, 2),
    ]


def test_buscas_de_um_programa_nao_sabem_quem_buscou() -> None:
    r = _diretoria().get("/buscas", programa="Hoje").json()

    assert r["total"] == {"buscas": 2, "sem_resultado": 2, "usuarios_que_buscam": None}
    assert r["por_usuario"] == []
    assert r["por_dia"][0]["usuarios_que_buscam"] is None


def test_buscas_de_um_usuario() -> None:
    r = _diretoria().get("/buscas", usuario="caio").json()

    assert (r["total"]["buscas"], r["total"]["usuarios_que_buscam"]) == (3, 1)


def test_sistema_que_busca_aparece_por_usuario_mas_nao_conta_como_quem_busca() -> None:
    resumos = ResumosEmMemoria(uso=[_uso(1, quem=CMS, buscas=4)])

    r = Mundo(["diretoria"], resumos=resumos).get("/buscas").json()

    assert r["total"]["usuarios_que_buscam"] == 0
    assert [u["quem_id"] for u in r["por_usuario"]] == ["cms"]


def test_csv_de_videos_e_de_buscas_e_a_base_do_filtro() -> None:
    mundo = _diretoria()

    videos = mundo.get("/videos", formato="csv")
    linhas = list(csv.reader(io.StringIO(videos.text)))
    assert "videos.csv" in videos.headers["content-disposition"]
    assert linhas[0][:6] == [
        "dia",
        "quem_tipo",
        "quem_id",
        "email",
        "programa",
        "enviados",
    ]
    assert linhas[1] == [
        "2026-11-01",
        "usuario",
        "bia",
        "bia@redetv.com.br",
        "",
        "2",
        "1",
        "1",
        "2",
        "600",
    ]
    assert linhas[2][1:3] == ["sistema", "cms"]
    # Os dois do dia 1 e o do dia 3 (a linha só com login fica fora), mais a quebra por
    # programa: Hoje e Fala no dia 1 e Hoje no dia 3.
    assert len(linhas) == 7

    por_programa = list(
        csv.reader(
            io.StringIO(mundo.get("/videos", formato="csv", programa="Fala").text)
        )
    )
    assert por_programa[1][:5] == ["2026-11-01", "", "", "", "Fala"]

    buscas = list(csv.reader(io.StringIO(mundo.get("/buscas", formato="csv").text)))
    assert buscas[0] == [
        "dia",
        "quem_tipo",
        "quem_id",
        "email",
        "programa",
        "buscas",
        "sem_resultado",
    ]
    assert buscas[1] == [
        "2026-11-01",
        "usuario",
        "caio",
        "caio@redetv.com.br",
        "",
        "3",
        "1",
    ]


def test_abrir_e_baixar_videos_e_buscas_gravam_a_aba_na_auditoria() -> None:
    mundo = _diretoria()

    mundo.get("/videos")
    mundo.get("/buscas", programa="Hoje")
    mundo.get("/buscas", programa="Hoje", formato="csv")

    abertos = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.aberto")
    ).registros
    exportados = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.exportado")
    ).registros
    assert sorted(r.detalhes["aba"] for r in abertos) == ["buscas", "videos"]
    assert [r.detalhes for r in exportados] == [
        {"aba": "buscas", "filtro": {"programa": "Hoje"}}
    ]


def test_uso_no_bigquery_traz_as_colunas_das_duas_tabelas() -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        valores = [
            "2026-11-01",
            "usuario",
            "bia",
            None,
            "2",
            "1",
            "1",
            "2.5",
            "600",
            "1",
            "3",
            "1",
        ]
        return {"jobComplete": True, "rows": [{"f": [{"v": v} for v in valores]}]}

    resumos = ResumosBigQuery(
        ConfigDosResumos(
            "proj",
            "ds",
            "regiao",
            "por_usuario",
            "por_programa",
            "correcoes",
            "chamadas",
        ),
        transporte,
    )

    [por_quem] = resumos.uso_por_quem(None, date(2026, 11, 2), "bia")
    [por_programa] = resumos.uso_por_programa(None, None, "Hoje'; DROP TABLE x")

    assert por_quem == UsoDoDia(
        date(2026, 11, 1), "usuario", "bia", None, 2, 1, 1, 2.5, 600, 1, 3, 1
    )
    assert por_programa.horas_concluidas == 2.5
    primeiro, segundo = pedidos
    assert "`proj.ds.por_usuario`" in primeiro["query"]
    assert "quem_id = @quem_id" in primeiro["query"]
    assert "`proj.ds.por_programa`" in segundo["query"]
    assert "DROP" not in segundo["query"]
    assert segundo["queryParameters"] == [_parametro("programa", "Hoje'; DROP TABLE x")]


def test_correcoes_e_chamadas_no_bigquery_trazem_as_colunas_das_duas_tabelas() -> None:
    pedidos: list[dict[str, Any]] = []
    respostas: list[list[str | None]] = [
        ["2026-11-01", "usuario", "bia", None, "fala.texto", "3"],
        ["2026-11-01", "sistema", "cms", "POST", "/v1/jobs", "5", "1", "2"],
    ]

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        valores = respostas[len(pedidos) - 1]
        return {"jobComplete": True, "rows": [{"f": [{"v": v} for v in valores]}]}

    resumos = ResumosBigQuery(
        ConfigDosResumos(
            "proj",
            "ds",
            "regiao",
            "por_usuario",
            "por_programa",
            "correcoes",
            "chamadas",
        ),
        transporte,
    )

    [correcao] = resumos.correcoes(None, None, "Hoje'; DROP TABLE x", "bia")
    [chamada] = resumos.chamadas(date(2026, 11, 1), None, "cms")

    assert correcao == CorrecaoDoDia(
        date(2026, 11, 1), "usuario", "bia", None, "fala.texto", 3
    )
    assert chamada == ChamadaDoDia(
        date(2026, 11, 1), "sistema", "cms", "POST", "/v1/jobs", 5, 1, 2
    )
    primeiro, segundo = pedidos
    assert "`proj.ds.correcoes`" in primeiro["query"]
    assert "DROP" not in primeiro["query"]
    assert primeiro["queryParameters"] == [
        _parametro("programa", "Hoje'; DROP TABLE x"),
        _parametro("quem_id", "bia"),
    ]
    assert "`proj.ds.chamadas`" in segundo["query"]
    assert segundo["queryParameters"] == [
        _parametro("desde", "2026-11-01", "DATE"),
        _parametro("quem_id", "cms"),
    ]


# `agrupar` (ADR 0014): os gráficos por dia viram por semana, mês ou trimestre.


@pytest.mark.parametrize(
    ("dias", "grupo"),
    [
        (0, "dia"),
        (90, "dia"),
        (91, "semana"),
        (548, "semana"),
        (549, "mes"),
        (2557, "mes"),
        (2558, "trimestre"),
        (25 * 366, "trimestre"),
    ],
)
def test_auto_escolhe_o_grupo_pelo_tamanho_do_periodo(dias: int, grupo: str) -> None:
    inicio = date(2001, 1, 1)
    periodo = [inicio, inicio + timedelta(days=dias - 1)] if dias else []

    assert escolhe_o_grupo("auto", periodo) == grupo


def test_inicio_do_grupo() -> None:
    quinta = date(2026, 11, 5)

    assert inicio_do_grupo(quinta, "dia") == quinta
    assert inicio_do_grupo(quinta, "semana") == date(2026, 11, 2)
    assert inicio_do_grupo(quinta, "mes") == date(2026, 11, 1)
    assert inicio_do_grupo(quinta, "trimestre") == date(2026, 10, 1)
    assert inicio_do_grupo(date(2026, 3, 31), "trimestre") == date(2026, 1, 1)


def test_sem_agrupar_e_por_dia_como_antes_e_sem_o_cabecalho() -> None:
    mundo = _diretoria()

    sem = mundo.get("/acessos")
    por_dia = mundo.get("/acessos", agrupar="dia")

    assert "X-Agrupamento" not in sem.headers
    assert por_dia.headers["X-Agrupamento"] == "dia"
    assert sem.json() == por_dia.json()


def test_acessos_por_semana_somam_e_contam_cada_ativo_uma_vez() -> None:
    resposta = _diretoria().get("/acessos", agrupar="semana")

    assert resposta.headers["X-Agrupamento"] == "semana"
    r = resposta.json()
    # 01/11 é domingo (semana de 26/10); 02 e 03 são da semana seguinte, só a bia.
    assert r["por_dia"] == [
        {"dia": "2026-10-26", "acessos": 3, "usuarios_ativos": 2},
        {"dia": "2026-11-02", "acessos": 4, "usuarios_ativos": 1},
    ]
    assert r["total"] == {"acessos": 7, "usuarios_ativos": 2}


def test_videos_e_buscas_agrupados_recalculam_media_e_quem_busca() -> None:
    mundo = _diretoria()

    videos = mundo.get("/videos", agrupar="mes").json()
    buscas = mundo.get("/buscas", agrupar="trimestre").json()

    assert videos["por_dia"] == [{"dia": "2026-11-01", **videos["total"]}]
    assert buscas["por_dia"] == [{"dia": "2026-10-01", **buscas["total"]}]
    assert buscas["total"]["usuarios_que_buscam"] == 2


def test_agrupamento_com_pontos_demais_e_422_e_nao_grava_a_abertura() -> None:
    resumos = ResumosEmMemoria(
        [AcessoDoDia(date(2025, 1, 1), "bia", 1, True, None), _acesso(1, "caio", 1)]
    )
    mundo = Mundo(["diretoria"], resumos=resumos)

    assert mundo.get("/acessos", agrupar="dia").status_code == 422
    assert mundo.get("/acessos", agrupar="xpto").status_code == 422
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []
    auto = mundo.get("/acessos", agrupar="auto")
    assert auto.headers["X-Agrupamento"] == "mes"
    assert len(auto.json()["por_dia"]) == 23  # de jan/2025 a nov/2026
    # O CSV não agrupa: sai inteiro, sem 422.
    assert mundo.get("/acessos", agrupar="dia", formato="csv").status_code == 200


AGORA = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _job_ha(id: str, estado: Estado, minutos: float) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        sha256="a" * 64,
        duracao_s=60.0,
        estado=estado,
        criado_por="bia",
        criado_em=AGORA - timedelta(minutes=minutos),
        atualizado_em=AGORA,
    )


def _fila(*jobs: Job) -> dict[str, dict[str, Any]]:
    repositorio = RepositorioEmMemoria()
    for job in jobs:
        repositorio.salvar(job)
    resposta = Mundo(["diretoria"], jobs=repositorio, relogio=lambda: AGORA).get(
        "/fila"
    )
    assert resposta.status_code == 200
    return {e.pop("estado"): e for e in resposta.json()["por_estado"]}


def test_fila_conta_por_estado_com_a_idade_do_mais_antigo_sem_os_terminados() -> None:
    assert _fila(
        _job_ha("a", "analisando", 30),
        _job_ha("b", "analisando", 90),
        _job_ha("c", "validando", 5),
        _job_ha("d", "concluido", 600),
        _job_ha("e", "falhou", 600),
        _job_ha("f", "cancelado", 600),
    ) == {
        "aguardando_upload": {"quantidade": 0, "idade_do_mais_antigo_s": 0},
        "validando": {"quantidade": 1, "idade_do_mais_antigo_s": 300},
        "analisando": {"quantidade": 2, "idade_do_mais_antigo_s": 5400},
    }


def test_fila_vazia_vem_com_zero_em_cada_estado() -> None:
    assert _fila() == {
        e: {"quantidade": 0, "idade_do_mais_antigo_s": 0}
        for e in ("aguardando_upload", "validando", "analisando")
    }
