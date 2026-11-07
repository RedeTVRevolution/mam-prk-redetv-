"""A taxa de correção do painel lida da tabela diária (#468, parte 2 de 2)."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from api.qualidade_do_painel import QualidadeReal, _periodo
from api.revisao_do_painel import RevisaoEmMemoria
from api.taxa_de_correcao import calcular, em_csv
from api.taxa_diaria import (
    ConfigDaTaxa,
    LinhaDiaria,
    TabelaDaTaxaEmMemoria,
    atualizar,
    dias_recentes,
)
from api.taxa_do_painel import TaxaBigQuery, TaxaEmMemoria, taxa_do_ambiente
from api.tests.test_taxa_diaria import DIA, _caso_de_hoje

MAM = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
CONFIG = ConfigDaTaxa("proj", "decupagens", "regiao-x", "taxa")


def _tabela_do_caso_de_hoje() -> tuple[TabelaDaTaxaEmMemoria, tuple[Any, ...]]:
    mundo = _caso_de_hoje()
    jobs, _, itens, correcoes, revisao = mundo
    tabela = TabelaDaTaxaEmMemoria()
    dias = dias_recentes(DIA + timedelta(days=15), 30)
    atualizar(dias, jobs, itens, correcoes, revisao, tabela)
    return tabela, mundo


def _antigo(mundo: Any, desde: date | None, ate: date | None) -> list[Any]:
    jobs, decupagens, _, correcoes, revisao = mundo
    inicio, fim = _periodo(desde, ate)
    return calcular(jobs, decupagens, correcoes, revisao, inicio, fim)


def test_cada_dia_da_tabela_da_o_mesmo_numero_do_calculo_antigo() -> None:
    """O caso de hoje: correção pendente, aprovada, reprocessamento com versão nova."""
    tabela, mundo = _tabela_do_caso_de_hoje()
    taxa = TaxaEmMemoria(tabela)

    for dias in range(-12, 14):
        d = DIA + timedelta(days=dias)
        assert taxa.somar(d, d, None) == _antigo(mundo, d, d), d


def test_o_periodo_de_um_video_so_dia_da_o_mesmo_numero_do_calculo_antigo() -> None:
    tabela, mundo = _tabela_do_caso_de_hoje()
    taxa = TaxaEmMemoria(tabela)

    # j1 (pendente, dia 3), j2 (dia 4), j4 (dia 5) e j3 (dia 10): um dia cada.
    desde, ate = DIA + timedelta(days=3), DIA + timedelta(days=13)

    assert taxa.somar(desde, ate, None) == _antigo(mundo, desde, ate)
    assert taxa.somar(desde, ate, "Fama") == [
        x for x in _antigo(mundo, desde, ate) if x.programa == "Fama"
    ]


def test_video_em_dois_dias_soma_as_correcoes_e_conta_os_itens_nos_dois() -> None:
    """A diferença aceita: a tabela não guarda o vídeo. j1 tem correção criada 10 dias antes e
    aprovada 2 dias depois: dois dias revisados."""
    tabela, mundo = _tabela_do_caso_de_hoje()

    do_periodo = TaxaEmMemoria(tabela).somar(
        DIA - timedelta(days=12), DIA + timedelta(days=13), None
    )
    antigo = _antigo(mundo, DIA - timedelta(days=12), DIA + timedelta(days=13))

    assert [(x.programa, x.tipo, x.correcoes) for x in do_periodo] == [
        (x.programa, x.tipo, x.correcoes) for x in antigo
    ]
    assert sum(x.itens for x in do_periodo) > sum(x.itens for x in antigo)


def test_a_taxa_e_correcoes_sobre_itens_do_periodo_e_nao_a_media_das_taxas() -> None:
    d1, d2 = date(2026, 11, 1), date(2026, 11, 2)
    tabela = TabelaDaTaxaEmMemoria()
    tabela.linhas = [
        LinhaDiaria(d1, "J", "v1", "pessoa.renomear", 1, 1),
        LinhaDiaria(d2, "J", "v1", "pessoa.renomear", 1, 9),
    ]

    [linha] = TaxaEmMemoria(tabela).somar(d1, d2, None)

    assert (linha.correcoes, linha.itens, linha.taxa_de_correcao) == (2, 10, 0.2)


def test_sem_itens_a_taxa_e_vazia_e_o_csv_continua_o_mesmo() -> None:
    tabela = TabelaDaTaxaEmMemoria()
    tabela.linhas = [LinhaDiaria(DIA, None, None, "pessoa.renomear", 0, 0)]

    linhas = TaxaEmMemoria(tabela).somar(None, None, None)

    assert em_csv(linhas) == (
        "programa,versao_pipeline,tipo,correcoes,itens,taxa_de_correcao\n"
        ",,pessoa.renomear,0,0,\n"
    )


def test_o_painel_so_precisa_da_tabela_nao_de_decupagem_nem_de_correcoes() -> None:
    tabela, _ = _tabela_do_caso_de_hoje()
    qualidade = QualidadeReal(
        TaxaEmMemoria(tabela), RevisaoEmMemoria(*_vazios_da_revisao())
    )

    assert qualidade.taxa_de_correcao(DIA, DIA + timedelta(days=13), None)
    fonte = (Path(__file__).parents[1] / "taxa_do_painel.py").read_text()
    for lido_de_longe in ("abrir_decupagem", "calcular(", "DecupagensStorage"):
        assert lido_de_longe not in fonte.split('"""', 2)[2]


