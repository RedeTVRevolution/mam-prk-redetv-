"""Texto de quem usa é dado: no SQL só como parâmetro e nos CSVs sempre neutralizado (#461)."""

import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from api.copia_bigquery import ConfigDoBigQuery, CopiaBigQuery, LinhaDoMomento
from api.csv_seguro import csv_em_texto
from api.relatorio_de_marcas import (
    ConsultaBigQuery as MarcasBigQuery,
)
from api.relatorio_de_marcas import (
    MarcaNoRelatorio,
    TotalPorTipo,
)
from api.relatorio_de_marcas import em_csv as marcas_em_csv
from api.resumos_de_uso import ConfigDosResumos, ResumosBigQuery
from api.revisao import Medida, relatorio_em_csv
from api.sinal_do_programa import EVENTOS, HistoricoBigQuery
from api.taxa_de_correcao import LinhaDaTaxa
from api.taxa_de_correcao import em_csv as taxa_em_csv
from api.tempo_de_tela import (
    ConsultaBigQuery as TempoDeTelaBigQuery,
)
from api.tempo_de_tela import PessoaNoRelatorio
from api.tempo_de_tela import em_csv as pessoas_em_csv

# Um texto com aspas, `;`, comentário e `@x`: se chegasse ao SQL, quebraria a consulta.
HOSTIL = "=x'; DROP TABLE t; -- @x"


class TransporteQueGuarda:
    """Dublê do transporte do BigQuery: guarda cada corpo e responde `resposta`."""

    def __init__(self, resposta: dict[str, Any] | None = None) -> None:
        self.corpos: list[dict[str, Any]] = []
        self._resposta = resposta or {"jobComplete": True}

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return self._resposta


def _parametros(corpo: dict[str, Any]) -> dict[str, str]:
    return {p["name"]: p["parameterValue"]["value"] for p in corpo["queryParameters"]}


def _confere(transporte: TransporteQueGuarda, nomes: set[str]) -> None:
    assert transporte.corpos
    for corpo in transporte.corpos:
        assert "DROP" not in corpo["query"]
        assert "x'" not in corpo["query"]
        assert HOSTIL not in corpo["query"]
        valores = _parametros(corpo)
        assert nomes <= set(valores)
        for nome in nomes:
            assert valores[nome] == HOSTIL
        # todo `@nome` do SQL tem o seu parâmetro
        for nome in valores:
            assert f"@{nome}" in corpo["query"]


CONFIG = ConfigDoBigQuery("proj", "ds", "tab", "regiao")
DIA = date(2026, 10, 1)


def test_filtros_do_tempo_de_tela_chegam_so_como_parametro() -> None:
    transporte = TransporteQueGuarda()
    consulta = TempoDeTelaBigQuery(CONFIG, transporte)

    consulta.somas(HOSTIL, DIA, DIA)
    consulta.ranking(HOSTIL, DIA, DIA, 0, 10)
    consulta.videos_da_pessoa(HOSTIL, HOSTIL, DIA, DIA, 0, 10)

    _confere(transporte, {"programa"})
    assert _parametros(transporte.corpos[2])["pessoa_id"] == HOSTIL


def test_filtros_das_marcas_chegam_so_como_parametro() -> None:
    transporte = TransporteQueGuarda()
    consulta = MarcasBigQuery(CONFIG, transporte)

    consulta.somas(HOSTIL, DIA, DIA, HOSTIL)
    consulta.ranking(HOSTIL, DIA, DIA, HOSTIL, 0, 10)
    consulta.lista_da_marca(HOSTIL, HOSTIL, DIA, DIA, HOSTIL, 0, 10)

    _confere(transporte, {"programa", "tipo_de_insercao"})
    assert _parametros(transporte.corpos[2])["marca"] == HOSTIL


