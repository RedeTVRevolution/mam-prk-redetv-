"""A tabela diária da taxa de correção (#455, parte 1 de 2): as linhas por dia, a troca
das linhas no BigQuery e o Terraform."""

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.itens_da_decupagem import ItensDaDecupagem, contar_itens
from api.jobs import ServicoIndisponivel
from api.qualidade_do_painel import _periodo
from api.taxa_de_correcao import calcular
from api.taxa_diaria import (
    ConfigDaTaxa,
    ItensEmMemoria,
    LinhaDiaria,
    TabelaDaTaxaBigQuery,
    TabelaDaTaxaEmMemoria,
    atualizar,
    dias_recentes,
    linhas_do_dia,
    preencher_itens,
)
from api.tests.test_taxa_de_correcao import BASE, Decupagens, _c, _mundo, _pulsar

MAM = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
DIA = BASE.date()


def _mundo_com_itens() -> Any:
    jobs, decupagens, correcoes, revisao = _mundo()
    itens = ItensEmMemoria(
        {
            job_id: contar_itens(b"".join(decupagens.abrir_decupagem(job_id)))
            for job_id in ("j1", "j2", "j3", "j4")
        }
    )
    return jobs, decupagens, itens, correcoes, revisao


def _dia(d: date) -> tuple[datetime | None, datetime | None]:
    """O período que o painel pede para o dia `d` (dia de São Paulo)."""
    return _periodo(d, d)


def _somar(linhas: list[LinhaDiaria]) -> dict[tuple[Any, ...], tuple[int, int]]:
    soma: dict[tuple[Any, ...], list[int]] = defaultdict(lambda: [0, 0])
    for x in linhas:
        chave = (x.programa, x.versao_pipeline, x.tipo)
        soma[chave][0] += x.correcoes
        soma[chave][1] += x.itens
    return {k: (v[0], v[1]) for k, v in soma.items()}


def _de_hoje(
    jobs: Any, decupagens: Any, correcoes: Any, revisao: Any, d: date
) -> dict[tuple[Any, ...], tuple[int, int]]:
    inicio, fim = _dia(d)
    return {
        (x.programa, x.versao_pipeline, x.tipo): (x.correcoes, x.itens)
        for x in calcular(jobs, decupagens, correcoes, revisao, inicio, fim)
    }


def _caso_de_hoje() -> Any:
    """Correção pendente, aprovada (criada 10 dias antes), a aprovada de um JSON anterior
    ao reprocessamento (sai) e um pulso sem correção."""
    jobs, decupagens, itens, correcoes, revisao = _mundo_com_itens()
    modelo = decupagens._dados["j1"]
    correcoes.acrescentar(
        _c("f", "j1", modelo, "pessoa.nao_e", dias=-10, exige_aprovacao=True)
    )
    correcoes.acrescentar(
        _c("g", "j1", modelo, "aprovar", dias=2, aprova="f", antes="", depois="")
    )
    correcoes.acrescentar(
        _c("h", "j1", modelo, "pessoa.fontes_do_nome", dias=3, exige_aprovacao=True)
    )
    # reprocessado: a correção de j2 foi feita sobre um JSON que já não é o da decupagem
    correcoes.acrescentar(_c("i", "j2", {"versao": "antiga"}, dias=4))
    _pulsar(revisao, "j4", dias=5)
    return jobs, decupagens, itens, correcoes, revisao


def test_cada_dia_da_tabela_e_o_calculo_de_hoje_sobre_aquele_dia() -> None:
    jobs, decupagens, itens, correcoes, revisao = _caso_de_hoje()

    for dias in range(-12, 14):
        d = DIA + timedelta(days=dias)
        da_tabela = _somar(
            linhas_do_dia(
                d,
                jobs,
                itens,
                correcoes,
                revisao,
                lambda job_id: json.loads(b"".join(decupagens.abrir_decupagem(job_id))),
            )
        )
        assert da_tabela == _de_hoje(jobs, decupagens, correcoes, revisao, d), d


