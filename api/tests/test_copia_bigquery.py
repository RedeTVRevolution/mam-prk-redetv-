"""Cópia das decupagens no BigQuery (#260), sem rede."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Event
from typing import Any

import pytest

from api.ciclo_de_vida import PRAZO_DA_RODADA
from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaBigQuery,
    CopiaEmMemoria,
    LinhaDoMomento,
    PessoaDoMomento,
    _json_da_linha,
    linhas_da_decupagem,
)
from api.copiar_para_bigquery import copiar, copiar_jobs
from api.decupagem import (
    Aparicao,
    Comercial,
    MencaoNaFala,
    MencaoNoTexto,
    Pessoa,
)
from api.exemplos_da_busca import EXEMPLOS
from api.indexacao import reindexar
from api.jobs import CopiaNoBigQuery, Indexacao, Job
from api.tests.test_correcoes import BASE
from api.tests.test_indexacao import (
    AUTORIZACAO,
    Mundo,
    _job,
    _modelo_com_sandalia_e_scarpin,
)
from api.tests.test_sinal_do_programa import _historico, _sinal

DECUPAGEM = EXEMPLOS[0].decupagem
DIA = date(2026, 10, 30)


def _linhas(gravado_em: Any = None) -> list[LinhaDoMomento]:
    return linhas_da_decupagem("j1", DECUPAGEM, "Exemplo", DIA, gravado_em or BASE)


class CopiaQueFalha(CopiaEmMemoria):
    def gravar(
        self,
        job_id: str,
        linhas: list[LinhaDoMomento],
        *,
        anos: list[int] | None = None,
    ) -> None:
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
    assert com_pessoa and all(
        p.id and not p.nome for x in com_pessoa for p in x.pessoas
    )
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
    mundo.aprovar_revisao()
    mundo.rodar_o_job()

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
    assert "texto da rota" not in [
        x.texto for x in copia.por_job["j1"] if x.tipo == "fala"
    ]
    mundo.aprovar_revisao()
    mundo.rodar_o_job()

    assert "texto da rota" in [x.texto for x in copia.por_job["j1"] if x.tipo == "fala"]


def test_falha_e_refeita_pela_carga() -> None:
    mundo = MundoComCopia(CopiaQueFalha())
    mundo.reindexar()
    copia = CopiaEmMemoria()

    resultado = copiar_jobs(
        None,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        copia,
        indice=mundo.indice,
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
        indice=mundo.indice,
    )

    assert resultado == {"nada": "inexistente", "j1": "copiado", "j2": "ignorado"}
    assert mundo.disparo.pedidos == []
    assert mundo.indice.total() == 0
    atual = mundo.jobs.obter("j1")
    assert atual and atual.versao_pedida == atual.versao_indexada == 0


@pytest.mark.parametrize("pendencia", ["estado", "versao"])
def test_carga_atende_pedido_pendente_pelo_estado_ou_pela_versao(
    pendencia: str,
) -> None:
    mundo = Mundo(copia=CopiaEmMemoria())
    mundo.jobs.salvar(
        _job().model_copy(
            update={
                "indexacao": Indexacao(
                    estado="pendente" if pendencia == "estado" else "indexado", em=BASE
                ),
                "versao_pedida": 0 if pendencia == "estado" else 9,
                "versao_indexada": 0 if pendencia == "estado" else 8,
            }
        )
    )

    assert copiar_jobs(
        None,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.copia,
        indice=mundo.indice,
    ) == {"j1": "copiado"}

    atual = mundo.jobs.obter("j1")
    assert atual and atual.versao_pedida == atual.versao_indexada
    assert atual.indexacao and atual.indexacao.estado == "indexado"
    assert mundo.indice.total() > 0


def test_carga_atende_indexacao_pendente_com_tipos_de_objeto_e_sinal() -> None:
    class CopiaQueRecebePedido(CopiaEmMemoria):
        def gravar(
            self,
            job_id: str,
            linhas: list[LinhaDoMomento],
            *,
            anos: list[int] | None = None,
        ) -> None:
            if self.total() == 0:
                atual = mundo.jobs.obter(job_id)
                assert atual
                mundo.jobs.salvar(
                    atual.model_copy(
                        update={"indexacao": Indexacao(estado="pendente", em=BASE)}
                    )
                )
            super().gravar(job_id, linhas, anos=anos)

    mundo = Mundo(copia=CopiaQueRecebePedido(), modelo=_modelo_com_sandalia_e_scarpin())
    sinal, saidas = _sinal(_historico([4, 6, 5, 4, 6]), k=0.0001)

    assert copiar_jobs(
        None,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.copia,
        indice=mundo.indice,
        tipos_de_objeto=mundo.tipos,
        sinal=sinal,
    ) == {"j1": "copiado"}

    atual = mundo.jobs.obter("j1")
    assert atual and atual.indexacao and atual.indexacao.estado == "indexado"
    assert mundo.tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 1}]
    assert saidas
    assert all(s["job_id"] == "j1" and s["programa"] == "Exemplo" for s in saidas)


@pytest.mark.parametrize("escritor", ["carga", "indexacao"])
@pytest.mark.parametrize(
    "interferencia", ["final", "final_no_mesmo_instante", "pendente"]
)
@pytest.mark.parametrize(
    ("data", "anos_iniciais", "conhecidas", "anos_repostos"),
    [
        (DIA, [2025], True, []),
        (None, [2025], True, []),
        (DIA, [2025], True, [2025]),
        (DIA, [2025], True, [2026]),
        (None, [2025], True, [2026]),
        (None, [], True, []),
        (None, [], False, []),
    ],
)
def test_imagem_anterior_apaga_os_anos_e_a_proxima_copia_limpa_sem_filtro(
    escritor: str,
    interferencia: str,
    data: date | None,
    anos_iniciais: list[int],
    conhecidas: bool,
    anos_repostos: list[int],
) -> None:
    consultas: list[str] = []
    with sqlite3.connect(":memory:") as banco:
        banco.execute("CREATE TABLE momentos (job_id TEXT, data_de_exibicao TEXT)")

        def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
            sql = corpo["query"]
            consultas.append(sql)
            parametros = {
                p["name"]: p["parameterValue"]["value"]
                for p in corpo["queryParameters"]
            }
            predicado = sql.split("WHEN NOT MATCHED BY SOURCE AND ")[1].split(
                " THEN DELETE"
            )[0]
            banco.execute(f"DELETE FROM momentos AS t WHERE {predicado}", parametros)
            banco.executemany(
                "INSERT INTO momentos VALUES (?, ?)",
                [
                    (l["job_id"], l["data_de_exibicao"])
                    for l in json.loads(parametros["linhas"])
                ],
            )
            if len(consultas) == 1:
                atual = mundo.jobs.obter("j1")
                assert atual and atual.copia_bigquery
                # A imagem anterior regrava só os campos antigos.
                banco.execute("INSERT INTO momentos VALUES ('j1', '2025-01-01')")
                dados = atual.model_dump()
                dados["copia_bigquery"] = {
                    "estado": "pendente" if interferencia == "pendente" else "copiado",
                    "em": atual.copia_bigquery.em
                    if interferencia == "final_no_mesmo_instante"
                    else BASE,
                }
                mundo.jobs.salvar(Job.model_validate(dados))
                for ano in anos_repostos:
                    mundo.jobs.acrescentar_ano_da_copia("j1", ano)
            return {"jobComplete": True}

        mundo = Mundo(
            copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
        )
        mundo.jobs.salvar(
            _job().model_copy(
                update={
                    "data_exibicao": data,
                    "copia_bigquery": CopiaNoBigQuery(
                        estado="copiado",
                        em=BASE,
                        anos=anos_iniciais,
                        particoes_conhecidas=conhecidas,
                    ),
                }
            )
        )
        for rodada in range(2):
            if escritor == "carga":
                assert copiar_jobs(
                    None,
                    mundo.jobs,
                    mundo.armazenamento,
                    mundo.correcoes,
                    mundo.copia,
                    indice=mundo.indice,
                ) == {"j1": "copiado"}
            else:
                mundo.reindexar()
            atual = mundo.jobs.obter("j1")
            assert atual and atual.copia_bigquery
            if rodada == 0:
                assert not atual.copia_bigquery.particoes_conhecidas
                mundo.jobs.salvar(
                    atual.model_copy(update={"data_exibicao": date(2027, 1, 1)})
                )

        assert ("t.data_de_exibicao IS NULL" in consultas[0]) is conhecidas
        assert "t.data_de_exibicao IS NULL" not in consultas[1]
        assert banco.execute("SELECT * FROM momentos").fetchall() == [
            ("j1", "2027-01-01")
        ] * len(_linhas())
        assert atual and atual.copia_bigquery
        assert atual.copia_bigquery.particoes_conhecidas


@pytest.mark.parametrize("escritor", ["carga", "indexacao"])
@pytest.mark.parametrize("marcador", ["legado", "desconhecido", "conhecido"])
def test_interferencia_antes_do_pendente_nao_deixa_linhas_orfas(
    escritor: str, marcador: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    consultas: list[str] = []
    interferiu = False
    with sqlite3.connect(":memory:") as banco:
        banco.execute("CREATE TABLE momentos (job_id TEXT, data_de_exibicao TEXT)")

        def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
            sql = corpo["query"]
            consultas.append(sql)
            parametros = {
                p["name"]: p["parameterValue"]["value"]
                for p in corpo["queryParameters"]
            }
            predicado = sql.split("WHEN NOT MATCHED BY SOURCE AND ")[1].split(
                " THEN DELETE"
            )[0]
            banco.execute(f"DELETE FROM momentos AS t WHERE {predicado}", parametros)
            banco.executemany(
                "INSERT INTO momentos VALUES (?, ?)",
                [
                    (l["job_id"], l["data_de_exibicao"])
                    for l in json.loads(parametros["linhas"])
                ],
            )
            return {"jobComplete": True}

        mundo = Mundo(
            copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
        )
        mundo.jobs.salvar(
            _job().model_copy(
                update={
                    "copia_bigquery": CopiaNoBigQuery(
                        estado="copiado",
                        em=BASE,
                        anos=[2026],
                        particoes_conhecidas=True,
                    )
                }
            )
        )
        trocar = mundo.jobs.trocar

        def gravar(job_id: str, mudar: Any) -> Job | None:
            nonlocal interferiu
            atual = mundo.jobs.obter(job_id)
            assert atual
            registro = (mudar(atual) or {}).get("copia_bigquery")
            if not interferiu and registro and registro.estado == "pendente":
                interferiu = True
                banco.execute("INSERT INTO momentos VALUES ('j1', '2028-01-01')")
                dados = atual.model_dump()
                dados["copia_bigquery"] = {"estado": "copiado", "em": BASE}
                if marcador != "legado":
                    dados["copia_bigquery"].update(
                        anos=[2026, 2028], particoes_conhecidas=marcador == "conhecido"
                    )
                mundo.jobs.salvar(Job.model_validate(dados))
            # A transação relê o marcador depois da interferência.
            return trocar(job_id, mudar)

        monkeypatch.setattr(mundo.jobs, "trocar", gravar)
        for data in (DIA, date(2027, 1, 1)):
            atual = mundo.jobs.obter("j1")
            assert atual
            mundo.jobs.salvar(atual.model_copy(update={"data_exibicao": data}))
            if escritor == "carga":
                assert copiar_jobs(
                    None,
                    mundo.jobs,
                    mundo.armazenamento,
                    mundo.correcoes,
                    mundo.copia,
                    indice=mundo.indice,
                ) == {"j1": "copiado"}
            else:
                mundo.reindexar()

        assert interferiu
        assert banco.execute("SELECT * FROM momentos").fetchall() == [
            ("j1", "2027-01-01")
        ] * len(_linhas())
        assert ("t.data_de_exibicao IS NULL" in consultas[0]) is (
            marcador == "conhecido"
        )
        if marcador == "conhecido":
            assert "@inicio_2028" in consultas[0]


@pytest.mark.parametrize("escritor", ["carga", "indexacao"])
@pytest.mark.parametrize("falha", [False, True])
@pytest.mark.parametrize("anterior", [date(2025, 12, 31), None])
@pytest.mark.parametrize("nova", [DIA, None])
def test_escritores_nunca_reduzem_o_conjunto_de_anos(
    escritor: str, falha: bool, anterior: date | None, nova: date | None
) -> None:
    pendentes: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        job = mundo.jobs.obter("j1")
        assert job and job.copia_bigquery
        pendentes.append(job.copia_bigquery.model_dump())
        if falha:
            raise ConnectionError("BigQuery fora do ar")
        return {"jobComplete": True}

    mundo = Mundo(copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte))
    job = _job().model_copy(
        update={
            "data_exibicao": nova,
            "copia_bigquery": CopiaNoBigQuery.model_validate(
                {
                    "estado": "copiado",
                    "em": BASE,
                    "anos": [anterior.year] if anterior else [],
                    "particoes_conhecidas": True,
                }
            ),
        }
    )
    mundo.jobs.salvar(job)

    if escritor == "carga":
        copiar_jobs(
            None,
            mundo.jobs,
            mundo.armazenamento,
            mundo.correcoes,
            mundo.copia,
            indice=mundo.indice,
        )
    else:
        mundo.reindexar()

    (pendente,) = pendentes
    assert pendente["estado"] == "pendente"
    assert pendente["anos"] == sorted({d.year for d in (anterior, nova) if d})
    assert pendente["particoes_conhecidas"] is True
    copiado = mundo.jobs.obter("j1")
    assert copiado and copiado.copia_bigquery
    registro = copiado.model_dump()
    final = registro["copia_bigquery"]
    assert final["estado"] == ("falhou" if falha else "copiado")
    esperados = sorted({d.year for d in (anterior, nova) if d})
    assert final["anos"] == esperados
    assert final["particoes_conhecidas"] is True
    assert Job.model_validate(registro).model_dump() == registro


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


@pytest.mark.parametrize(
    ("nova", "anos"),
    [
        (DIA, [2025, 2026]),
        (DIA, [2026]),
        (None, [2026]),
        (DIA, [2023, 2025, 2026]),
        (None, []),
    ],
)
def test_merge_limita_o_delete_ao_conjunto_de_anos_e_null(
    nova: date | None, anos: list[int]
) -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        return {"jobComplete": True}

    copia = CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
    linhas = linhas_da_decupagem("j1", DECUPAGEM, "Exemplo", nova, BASE)

    copia.gravar("j1", linhas, anos=anos)

    (pedido,) = pedidos
    parametros = {q["name"]: q for q in pedido["queryParameters"]}
    predicados = ["t.data_de_exibicao IS NULL"]
    for ano in anos:
        predicados.append(f"t.data_de_exibicao BETWEEN @inicio_{ano} AND @fim_{ano}")
        assert parametros[f"inicio_{ano}"] == {
            "name": f"inicio_{ano}",
            "parameterType": {"type": "DATE"},
            "parameterValue": {"value": f"{ano}-01-01"},
        }
        assert parametros[f"fim_{ano}"]["parameterType"] == {"type": "DATE"}
        assert parametros[f"fim_{ano}"]["parameterValue"] == {"value": f"{ano}-12-31"}
    assert set(parametros) == {
        "job_id",
        "linhas",
        *(f"{limite}_{ano}" for ano in anos for limite in ("inicio", "fim")),
    }
    filtro = " OR ".join(predicados)
    assert (
        f"WHEN NOT MATCHED BY SOURCE AND t.job_id = @job_id AND ({filtro}) THEN DELETE"
        in pedido["query"]
    )


@pytest.mark.parametrize("escritor", ["carga", "indexacao"])
@pytest.mark.parametrize("registrada", [False, True])
@pytest.mark.parametrize("falha_ao_finalizar", [False, True])
@pytest.mark.parametrize(
    ("anterior", "nova"),
    [(date(2025, 12, 31), DIA), (DIA, None), (None, DIA), (None, None)],
)
def test_recopia_apaga_linhas_antigas_e_limita_as_particoes_apos_o_primeiro_sucesso(
    escritor: str,
    registrada: bool,
    falha_ao_finalizar: bool,
    anterior: date | None,
    nova: date | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consultas: list[str] = []
    with sqlite3.connect(":memory:") as banco:
        banco.execute("CREATE TABLE momentos (job_id TEXT, data_de_exibicao TEXT)")
        banco.executemany(
            "INSERT INTO momentos VALUES (?, ?)",
            [
                ("j1", anterior.isoformat() if anterior else None),
                ("j1", None),
                ("outro", "2000-01-01"),
            ],
        )

        def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
            sql = corpo["query"]
            consultas.append(sql)
            parametros = {
                p["name"]: p["parameterValue"]["value"]
                for p in corpo["queryParameters"]
            }
            # Executa localmente o predicado real do DELETE; o INSERT vem do JSON enviado.
            predicado = sql.split("WHEN NOT MATCHED BY SOURCE AND ")[1].split(
                " THEN DELETE"
            )[0]
            banco.execute(f"DELETE FROM momentos AS t WHERE {predicado}", parametros)
            banco.executemany(
                "INSERT INTO momentos VALUES (?, ?)",
                [
                    (l["job_id"], l["data_de_exibicao"])
                    for l in json.loads(parametros["linhas"])
                ],
            )
            return {"jobComplete": True}

        mundo = Mundo(
            copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
        )
        marcador: dict[str, Any] = {"estado": "copiado", "em": BASE}
        if registrada:
            marcador.update(
                anos=[anterior.year] if anterior else [], particoes_conhecidas=True
            )
        mundo.jobs.salvar(
            _job().model_copy(
                update={
                    "data_exibicao": nova,
                    "copia_bigquery": CopiaNoBigQuery.model_validate(marcador),
                }
            )
        )

        trocar = mundo.jobs.trocar

        def gravar(job_id: str, mudar: Any) -> Job | None:
            def na_transacao(job: Job) -> dict[str, Any] | None:
                mudancas: dict[str, Any] | None = mudar(job)
                copia = (mudancas or {}).get("copia_bigquery")
                if falha_ao_finalizar and copia and copia.estado == "copiado":
                    raise ConnectionError("Firestore caiu depois do MERGE")
                return mudancas

            return trocar(job_id, na_transacao)

        monkeypatch.setattr(mundo.jobs, "trocar", gravar)
        for rodada in range(2):
            if rodada == 1 and falha_ao_finalizar:
                monkeypatch.setattr(mundo.jobs, "trocar", trocar)
                nova = date(2027, 1, 1)
                atual = mundo.jobs.obter("j1")
                assert atual
                mundo.jobs.salvar(atual.model_copy(update={"data_exibicao": nova}))
            if escritor == "carga":
                copiar_jobs(
                    None,
                    mundo.jobs,
                    mundo.armazenamento,
                    mundo.correcoes,
                    mundo.copia,
                    indice=mundo.indice,
                )
            else:
                mundo.reindexar()
            linhas = banco.execute(
                "SELECT * FROM momentos WHERE job_id = 'j1'"
            ).fetchall()
            assert linhas == [("j1", nova.isoformat() if nova else None)] * len(
                _linhas()
            )
            assert banco.execute(
                "SELECT * FROM momentos WHERE job_id = 'outro'"
            ).fetchall() == [("outro", "2000-01-01")]

    atual = mundo.jobs.obter("j1")
    assert atual and atual.copia_bigquery and atual.copia_bigquery.particoes_conhecidas
    assert ("t.data_de_exibicao IS NULL" in consultas[0]) is registrada
    if not falha_ao_finalizar or registrada:
        assert "t.data_de_exibicao IS NULL" in consultas[1]
    if registrada and anterior:
        assert f"@inicio_{anterior.year}" in consultas[0]
    if nova and (not falha_ao_finalizar or registrada):
        assert f"@inicio_{nova.year}" in consultas[1]


def test_adaptador_recusa_resposta_incompleta() -> None:
    copia = CopiaBigQuery(
        ConfigDoBigQuery("p", "d", "t", "r"), lambda corpo: {"jobComplete": False}
    )
    try:
        copia.gravar("j1", [])
    except RuntimeError:
        return
    raise AssertionError("devia levantar")


@pytest.mark.parametrize(
    "desfecho", ["sucesso", "erro", "cancelado", "concluiu_ao_cancelar"]
)
@pytest.mark.parametrize("falha_no_transporte", [False, True])
def test_merge_espera_done_inclusive_depois_de_pedir_cancelamento(
    desfecho: str, falha_no_transporte: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.copia_bigquery as modulo

    segundos = 0
    consultas = 0
    falhou = False
    cancelamentos: list[int] = []
    referencia = {"projectId": "p", "jobId": "merge", "location": "r"}
    demora = desfecho in {"cancelado", "concluiu_ao_cancelar"}

    def esperar(tempo: float) -> None:
        nonlocal segundos
        segundos += 60

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        nonlocal consultas, falhou
        if "query" in corpo:
            return {"jobComplete": False, "jobReference": referencia}
        assert corpo["jobReference"] == referencia
        if (
            falha_no_transporte
            and not falhou
            and (corpo.get("cancelar") if demora else consultas == 1)
        ):
            falhou = True
            raise ConnectionError("resposta do BigQuery perdida")
        if corpo.get("cancelar"):
            cancelamentos.append(segundos)
            return {"job": {"status": {"state": "RUNNING"}}}
        consultas += 1
        if consultas < (8 if demora else 2):
            return {"status": {"state": "RUNNING"}}
        estado: dict[str, Any] = {"state": "DONE"}
        if desfecho in {"erro", "cancelado"}:
            estado["errorResult"] = {
                "reason": "stopped" if desfecho == "cancelado" else "invalidQuery"
            }
        return {"status": estado}

    monkeypatch.setattr(modulo, "monotonic", lambda: segundos, raising=False)
    monkeypatch.setattr(modulo, "sleep", esperar)
    copia = CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)

    if desfecho in {"erro", "cancelado"}:
        with pytest.raises(RuntimeError, match="stopped|invalidQuery"):
            copia.gravar("j1", [])
    else:
        copia.gravar("j1", [])

    assert consultas == (8 if demora else 2)
    assert cancelamentos == ([360 if falha_no_transporte else 300] if demora else [])


def test_merge_pede_cancelamento_mesmo_sem_conseguir_consultar_o_estado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.copia_bigquery as modulo

    segundos = 0
    consultas = 0
    cancelamentos: list[int] = []

    def esperar(tempo: float) -> None:
        nonlocal segundos
        segundos += 300

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        nonlocal consultas
        if "query" in corpo:
            return {
                "jobComplete": False,
                "jobReference": {"projectId": "p", "jobId": "merge", "location": "r"},
            }
        if corpo.get("cancelar"):
            cancelamentos.append(segundos)
            return {}
        consultas += 1
        if not cancelamentos and consultas < 4:
            raise ConnectionError("consulta do estado indisponível")
        return {"status": {"state": "DONE", "errorResult": {"reason": "stopped"}}}

    monkeypatch.setattr(modulo, "monotonic", lambda: segundos)
    monkeypatch.setattr(modulo, "sleep", esperar)
    with pytest.raises(RuntimeError, match="stopped"):
        CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte).gravar("j1", [])

    assert cancelamentos == [300]


@pytest.mark.parametrize("falha", ["nenhuma", "consulta", "cancelamento", "ambos"])
def test_merge_desiste_em_quinze_minutos_e_a_copia_fica_falhou(
    falha: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.copia_bigquery as modulo

    segundos = 0
    cancelamentos: list[int] = []

    def esperar(tempo: float) -> None:
        nonlocal segundos
        segundos += int(tempo)
        assert segundos <= 900, "o acompanhamento passou do teto total"

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        if "query" in corpo:
            return {
                "jobComplete": False,
                "jobReference": {"projectId": "p", "jobId": "merge"},
            }
        if corpo.get("cancelar"):
            cancelamentos.append(segundos)
            if falha in {"cancelamento", "ambos"}:
                raise ConnectionError("cancelamento não confirmado")
            return {}
        if falha in {"consulta", "ambos"}:
            raise ConnectionError("estado indisponível")
        return {"status": {"state": "RUNNING"}}

    monkeypatch.setattr(modulo, "monotonic", lambda: segundos)
    monkeypatch.setattr(modulo, "sleep", esperar)
    mundo = Mundo(copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte))

    mundo.reindexar()

    assert segundos == 900
    assert cancelamentos and cancelamentos[0] == 300
    atual = mundo.jobs.obter("j1")
    assert atual and atual.copia_bigquery
    assert atual.copia_bigquery.estado == "falhou"
    assert atual.copia_bigquery.anos == [2026]
    assert not atual.copia_bigquery.particoes_conhecidas
    assert atual.rodada_da_indexacao is None


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
    sem_identificacao = pessoa.model_copy(
        update={"id": "p4", "catalogo_id": "c4", "estado_do_nome": None}
    )
    decupagem = DECUPAGEM.model_copy(
        update={"pessoas": [pessoa, palpite, sem_catalogo, sem_identificacao]}
    )

    linhas = linhas_da_decupagem("j1", decupagem, "Exemplo", DIA, BASE)

    das_pessoas = {
        (x.tipo, x.inicio_ms, x.fim_ms, tuple(x.pessoas))
        for x in linhas
        if x.tipo in ("aparicao", "mencao_na_fala", "mencao_no_texto")
    }
    dona = PessoaDoMomento("c1")
    assert das_pessoas == {
        ("aparicao", 1000, 4000, (dona,)),
        ("mencao_na_fala", 5000, 6000, (dona,)),
        ("mencao_no_texto", 7000, 8000, (dona,)),
    }


def test_as_linhas_nao_levam_o_nome_da_pessoa() -> None:
    pessoa = Pessoa(
        id="p1",
        nome="Sabrina Sato",
        catalogo_id="c1",
        estado_do_nome="confirmado",
        na_imagem=[Aparicao(inicio_ms=1000, fim_ms=4000, evidencia="rosto")],
        citada_na_fala=[],
        citada_no_texto=[],
    )
    decupagem = DECUPAGEM.model_copy(update={"pessoas": [pessoa]})

    linhas = linhas_da_decupagem("j1", decupagem, "Exemplo", DIA, BASE)

    assert any(x.pessoas for x in linhas)
    assert "Sabrina" not in json.dumps([_json_da_linha(x) for x in linhas])
    assert all(p.nome == "" for x in linhas for p in x.pessoas)


@pytest.mark.parametrize("primeiro", ["carga", "indexacao"])
@pytest.mark.parametrize("demorada", [False, True])
def test_carga_e_indexacao_compartilham_a_vez_e_releem_o_job(
    primeiro: str, demorada: bool
) -> None:
    entrou, continuar = Event(), Event()
    consultas: list[dict[str, Any]] = []
    with sqlite3.connect(":memory:", check_same_thread=False) as banco:
        banco.execute("CREATE TABLE momentos (job_id TEXT, data_de_exibicao TEXT)")

        def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
            if "query" in corpo:
                consultas.append(corpo)
                if demorada and len(consultas) == 1:
                    return {
                        "jobComplete": False,
                        "jobReference": {
                            "projectId": "p",
                            "jobId": "merge",
                            "location": "r",
                        },
                    }
            else:
                assert corpo == {
                    "jobReference": {
                        "projectId": "p",
                        "jobId": "merge",
                        "location": "r",
                    }
                }
                corpo = consultas[0]
            if len(consultas) == 1:
                entrou.set()
                assert continuar.wait(10), "a primeira cópia não foi liberada"
            parametros = {
                p["name"]: p["parameterValue"]["value"]
                for p in corpo["queryParameters"]
            }
            predicado = (
                corpo["query"]
                .split("WHEN NOT MATCHED BY SOURCE AND ")[1]
                .split(" THEN DELETE")[0]
            )
            banco.execute(f"DELETE FROM momentos AS t WHERE {predicado}", parametros)
            banco.executemany(
                "INSERT INTO momentos VALUES (?, ?)",
                [
                    (l["job_id"], l["data_de_exibicao"])
                    for l in json.loads(parametros["linhas"])
                ],
            )
            return (
                {"status": {"state": "DONE"}}
                if demorada and len(consultas) == 1
                else {"jobComplete": True}
            )

        mundo = Mundo(
            copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
        )
        antigo = _job().model_copy(
            update={
                "copia_bigquery": CopiaNoBigQuery(
                    estado="copiado", em=BASE, anos=[2025], particoes_conhecidas=True
                ),
                "indexacao": Indexacao(estado="pendente", em=BASE),
                "versao_pedida": 4,
                "versao_indexada": 3,
            }
        )
        mundo.jobs.salvar(antigo)

        def carga() -> dict[str, str]:
            return copiar_jobs(
                None,
                mundo.jobs,
                mundo.armazenamento,
                mundo.correcoes,
                mundo.copia,
                indice=mundo.indice,
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(carga if primeiro == "carga" else mundo.reindexar)
            try:
                assert entrou.wait(10), "a primeira cópia não começou"
                atual = mundo.jobs.obter("j1")
                assert atual
                mundo.jobs.salvar(
                    atual.model_copy(update={"data_exibicao": date(2027, 1, 1)})
                )
                if primeiro == "carga":
                    assert (
                        mundo.corrigir_a_fala("aprovada durante a carga").status_code
                        == 201
                    )
                    assert mundo.aprovar_revisao().status_code == 202
                    mundo.reindexar()
                else:
                    assert carga() == {"j1": "ignorado"}
                assert len(consultas) == 1
            finally:
                continuar.set()
            futuro.result(timeout=10)

        atual = mundo.jobs.obter("j1")
        assert atual and atual.rodada_da_indexacao is None
        if primeiro == "carga":
            assert atual.versao_indexada == atual.versao_pedida
            assert atual.indexacao and atual.indexacao.estado == "indexado"
            assert mundo.textos_das_falas() == ["aprovada durante a carga"]
        assert banco.execute("SELECT * FROM momentos").fetchall() == [
            ("j1", "2027-01-01" if primeiro == "carga" else "2026-10-30")
        ] * len(_linhas())
        if primeiro == "carga":
            assert "@inicio_2026" in consultas[-1]["query"]
            assert "@inicio_2027" in consultas[-1]["query"]
        # O snapshot da listagem ficou velho enquanto esperava a vez.
        assert (
            copiar(
                antigo,
                mundo.jobs,
                mundo.armazenamento,
                mundo.correcoes,
                mundo.copia,
                indice=mundo.indice,
            )
            == "copiado"
        )
        assert banco.execute("SELECT * FROM momentos").fetchall() == [
            ("j1", "2027-01-01")
        ] * len(_linhas())
        if primeiro != "carga":
            assert "@inicio_2026" in consultas[-1]["query"]
        assert "@inicio_2027" in consultas[-1]["query"]


@pytest.mark.parametrize("escritor", ["carga", "indexacao"])
@pytest.mark.parametrize("gravacao", ["pendente", "sem_job", "ano"])
def test_falha_antes_do_merge_impede_a_copia(
    escritor: str, gravacao: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    copia = CopiaEmMemoria()
    mundo = Mundo(copia=copia)
    mundo.jobs.salvar(
        _job().model_copy(
            update={
                "copia_bigquery": CopiaNoBigQuery(
                    estado="copiado", em=BASE, anos=[2025], particoes_conhecidas=True
                )
            }
        )
    )
    trocar = mundo.jobs.trocar

    def gravar(job_id: str, mudar: Any) -> Job | None:
        def na_transacao(job: Job) -> dict[str, Any] | None:
            mudancas: dict[str, Any] | None = mudar(job)
            registro = (mudancas or {}).get("copia_bigquery")
            if registro and registro.estado == "pendente":
                if gravacao == "sem_job":
                    return None
                raise ConnectionError("Firestore caiu antes do MERGE")
            return mudancas

        return trocar(job_id, na_transacao)

    def acrescentar(job_id: str, ano: int) -> None:
        raise ConnectionError("ArrayUnion não foi gravado")

    if gravacao in {"pendente", "sem_job"}:
        monkeypatch.setattr(mundo.jobs, "trocar", gravar)
    else:
        monkeypatch.setattr(mundo.jobs, "acrescentar_ano_da_copia", acrescentar)
    if escritor == "carga":
        assert copiar_jobs(
            None,
            mundo.jobs,
            mundo.armazenamento,
            mundo.correcoes,
            copia,
            indice=mundo.indice,
        ) == {"j1": "falhou"}
    else:
        mundo.reindexar()
    assert copia.total() == 0
    atual = mundo.jobs.obter("j1")
    assert atual and atual.copia_bigquery
    assert atual.copia_bigquery.estado == "falhou"
    assert 2025 in atual.copia_bigquery.anos
    assert not atual.copia_bigquery.particoes_conhecidas
    assert atual.rodada_da_indexacao is None


@pytest.mark.parametrize("escritor", ["carga", "indexacao"])
@pytest.mark.parametrize("commit_depois", [False, True])
@pytest.mark.parametrize(
    "atraso", ["resposta_perdida", "vez_vencida", "pendente_velho", "final_velho"]
)
def test_todo_ano_com_linhas_permanece_no_conjunto_e_a_proxima_copia_limpa(
    escritor: str, commit_depois: bool, atraso: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agora = BASE
    consultas: list[dict[str, Any]] = []
    observacoes: list[tuple[set[int], set[int], bool]] = []
    atrasou = False
    with sqlite3.connect(":memory:") as banco:
        banco.execute("CREATE TABLE momentos (job_id TEXT, data_de_exibicao TEXT)")
        banco.execute("INSERT INTO momentos VALUES ('j1', '2025-01-01')")

        def observar() -> None:
            atual = mundo.jobs.obter("j1")
            assert atual and atual.copia_bigquery
            anos_das_linhas = {
                date.fromisoformat(d).year
                for (d,) in banco.execute("SELECT data_de_exibicao FROM momentos")
            }
            observacoes.append(
                (
                    anos_das_linhas,
                    set(atual.copia_bigquery.anos),
                    atual.copia_bigquery.particoes_conhecidas,
                )
            )

        def aplicar(corpo: dict[str, Any]) -> None:
            parametros = {
                p["name"]: p["parameterValue"]["value"]
                for p in corpo["queryParameters"]
            }
            predicado = (
                corpo["query"]
                .split("WHEN NOT MATCHED BY SOURCE AND ")[1]
                .split(" THEN DELETE")[0]
            )
            banco.execute(f"DELETE FROM momentos AS t WHERE {predicado}", parametros)
            banco.executemany(
                "INSERT INTO momentos VALUES (?, ?)",
                [
                    (l["job_id"], l["data_de_exibicao"])
                    for l in json.loads(parametros["linhas"])
                ],
            )
            observar()

        def executar() -> None:
            job = mundo.jobs.obter("j1")
            assert job
            if escritor == "carga":
                copiar(
                    job,
                    mundo.jobs,
                    mundo.armazenamento,
                    mundo.correcoes,
                    mundo.copia,
                    relogio=lambda: agora,
                    indice=mundo.indice,
                )
            else:
                reindexar(
                    job,
                    mundo.jobs,
                    mundo.armazenamento,
                    mundo.correcoes,
                    mundo.indice,
                    copia=mundo.copia,
                    relogio=lambda: agora,
                )
            observar()

        def copiar_a_nova_versao() -> None:
            nonlocal agora
            agora += PRAZO_DA_RODADA + timedelta(seconds=1)
            atual = mundo.jobs.obter("j1")
            assert atual
            mundo.jobs.salvar(
                atual.model_copy(update={"data_exibicao": date(2027, 1, 1)})
            )
            executar()

        def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
            consultas.append(corpo)
            if len(consultas) == 1:
                if atraso in {"resposta_perdida", "final_velho"}:
                    raise ConnectionError(
                        "resposta do POST perdida; MERGE ainda pode gravar"
                    )
                if atraso == "vez_vencida":
                    if not commit_depois:
                        aplicar(corpo)
                    copiar_a_nova_versao()
                    if commit_depois:
                        aplicar(corpo)
                    return {"jobComplete": True}
            aplicar(corpo)
            return {"jobComplete": True}

        mundo = Mundo(
            copia=CopiaBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
        )
        mundo.jobs.salvar(
            _job().model_copy(
                update={
                    "copia_bigquery": CopiaNoBigQuery(
                        estado="copiado",
                        em=BASE,
                        anos=[2025],
                        particoes_conhecidas=atraso
                        not in {"pendente_velho", "final_velho"},
                    ),
                }
            )
        )
        transitar, trocar = mundo.jobs.transitar, mundo.jobs.trocar

        def antes_de_gravar(mudancas: dict[str, Any] | None) -> None:
            nonlocal atrasou
            copia = (mudancas or {}).get("copia_bigquery")
            estado_atrasado = "pendente" if atraso == "pendente_velho" else "falhou"
            if (
                atraso in {"pendente_velho", "final_velho"}
                and copia
                and copia.estado == estado_atrasado
                and not atrasou
            ):
                atrasou = True
                copiar_a_nova_versao()

        def transitar_atrasado(
            job_id: str, de: Any, mudancas: dict[str, Any]
        ) -> Job | None:
            antes_de_gravar(mudancas)
            resultado = transitar(job_id, de, mudancas)
            observar()
            return resultado

        def trocar_atrasado(job_id: str, mudar: Any) -> Job | None:
            atual = mundo.jobs.obter(job_id)
            if atual:
                antes_de_gravar(mudar(atual))
            # Relê o Job, como ao repetir uma transação do Firestore sob disputa.
            resultado = trocar(job_id, mudar)
            observar()
            return resultado

        monkeypatch.setattr(mundo.jobs, "transitar", transitar_atrasado)
        monkeypatch.setattr(mundo.jobs, "trocar", trocar_atrasado)
        executar()
        if atraso == "resposta_perdida":
            if not commit_depois:
                aplicar(consultas[0])
            copiar_a_nova_versao()
            if commit_depois:
                aplicar(consultas[0])
        elif atraso == "final_velho":
            aplicar(consultas[0])
        executar()
        assert banco.execute("SELECT * FROM momentos").fetchall() == [
            ("j1", "2027-01-01")
        ] * len(_linhas())

    anteriores: set[int] = {2025}
    conhecidas = False
    perdeu_confianca = False
    for linhas, anos, conhecidas_agora in observacoes:
        assert linhas <= anos
        assert anteriores <= anos
        perdeu_confianca |= conhecidas and not conhecidas_agora
        anteriores, conhecidas = anos, conhecidas_agora
    assert perdeu_confianca is (atraso in {"vez_vencida", "final_velho"})
    assert conhecidas