def test_filtros_dos_resumos_de_uso_chegam_so_como_parametro() -> None:
    transporte = TransporteQueGuarda()
    config = ConfigDosResumos(
        projeto="proj",
        dataset="ds",
        regiao="regiao",
        tabela_por_dia_e_usuario="a",
        tabela_por_dia_e_programa="b",
        tabela_de_correcoes_por_dia="c",
        tabela_de_chamadas_por_dia="d",
    )
    consulta = ResumosBigQuery(config, transporte)

    consulta.acessos(DIA, DIA, HOSTIL)
    consulta.uso_por_quem(DIA, DIA, HOSTIL)
    consulta.uso_por_programa(DIA, DIA, HOSTIL)
    consulta.correcoes(DIA, DIA, HOSTIL, HOSTIL)
    consulta.chamadas(DIA, DIA, HOSTIL)

    assert len(transporte.corpos) == 5
    _confere(transporte, set())
    for corpo in transporte.corpos:
        assert HOSTIL in _parametros(corpo).values()


def test_programa_do_sinal_chega_so_como_parametro() -> None:
    linha = {"f": [{"v": "0"}] + [{"v": None}] * (2 * len(EVENTOS))}
    transporte = TransporteQueGuarda({"jobComplete": True, "rows": [linha]})

    HistoricoBigQuery(CONFIG, transporte).do_programa(HOSTIL, HOSTIL, 10)

    _confere(transporte, {"programa", "job_id"})


def test_texto_da_copia_chega_so_como_parametro() -> None:
    transporte = TransporteQueGuarda()
    linha = LinhaDoMomento(
        job_id=HOSTIL,
        programa=HOSTIL,
        data_de_exibicao=DIA,
        tipo="comercial",
        inicio_ms=0,
        fim_ms=1,
        marca=HOSTIL,
        texto=HOSTIL,
    )

    CopiaBigQuery(CONFIG, transporte).gravar(HOSTIL, [linha])

    _confere(transporte, {"job_id"})
    gravada = json.loads(_parametros(transporte.corpos[0])["linhas"])[0]
    assert gravada["programa"] == gravada["marca"] == gravada["texto"] == HOSTIL


def test_csv_da_taxa_de_correcao_neutraliza_programa_com_igual() -> None:
    linha = LinhaDaTaxa(
        programa="=1+1",
        versao_pipeline="v1",
        tipo="pessoa.renomear",
        correcoes=1,
        itens=2,
        taxa_de_correcao=0.5,
    )

    saida = taxa_em_csv([linha])

    assert saida.splitlines()[1].startswith("'=1+1,")


def test_csv_das_marcas_neutraliza_marca_com_igual() -> None:
    marca = MarcaNoRelatorio(
        marca="=1+1",
        insercoes=1,
        tempo_ms=1,
        videos=1,
        por_tipo=[TotalPorTipo(tipo="comercial", insercoes=1, tempo_ms=1, videos=1)],
        lista=[],
    )

    linhas = marcas_em_csv([marca]).splitlines()[1:]

    assert linhas and all(linha.startswith("'=1+1,") for linha in linhas)


def test_csv_de_pessoas_neutraliza_nome_com_igual() -> None:
    pessoa = PessoaNoRelatorio(
        pessoa_id="p1",
        nome="=1+1",
        tempo_de_tela_ms=1,
        videos=1,
        aparicoes=1,
        mencoes_na_fala=0,
        mencoes_no_texto=0,
        por_video=[],
    )

    assert pessoas_em_csv([pessoa]).splitlines()[1].startswith("p1,'=1+1,")


def test_csv_da_revisao_neutraliza_texto_com_igual() -> None:
    medida = Medida(
        job_id="j1",
        uid="u1",
        email="=1+1",
        ultimo_pulso=datetime(2026, 10, 1, tzinfo=UTC),
    )

    assert relatorio_em_csv([medida]).splitlines()[1].startswith("j1,'=1+1,")


@pytest.mark.parametrize("inicio", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_em_texto_neutraliza_todo_inicio_de_formula(inicio: str) -> None:
    saida = csv_em_texto(["a"], [[f"{inicio}cmd", "x"]])

    assert list(csv.reader(io.StringIO(saida)))[1] == [f"'{inicio}cmd", "x"]


def test_so_o_csv_seguro_escreve_csv() -> None:
    api = Path(__file__).resolve().parents[1]
    fora = [
        p.relative_to(api).as_posix()
        for p in api.rglob("*.py")
        if "tests" not in p.parts
        and p.name != "csv_seguro.py"
        and "csv.writer" in p.read_text(encoding="utf-8")
    ]

    assert fora == []