def test_o_caso_de_hoje_tem_correcao_pendente_aprovada_e_reprocessada() -> None:
    jobs, _, itens, correcoes, revisao = _caso_de_hoje()

    def contagem(d: int, tipo: str) -> int:
        linhas = linhas_do_dia(DIA + timedelta(days=d), jobs, itens, correcoes, revisao)
        return sum(x.correcoes for x in linhas if x.tipo == tipo)

    assert contagem(2, "pessoa.nao_e") == 1  # conta no dia da aprovação
    assert contagem(-10, "pessoa.nao_e") == 0  # e não no da criação
    assert contagem(3, "pessoa.fontes_do_nome") == 0  # pendente
    assert contagem(4, "pessoa.renomear") == 0  # reprocessada: JSON de outra versão


def test_o_dia_e_o_de_sao_paulo_como_o_do_painel() -> None:
    """Às 22h de São Paulo já é o dia seguinte em UTC: a correção conta no dia de São Paulo,
    senão somar dias nunca daria o período que o painel pede."""
    jobs, decupagens, itens, correcoes, revisao = _mundo_com_itens()
    tarde = datetime(2026, 11, 3, 1, 0, tzinfo=UTC)  # 22h de 02/11 em São Paulo
    correcoes.acrescentar(
        _c("z", "j3", decupagens._dados["j3"], dias=0).model_copy(
            update={"criada_em": tarde}
        )
    )

    def do_fama(d: date) -> int:
        linhas = linhas_do_dia(d, jobs, itens, correcoes, revisao)
        return sum(
            x.correcoes
            for x in linhas
            if x.programa == "Fama" and x.tipo == "pessoa.renomear"
        )

    assert do_fama(date(2026, 11, 2)) == 1
    assert do_fama(date(2026, 11, 3)) == 0


def test_as_linhas_trazem_o_dia_o_programa_a_versao_e_so_jobs_concluidos() -> None:
    jobs, _, itens, correcoes, revisao = _mundo_com_itens()
    jobs.salvar(jobs.obter("j1").model_copy(update={"estado": "falhou"}))

    linhas = linhas_do_dia(DIA, jobs, itens, correcoes, revisao)

    assert {(x.dia, x.job_id, x.programa, x.versao_pipeline) for x in linhas} == {
        (DIA, "j2", "Jornal", "v2")
    }


def test_job_sem_contagem_fica_de_fora_sem_derrubar_o_dia() -> None:
    jobs, _, itens, correcoes, revisao = _mundo_com_itens()
    itens.apagar("j1")

    linhas = linhas_do_dia(DIA, jobs, itens, correcoes, revisao)

    assert {x.programa for x in linhas} == {"Jornal"}
    assert {x.versao_pipeline for x in linhas} == {"v2"}


def test_dois_jobs_no_mesmo_grupo_e_dia_ficam_em_linhas_separadas() -> None:
    jobs, _, itens, correcoes, revisao = _mundo_com_itens()
    _pulsar(revisao, "j4")

    linhas = linhas_do_dia(DIA, jobs, itens, correcoes, revisao)

    assert {
        (x.job_id, x.correcoes, x.itens) for x in linhas if x.tipo == "pessoa.renomear"
    } == {
        ("j1", 2, 10),
        ("j2", 1, 10),
        ("j4", 0, 100),
    }
    assert len(linhas) == len({(x.dia, x.job_id, x.tipo) for x in linhas})


def test_atualizar_troca_os_dias_pedidos_e_deixa_os_outros() -> None:
    jobs, _, itens, correcoes, revisao = _caso_de_hoje()
    tabela = TabelaDaTaxaEmMemoria()
    tabela.linhas.append(LinhaDiaria(DIA, "j1", "Velho", None, "pessoa.renomear", 9, 9))
    tabela.linhas.append(
        LinhaDiaria(DIA - timedelta(days=99), "j2", "X", None, "t", 1, 1)
    )

    atualizar([DIA, DIA + timedelta(days=2)], jobs, itens, correcoes, revisao, tabela)
    atualizar([DIA, DIA + timedelta(days=2)], jobs, itens, correcoes, revisao, tabela)

    assert not any(x.programa == "Velho" for x in tabela.linhas)
    assert any(x.dia == DIA - timedelta(days=99) for x in tabela.linhas)
    assert {x.dia for x in tabela.linhas} == {
        DIA - timedelta(days=99),
        DIA,
        DIA + timedelta(days=2),
    }
    assert len(tabela.linhas) == len(set(tabela.linhas))  # repetir não duplica


