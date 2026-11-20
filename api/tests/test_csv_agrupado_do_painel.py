"""O CSV de cada aba do painel agrupado como a tela (#785): `agrupar` soma as linhas do
mesmo grupo e das mesmas chaves, com a coluna `dia` no primeiro dia do grupo."""

import csv
import io
from dataclasses import replace
from datetime import UTC, date, datetime

from api.auditoria import FiltroDeAuditoria
from api.qualidade_do_painel import QualidadeEmMemoria
from api.resumos_de_uso import (
    AcessoDoDia,
    ChamadaDoDia,
    CorrecaoDoDia,
    ResumosEmMemoria,
)
from api.tests.test_rotas_do_painel import BIA, CAIO, CMS, Mundo, _uso
from api.tests.test_rotas_do_painel_revisao_e_api import TAXA, TEMPOS

OUT30, OUT31, NOV1, NOV2, NOV20 = (
    date(2026, 10, 30),
    date(2026, 10, 31),
    date(2026, 11, 1),
    date(2026, 11, 2),
    date(2026, 11, 20),
)


def _lido(texto: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(texto)))


def _no_mes(
    linhas: list[dict[str, str]],
    chaves: tuple[str, ...],
    somas: tuple[str, ...],
) -> list[dict[str, str]]:
    """O CSV por dia somado por mês, como o agrupado deve sair."""
    juntas: dict[tuple[str, ...], dict[str, str]] = {}
    for linha in linhas:
        dia = linha["dia"][:8] + "01"
        chave = (dia, *(linha[c] for c in chaves))
        if chave not in juntas:
            juntas[chave] = {**linha, "dia": dia}
        else:
            for s in somas:
                juntas[chave][s] = str(int(juntas[chave][s]) + int(linha[s]))
    return sorted(juntas.values(), key=lambda k: k["dia"])


