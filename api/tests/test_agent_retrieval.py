from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from api.agent_retrieval import (
    AgentRetrieval,
    ConfigDaBusca,
    CotaEsgotada,
    EsquemaIncompativel,
    JaExiste,
    apagar_colecao,
    conferir_esquema,
    criar_colecao,
    esperar,
    esquema_da_colecao,
    filtro_do_pedido,
    indices_da_colecao,
    pedido_de_busca,
    transporte_http,
)
from api.indice_da_busca import Consulta, Filtros, Registro

CONFIG = ConfigDaBusca(
    projeto="proj-x",
    regiao="reg-y",
    colecao="col-z",
    indice_da_descricao="ind-d",
    indice_do_quadro="ind-q",
    dimensao=256,
)


def test_config_vem_so_do_ambiente() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_INDICE_QUADRO": "q",
        "BUSCA_DIMENSAO": "128",
    }
    assert ConfigDaBusca.do_ambiente(ambiente) == ConfigDaBusca(
        "p", "r", "c", "d", "q", 128
    )
    with pytest.raises(KeyError):
        ConfigDaBusca.do_ambiente({})
    # Vazio desliga o índice do quadro-chave (ADR 0006).
    sem_quadro = ConfigDaBusca.do_ambiente(ambiente | {"BUSCA_INDICE_QUADRO": ""})
    assert sem_quadro.indice_do_quadro is None


@pytest.mark.parametrize(
    ("valor", "ligados"),
    [(None, True), ("", True), ("true", True), ("false", False), ("FALSE", False)],
)
def test_os_indices_ann_vem_do_ambiente_e_sem_a_variavel_ficam_ligados(
    valor: str | None, ligados: bool
) -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_INDICE_QUADRO": "q",
        "BUSCA_DIMENSAO": "128",
    }
    if valor is not None:
        ambiente["BUSCA_INDICES_LIGADOS"] = valor
    config = ConfigDaBusca.do_ambiente(ambiente)
    assert config.indices_ligados is ligados
    # Desligar os índices não desliga o vetor do quadro.
    assert config.indice_do_quadro == "q"


def test_valor_estranho_nos_indices_ann_levanta() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_INDICE_QUADRO": "q",
        "BUSCA_DIMENSAO": "128",
        "BUSCA_INDICES_LIGADOS": "0",
    }
    with pytest.raises(ValueError, match="BUSCA_INDICES_LIGADOS"):
        ConfigDaBusca.do_ambiente(ambiente)


SEM_QUADRO = ConfigDaBusca("proj-x", "reg-y", "col-z", "ind-d", None, 256)


def test_sem_o_indice_do_quadro_a_colecao_nasce_so_com_o_da_descricao() -> None:
    transporte = TransporteFalso({"name": "op", "done": True})
    criar_colecao(SEM_QUADRO, transporte, _nao_dorme)
    [(_, _, colecao), (_, c2, corpo2)] = transporte.chamadas
    assert c2.endswith("indexes?indexId=ind-d")
    assert corpo2 is not None and corpo2["indexField"] == "descricao_vetor"
    # O campo do vetor do quadro continua na coleção: ligar o índice depois não a recria.
    assert colecao is not None and "quadro_vetor" in colecao["vectorSchema"]


def test_sem_o_indice_do_quadro_a_busca_por_quadro_e_recusada() -> None:
    with pytest.raises(ValueError):
        pedido_de_busca(SEM_QUADRO, Consulta(texto="a", vetor_do_quadro=[0.0]))
    pedido = pedido_de_busca(SEM_QUADRO, Consulta(texto="a", significado="b"))
    assert set(_buscas(pedido)) == {"textSearch", "semanticSearch"}


def test_filtro_composto_junta_todos_os_campos_com_and() -> None:
    filtro = filtro_do_pedido(
        Filtros(tipo="objeto", categoria="roupa", cor_base="vermelho", dono="cat-1")
    )
    assert filtro == {
        "$and": [
            {"tipo": {"$eq": "objeto"}},
            {"categoria": {"$eq": "roupa"}},
            {"cor_base": {"$in": ["vermelho"]}},
            {"dono": {"$eq": "cat-1"}},
        ]
    }


def test_filtro_de_datas_e_pessoa() -> None:
    filtro = filtro_do_pedido(
        Filtros(
            pessoa="cat-1", exibido_desde=date(2026, 1, 2), exibido_ate=date(2026, 3, 4)
        )
    )
    assert filtro == {
        "$and": [
            {"pessoas": {"$in": ["cat-1"]}},
            {"data_de_exibicao": {"$gte": 20260102}},
            {"data_de_exibicao": {"$lte": 20260304}},
        ]
    }


def test_sem_filtros_nao_ha_filtro() -> None:
    assert filtro_do_pedido(Filtros()) is None


