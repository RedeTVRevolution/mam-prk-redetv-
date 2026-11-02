"""Cópia das decupagens no BigQuery (#260), sem rede."""

import json
from datetime import date
from typing import Any

from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaBigQuery,
    CopiaEmMemoria,
    LinhaDoMomento,
    PessoaDoMomento,
    linhas_da_decupagem,
)
from api.copiar_para_bigquery import copiar_jobs
from api.decupagem import (
    Aparicao,
    Comercial,
    MencaoNaFala,
    MencaoNoTexto,
    Pessoa,
)
from api.exemplos_da_busca import EXEMPLOS
from api.tests.test_correcoes import BASE
from api.tests.test_indexacao import AUTORIZACAO, Mundo, _job

DECUPAGEM = EXEMPLOS[0].decupagem
DIA = date(2026, 10, 30)


def _linhas(gravado_em: Any = None) -> list[LinhaDoMomento]:
    return linhas_da_decupagem("j1", DECUPAGEM, "Exemplo", DIA, gravado_em or BASE)


class CopiaQueFalha(CopiaEmMemoria):
    def gravar(self, job_id: str, linhas: list[LinhaDoMomento]) -> None:
        raise ConnectionError("BigQuery fora do ar")


def MundoComCopia(copia: CopiaEmMemoria) -> Mundo:
    return Mundo(copia=copia)


def test_uma_linha_por_momento_com_pessoa_marca_e_texto() -> None:
    comercial = Comercial(
        inicio_ms=1000,
        fim_ms=2000,
        marca="Marca X",
        tipo="merchan_apresentador",
        evidencias=["fala"],
    )
    decupagem = DECUPAGEM.model_copy(update={"comerciais": [comercial]})
    linhas = linhas_da_decupagem("j1", decupagem, "Exemplo", DIA, BASE)

    por_tipo = {t: [x for x in linhas if x.tipo == t] for t in {x.tipo for x in linhas}}
    assert len(por_tipo["fala"]) == len(DECUPAGEM.transcricao)
    assert len(por_tipo["comercial"]) == len(decupagem.comerciais)
    assert all(x.job_id == "j1" and x.programa == "Exemplo" for x in linhas)
    assert all(x.data_de_exibicao == DIA for x in linhas)
    com_pessoa = [x for x in linhas if x.pessoas]
    assert com_pessoa and all(p.id and p.nome for x in com_pessoa for p in x.pessoas)
    for c, linha in zip(decupagem.comerciais, por_tipo["comercial"], strict=True):
        assert (linha.marca, linha.tipo_de_insercao) == (c.marca, c.tipo)
        assert (linha.inicio_ms, linha.fim_ms) == (c.inicio_ms, c.fim_ms)


def test_gravar_duas_vezes_deixa_as_mesmas_linhas() -> None:
    copia = CopiaEmMemoria()
    copia.gravar("j1", _linhas())
    antes = copia.por_job["j1"]

    copia.gravar("j1", _linhas())

    assert copia.por_job["j1"] == antes
    assert copia.total() == len(antes)


def test_concluir_o_job_copia_e_marca_copiado() -> None:
    mundo = MundoComCopia(CopiaEmMemoria())

    mundo.reindexar()

    assert mundo.copia.total() > 0
    job = mundo.jobs.obter("j1")
    assert job and job.copia_bigquery and job.copia_bigquery.estado == "copiado"


def test_correcao_troca_as_linhas_do_job() -> None:
    mundo = MundoComCopia(CopiaEmMemoria())
    mundo.reindexar()
    antes = mundo.copia.total()

    mundo.corrigir_a_fala("texto corrigido pela revisão")
    mundo.reindexar()

    textos = [x.texto for x in mundo.copia.por_job["j1"] if x.tipo == "fala"]
    assert "texto corrigido pela revisão" in textos
    assert len(textos) == len(DECUPAGEM.transcricao)
    assert mundo.copia.total() == antes


def test_falha_do_bigquery_nao_derruba_o_job_nem_a_indexacao() -> None:
    mundo = MundoComCopia(CopiaQueFalha())

    mundo.reindexar()

    job = mundo.jobs.obter("j1")
    assert job and job.estado == "concluido"
    assert job.copia_bigquery and job.copia_bigquery.estado == "falhou"
    assert job.indexacao and job.indexacao.estado == "indexado"
    assert mundo.indice.total() > 0