def _dos_dois(
    mundo: Mundo, rota: str, **filtros: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    por_dia = _lido(mundo.get(rota, formato="csv", **filtros).text)
    por_mes = _lido(mundo.get(rota, formato="csv", agrupar="mes", **filtros).text)
    return por_dia, por_mes


def _sem_horas(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{k: v for k, v in r.items() if k != "horas_concluidas"} for r in linhas]


def _sem_correcoes(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in linhas if r["indicador"] != "correcoes"]


def _so_chamadas(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    return [r for r in linhas if r["chamadas"]]


def _ordenado(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(linhas, key=lambda lin: sorted(lin.items()))


def test_acessos_somam_por_mes_com_ativo_pelo_ou_e_ultimo_acesso_o_maior() -> None:
    def a(dia: date, uid: str, n: int, ativo: bool, hora: int) -> AcessoDoDia:
        return AcessoDoDia(
            dia, uid, n, ativo, datetime(dia.year, dia.month, dia.day, hora, tzinfo=UTC)
        )

    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria(
            [
                a(OUT30, "bia", 2, True, 10),
                a(OUT31, "bia", 1, True, 12),
                a(NOV1, "bia", 3, True, 9),
                a(NOV2, "bia", 0, False, 18),
                a(NOV2, "caio", 1, False, 8),
                a(NOV20, "caio", 4, True, 7),
            ]
        ),
    )
    por_dia, por_mes = _dos_dois(mundo, "/acessos")

    esperado = _no_mes(por_dia, ("uid",), ("acessos",))
    assert [(r["dia"], r["uid"], r["acessos"]) for r in por_mes] == [
        (r["dia"], r["uid"], r["acessos"]) for r in esperado
    ]
    assert [r["dia"] for r in por_mes] == sorted(r["dia"] for r in por_mes)
    assert {(r["dia"], r["uid"]): r["ativo"] for r in por_mes} == {
        ("2026-10-01", "bia"): "sim",
        ("2026-11-01", "bia"): "sim",
        ("2026-11-01", "caio"): "sim",
    }
    # `caio` tem acesso em 2/11 (não ativo) e 20/11 (ativo): vale o "ou"; o último é o maior.
    assert {(r["dia"], r["uid"]): r["ultimo_acesso"] for r in por_mes}[
        ("2026-11-01", "caio")
    ].startswith("2026-11-20T04:00")  # 7h UTC em São Paulo


def test_acessos_so_sem_dia_ativo_vale_nao() -> None:
    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria(
            [
                AcessoDoDia(NOV1, "bia", 1, False, None),
                AcessoDoDia(NOV2, "bia", 1, False, None),
            ]
        ),
    )
    (linha,) = _lido(mundo.get("/acessos", formato="csv", agrupar="mes").text)
    assert (linha["dia"], linha["acessos"], linha["ativo"]) == (
        "2026-11-01",
        "2",
        "não",
    )
    assert linha["ultimo_acesso"] == ""


def _uso_em(dia: date, **kw):  # type: ignore[no-untyped-def]
    return replace(_uso(1, **kw), dia=dia)


USO_LONGO = [
    _uso_em(OUT30, quem=BIA, enviados=2, concluidos=1, falhos=1, horas=2, segundos=600),
    _uso_em(OUT31, quem=BIA, enviados=1, concluidos=1, horas=1, segundos=60, buscas=2),
    _uso_em(NOV1, quem=BIA, concluidos=1, horas=0.004, segundos=5, sem_resultado=1),
    _uso_em(NOV2, quem=BIA, concluidos=1, horas=0.004, segundos=5, buscas=3),
    _uso_em(NOV2, quem=CMS, enviados=1, concluidos=1, horas=1, segundos=10, buscas=1),
    _uso_em(NOV20, quem=CAIO, enviados=1, buscas=1, sem_resultado=1),
    _uso_em(OUT30, programa="Hoje", enviados=2, concluidos=1, falhos=1, horas=2),
    _uso_em(OUT31, programa="Fala", enviados=1, concluidos=1, horas=1, segundos=60),
    _uso_em(NOV1, programa="Hoje", concluidos=1, horas=0.004, segundos=5),
    _uso_em(NOV2, programa="Hoje", concluidos=1, horas=0.004, segundos=5),
    _uso_em(NOV20, programa="Fala", buscas=1, sem_resultado=1),
]
INTEIROS_DE_VIDEOS = ("enviados", "concluidos", "falhos", "segundos_de_processamento")
CHAVES_DE_VIDEOS = ("quebra", "quem_tipo", "quem_id", "programa")


def _mundo_de_uso() -> Mundo:
    return Mundo(["diretoria"], resumos=ResumosEmMemoria(uso=USO_LONGO))


def test_videos_somam_por_mes_e_as_horas_vem_dos_milissegundos_somados() -> None:
    por_dia, por_mes = _dos_dois(_mundo_de_uso(), "/videos")

    esperado = _no_mes(por_dia, CHAVES_DE_VIDEOS, INTEIROS_DE_VIDEOS)
    assert _ordenado(_sem_horas(por_mes)) == _ordenado(_sem_horas(esperado))
    # Cada dia de 14.400 ms dá 0,00 h; os dois juntos, 0,01 h (e a "Sem programa" bate).
    horas = {
        (r["quebra"], r["dia"], r["quem_id"], r["programa"]): r["horas_concluidas"]
        for r in por_mes
    }
    assert horas[("usuario", "2026-11-01", "bia", "")] == "0.01"
    assert horas[("programa", "2026-11-01", "", "Hoje")] == "0.01"
    assert {r["horas_concluidas"] for r in por_dia if r["quem_id"] == "bia"} >= {"0.0"}
    # A ordem de cada bloco é por dia.
    for quebra in ("usuario", "programa"):
        dias = [r["dia"] for r in por_mes if r["quebra"] == quebra]
        assert dias == sorted(dias)


def test_videos_sem_programa_e_calculado_por_grupo_com_inteiros() -> None:
    _, por_mes = _dos_dois(_mundo_de_uso(), "/videos")
    json = _mundo_de_uso().get("/videos", agrupar="mes").json()

    sem = {
        r["dia"]: r
        for r in por_mes
        if r["quebra"] == "programa" and r["programa"] == "Sem programa"
    }
    # O total do mês menos os programas, como no JSON.
    por_programa = {
        (r["dia"], r["programa"]): int(r["enviados"])
        for r in por_mes
        if r["quebra"] == "programa"
    }
    total_do_mes = {d["dia"]: d["enviados"] for d in json["por_dia"]}
    for dia, enviados in total_do_mes.items():
        assert sum(v for (d, _), v in por_programa.items() if d == dia) == enviados
    assert sem  # há vídeo sem programa nos dois meses


def test_buscas_somam_por_mes() -> None:
    por_dia, por_mes = _dos_dois(_mundo_de_uso(), "/buscas")

    esperado = _no_mes(
        por_dia, ("quem_tipo", "quem_id", "programa"), ("buscas", "sem_resultado")
    )
    assert _ordenado(por_mes) == _ordenado(esperado)
    assert [r["dia"] for r in por_mes] == sorted(r["dia"] for r in por_mes)


def test_revisao_soma_as_correcoes_e_deixa_taxa_e_tempo_como_estao() -> None:
    def c(dia: date, quem: str, prog: str | None, tipo: str | None, n: int):  # type: ignore[no-untyped-def]
        return CorrecaoDoDia(dia, "usuario", quem, prog, tipo, n)

    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria(
            uso=USO_LONGO,
            correcoes=[
                c(OUT30, "bia", "Hoje", "fala.texto", 3),
                c(OUT31, "bia", "Hoje", "fala.texto", 1),
                c(NOV1, "bia", "Hoje", "fala.texto", 2),
                c(NOV2, "bia", None, None, 1),
                c(NOV20, "caio", "Hoje", "fala.texto", 5),
            ],
        ),
        qualidade=QualidadeEmMemoria(TAXA, TEMPOS),
    )
    por_dia, por_mes = _dos_dois(mundo, "/revisao")

    corr_dia = [r for r in por_dia if r["indicador"] == "correcoes"]
    corr_mes = [r for r in por_mes if r["indicador"] == "correcoes"]
    assert _ordenado(corr_mes) == _ordenado(
        _no_mes(corr_dia, ("quem_id", "programa", "tipo"), ("correcoes",))
    )
    assert [
        (r["dia"], r["quem_id"], r["programa"], r["correcoes"]) for r in corr_mes
    ] == [
        ("2026-10-01", "bia", "Hoje", "4"),
        ("2026-11-01", "bia", "", "1"),
        ("2026-11-01", "bia", "Hoje", "2"),
        ("2026-11-01", "caio", "Hoje", "5"),
    ]
    assert _sem_correcoes(por_mes) == _sem_correcoes(por_dia)