def _buscas(pedido: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {next(iter(b)): b[next(iter(b))] for b in pedido["searches"]}


def test_pedido_hibrido_leva_texto_significado_vetor_e_rrf() -> None:
    pedido = pedido_de_busca(
        CONFIG,
        Consulta(
            filtros=Filtros(tipo="plano"),
            texto="vestido vermelho",
            significado="mulher de vestido de gala",
            vetor_do_quadro=[0.1, 0.2],
            limite=7,
        ),
    )
    buscas = _buscas(pedido)
    assert set(buscas) == {"textSearch", "semanticSearch", "vectorSearch"}
    assert buscas["textSearch"]["structuredQuery"] == {
        "text": {"text": "vestido vermelho", "fields": ["texto_da_busca"]}
    }
    assert buscas["semanticSearch"]["searchText"] == "mulher de vestido de gala"
    assert buscas["semanticSearch"]["searchField"] == "descricao_vetor"
    assert buscas["vectorSearch"]["vector"] == {"values": [0.1, 0.2]}
    assert buscas["vectorSearch"]["searchField"] == "quadro_vetor"
    assert all(b["topK"] == 7 for b in buscas.values())
    assert all(b["outputFields"] == {"dataFields": ["*"]} for b in buscas.values())
    filtro = {"$and": [{"tipo": {"$eq": "plano"}}]}
    assert all(b["filter"] == filtro for b in buscas.values())
    assert pedido["combine"] == {
        "ranker": {"rrf": {"weights": [1.0, 1.0, 1.0]}},
        "topK": 7,
        "outputFields": {"dataFields": ["*"]},
    }


def test_toda_busca_por_vetor_leva_o_index_hint_do_indice_ann_do_seu_campo() -> None:
    pedido = pedido_de_busca(
        CONFIG,
        Consulta(
            texto="a",
            significado="b",
            vetor_do_quadro=[0.0],
            filtros=Filtros(tipo="fala"),
        ),
    )
    colecao = "projects/proj-x/locations/reg-y/collections/col-z"
    buscas = _buscas(pedido)
    for chave, indice in (("semanticSearch", "ind-d"), ("vectorSearch", "ind-q")):
        assert buscas[chave]["searchHint"] == {
            "indexHint": {
                "name": f"{colecao}/indexes/{indice}",
                "denseScannParams": {"targetRecall": 0.95},
            }
        }
    # A busca por texto não é KNN: não usa índice de vetor.
    assert "searchHint" not in buscas["textSearch"]


SEM_INDICES = replace(CONFIG, indices_ligados=False)


VETOR_DA_CONSULTA = [0.5, 0.25]


@pytest.mark.parametrize(
    "consulta",
    [
        Consulta(texto="a", significado="b", vetor_do_quadro=[0.0]),
        Consulta(significado="b", filtros=Filtros(tipo="fala")),
        Consulta(vetor_do_quadro=[0.0]),
        Consulta(texto="a", significado="b", cortar_significado=True),
    ],
)
def test_sem_os_indices_ann_toda_busca_por_vetor_vai_pelo_knn_em_cosseno(
    consulta: Consulta,
) -> None:
    pedido = pedido_de_busca(SEM_INDICES, consulta, VETOR_DA_CONSULTA)
    assert "indexHint" not in str(pedido) and "targetRecall" not in str(pedido)
    assert "semanticSearch" not in str(pedido)
    buscas = [b for b in pedido["searches"] if "textSearch" not in b]
    assert buscas
    for busca in buscas:
        [corpo] = busca.values()
        assert corpo["searchHint"] == {"knnHint": {}}
        assert corpo["distanceMetric"] == "COSINE_DISTANCE"
        assert corpo["topK"] == consulta.limite
    assert "searchHint" not in _buscas(pedido).get("textSearch", {})


def test_sem_os_indices_ann_o_significado_vai_como_vetor_da_consulta() -> None:
    pedido = pedido_de_busca(
        SEM_INDICES, Consulta(significado="vestido"), VETOR_DA_CONSULTA
    )
    assert _buscas(pedido)["vectorSearch"] == {
        "topK": 20,
        "outputFields": {"dataFields": ["*"]},
        "searchField": "descricao_vetor",
        "searchHint": {"knnHint": {}},
        "distanceMetric": "COSINE_DISTANCE",
        "vector": {"values": VETOR_DA_CONSULTA},
    }
    with pytest.raises(ValueError, match="vetor da consulta"):
        pedido_de_busca(SEM_INDICES, Consulta(significado="vestido"))


def test_sem_os_indices_ann_a_busca_por_quadro_continua_aceita() -> None:
    pedido = pedido_de_busca(SEM_INDICES, Consulta(vetor_do_quadro=[0.1, 0.2]))
    assert _buscas(pedido)["vectorSearch"] == {
        "topK": 20,
        "outputFields": {"dataFields": ["*"]},
        "searchField": "quadro_vetor",
        "searchHint": {"knnHint": {}},
        "distanceMetric": "COSINE_DISTANCE",
        "vector": {"values": [0.1, 0.2]},
    }


def test_sem_os_indices_ann_buscar_calcula_o_vetor_da_consulta_na_regiao_da_busca() -> (
    None
):
    transporte = TransporteFalso(
        {
            "predictions": [{"embeddings": {"values": [0.5] * 256}}],
            "results": [],
        }
    )
    AgentRetrieval(SEM_INDICES, transporte).buscar(
        Consulta(texto="vestido", significado="vestido")
    )
    [(_, url, corpo), (_, caminho, busca)] = transporte.chamadas
    assert url == (
        "https://reg-y-aiplatform.googleapis.com/v1/projects/proj-x/locations/reg-y/"
        "publishers/google/models/gemini-embedding-001:predict"
    )
    assert corpo == {
        "instances": [{"content": "vestido", "task_type": "RETRIEVAL_QUERY"}],
        "parameters": {"outputDimensionality": 256},
    }
    assert caminho.endswith("/dataObjects:batchSearch")
    assert busca is not None
    assert busca["searches"][1]["vectorSearch"]["vector"] == {"values": [0.5] * 256}


def test_com_os_indices_ann_buscar_nao_calcula_embedding() -> None:
    transporte = TransporteFalso({"results": []})
    AgentRetrieval(CONFIG, transporte).buscar(Consulta(significado="vestido"))
    [(_, caminho, _)] = transporte.chamadas
    assert caminho.endswith("/dataObjects:batchSearch")


def test_o_mesmo_texto_e_embutido_uma_vez_so() -> None:
    transporte = TransporteFalso(
        {"predictions": [{"embeddings": {"values": [0.5] * 256}}]}
    )
    adaptador = AgentRetrieval(SEM_INDICES, transporte)
    assert adaptador.vetor_da_consulta("a") == adaptador.vetor_da_consulta("a")
    adaptador.vetor_da_consulta("b")
    assert len(transporte.chamadas) == 2


def test_outra_thread_limpando_o_cache_no_meio_nao_derruba_a_busca() -> None:
    class Limpa(dict[str, list[float]]):
        """Outra thread chama `clear()` entre o `in` e a leitura."""

        def __contains__(self, chave: object) -> bool:
            self.clear()
            return True

    transporte = TransporteFalso(
        {"predictions": [{"embeddings": {"values": [0.5] * 256}}]}
    )
    adaptador = AgentRetrieval(SEM_INDICES, transporte)
    adaptador._vetores = Limpa()
    assert adaptador.vetor_da_consulta("a") == [0.5] * 256


def test_o_cache_do_embedding_guarda_no_maximo_256_textos() -> None:
    transporte = TransporteFalso(
        {"predictions": [{"embeddings": {"values": [0.5] * 256}}]}
    )
    adaptador = AgentRetrieval(SEM_INDICES, transporte)
    for n in range(256):
        adaptador.vetor_da_consulta(f"t{n}")
    adaptador.vetor_da_consulta("t0")  # ainda guardado: sem chamada nova
    assert len(transporte.chamadas) == 256
    adaptador.vetor_da_consulta("t256")  # passou do limite: o cache recomeça
    assert len(adaptador._vetores) == 1
    adaptador.vetor_da_consulta("t0")  # foi esquecido: chama de novo
    assert len(transporte.chamadas) == 258


def test_embedding_da_consulta_de_outra_dimensao_levanta() -> None:
    transporte = TransporteFalso({"predictions": [{"embeddings": {"values": [0.5]}}]})
    with pytest.raises(ValueError, match="dimensão"):
        AgentRetrieval(SEM_INDICES, transporte).vetor_da_consulta("x")


@pytest.mark.parametrize(
    ("config", "registros", "avisa"),
    [
        (SEM_INDICES, 80_001, True),
        (SEM_INDICES, 80_000, False),
        (CONFIG, 80_001, False),
    ],
)
def test_sem_os_indices_ann_gravar_avisa_perto_do_teto_do_knn(
    config: ConfigDaBusca,
    registros: int,
    avisa: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transporte = TransporteFalso({"aggregateResults": [{"count": registros}]})
    AgentRetrieval(config, transporte).gravar("j", [])
    avisos = [r for r in caplog.records if r.levelname == "WARNING"]
    assert bool(avisos) is avisa
    if avisa:
        assert "100 mil" in avisos[0].getMessage()


def test_falha_da_contagem_nao_derruba_a_gravacao() -> None:
    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        if caminho.endswith(":aggregate"):
            raise RuntimeError("fora do ar")
        return {}

    AgentRetrieval(SEM_INDICES, transporte).gravar("j", [])


def test_sem_os_indices_ann_a_colecao_nasce_sem_indice() -> None:
    assert indices_da_colecao(SEM_INDICES) == {}
    transporte = TransporteFalso({"name": "op", "done": True})
    criar_colecao(SEM_INDICES, transporte, _nao_dorme)
    [(metodo, caminho, _)] = transporte.chamadas
    assert (metodo, caminho) == (
        "POST",
        "projects/proj-x/locations/reg-y/collections?collectionId=col-z",
    )


def test_so_filtros_nao_e_busca() -> None:
    with pytest.raises(ValueError):
        pedido_de_busca(CONFIG, Consulta(filtros=Filtros(tipo="objeto", dono="c")))


def test_uma_busca_so_nao_leva_rrf() -> None:
    pedido = pedido_de_busca(CONFIG, Consulta(texto="vestido"))
    assert list(_buscas(pedido)) == ["textSearch"]
    assert "combine" not in pedido


def test_esquema_da_colecao_tem_a_dimensao_e_os_campos_de_filtro() -> None:
    esquema = esquema_da_colecao(CONFIG)
    vetores = esquema["vectorSchema"]
    assert vetores["quadro_vetor"]["denseVector"]["dimensions"] == 256
    assert vetores["descricao_vetor"]["denseVector"]["dimensions"] == 256
    embedding = vetores["descricao_vetor"]["denseVector"]["vertexEmbeddingConfig"]
    assert embedding["modelId"] and embedding["taskType"] == "RETRIEVAL_DOCUMENT"
    # O embedding automático recusa registro sem o campo do modelo ou com ele vazio.
    assert embedding["textTemplate"] == "{significado}"
    propriedades = esquema["dataSchema"]["properties"]
    assert propriedades["data_de_exibicao"] == {"type": "integer"}
    indices = indices_da_colecao(CONFIG)
    assert {i: c["indexField"] for i, c in indices.items()} == {
        "ind-d": "descricao_vetor",
        "ind-q": "quadro_vetor",
    }
    for corpo in indices.values():
        assert {"tipo", "cor_base", "dono", "categoria", "pessoas"} <= set(
            corpo["filterFields"]
        )
        assert set(corpo["filterFields"]) <= set(propriedades)
        # O significado só alimenta o embedding: não volta na busca.
        assert set(corpo["storeFields"]) == set(propriedades) - {"significado"}
        # Uma réplica só, explícita: o padrão do serviço é de 2 a 5, cobradas por hora.
        assert corpo["dedicatedInfrastructure"]["autoscalingSpec"] == {
            "minReplicaCount": 1,
            "maxReplicaCount": 1,
        }


class TransporteFalso:
    def __init__(self, resposta: dict[str, Any] | None = None) -> None:
        self.chamadas: list[tuple[str, str, dict[str, Any] | None]] = []
        self.resposta = resposta or {}

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        self.chamadas.append((metodo, caminho, corpo))
        return self.resposta


def test_buscar_devolve_os_registros_gravados() -> None:
    registro = Registro(
        id="j:objeto:0",
        tipo="objeto",
        job_id="j",
        inicio_ms=0,
        fim_ms=10,
        categoria="roupa",
        cor_base=["vermelho"],
        dono="c",
        data_de_exibicao=date(2026, 1, 2),
    )
    transporte = TransporteFalso()
    adaptador = AgentRetrieval(CONFIG, transporte)
    adaptador.gravar("j", [registro])
    [_, (metodo, caminho, corpo)] = transporte.chamadas  # a consulta do apagar, vazia
    assert (metodo, caminho.endswith("/dataObjects:batchCreate")) == ("POST", True)
    assert corpo is not None
    [pedido] = corpo["requests"]
    # O id do objeto começa por letra: o job_id (uuid em hex) pode começar por dígito.
    assert pedido["dataObjectId"] == "m-j-objeto-0"
    assert pedido["dataObject"]["data"]["cor_base"] == ["vermelho"]
    assert pedido["dataObject"]["data"]["data_de_exibicao"] == 20260102
    assert pedido["dataObject"]["data"]["significado"] == "objeto"

    transporte.resposta = {
        "results": [{"results": [{"dataObject": pedido["dataObject"]}]}]
    }
    [achado] = adaptador.buscar(Consulta(texto="vestido", filtros=Filtros(dono="c")))
    assert achado == registro


def test_o_registro_leva_a_copia_do_texto_sem_acento_nem_maiuscula() -> None:
    registro = Registro(
        id="j:fala:0",
        tipo="fala",
        job_id="j",
        inicio_ms=0,
        fim_ms=10,
        texto="A ANGÉLICA chegou",
        descricao="Promoção em São Paulo",
    )
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).gravar("j", [registro])
    corpo = transporte.chamadas[-1][2]
    assert corpo is not None
    dados = corpo["requests"][0]["dataObject"]["data"]
    assert dados["texto_da_busca"] == "a angelica chegou promocao em sao paulo"
    # A tela segue lendo o texto original.
    assert (dados["texto"], dados["descricao"]) == (
        "A ANGÉLICA chegou",
        "Promoção em São Paulo",
    )
    assert "texto_da_busca" in esquema_da_colecao(CONFIG)["dataSchema"]["properties"]


@pytest.mark.parametrize("consulta", ["Angelica", "ANGÉLICA", "angélica"])
def test_o_pedido_de_texto_vai_normalizado_ao_campo_normalizado(consulta: str) -> None:
    pedido = pedido_de_busca(CONFIG, Consulta(texto=consulta))
    assert _buscas(pedido)["textSearch"]["structuredQuery"] == {
        "text": {"text": "angelica", "fields": ["texto_da_busca"]}
    }


def test_gravar_apaga_antes_os_registros_do_video() -> None:
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).gravar("j", [])
    [(metodo, caminho, corpo)] = transporte.chamadas
    assert metodo == "POST"
    assert caminho.endswith("/dataObjects:query")
    assert corpo == {"filter": {"job_id": {"$eq": "j"}}, "pageSize": 1000}