def test_falha_do_bigquery_numa_correcao_nao_derruba_a_correcao() -> None:
    mundo = Mundo(copia=CopiaQueFalha())

    resposta = mundo.corrigir_a_fala("outro texto")

    assert resposta.status_code == 201
    assert mundo.textos_das_falas() == ["outro texto"]
    job = mundo.jobs.obter("j1")
    assert job and job.copia_bigquery and job.copia_bigquery.estado == "falhou"
    publico = mundo.cliente.get("/v1/jobs/j1", headers=AUTORIZACAO).json()
    assert publico["copia_bigquery"]["estado"] == "falhou"


def test_correcao_pela_rota_troca_as_linhas_na_copia() -> None:
    copia = CopiaEmMemoria()
    mundo = Mundo(copia=copia)
    mundo.reindexar()

    mundo.corrigir_a_fala("texto da rota")

    assert "texto da rota" in [x.texto for x in copia.por_job["j1"] if x.tipo == "fala"]


def test_falha_e_refeita_pela_carga() -> None:
    mundo = MundoComCopia(CopiaQueFalha())
    mundo.reindexar()
    copia = CopiaEmMemoria()

    resultado = copiar_jobs(
        None, mundo.jobs, mundo.armazenamento, mundo.correcoes, copia
    )

    assert resultado == {"j1": "copiado"}
    job = mundo.jobs.obter("j1")
    assert job and job.copia_bigquery and job.copia_bigquery.estado == "copiado"
    assert copia.total() > 0


def test_carga_ignora_job_nao_concluido_e_aponta_inexistente() -> None:
    mundo = Mundo()
    mundo.jobs.salvar(_job("j2", estado="analisando"))

    resultado = copiar_jobs(
        ["j1", "j2", "nada"],
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        CopiaEmMemoria(),
    )

    assert resultado == {"nada": "inexistente", "j1": "copiado", "j2": "ignorado"}


def test_adaptador_troca_as_linhas_do_job_num_unico_merge() -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        return {"jobComplete": True}

    copia = CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "regiao-x"), transporte)

    copia.gravar("j1", _linhas())

    (pedido,) = pedidos
    sql = pedido["query"]
    assert "TRANSACTION" not in sql and sql.count(";") == 0
    assert sql.index("MERGE `p.d.t`") < sql.index("ON FALSE")
    assert "NOT MATCHED BY SOURCE AND t.job_id = @job_id THEN DELETE" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert pedido["location"] == "regiao-x"
    parametros = {
        q["name"]: q["parameterValue"]["value"] for q in pedido["queryParameters"]
    }
    assert parametros["job_id"] == "j1"
    linhas = json.loads(parametros["linhas"])
    assert len(linhas) == len(_linhas())
    assert linhas[0]["data_de_exibicao"] == "2026-10-30"


def test_adaptador_recusa_resposta_incompleta() -> None:
    copia = CopiaBigQuery(
        ConfigDoBigQuery("p", "d", "t", "r"), lambda corpo: {"jobComplete": False}
    )
    try:
        copia.gravar("j1", [])
    except RuntimeError:
        return
    raise AssertionError("devia levantar")


def test_aparicoes_e_mencoes_viram_linhas_separadas_por_pessoa() -> None:
    pessoa = Pessoa(
        id="p1",
        nome="Sabrina Sato",
        catalogo_id="c1",
        estado_do_nome="confirmado",
        na_imagem=[Aparicao(inicio_ms=1000, fim_ms=4000, evidencia="rosto")],
        citada_na_fala=[MencaoNaFala(inicio_ms=5000, fim_ms=6000)],
        citada_no_texto=[MencaoNoTexto(inicio_ms=7000, fim_ms=8000, texto="Sabrina")],
    )
    palpite = pessoa.model_copy(
        update={"id": "p2", "catalogo_id": "c2", "estado_do_nome": "palpite"}
    )
    sem_catalogo = pessoa.model_copy(update={"id": "p3", "catalogo_id": None})
    decupagem = DECUPAGEM.model_copy(
        update={"pessoas": [pessoa, palpite, sem_catalogo]}
    )

    linhas = linhas_da_decupagem("j1", decupagem, "Exemplo", DIA, BASE)

    das_pessoas = {
        (x.tipo, x.inicio_ms, x.fim_ms, tuple(x.pessoas))
        for x in linhas
        if x.tipo in ("aparicao", "mencao_na_fala", "mencao_no_texto")
    }
    dona = PessoaDoMomento("c1", "Sabrina Sato")
    assert das_pessoas == {
        ("aparicao", 1000, 4000, (dona,)),
        ("mencao_na_fala", 5000, 6000, (dona,)),
        ("mencao_no_texto", 7000, 8000, (dona,)),
    }