def test_api_soma_chamadas_erros_e_envios_por_mes() -> None:
    def ch(dia: date, quem: str, rota: str, n: int, e4: int, e5: int):  # type: ignore[no-untyped-def]
        return ChamadaDoDia(dia, "sistema", quem, "GET", rota, n, e4, e5)

    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria(
            uso=USO_LONGO,
            chamadas=[
                ch(OUT30, "cms", "/v1/videos", 5, 1, 0),
                ch(OUT31, "cms", "/v1/videos", 3, 0, 1),
                ch(NOV1, "cms", "/v1/videos", 2, 1, 1),
                ch(NOV2, "cms", "/v1/busca", 4, 0, 0),
                ch(NOV20, "cms", "/v1/videos", 1, 0, 0),
            ],
        ),
    )
    por_dia, por_mes = _dos_dois(mundo, "/api")

    esperado = _no_mes(
        por_dia,
        ("quem_tipo", "quem_id", "metodo", "rota"),
        ("chamadas", "erros_do_cliente", "erros_do_servidor"),
    )
    assert _ordenado(_so_chamadas(por_mes)) == _ordenado(_so_chamadas(esperado))
    envios = [r for r in por_mes if r["videos_enviados"]]
    assert [(r["dia"], r["quem_id"], r["videos_enviados"]) for r in envios] == [
        ("2026-11-01", "cms", "1"),
    ]
    assert [r["dia"] for r in por_mes] == sorted(r["dia"] for r in por_mes)


def test_sem_agrupar_sai_por_dia_mesmo_com_periodo_enorme_e_auto_escolhe_como_o_json() -> (
    None
):
    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria(
            [
                AcessoDoDia(date(2025, 1, 1), "bia", 1, True, None),
                AcessoDoDia(NOV1, "caio", 1, True, None),
            ]
        ),
    )
    sem = mundo.get("/acessos", formato="csv")
    assert sem.status_code == 200
    assert [r["dia"] for r in _lido(sem.text)] == ["2025-01-01", "2026-11-01"]

    auto = _lido(mundo.get("/acessos", formato="csv", agrupar="auto").text)
    assert [r["dia"] for r in auto] == ["2025-01-01", "2026-11-01"]  # grupo mensal
    assert mundo.get("/acessos", formato="csv", agrupar="dia").status_code == 422
    assert mundo.get("/acessos", formato="csv", agrupar="semana").status_code == 200
    assert mundo.get("/acessos", formato="csv", agrupar="xpto").status_code == 422
    # Cada download que saiu grava a exportação; o 422 não grava nada.
    registros = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert len(registros) == 3


def test_o_grupo_do_auto_conta_o_desde_do_filtro_como_no_json() -> None:
    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria([AcessoDoDia(NOV20, "bia", 1, True, None)]),
    )
    # Sem `desde` o período tem 1 dia (dia); com `desde` um ano antes, vira semana.
    assert (
        _lido(mundo.get("/acessos", formato="csv", agrupar="auto").text)[0]["dia"]
        == "2026-11-20"
    )
    csv_longo = mundo.get("/acessos", formato="csv", agrupar="auto", desde="2025-11-20")
    json_longo = mundo.get("/acessos", agrupar="auto", desde="2025-11-20")
    assert json_longo.headers["X-Agrupamento"] == "semana"
    assert _lido(csv_longo.text)[0]["dia"] == "2026-11-16"


def test_um_periodo_comecando_sem_dados_passa_dos_400_pontos_com_dia_como_no_json() -> (
    None
):
    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosEmMemoria([AcessoDoDia(NOV20, "bia", 1, True, None)]),
    )
    assert mundo.get("/acessos", agrupar="dia", desde="2025-01-01").status_code == 422
    assert (
        mundo.get(
            "/acessos", agrupar="dia", desde="2025-01-01", formato="csv"
        ).status_code
        == 422
    )