def test_apagar_consulta_os_nomes_pagina_a_pagina_e_apaga_em_lote() -> None:
    nomes = [f"col/dataObjects/{n}" for n in range(3)]
    respostas = iter(
        [
            {"dataObjects": [{"name": n} for n in nomes[:2]], "nextPageToken": "p2"},
            {"dataObjects": [{"name": nomes[2]}]},
            {},
        ]
    )
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, _Sequencia(transporte, respostas)).apagar("j")
    [(_, c1, _), (_, _, corpo2), (_, c3, corpo3)] = transporte.chamadas
    colecao = "projects/proj-x/locations/reg-y/collections/col-z"
    assert c1 == f"{colecao}/dataObjects:query"
    assert corpo2 is not None and corpo2["pageToken"] == "p2"
    assert c3 == f"{colecao}/dataObjects:batchDelete"
    assert corpo3 == {"requests": [{"name": n} for n in nomes]}


def test_vetores_dos_planos_le_o_vetor_do_quadro_pagina_a_pagina() -> None:
    def plano(n: int, vetor: list[float] | None) -> dict[str, Any]:
        objeto: dict[str, Any] = {"data": {"id": f"j:plano:{n}"}}
        if vetor:
            objeto["vectors"] = {"quadro_vetor": {"dense": {"values": vetor}}}
        return objeto

    respostas = iter(
        [
            {
                "dataObjects": [plano(0, [1.0, 0.0]), plano(1, None)],
                "nextPageToken": "p",
            },
            {"dataObjects": [plano(2, [0.0, 1.0])]},
        ]
    )
    transporte = TransporteFalso()
    vetores = AgentRetrieval(
        CONFIG, _Sequencia(transporte, respostas)
    ).vetores_dos_planos("j")
    assert vetores == {0: [1.0, 0.0], 2: [0.0, 1.0]}
    [(_, _, corpo1), (_, _, corpo2)] = transporte.chamadas
    assert corpo1 is not None and corpo2 is not None
    assert corpo1["outputFields"]["vectorFields"] == ["quadro_vetor"]
    assert corpo2["pageToken"] == "p"