def _vazios_da_revisao() -> tuple[Any, Any]:
    from api.jobs import RepositorioEmMemoria
    from api.revisao import RepositorioDeRevisaoEmMemoria

    return RepositorioDeRevisaoEmMemoria(), RepositorioEmMemoria()


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


def test_cinco_anos_leem_so_linhas_diarias_numa_consulta() -> None:
    transporte = _Transporte([])
    desde, ate = date(2021, 11, 1), date(2026, 10, 31)

    TaxaBigQuery(CONFIG, transporte).somar(desde, ate, None)

    [corpo] = transporte.corpos
    sql = corpo["query"]
    assert "FROM `proj.decupagens.taxa`" in sql
    assert "dia >= @desde AND dia <= @ate" in sql
    assert "GROUP BY programa, versao_pipeline, tipo" in sql
    assert sql.count("FROM") == 1  # só a tabela diária: nem Jobs, nem momentos
    parametros = {
        p["name"]: (p["parameterType"]["type"], p["parameterValue"]["value"])
        for p in corpo["queryParameters"]
    }
    assert parametros == {
        "desde": ("DATE", "2021-11-01"),
        "ate": ("DATE", "2026-10-31"),
    }
    assert corpo["location"] == "regiao-x"


def test_a_consulta_filtra_por_programa_e_aceita_periodo_aberto() -> None:
    transporte = _Transporte([])

    TaxaBigQuery(CONFIG, transporte).somar(None, None, "Jornal")

    [corpo] = transporte.corpos
    assert "programa = @programa" in corpo["query"]
    assert "@desde" not in corpo["query"]
    assert [p["name"] for p in corpo["queryParameters"]] == ["programa"]


def test_o_bigquery_devolve_as_linhas_somadas_em_ordem() -> None:
    transporte = _Transporte(
        [
            ["Jornal", "v2", "pessoa.renomear", "3", "12"],
            [None, None, "pauta.titulo", "0", "0"],
            ["Jornal", "v1", "pessoa.renomear", "1", "4"],
        ]
    )

    linhas = TaxaBigQuery(CONFIG, transporte).somar(DIA, DIA, None)

    assert [(x.programa, x.versao_pipeline, x.tipo) for x in linhas] == [
        (None, None, "pauta.titulo"),
        ("Jornal", "v1", "pessoa.renomear"),
        ("Jornal", "v2", "pessoa.renomear"),
    ]
    assert [x.taxa_de_correcao for x in linhas] == [None, 0.25, 0.25]


def test_a_consulta_que_nao_termina_no_prazo_e_erro() -> None:
    import pytest

    with pytest.raises(RuntimeError):
        TaxaBigQuery(CONFIG, lambda corpo: {"jobComplete": False}).somar(
            None, None, None
        )


def test_o_ambiente_diz_onde_a_tabela_mora() -> None:
    assert taxa_do_ambiente({}) is None


def test_o_terraform_da_web_recebe_o_nome_da_tabela_da_taxa() -> None:
    main = (MAM / "main.tf").read_text()
    assert 'name  = "BIGQUERY_TABELA_DA_TAXA"' in main