def test_dias_recentes_vao_de_hoje_para_tras() -> None:
    assert dias_recentes(date(2026, 11, 7), 3) == [
        date(2026, 11, 5),
        date(2026, 11, 6),
        date(2026, 11, 7),
    ]


def test_preencher_itens_conta_so_os_concluidos_que_ainda_nao_tem() -> None:
    jobs, decupagens, itens, _, _ = _mundo_com_itens()
    itens.apagar("j1")
    itens.apagar("j2")
    jobs.salvar(jobs.obter("j2").model_copy(update={"estado": "falhou"}))

    gravados = preencher_itens(jobs, decupagens, itens)

    assert gravados == 1
    assert itens.ler_itens("j1").itens["pessoa.renomear"] == 10
    with pytest.raises(ServicoIndisponivel):
        itens.ler_itens("j2")


def test_preencher_itens_pula_decupagem_que_nao_le() -> None:
    jobs, _, itens, _, _ = _mundo_com_itens()
    itens.apagar("j1")

    assert preencher_itens(jobs, Decupagens({}), itens) == 0


class _Transporte:
    def __init__(self) -> None:
        self.corpos: list[dict[str, Any]] = []

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return {"jobComplete": True}


CONFIG = ConfigDaTaxa("proj", "decupagens", "regiao-x", "taxa")


def test_o_bigquery_troca_os_dias_num_unico_merge() -> None:
    transporte = _Transporte()
    linhas = [LinhaDiaria(DIA, "j1", "Jornal", None, "pessoa.renomear", 2, 10)]

    TabelaDaTaxaBigQuery(CONFIG, transporte).substituir([DIA], linhas)

    [corpo] = transporte.corpos
    consulta = corpo["query"]
    assert "MERGE `proj.decupagens.taxa`" in consulta
    assert "WHEN NOT MATCHED BY SOURCE" in consulta
    assert "JSON_VALUE(l, '$.job_id') AS job_id" in consulta
    assert "AND t.job_id = s.job_id" in consulta
    assert (
        "INSERT (dia, job_id, programa, versao_pipeline, tipo, correcoes, itens)"
        in consulta
    )
    assert "VALUES (s.dia, s.job_id, s.programa, s.versao_pipeline, s.tipo," in consulta
    assert corpo["location"] == "regiao-x"
    assert "SELECT DATE(d)" not in consulta  # o BigQuery recusa subconsulta no ON
    assert consulta.count("t.dia IN UNNEST(@dias)") == 2
    parametros = {p["name"]: p for p in corpo["queryParameters"]}
    assert parametros["dias"]["parameterType"] == {
        "type": "ARRAY",
        "arrayType": {"type": "DATE"},
    }
    assert parametros["dias"]["parameterValue"] == {
        "arrayValues": [{"value": DIA.isoformat()}]
    }
    assert json.loads(parametros["linhas"]["parameterValue"]["value"]) == [
        {
            "dia": DIA.isoformat(),
            "job_id": "j1",
            "programa": "Jornal",
            "versao_pipeline": None,
            "tipo": "pessoa.renomear",
            "correcoes": 2,
            "itens": 10,
        }
    ]


def test_o_merge_que_nao_termina_no_prazo_e_erro() -> None:
    with pytest.raises(RuntimeError):
        TabelaDaTaxaBigQuery(CONFIG, lambda corpo: {"jobComplete": False}).substituir(
            [DIA], []
        )


def test_os_dias_sao_trocados_em_lotes_para_caber_no_parametro() -> None:
    transporte = _Transporte()
    dias = [DIA + timedelta(days=n) for n in range(400)]
    linhas = [LinhaDiaria(d, "j1", "J", None, "t", 1, 1) for d in dias]

    TabelaDaTaxaBigQuery(CONFIG, transporte, dias_por_merge=100).substituir(
        dias, linhas
    )

    assert len(transporte.corpos) == 4