def test_total_soma_a_contagem_do_aggregate() -> None:
    transporte = TransporteFalso({"aggregateResults": [{"count": 16}]})
    assert AgentRetrieval(CONFIG, transporte).total() == 16
    [(_, caminho, corpo)] = transporte.chamadas
    assert caminho.endswith("/dataObjects:aggregate")
    assert corpo == {"aggregate": "COUNT"}


def _nao_dorme(_: float) -> None:
    pass


def test_criar_colecao_cria_a_colecao_e_um_indice_ann_por_vetor() -> None:
    transporte = TransporteFalso({"name": "op", "done": True})
    criar_colecao(CONFIG, transporte, _nao_dorme)
    [(m1, c1, corpo1), (m2, c2, corpo2), (m3, c3, corpo3)] = transporte.chamadas
    base = "projects/proj-x/locations/reg-y/collections"
    assert (m1, c1) == ("POST", f"{base}?collectionId=col-z")
    assert corpo1 is not None and corpo1["dataSchema"]["properties"]["dono"]
    assert (m2, c2) == ("POST", f"{base}/col-z/indexes?indexId=ind-d")
    assert (m3, c3) == ("POST", f"{base}/col-z/indexes?indexId=ind-q")
    assert corpo2 is not None and corpo2["indexField"] == "descricao_vetor"
    assert corpo3 is not None and corpo3["indexField"] == "quadro_vetor"
    assert "dono" in corpo2["filterFields"] and "dono" in corpo3["filterFields"]


def test_criar_colecao_espera_cada_operacao_antes_da_seguinte() -> None:
    respostas = iter(
        [
            {"name": "op-colecao", "done": False},
            {"name": "op-colecao", "done": True},
            {"name": "op-d"},
            {"name": "op-q", "done": True},
        ]
    )
    transporte = TransporteFalso()
    esperas: list[float] = []
    criar_colecao(CONFIG, _Sequencia(transporte, respostas), esperas.append)
    assert [(m, c.split("/")[-1]) for m, c, _ in transporte.chamadas] == [
        ("POST", "collections?collectionId=col-z"),
        ("GET", "op-colecao"),
        ("POST", "indexes?indexId=ind-d"),
        ("POST", "indexes?indexId=ind-q"),
    ]
    assert len(esperas) == 1


class _Sequencia:
    """Transporte que anota as chamadas e responde, em ordem, com `respostas`."""

    def __init__(self, falso: TransporteFalso, respostas: Any) -> None:
        self._falso = falso
        self._respostas = respostas

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        self._falso(metodo, caminho, corpo)
        resposta: dict[str, Any] = next(self._respostas)
        return resposta


def test_operacao_com_erro_levanta() -> None:
    with pytest.raises(RuntimeError):
        esperar({"name": "op", "done": True, "error": {"code": 3}}, TransporteFalso())