def test_muitas_linhas_em_poucos_dias_respeitam_os_bytes_sem_partir_dia() -> None:
    transporte = _Transporte()
    dias = [DIA + timedelta(days=n) for n in range(5)]
    linhas = [
        LinhaDiaria(d, f"j{n}", 'Jornal "São Paulo"', None, "pessoa.renomear", 1, 10)
        for n in range(15_000)
        for d in dias[1:]  # um dia vazio também precisa ser substituído
    ]

    TabelaDaTaxaBigQuery(CONFIG, transporte).substituir(dias, linhas)

    assert len(transporte.corpos) > 1
    dias_trocados: set[str] = set()
    recebidas: list[tuple[str, str]] = []
    for corpo in transporte.corpos:
        parametros = {p["name"]: p["parameterValue"] for p in corpo["queryParameters"]}
        valor = parametros["linhas"]["value"]
        assert len(json.dumps(valor).encode("utf-8")) <= 8_000_000
        assert len(json.dumps(corpo).encode("utf-8")) < 10_000_000
        lote = {x["value"] for x in parametros["dias"]["arrayValues"]}
        assert not dias_trocados & lote
        dias_trocados.update(lote)
        linhas_do_lote = json.loads(valor)
        assert {x["dia"] for x in linhas_do_lote} <= lote
        recebidas.extend((x["dia"], x["job_id"]) for x in linhas_do_lote)
    assert dias_trocados == {d.isoformat() for d in dias}
    assert sorted(recebidas) == sorted((x.dia.isoformat(), x.job_id) for x in linhas)


def test_dia_acima_do_teto_vai_sozinho_sem_perder_linhas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.taxa_diaria.BYTES_POR_MERGE", 1_000)
    transporte = _Transporte()
    dias = [DIA + timedelta(days=n) for n in range(3)]
    linhas = [
        LinhaDiaria(d, f"j{n}", None, None, "pessoa.renomear", 1, 10)
        for d, quantidade in zip(dias, [1, 20, 1], strict=True)
        for n in range(quantidade)
    ]

    TabelaDaTaxaBigQuery(CONFIG, transporte).substituir(dias, linhas)

    assert len(transporte.corpos) == 3
    for corpo, dia, quantidade in zip(transporte.corpos, dias, [1, 20, 1], strict=True):
        parametros = {p["name"]: p["parameterValue"] for p in corpo["queryParameters"]}
        assert parametros["dias"]["arrayValues"] == [{"value": dia.isoformat()}]
        recebidas = json.loads(parametros["linhas"]["value"])
        assert len(recebidas) == quantidade
        assert {x["dia"] for x in recebidas} == {dia.isoformat()}


def test_o_json_de_itens_ida_e_volta_com_a_versao_do_modelo() -> None:
    itens = ItensDaDecupagem("abc", None, {"pessoa.renomear": 1})
    assert ItensDaDecupagem.do_json(itens.em_json()) == itens


def test_o_terraform_da_tabela_tem_as_colunas_da_carga_e_particiona_por_dia() -> None:
    tf = (MAM / "taxa_diaria.tf").read_text()

    for coluna in (
        "dia",
        "job_id",
        "programa",
        "versao_pipeline",
        "tipo",
        "correcoes",
        "itens",
    ):
        assert f'name = "{coluna}"' in tf
    assert 'field = "dia"' in tf
    assert '{ name = "job_id", type = "STRING", mode = "NULLABLE"' in tf
    assert 'type  = "DAY"' in tf
    assert "deletion_protection = true" in tf


def test_o_job_agendado_recebe_os_nomes_do_terraform() -> None:
    tf = (MAM / "taxa_diaria.tf").read_text()

    for variavel in (
        "GCP_PROJECT_ID",
        "BUCKET_DECUPAGENS",
        "BIGQUERY_DATASET",
        "BIGQUERY_TABELA_DA_TAXA",
        "BIGQUERY_REGIAO",
    ):
        assert f'"{variavel}"' in tf
    assert "api.taxa_diaria" in tf
    assert "google_cloud_scheduler_job" in tf
    main = (MAM.parent.parent / "main.tf").read_text()
    assert 'output "bigquery_tabela_da_taxa"' in main