class _ColecaoNoAr:
    """Transporte de uma coleção que já existe, com o `dataSchema` dado: a criação dá 409."""

    def __init__(self, esquema: dict[str, Any]) -> None:
        self.esquema = esquema
        self.chamadas: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        self.chamadas.append((metodo, caminho, corpo))
        if metodo == "POST":
            raise JaExiste(caminho)
        if metodo == "PATCH":
            return {"name": "op-patch", "done": True}
        return {"dataSchema": self.esquema}

    def patches(self) -> list[dict[str, Any] | None]:
        return [c for m, _, c in self.chamadas if m == "PATCH"]


def _esquema_no_ar(**mudancas: Any) -> dict[str, Any]:
    """O esquema atual com as propriedades trocadas; `None` tira o campo."""
    esquema = esquema_da_colecao(CONFIG)["dataSchema"]
    propriedades = {**esquema["properties"], **mudancas}
    return {
        **esquema,
        "properties": {c: p for c, p in propriedades.items() if p is not None},
    }


def test_criar_colecao_igual_nao_recebe_patch_nem_pede_reindexar() -> None:
    transporte = _ColecaoNoAr(_esquema_no_ar())
    assert criar_colecao(CONFIG, transporte, _nao_dorme) == []
    assert transporte.patches() == []


def test_criar_colecao_que_ja_existe_acrescenta_o_campo_que_falta() -> None:
    transporte = _ColecaoNoAr(_esquema_no_ar(texto_da_busca=None))
    acrescentados = criar_colecao(CONFIG, transporte, _nao_dorme)
    assert acrescentados == ["texto_da_busca"]
    [(_, caminho, corpo)] = [c for c in transporte.chamadas if c[0] == "PATCH"]
    assert caminho == (
        "projects/proj-x/locations/reg-y/collections/col-z?updateMask=dataSchema"
    )
    assert corpo is not None
    propriedades = corpo["dataSchema"]["properties"]
    # O PATCH troca o esquema inteiro: leva o que já estava e o campo novo.
    assert propriedades == esquema_da_colecao(CONFIG)["dataSchema"]["properties"]
    assert propriedades["texto_da_busca"] == {"type": "string"}


def test_o_patch_preserva_o_que_mais_vier_no_esquema_no_ar() -> None:
    no_ar = _esquema_no_ar(texto_da_busca=None)
    no_ar["required"] = ["id"]
    transporte = _ColecaoNoAr(no_ar)
    criar_colecao(CONFIG, transporte, _nao_dorme)
    [corpo] = transporte.patches()
    assert corpo is not None and corpo["dataSchema"]["required"] == ["id"]


def test_campo_com_tipo_diferente_para_com_erro_nomeando_o_campo() -> None:
    transporte = _ColecaoNoAr(_esquema_no_ar(inicio_ms={"type": "string"}))
    with pytest.raises(EsquemaIncompativel, match="inicio_ms.*string.*integer"):
        criar_colecao(CONFIG, transporte, _nao_dorme)
    assert transporte.patches() == []


def test_campo_que_sobra_na_colecao_para_com_erro_nomeando_o_campo() -> None:
    transporte = _ColecaoNoAr(_esquema_no_ar(antigo={"type": "string"}))
    with pytest.raises(EsquemaIncompativel, match="antigo"):
        criar_colecao(CONFIG, transporte, _nao_dorme)
    assert transporte.patches() == []


def test_conferir_esquema_lista_os_campos_de_texto_que_faltam() -> None:
    assert conferir_esquema(CONFIG, _ColecaoNoAr(_esquema_no_ar())) == []
    sem_campo = _ColecaoNoAr(_esquema_no_ar(texto_da_busca=None))
    assert conferir_esquema(CONFIG, sem_campo) == ["texto_da_busca"]


def test_apagar_colecao_leva_os_indices_e_os_objetos_e_espera() -> None:
    transporte = TransporteFalso({"name": "op", "done": True})
    apagar_colecao(CONFIG, transporte, _nao_dorme)
    # Sem force, o DELETE só funciona com a coleção sem índices e sem objetos.
    assert transporte.chamadas == [
        ("DELETE", "projects/proj-x/locations/reg-y/collections/col-z?force=true", None)
    ]


def test_significado_e_a_descricao_ou_o_texto_do_registro() -> None:
    base: dict[str, Any] = {"id": "j:x:0", "job_id": "j", "inicio_ms": 0, "fim_ms": 1}
    plano = Registro(tipo="plano", descricao="estúdio", texto="t", **base)
    fala = Registro(tipo="fala", texto="boa noite", **base)
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).gravar("j", [plano, fala])
    corpo = transporte.chamadas[-1][2]
    assert corpo is not None
    assert [r["dataObject"]["data"]["significado"] for r in corpo["requests"]] == [
        "estúdio",
        "boa noite",
    ]


def _achado(id: str, texto: str, *distancias: tuple[int, float]) -> dict[str, Any]:
    """Um resultado fundido, com a distância de cada busca (índice, distância) que o achou."""
    return {
        "dataObject": {
            "data": {
                "id": id,
                "tipo": "fala",
                "job_id": "j",
                "inicio_ms": 0,
                "fim_ms": 1,
            }
            | {"texto": texto}
        },
        "searchResultMetadata": {
            "searchDistances": [
                {"searchIndex": i, "distance": d} for i, d in distancias
            ]
        },
    }


def test_so_do_significado_volta_o_que_esta_perto_e_tem_palavras_bastantes() -> None:
    # Medido no dev: "terno" achava "ok." a 0,30 e "Tchau," a 0,32 só pelo vetor.
    config = replace(CONFIG, distancia_maxima=0.25, palavras_minimas=3)
    transporte = TransporteFalso(
        {
            "results": [
                {
                    "results": [
                        _achado("pelo-texto", "terno", (0, 1.26), (1, 0.32)),
                        _achado("perto", "terno preto de alfaiataria", (1, 0.20)),
                        _achado("longe", "calça vinho estilo pantalona", (1, 0.30)),
                        _achado("curta", "ok.", (1, 0.10)),
                    ]
                }
            ]
        }
    )
    adaptador = AgentRetrieval(config, transporte)
    consulta = Consulta(texto="terno", significado="terno", cortar_significado=True)
    assert [r.id for r in adaptador.buscar(consulta)] == ["pelo-texto", "perto"]
    [(_, _, corpo)] = transporte.chamadas
    assert corpo is not None
    assert corpo["metadataOptions"] == {"searchSignalsEnabled": True}
    # Sem o pedido de corte (a cláusula de pessoa na imagem), volta tudo.
    sem_corte = replace(consulta, cortar_significado=False)
    assert len(adaptador.buscar(sem_corte)) == 4


def test_so_o_significado_tambem_e_cortado() -> None:
    config = replace(CONFIG, distancia_maxima=0.25, palavras_minimas=3)
    transporte = TransporteFalso(
        {
            "results": [
                {
                    "results": [
                        _achado("perto", "terno preto de alfaiataria", (0, 0.20)),
                        _achado("longe", "calça vinho estilo pantalona", (0, 0.30)),
                    ]
                }
            ]
        }
    )
    consulta = Consulta(significado="terno", cortar_significado=True)
    assert [r.id for r in AgentRetrieval(config, transporte).buscar(consulta)] == [
        "perto"
    ]


def test_corte_vem_do_ambiente_e_sem_ele_nao_ha_corte() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_INDICE_QUADRO": "q",
        "BUSCA_DIMENSAO": "128",
    }
    sem_corte = ConfigDaBusca.do_ambiente(ambiente)
    assert (sem_corte.distancia_maxima, sem_corte.palavras_minimas) == (None, 0)
    corte = ConfigDaBusca.do_ambiente(
        ambiente | {"BUSCA_DISTANCIA_MAXIMA": "0.25", "BUSCA_PALAVRAS_MINIMAS": "3"}
    )
    assert (corte.distancia_maxima, corte.palavras_minimas) == (0.25, 3)


def test_o_destaque_vai_ao_indice_e_volta_na_busca() -> None:
    base: dict[str, Any] = {"id": "j:x:0", "job_id": "j", "inicio_ms": 0, "fim_ms": 1}
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).gravar(
        "j", [Registro(tipo="objeto", destaque=3, texto="carro azul, veiculo", **base)]
    )
    corpo = transporte.chamadas[-1][2]
    assert corpo is not None
    dados = corpo["requests"][0]["dataObject"]["data"]
    assert dados["destaque"] == 3
    assert esquema_da_colecao(CONFIG)["dataSchema"]["properties"]["destaque"] == {
        "type": "integer"
    }
    transporte = TransporteFalso(
        {"results": [{"results": [{"dataObject": {"data": dados}}]}]}
    )
    [achado] = AgentRetrieval(CONFIG, transporte).buscar(Consulta(texto="carro"))
    assert achado.destaque == 3


def _registros(n: int) -> list[Registro]:
    return [
        Registro(id=f"j:fala:{i}", tipo="fala", job_id="j", inicio_ms=i, fim_ms=i + 1)
        for i in range(n)
    ]


class _Relogio:
    """Relógio falso: dormir avança o tempo, sem esperar de verdade."""

    def __init__(self) -> None:
        self.agora = 0.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.agora += segundos


def test_cota_de_escrita_vem_do_ambiente_e_sem_ela_nao_ha_ritmo() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_INDICE_QUADRO": "q",
        "BUSCA_DIMENSAO": "128",
    }
    assert ConfigDaBusca.do_ambiente(ambiente).cota_de_escrita is None
    # Vazia (o output do Terraform que o make ainda não acha): sem ritmo também.
    vazia = ambiente | {"BUSCA_COTA_DE_ESCRITA": ""}
    assert ConfigDaBusca.do_ambiente(vazia).cota_de_escrita is None
    com_cota = ambiente | {"BUSCA_COTA_DE_ESCRITA": "3000"}
    assert ConfigDaBusca.do_ambiente(com_cota).cota_de_escrita == 3000


def test_gravar_no_429_espera_e_reenvia_o_lote() -> None:
    relogio = _Relogio()
    transporte = TransporteFalso()
    lotes = 0

    def com_um_429(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        nonlocal lotes
        if caminho.endswith(":batchCreate"):
            lotes += 1
            if lotes == 1:
                raise CotaEsgotada(caminho)
        return transporte(metodo, caminho, corpo)

    AgentRetrieval(CONFIG, com_um_429, relogio.dormir, relogio).gravar(
        "j", _registros(3)
    )
    criados = [c for _, c, _ in transporte.chamadas if c.endswith(":batchCreate")]
    assert (lotes, len(criados)) == (2, 1)
    assert relogio.esperas and relogio.esperas[0] > 0


def test_esperas_no_429_crescem_e_cabem_no_timeout_do_job() -> None:
    relogio = _Relogio()

    def sempre_429(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        raise CotaEsgotada(caminho)

    with pytest.raises(CotaEsgotada):
        AgentRetrieval(CONFIG, sempre_429, relogio.dormir, relogio).apagar("j")
    esperas = relogio.esperas
    assert len(esperas) > 1
    assert esperas == sorted(esperas) and esperas[-1] > esperas[0]
    # O Job mam-indexacao tem 1800 s (infra/modulos/mam/main.tf); uma chamada não o come.
    assert sum(esperas) < 600


@pytest.mark.parametrize("operacao", [":query", ":batchDelete"])
def test_apagar_tambem_tenta_de_novo_no_429(operacao: str) -> None:
    relogio = _Relogio()
    respostas = {":query": {"dataObjects": [{"name": "n"}]}, ":batchDelete": {}}
    falhou = False

    def com_um_429(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        nonlocal falhou
        if caminho.endswith(operacao) and not falhou:
            falhou = True
            raise CotaEsgotada(caminho)
        return next(r for o, r in respostas.items() if caminho.endswith(o))

    AgentRetrieval(CONFIG, com_um_429, relogio.dormir, relogio).apagar("j")
    assert falhou and relogio.esperas


def test_a_busca_do_usuario_nao_espera_no_429() -> None:
    relogio = _Relogio()

    def sempre_429(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        raise CotaEsgotada(caminho)

    with pytest.raises(CotaEsgotada):
        AgentRetrieval(CONFIG, sempre_429, relogio.dormir, relogio).buscar(
            Consulta(texto="x")
        )
    assert relogio.esperas == []


def test_lote_repetido_que_volta_com_409_conta_como_gravado() -> None:
    relogio = _Relogio()
    lotes = 0

    def resposta_perdida(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        nonlocal lotes
        if caminho.endswith(":batchCreate"):
            lotes += 1
            if lotes == 1:
                raise CotaEsgotada(caminho)
            if lotes == 2:
                raise JaExiste(caminho)
        return {}

    AgentRetrieval(CONFIG, resposta_perdida, relogio.dormir, relogio).gravar(
        "j", _registros(250)
    )
    assert lotes == 3  # o segundo lote seguiu depois do 409 do primeiro


def _anota_os_lotes(relogio: _Relogio, envios: list[tuple[float, int]]) -> Any:
    def anota(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        if caminho.endswith(":batchCreate") and corpo is not None:
            envios.append((relogio.agora, len(corpo["requests"])))
        return {}

    return anota


def _nenhuma_janela_de_60_s_passa(envios: list[tuple[float, int]], cota: int) -> None:
    for inicio, _ in envios:
        assert sum(n for t, n in envios if inicio <= t < inicio + 60) <= cota


def test_ritmo_nenhuma_janela_de_60_s_passa_da_cota() -> None:
    relogio = _Relogio()
    envios: list[tuple[float, int]] = []
    config = replace(CONFIG, cota_de_escrita=3000)
    AgentRetrieval(
        config, _anota_os_lotes(relogio, envios), relogio.dormir, relogio
    ).gravar("j", _registros(5000))
    assert sum(n for _, n in envios) == 5000
    _nenhuma_janela_de_60_s_passa(envios, 3000)
    # Abaixo da cota, sem parar à toa: 25 lotes em menos de 2 minutos e meio.
    assert envios[-1][0] < 150


def test_ritmo_vale_entre_videos_gravados_no_mesmo_processo() -> None:
    relogio = _Relogio()
    envios: list[tuple[float, int]] = []
    indice = AgentRetrieval(
        replace(CONFIG, cota_de_escrita=3000),
        _anota_os_lotes(relogio, envios),
        relogio.dormir,
        relogio,
    )
    indice.gravar("a", _registros(2000))
    indice.gravar("b", _registros(2000))
    _nenhuma_janela_de_60_s_passa(envios, 3000)


def test_transporte_http_levanta_cota_esgotada_no_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Resposta:
        status_code = 429
        ok = False
        text = "RESOURCE_EXHAUSTED"

    class Sessao:
        def __init__(self, _: object) -> None: ...

        def request(self, *_: object, **__: object) -> Resposta:
            return Resposta()

    monkeypatch.setattr("google.auth.default", lambda scopes: (None, None))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Sessao)
    with pytest.raises(CotaEsgotada, match="429"):
        transporte_http()("POST", "x:batchCreate", {})
