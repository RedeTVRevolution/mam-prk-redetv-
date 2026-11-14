import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from api.agent_retrieval import (
    CAMPOS_DE_FILTRO,
    CAMPOS_DO_REGISTRO,
    CONEXOES_AO_INDICE,
    FRACAO_DA_COTA,
    AgentRetrieval,
    ConfigDaBusca,
    CotaEsgotada,
    EsquemaIncompativel,
    JaExiste,
    _criacao,
    _fundir_por_rrf,
    _registro,
    apagar_colecao,
    aquecer_o_indice,
    conferir_esquema,
    criar_colecao,
    esperar,
    esquema_da_colecao,
    filtro_do_pedido,
    indices_com_filtros_diferentes,
    indices_da_colecao,
    montar_plano,
    pedido_de_busca,
    transporte_http,
)
from api.busca import TETO_DE_CONSULTAS_AO_INDICE
from api.indice_da_busca import Consulta, Filtros, Registro
from api.orcamento_de_escrita import reservar_na_janela

CONFIG = ConfigDaBusca(
    projeto="proj-x",
    regiao="reg-y",
    colecao="col-z",
    indice_da_descricao="ind-d",
    dimensao=256,
    colecao_de_texto="col-texto",
)


def test_config_vem_so_do_ambiente() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_COLECAO_DE_TEXTO": "ct",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_DIMENSAO": "128",
    }
    assert ConfigDaBusca.do_ambiente(ambiente) == ConfigDaBusca(
        "p", "r", "c", "d", 128, "ct"
    )
    del ambiente["BUSCA_COLECAO_DE_TEXTO"]
    with pytest.raises(KeyError, match="BUSCA_COLECAO_DE_TEXTO"):
        ConfigDaBusca.do_ambiente(ambiente)
    with pytest.raises(KeyError):
        ConfigDaBusca.do_ambiente({})


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
        "BUSCA_COLECAO_DE_TEXTO": "ct",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_DIMENSAO": "128",
    }
    if valor is not None:
        ambiente["BUSCA_INDICES_LIGADOS"] = valor
    config = ConfigDaBusca.do_ambiente(ambiente)
    assert config.indices_ligados is ligados


def test_valor_estranho_nos_indices_ann_levanta() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_COLECAO_DE_TEXTO": "ct",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_DIMENSAO": "128",
        "BUSCA_INDICES_LIGADOS": "0",
    }
    with pytest.raises(ValueError, match="BUSCA_INDICES_LIGADOS"):
        ConfigDaBusca.do_ambiente(ambiente)


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


def test_pedido_hibrido_leva_texto_significado_e_rrf() -> None:
    pedido = pedido_de_busca(
        CONFIG,
        Consulta(
            filtros=Filtros(tipo="plano"),
            texto="vestido vermelho",
            significado="mulher de vestido de gala",
            limite=7,
        ),
    )
    buscas = _buscas(pedido)
    assert set(buscas) == {"textSearch", "semanticSearch"}
    assert buscas["textSearch"]["structuredQuery"] == {
        "text": {"text": "vestido vermelho", "fields": ["texto_da_busca"]}
    }
    assert buscas["semanticSearch"]["searchText"] == "mulher de vestido de gala"
    assert buscas["semanticSearch"]["searchField"] == "descricao_vetor"
    assert all(b["topK"] == 7 for b in buscas.values())
    assert all(
        b["outputFields"] == {"dataFields": CAMPOS_DO_REGISTRO} for b in buscas.values()
    )
    filtro = {"$and": [{"tipo": {"$eq": "plano"}}]}
    assert all(b["filter"] == filtro for b in buscas.values())
    assert pedido["combine"] == {
        "ranker": {"rrf": {"weights": [1.0, 1.0]}},
        "topK": 7,
        "outputFields": {"dataFields": CAMPOS_DO_REGISTRO},
    }


def test_a_busca_por_significado_leva_o_index_hint_do_indice_ann_da_descricao() -> None:
    pedido = pedido_de_busca(
        CONFIG,
        Consulta(
            texto="a",
            significado="b",
            filtros=Filtros(tipo="fala"),
        ),
    )
    colecao = "projects/proj-x/locations/reg-y/collections/col-z"
    buscas = _buscas(pedido)
    assert buscas["semanticSearch"]["searchHint"] == {
        "indexHint": {
            "name": f"{colecao}/indexes/ind-d",
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
        Consulta(texto="a", significado="b"),
        Consulta(significado="b", filtros=Filtros(tipo="fala")),
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
        "outputFields": {"dataFields": CAMPOS_DO_REGISTRO},
        "searchField": "descricao_vetor",
        "searchHint": {"knnHint": {}},
        "distanceMetric": "COSINE_DISTANCE",
        "vector": {"values": VETOR_DA_CONSULTA},
    }
    with pytest.raises(ValueError, match="vetor da consulta"):
        pedido_de_busca(SEM_INDICES, Consulta(significado="vestido"))


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
        Consulta(texto="vestido", significado="vestido", filtros=Filtros(tipo="plano"))
    )
    [(_, url, corpo), *buscas] = transporte.chamadas
    assert url == (
        "https://reg-y-aiplatform.googleapis.com/v1/projects/proj-x/locations/reg-y/"
        "publishers/google/models/gemini-embedding-001:predict"
    )
    assert corpo == {
        "instances": [{"content": "vestido", "task_type": "RETRIEVAL_QUERY"}],
        "parameters": {"outputDimensionality": 256},
    }
    # Dois pedidos (#568): o do texto e o do significado, com o vetor da consulta.
    assert all(c.endswith("/dataObjects:batchSearch") for _, c, _ in buscas)
    # Os pedidos vão em threads: a ordem de chegada não é fixa.
    corpos = sorted(
        (b["searches"][0] for _, _, b in buscas if b is not None),
        key=lambda c: next(iter(c)),
    )
    assert [next(iter(c)) for c in corpos] == ["textSearch", "vectorSearch"]
    assert corpos[1]["vectorSearch"]["vector"] == {"values": [0.5] * 256}


def test_o_mesmo_texto_e_embutido_uma_vez_so() -> None:
    transporte = TransporteFalso(
        {"predictions": [{"embeddings": {"values": [0.5] * 256}}]}
    )
    adaptador = AgentRetrieval(SEM_INDICES, transporte)
    assert adaptador.vetor_da_consulta("a") == adaptador.vetor_da_consulta("a")
    adaptador.vetor_da_consulta("b")
    assert len(transporte.chamadas) == 2


def test_duas_clausulas_juntas_com_o_mesmo_texto_embutem_uma_vez_so() -> None:
    entrou = threading.Event()
    solta = threading.Event()

    class TransporteLento(TransporteFalso):
        def __call__(
            self, metodo: str, caminho: str, corpo: dict[str, Any] | None
        ) -> dict[str, Any]:
            entrou.set()
            solta.wait(timeout=5)
            return super().__call__(metodo, caminho, corpo)

    transporte = TransporteLento(
        {"predictions": [{"embeddings": {"values": [0.5] * 256}}]}
    )
    adaptador = AgentRetrieval(SEM_INDICES, transporte)
    vetores: list[list[float]] = []
    primeira = threading.Thread(
        target=lambda: vetores.append(adaptador.vetor_da_consulta("a"))
    )
    segunda = threading.Thread(
        target=lambda: vetores.append(adaptador.vetor_da_consulta("a"))
    )
    primeira.start()
    assert entrou.wait(timeout=5)
    segunda.start()
    segunda.join(timeout=0.1)  # a segunda chega e espera a primeira
    solta.set()
    primeira.join(timeout=5)
    segunda.join(timeout=5)
    assert vetores == [[0.5] * 256] * 2
    assert len(transporte.chamadas) == 1
    assert adaptador._embutindo == {}


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
    [(metodo, caminho, _), (_, texto, esquema)] = transporte.chamadas
    assert texto.endswith("collectionId=col-texto")
    assert esquema is not None and "vectorSchema" not in esquema
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
    assert "quadro_vetor" not in vetores
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
        texto="vestido",
        cor_base=["vermelho"],
        dono="c",
        data_de_exibicao=date(2026, 1, 2),
    )
    transporte = TransporteFalso()
    adaptador = AgentRetrieval(CONFIG, transporte)
    adaptador.gravar("j", [registro])
    [_, _, (metodo, caminho, corpo)] = transporte.chamadas
    assert (metodo, caminho.endswith("/dataObjects:batchCreate")) == ("POST", True)
    assert corpo is not None
    [pedido] = corpo["requests"]
    # O id do objeto começa por letra: o job_id (uuid em hex) pode começar por dígito.
    assert pedido["dataObjectId"] == "m-j-objeto-0"
    assert pedido["dataObject"]["data"]["cor_base"] == ["vermelho"]
    assert pedido["dataObject"]["data"]["data_de_exibicao"] == 20260102
    assert "significado" not in pedido["dataObject"]["data"]

    # O índice devolve só os campos pedidos: o Registro volta inteiro mesmo assim.
    gravado = pedido["dataObject"]["data"]
    data = {c: v for c, v in gravado.items() if c in CAMPOS_DO_REGISTRO}
    assert data != gravado
    transporte.resposta = {"results": [{"results": [{"dataObject": {"data": data}}]}]}
    [achado] = adaptador.buscar(
        Consulta(texto="vestido", filtros=Filtros(tipo="objeto", dono="c"))
    )
    assert achado == registro


def test_a_consulta_pede_so_os_campos_do_registro_e_nunca_todos() -> None:
    pedido = pedido_de_busca(CONFIG, Consulta(texto="vestido", significado="gala"))
    campos = [b["outputFields"]["dataFields"] for b in _buscas(pedido).values()]
    campos.append(pedido["combine"]["outputFields"]["dataFields"])
    assert all(c == CAMPOS_DO_REGISTRO for c in campos)
    assert "*" not in CAMPOS_DO_REGISTRO
    assert not {"significado", "texto_da_busca"} & set(CAMPOS_DO_REGISTRO)


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


@pytest.mark.parametrize(
    "consulta, esperado",
    [
        ("(CARRO OR carros)", "(carro OR carros)"),
        ("(MÃE OR MÃES) (PAI OR PAIS)", "(mae OR maes) (pai OR pais)"),
        ("  Angélica,\tSATO  ", "angelica, sato"),
        ("(CARRO or carros)", "(carro or carros)"),
    ],
)
def test_normaliza_os_termos_preservando_or_exato_e_parenteses(
    consulta: str, esperado: str
) -> None:
    pedido = pedido_de_busca(CONFIG, Consulta(texto=consulta))
    assert _buscas(pedido)["textSearch"]["structuredQuery"]["text"]["text"] == esperado


def test_gravar_comeca_lendo_o_indice_do_video() -> None:
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).gravar("j", [])
    [(metodo, caminho, corpo), (_, texto, _)] = transporte.chamadas
    assert "/col-texto/" in texto
    assert metodo == "POST"
    assert caminho.endswith("/dataObjects:query")
    assert corpo is not None and corpo["filter"] == {"job_id": {"$eq": "j"}}


def test_apagar_consulta_os_nomes_pagina_a_pagina_e_apaga_em_lote() -> None:
    nomes = [f"col/dataObjects/{n}" for n in range(3)]
    respostas = iter(
        [
            {"dataObjects": [{"name": n} for n in nomes[:2]], "nextPageToken": "p2"},
            {"dataObjects": [{"name": nomes[2]}]},
            {},
            {},
        ]
    )
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, _Sequencia(transporte, respostas)).apagar("j")
    [(_, c1, _), (_, _, corpo2), (_, c3, corpo3), (_, texto, _)] = transporte.chamadas
    colecao = "projects/proj-x/locations/reg-y/collections/col-z"
    assert "/col-texto/" in texto
    assert c1 == f"{colecao}/dataObjects:query"
    assert corpo2 is not None and corpo2["pageToken"] == "p2"
    assert c3 == f"{colecao}/dataObjects:batchDelete"
    assert corpo3 == {"requests": [{"name": n} for n in nomes]}


def test_total_soma_a_contagem_do_aggregate() -> None:
    transporte = TransporteFalso({"aggregateResults": [{"count": 16}]})
    assert AgentRetrieval(CONFIG, transporte).total() == 16
    [(_, caminho, corpo)] = transporte.chamadas
    assert caminho.endswith("/dataObjects:aggregate")
    assert corpo == {"aggregate": "COUNT"}


def _nao_dorme(_: float) -> None:
    pass


def test_criar_colecao_cria_a_colecao_e_so_o_indice_ann_da_descricao() -> None:
    transporte = TransporteFalso({"name": "op", "done": True})
    criar_colecao(CONFIG, transporte, _nao_dorme)
    [(m1, c1, corpo1), (m2, c2, corpo2), (_, texto, _)] = transporte.chamadas
    base = "projects/proj-x/locations/reg-y/collections"
    assert texto.endswith("collectionId=col-texto")
    assert (m1, c1) == ("POST", f"{base}?collectionId=col-z")
    assert corpo1 is not None and corpo1["dataSchema"]["properties"]["dono"]
    assert (m2, c2) == ("POST", f"{base}/col-z/indexes?indexId=ind-d")
    assert corpo2 is not None and corpo2["indexField"] == "descricao_vetor"
    assert "dono" in corpo2["filterFields"]


def test_criar_colecao_espera_cada_operacao_antes_da_seguinte() -> None:
    respostas = iter(
        [
            {"name": "op-colecao", "done": False},
            {"name": "op-colecao", "done": True},
            {"name": "op-d", "done": True},
            {"name": "op-texto", "done": True},
        ]
    )
    transporte = TransporteFalso()
    esperas: list[float] = []
    criar_colecao(CONFIG, _Sequencia(transporte, respostas), esperas.append)
    assert [(m, c.split("/")[-1]) for m, c, _ in transporte.chamadas] == [
        ("POST", "collections?collectionId=col-z"),
        ("GET", "op-colecao"),
        ("POST", "indexes?indexId=ind-d"),
        ("POST", "collections?collectionId=col-texto"),
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
        if "/col-texto" in caminho:
            assert CONFIG.colecao_de_texto is not None
            return esquema_da_colecao(replace(CONFIG, colecao=CONFIG.colecao_de_texto))
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


def test_apagar_colecao_esvazia_antes_do_delete_e_espera() -> None:
    nome = f"{CONFIG.caminho_da_colecao}/dataObjects/m-exemplo"
    respostas = iter(
        [
            {"dataObjects": [{"name": nome}], "nextPageToken": "p2"},
            {},
            {},
            {"name": "op", "done": True},
        ]
    )
    transporte = TransporteFalso()
    apagar_colecao(CONFIG, _Sequencia(transporte, respostas), _nao_dorme)
    assert [m for m, _, _ in transporte.chamadas] == ["POST", "POST", "POST", "DELETE"]
    assert transporte.chamadas[1][2] == {"pageSize": 1000, "pageToken": "p2"}
    assert transporte.chamadas[2][2] == {"requests": [{"name": nome}]}
    assert transporte.chamadas[3][1] == f"{CONFIG.caminho_da_colecao}?force=true"


def test_significado_e_a_descricao_ou_o_texto_do_plano() -> None:
    registros = [
        _reg("j:p0", "plano", descricao="estúdio", texto="t"),
        _reg("j:p1", "plano", texto="boa noite"),
        _reg("j:p2", "plano"),
    ]
    assert [_lido(r)["significado"] for r in registros] == [
        "estúdio",
        "boa noite",
        "plano",
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


def _por_busca(
    do_texto: list[dict[str, Any]], do_significado: list[dict[str, Any]]
) -> tuple[Callable[..., Any], list[dict[str, Any]]]:
    """Um transporte que responde cada `batchSearch` de uma busca só (#568): a lista do texto
    ao pedido de texto e a do significado ao de significado. Devolve também os corpos."""
    corpos: list[dict[str, Any]] = []

    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        if caminho.endswith(":predict"):  # o vetor da consulta, para o cache
            return {"predictions": [{"embeddings": {"values": [0.1] * 256}}]}
        corpos.append(corpo)
        [busca] = corpo["searches"]
        achados = do_texto if "textSearch" in busca else do_significado
        return {"results": [{"results": achados}]}

    return transporte, corpos


def test_so_do_significado_volta_o_que_esta_perto_e_tem_palavras_bastantes() -> None:
    # Medido no dev: "terno" achava "ok." a 0,30 e "Tchau," a 0,32 só pelo vetor.
    config = replace(CONFIG, distancia_maxima=0.25, palavras_minimas=3)
    transporte, corpos = _por_busca(
        [_achado("pelo-texto", "terno")],
        [
            _achado("pelo-texto", "terno", (0, 0.32)),
            _achado("perto", "terno preto de alfaiataria", (0, 0.20)),
            _achado("longe", "calça vinho estilo pantalona", (0, 0.30)),
            _achado("curta", "ok.", (0, 0.10)),
        ],
    )
    adaptador = AgentRetrieval(config, transporte)
    consulta = Consulta(
        texto="terno",
        significado="terno",
        cortar_significado=True,
        filtros=Filtros(tipo="plano"),
    )
    # O achado pelo texto escapa do corte (a distância dele é a de outra busca).
    assert [r.id for r in adaptador.buscar(consulta)] == ["pelo-texto", "perto"]
    # Os pedidos vão em threads: a ordem de chegada não é fixa.
    [do_texto, do_significado] = sorted(
        corpos, key=lambda c: "textSearch" not in c["searches"][0]
    )
    # Só o pedido do significado pede os sinais; nenhum leva `combine`.
    assert "metadataOptions" not in do_texto
    assert do_significado["metadataOptions"] == {"searchSignalsEnabled": True}
    assert "combine" not in do_texto and "combine" not in do_significado
    # Sem o pedido de corte (a cláusula de pessoa na imagem), volta tudo.
    sem_corte = replace(consulta, cortar_significado=False)
    assert len(adaptador.buscar(sem_corte)) == 4
    assert all("metadataOptions" not in c for c in corpos[2:])


def test_corte_do_significado_sem_distancia_ou_so_no_texto() -> None:
    # Sem sinais na resposta, a distância cai no campo `distance`; sem nenhum dos dois, e
    # com corte configurado, o resultado só do significado não passa.
    config = replace(CONFIG, distancia_maxima=0.25, palavras_minimas=1)
    com_campo = _achado("campo", "plano perto")
    com_campo["distance"] = 0.1
    transporte, _ = _por_busca(
        [_achado("so-texto", "palavra")],
        [com_campo, _achado("sem-distancia", "plano sem distância")],
    )
    consulta = Consulta(texto="x", significado="y", cortar_significado=True)
    ids = [r.id for r in AgentRetrieval(config, transporte).buscar(consulta)]
    assert set(ids) == {"so-texto", "campo"}


def test_texto_e_significado_vao_em_dois_pedidos_ao_mesmo_tempo() -> None:
    barreira = threading.Barrier(2)

    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        if caminho.endswith(":predict"):
            return {"predictions": [{"embeddings": {"values": [0.1] * 256}}]}
        barreira.wait(timeout=2)  # falha se um esperar o outro terminar
        return {"results": [{"results": []}]}

    AgentRetrieval(CONFIG, transporte).buscar(
        Consulta(texto="a", significado="b", filtros=Filtros(tipo="plano"), limite=9)
    )


def test_pedidos_separados_levam_o_limite_o_filtro_e_o_indice_de_antes() -> None:
    transporte, corpos = _por_busca([], [])
    consulta = Consulta(
        texto="a", significado="b", filtros=Filtros(tipo="plano"), limite=9
    )
    AgentRetrieval(CONFIG, transporte).buscar(consulta)
    esperado = pedido_de_busca(CONFIG, consulta)["searches"]
    assert sorted(
        (c["searches"][0] for c in corpos), key=lambda b: next(iter(b))
    ) == sorted(esperado, key=lambda b: next(iter(b)))
    assert all(next(iter(c["searches"][0].values()))["topK"] == 9 for c in corpos)


def _ids(*ids: str) -> list[tuple[Registro, dict[str, Any]]]:
    return [(_reg(i, "plano"), {}) for i in ids]


def test_rrf_e_a_soma_de_1_sobre_60_mais_a_posicao_comecando_em_1() -> None:
    texto = _ids("a", "b", "c")
    significado = _ids("c", "d")
    fundido = _fundir_por_rrf(texto, significado, 10)
    # c: 1/63 + 1/61; a: 1/61; b e d: 1/62 (b só no texto, d só no significado; d antes).
    assert [r.id for r, _ in fundido] == ["c", "a", "d", "b"]
    # O limite corta depois da fusão.
    assert [r.id for r, _ in _fundir_por_rrf(texto, significado, 2)] == ["c", "a"]


def test_rrf_empate_fica_na_ordem_do_significado_e_depois_do_texto() -> None:
    # a e b: nota igual (texto 1 / significado 2, e texto 2 / significado 1).
    assert [r.id for r, _ in _fundir_por_rrf(_ids("a", "b"), _ids("b", "a"), 9)] == [
        "b",
        "a",
    ]
    # Só no texto na posição 1 e só no significado na posição 1: nota igual, e quem tem
    # posição no significado vem antes.
    assert [r.id for r, _ in _fundir_por_rrf(_ids("t"), _ids("s"), 9)] == ["s", "t"]
    # Repetível: a mesma entrada dá sempre a mesma ordem.
    entradas = (_ids("a", "b", "c", "d"), _ids("d", "c", "b", "a"))
    assert _fundir_por_rrf(*entradas, 9) == _fundir_por_rrf(*entradas, 9)


def test_rrf_guarda_o_resultado_do_significado_que_traz_a_distancia() -> None:
    do_texto = [(_reg("a", "plano"), {"origem": "texto"})]
    do_significado = [(_reg("a", "plano"), {"origem": "significado"})]
    [(_, cru)] = _fundir_por_rrf(do_texto, do_significado, 5)
    assert cru == {"origem": "significado"}
    [(_, so_texto)] = _fundir_por_rrf(do_texto, [], 5)
    assert so_texto == {"origem": "texto"}


def test_buscar_funde_as_duas_respostas_por_rrf_e_corta_no_limite() -> None:
    transporte, _ = _por_busca(
        [_achado("a", "um"), _achado("b", "dois"), _achado("c", "tres")],
        [_achado("c", "tres"), _achado("b", "dois"), _achado("d", "quatro")],
    )
    consulta = Consulta(texto="x", significado="y", filtros=Filtros(tipo="plano"))
    # c: 1/63+1/61 = 0,03227; b: 2/62 = 0,03226; a: 1/61; d: 1/63.
    assert [r.id for r in AgentRetrieval(CONFIG, transporte).buscar(consulta)] == [
        "c",
        "b",
        "a",
        "d",
    ]
    assert (
        len(AgentRetrieval(CONFIG, transporte).buscar(replace(consulta, limite=2))) == 2
    )


def test_pedido_com_uma_busca_so_vai_em_um_pedido() -> None:
    transporte, corpos = _por_busca([_achado("a", "um")], [])
    AgentRetrieval(CONFIG, transporte).buscar(
        Consulta(texto="x", filtros=Filtros(tipo="plano"))
    )
    assert len(corpos) == 1 and len(corpos[0]["searches"]) == 1


def test_o_pool_do_indice_cobre_o_pico_de_pedidos_simultaneos() -> None:
    # Pico: `TETO_DE_CONSULTAS_AO_INDICE` consultas juntas, cada uma com 2 pedidos nos
    # planos e 1 na coleção de texto.
    assert CONEXOES_AO_INDICE == TETO_DE_CONSULTAS_AO_INDICE * (2 + 1) == 24
    assert CONEXOES_AO_INDICE > 10  # o padrão do requests


def test_transporte_http_monta_o_pool_do_indice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import requests

    sessoes: list[requests.Session] = []

    class Sessao(requests.Session):
        def __init__(self, _: object) -> None:
            super().__init__()
            sessoes.append(self)

    monkeypatch.setattr("google.auth.default", lambda scopes: (None, None))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Sessao)
    chamada = transporte_http()
    [sessao] = sessoes
    adaptador = sessao.get_adapter("https://vectorsearch.googleapis.com/v1beta/x")
    assert adaptador._pool_maxsize == CONEXOES_AO_INDICE  # type: ignore[attr-defined]
    assert chamada is not None


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
        "BUSCA_COLECAO_DE_TEXTO": "ct",
        "BUSCA_INDICE_DESCRICAO": "d",
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
    [achado] = AgentRetrieval(CONFIG, transporte).buscar(
        Consulta(texto="carro", filtros=Filtros(tipo="objeto"))
    )
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


def _indice(
    transporte: Any,
    relogio: _Relogio,
    config: ConfigDaBusca = CONFIG,
    tentar_no_429: bool = True,
) -> AgentRetrieval:
    """O adaptador como o Job de indexação o monta, com o relógio falso."""
    return AgentRetrieval(
        config,
        transporte,
        tentar_no_429=tentar_no_429,
        dormir=relogio.dormir,
        relogio=relogio,
    )


def test_cota_de_escrita_vem_do_ambiente_e_sem_ela_nao_ha_ritmo() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_COLECAO_DE_TEXTO": "ct",
        "BUSCA_INDICE_DESCRICAO": "d",
        "BUSCA_DIMENSAO": "128",
    }
    assert ConfigDaBusca.do_ambiente(ambiente).cota_de_escrita is None
    # Vazia (o output do Terraform que o make ainda não acha): sem ritmo também.
    vazia = ambiente | {"BUSCA_COTA_DE_ESCRITA": ""}
    assert ConfigDaBusca.do_ambiente(vazia).cota_de_escrita is None
    com_cota = ambiente | {"BUSCA_COTA_DE_ESCRITA": "3000"}
    assert ConfigDaBusca.do_ambiente(com_cota).cota_de_escrita == 3000
    # Zero ou negativa gravaria um lote por minuto, sem aviso: para com erro.
    for invalida in ("0", "-1"):
        with pytest.raises(ValueError, match="BUSCA_COTA_DE_ESCRITA"):
            ConfigDaBusca.do_ambiente(ambiente | {"BUSCA_COTA_DE_ESCRITA": invalida})


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

    _indice(com_um_429, relogio).gravar("j", _registros(3))
    criados = [c for _, c, _ in transporte.chamadas if c.endswith(":batchCreate")]
    assert (lotes, len(criados)) == (2, 1)
    assert relogio.esperas and relogio.esperas[0] > 0


def _sempre_429(
    metodo: str, caminho: str, corpo: dict[str, Any] | None
) -> dict[str, Any]:
    raise CotaEsgotada(caminho)


def test_esperas_no_429_crescem_e_cabem_no_timeout_do_job() -> None:
    relogio = _Relogio()
    with pytest.raises(CotaEsgotada):
        _indice(_sempre_429, relogio).apagar("j")
    esperas = relogio.esperas
    assert len(esperas) > 1
    assert esperas == sorted(esperas) and esperas[-1] > esperas[0]
    # Os Jobs de indexação e de purga têm 1800 s (infra/modulos/mam/): as esperas de
    # uma chamada sozinha cabem neles.
    assert sum(esperas) < 1800


@pytest.mark.parametrize(
    "operacao",
    [
        lambda i: i.gravar("j", _registros(1)),
        lambda i: i.apagar("j"),
    ],
    ids=["gravar", "apagar"],
)
def test_sem_tentar_no_429_o_erro_sobe_na_hora(
    operacao: Callable[[AgentRetrieval], object],
) -> None:
    # O serviço web (a busca, a purga do admin) não segura a
    # thread esperando a cota: o 429 volta como erro do pedido.
    relogio = _Relogio()
    with pytest.raises(CotaEsgotada):
        operacao(AgentRetrieval(CONFIG, _sempre_429, dormir=relogio.dormir))
    assert relogio.esperas == []


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

    _indice(com_um_429, relogio).apagar("j")
    assert falhou and relogio.esperas


@pytest.mark.parametrize(
    ("operacao", "espera"),
    [
        (lambda i: i.buscar(Consulta(texto="x")), False),
        (lambda i: i.gravar("j", _registros(1)), True),
        (lambda i: i.apagar("j"), True),
    ],
    ids=["buscar", "gravar", "apagar"],
)
def test_com_tentar_no_429_so_a_gravacao_e_a_apagada_esperam(
    operacao: Callable[[AgentRetrieval], object], espera: bool
) -> None:
    # O mam-web cria o índice com `tentar_no_429`: a reindexação e a purga esperam, mas
    # a busca (também um `query`) fica sem esperar.
    relogio = _Relogio()
    with pytest.raises(CotaEsgotada):
        operacao(_indice(_sempre_429, relogio, tentar_no_429=True))
    assert bool(relogio.esperas) is espera


def test_a_busca_do_usuario_nao_espera_no_429() -> None:
    relogio = _Relogio()
    with pytest.raises(CotaEsgotada):
        _indice(_sempre_429, relogio).buscar(Consulta(texto="x"))
    assert relogio.esperas == []


def _com_409(*erros: Exception) -> tuple[TransporteFalso, Any]:
    """Transporte cujos `batchCreate` levantam `erros`, em ordem, e depois gravam."""
    falso = TransporteFalso()
    fila = list(erros)

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        falso(metodo, caminho, corpo)
        if caminho.endswith(":batchCreate") and fila:
            raise fila.pop(0)
        return {}

    return falso, transporte


def _operacoes(falso: TransporteFalso) -> list[str]:
    return [c.rsplit(":", 1)[1] for _, c, _ in falso.chamadas]


@pytest.mark.parametrize(
    "erros",
    [(JaExiste("x"),), (CotaEsgotada("x"), JaExiste("x"))],
    ids=["409 na primeira tentativa", "429 e depois 409"],
)
def test_409_apaga_o_video_e_grava_tudo_de_novo(erros: tuple[Exception, ...]) -> None:
    falso, transporte = _com_409(*erros)
    _indice(transporte, _Relogio()).gravar("j", _registros(250))
    # O 409 pode ser lote gravado em parte ou de outra indexação do mesmo vídeo: o
    # `apagar` tira só o que existe (query + batchDelete) e o vídeo entra inteiro.
    recusadas = ["batchCreate"] * len(erros)
    assert _operacoes(falso) == [
        "query",
        "query",
        *recusadas,
        "query",
        "batchCreate",
        "batchCreate",
    ]
    assert [len(c["requests"]) for _, _, c in falso.chamadas[-2:] if c] == [200, 50]


def test_409_de_novo_depois_de_regravar_sobe() -> None:
    falso, transporte = _com_409(JaExiste("x"), JaExiste("x"))
    with pytest.raises(JaExiste):
        _indice(transporte, _Relogio()).gravar("j", _registros(3))
    assert _operacoes(falso) == [
        "query",
        "query",
        "batchCreate",
        "query",
        "batchCreate",
    ]


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
    _indice(_anota_os_lotes(relogio, envios), relogio, config).gravar(
        "j", _registros(5000)
    )
    assert sum(n for _, n in envios) == 5000
    _nenhuma_janela_de_60_s_passa(envios, 3000)
    # Abaixo da cota, sem parar à toa: 25 lotes em menos de 2 minutos e meio.
    assert envios[-1][0] < 150


def test_ritmo_vale_entre_videos_gravados_no_mesmo_processo() -> None:
    relogio = _Relogio()
    envios: list[tuple[float, int]] = []
    indice = _indice(
        _anota_os_lotes(relogio, envios), relogio, replace(CONFIG, cota_de_escrita=3000)
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

        def mount(self, *_: object) -> None: ...

        def request(self, *_: object, **__: object) -> Resposta:
            return Resposta()

    monkeypatch.setattr("google.auth.default", lambda scopes: (None, None))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Sessao)
    with pytest.raises(CotaEsgotada, match="429"):
        transporte_http()("POST", "x:batchCreate", {})


def test_transporte_http_leitura_do_indice_tem_15_s_e_o_resto_60_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prazos: dict[str, object] = {}

    class Resposta:
        status_code = 200
        ok = True
        content = b"{}"

        def json(self) -> dict[str, object]:
            return {}

    class Sessao:
        def __init__(self, _: object) -> None: ...

        def mount(self, *_: object) -> None: ...

        def request(self, _m: str, url: str, **kw: object) -> Resposta:
            prazos[url.rsplit("/", 1)[-1]] = kw["timeout"]
            return Resposta()

    monkeypatch.setattr("google.auth.default", lambda scopes: (None, None))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Sessao)
    chamar = transporte_http()
    chamar("POST", "c/x/dataObjects:batchSearch", {})
    chamar("POST", "c/x/dataObjects:batchCreate", {})
    assert prazos == {"dataObjects:batchSearch": 15, "dataObjects:batchCreate": 60}


class _OrcamentoFalso:
    """O orçamento do Firestore, em memória: a transação vira um `Lock`."""

    def __init__(self) -> None:
        self.reservas: list[tuple[float, int]] = []
        self.historico: list[tuple[float, int]] = []
        self.trava = threading.Lock()

    def reservar(
        self, colecao: str, objetos: int, limite: float, agora: float
    ) -> float:
        with self.trava:
            self.reservas, espera = reservar_na_janela(
                self.reservas, objetos, limite, agora
            )
            if not espera:
                # A hora guardada: a de quem reservou, ou a que o orçamento adotou.
                self.historico.append((self.reservas[-1][0], objetos))
            return espera


class _RelogioDeVarias(_Relogio):
    """Relógio falso para vários fios: avançar é uma conta só, sob trava."""

    def __init__(self) -> None:
        super().__init__()
        self.trava = threading.Lock()

    def dormir(self, segundos: float) -> None:
        with self.trava:
            super().dormir(segundos)


def _reservado_em_janelas(orcamento: _OrcamentoFalso) -> int:
    """O maior total reservado numa janela de 60 s, pela hora de cada reserva."""
    ts = orcamento.historico
    return max(sum(n for u, n in ts if t <= u < t + 60) for t, _ in ts)


def test_orcamento_dois_indices_juntos_nao_passam_da_fracao_da_cota() -> None:
    relogio = _RelogioDeVarias()
    orcamento = _OrcamentoFalso()

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        return {}

    config = replace(CONFIG, cota_de_escrita=3000)

    def indice() -> AgentRetrieval:
        return AgentRetrieval(
            config,
            transporte,
            tentar_no_429=True,
            dormir=relogio.dormir,
            relogio=relogio,
            orcamento=orcamento,
        )

    fios = [
        threading.Thread(target=indice().gravar, args=(nome, _registros(5000)))
        for nome in ("a", "b")
    ]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert sum(n for _, n in orcamento.historico) == 10_000
    assert _reservado_em_janelas(orcamento) <= 3000 * FRACAO_DA_COTA


def test_orcamento_conta_a_apagada_junto_com_a_criada() -> None:
    relogio = _Relogio()
    orcamento = _OrcamentoFalso()
    # Nome que não é o do id: lixo de uma indexação antiga, que a gravação apaga.
    lixo = [
        {"name": f"c/dataObjects/velho-{n}", "data": _lido(_reg(f"j:fala:v{n}"))}
        for n in range(1500)
    ]

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        return (
            {"dataObjects": lixo}
            if caminho.endswith("/col-texto/dataObjects:query")
            else {}
        )

    AgentRetrieval(
        replace(CONFIG, cota_de_escrita=3000),
        transporte,
        dormir=relogio.dormir,
        relogio=relogio,
        orcamento=orcamento,
    ).gravar("j", _registros(400))
    # 1.000 + 500 apagados e 200 + 200 criados: tudo passa pela mesma conta.
    assert [n for _, n in orcamento.historico] == [1000, 500, 200, 200]


def test_orcamento_fora_do_ar_grava_pelo_ritmo_local_e_avisa(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Quebrado:
        def reservar(
            self, colecao: str, objetos: int, limite: float, agora: float
        ) -> float:
            raise RuntimeError("firestore fora do ar")

    relogio = _Relogio()
    envios: list[tuple[float, int]] = []
    with caplog.at_level("WARNING"):
        AgentRetrieval(
            replace(CONFIG, cota_de_escrita=3000),
            _anota_os_lotes(relogio, envios),
            dormir=relogio.dormir,
            relogio=relogio,
            orcamento=Quebrado(),
        ).gravar("j", _registros(5000))
    assert sum(n for _, n in envios) == 5000
    _nenhuma_janela_de_60_s_passa(envios, 3000)
    assert "orçamento de escrita fora do ar" in caplog.text


def test_reserva_espera_o_bastante_para_o_lote_caber() -> None:
    reservas = [(0.0, 1000), (10.0, 1000), (20.0, 500)]
    # Com 2.500 na janela, 1.000 não cabem em 2.700; basta a mais antiga sair.
    mantidas, espera = reservar_na_janela(reservas, 1000, 2700, 30.0)
    assert mantidas == reservas and espera == 30.0
    mantidas, espera = reservar_na_janela(reservas, 1000, 2700, 70.0)
    assert espera == 0 and mantidas == [(20.0, 500), (70.0, 1000)]


def test_reserva_com_hora_velha_nao_estoura_a_janela() -> None:
    orcamento = _OrcamentoFalso()
    # B (hora 70) descarta a reserva de A (hora 0); C chega depois, com a hora 30,
    # e já não via A: sem o relógio monotônico, A e C ficavam juntos na janela.
    for objetos, agora in [(2000, 0.0), (1000, 70.0), (1700, 30.0)]:
        orcamento.reservar("c", objetos, 2700, agora)
    _nenhuma_janela_de_60_s_passa(orcamento.historico, 2700)


def test_id_do_objeto_com_id_de_correcao_cabe_nos_63_caracteres_do_rfc_1035() -> None:
    longo = (
        "0123456789abcdef0123456789abcdef:texto:acr-0123456789abcdef0123456789abcdef"
    )
    curto = "j:fala:fal001"

    pedidos = [
        _criacao(Registro(id=i, tipo="fala", job_id="j", inicio_ms=0, fim_ms=1))
        for i in (longo, longo, curto)
    ]

    ids = [p["dataObjectId"] for p in pedidos]
    assert ids[0] == ids[1] != "m-" + longo.replace(":", "-")
    assert len(ids[0]) <= 63 and ids[0][0] == "m"
    assert ids[2] == "m-j-fala-fal001"


def _reg(id: str, tipo: str = "fala", **campos: Any) -> Registro:
    base: dict[str, Any] = {"job_id": "j", "inicio_ms": 0, "fim_ms": 10}
    return Registro(id=id, tipo=tipo, **(base | campos))  # type: ignore[arg-type]


def _lido(r: Registro) -> dict[str, Any]:
    return dict(_criacao(r)["dataObject"]["data"])


def test_plano_id_novo_cria_e_id_que_sumiu_apaga() -> None:
    velho, novo = _reg("j:fala:fal000", texto="a"), _reg("j:fala:fal001", texto="b")
    plano = montar_plano([novo], [_lido(velho)])
    assert plano.criar == [novo]
    assert plano.apagar == [velho.id]
    assert plano.atualizar == []


def test_plano_igual_nao_faz_nada() -> None:
    r = _reg("j:fala:fal000", texto="a", pessoas=["x", "y"], programa="p")
    assert montar_plano([r], [_lido(r)]).vazio


def test_plano_mudar_o_texto_da_fala_so_atualiza() -> None:
    antes = _reg("j:fala:fal000", texto="a")
    depois = _reg("j:fala:fal000", texto="b")
    plano = montar_plano([depois], [_lido(antes)])
    assert (plano.criar, plano.apagar, plano.atualizar) == (
        [],
        [],
        [depois],
    )


def test_plano_mudar_so_as_pessoas_atualiza() -> None:
    antes = _reg("j:fala:fal000", texto="a", pessoas=["x"])
    depois = _reg("j:fala:fal000", texto="a", pessoas=["x", "y"])
    plano = montar_plano([depois], [_lido(antes)])
    assert (plano.criar, plano.apagar, plano.atualizar) == ([], [], [depois])


def test_plano_compara_float_none_dias_e_listas_fora_de_ordem() -> None:
    r = _reg(
        "j:objeto:o1:0",
        "objeto",
        descricao="d",
        pessoas=["a", "b"],
        cor_base=["azul", "verde"],
        data_de_exibicao=date(2026, 1, 2),
        destaque=2,
    )
    lido = _lido(r)
    lido["pessoas"] = ["b", "a"]
    lido["cor_base"] = ["verde", "azul"]
    lido["inicio_ms"] = 0.0
    lido["destaque"] = 2.0
    lido["marca"] = None  # ausente no novo vale como None
    sem_listas = _reg("j:fala:fal000", texto="a")
    lido_sem_listas = _lido(sem_listas)
    del lido_sem_listas["pessoas"], lido_sem_listas["cor_base"]  # o índice omite []
    assert montar_plano([sem_listas], [lido_sem_listas]).vazio
    assert lido["data_de_exibicao"] == 20260102
    assert montar_plano([r], [lido]).vazio
    # Um dia diferente é mudança de verdade.
    outro = replace(r, data_de_exibicao=date(2026, 1, 3))
    assert montar_plano([outro], [lido]).atualizar == [outro]


def test_plano_diz_quais_planos_precisam_do_vetor_do_quadro() -> None:
    def plano(id: str, quadro: str, descricao: str = "d") -> Registro:
        return _reg(id, "plano", descricao=descricao, quadro=quadro)

    igual, novo = plano("j:plano:p0", "q0"), plano("j:plano:p1", "q1")
    quadro = plano("j:plano:p2", "q2")
    texto = plano("j:plano:p3", "q3")
    pessoas = replace(plano("j:plano:p4", "q4"), pessoas=["x"])
    # Sem descrição o `significado` cai no tipo, igual ao da descrição "plano" de antes.
    sem_descricao = replace(plano("j:plano:p5", "q5"), descricao=None)
    lidos = [
        _lido(igual),
        _lido(plano("j:plano:p2", "velho")),
        _lido(plano("j:plano:p3", "q3", "outra descrição")),
        _lido(plano("j:plano:p4", "q4")),
        _lido(plano("j:plano:p5", "q5", "plano")),
    ]
    resultado = montar_plano(
        [igual, novo, quadro, texto, pessoas, sem_descricao], lidos
    )
    assert resultado.planos_com_quadro_novo == [
        "j:plano:p1",
        "j:plano:p2",
        "j:plano:p3",
        "j:plano:p5",
    ]


def test_ler_indice_pede_so_os_campos_do_esquema_e_pagina() -> None:
    r1, r2 = _reg("j:fala:fal000", texto="a"), _reg("j:fala:fal001", texto="b")
    respostas = iter(
        [
            {
                "dataObjects": [{"name": "c/dataObjects/a", "data": _lido(r1)}],
                "nextPageToken": "p2",
            },
            {"dataObjects": [{"name": "c/dataObjects/b", "data": _lido(r2)}]},
            {},
        ]
    )
    transporte = TransporteFalso()
    lidos = AgentRetrieval(CONFIG, _Sequencia(transporte, respostas)).ler_indice("j")
    assert [d["id"] for d in lidos] == [r1.id, r2.id]
    [(_, caminho, corpo1), (_, _, corpo2), (_, texto, corpo3)] = transporte.chamadas
    assert caminho.endswith("/dataObjects:query")
    assert corpo1 is not None and corpo2 is not None
    assert corpo1["filter"] == {"job_id": {"$eq": "j"}}
    campos = corpo1["outputFields"]["dataFields"]
    assert campos == list(esquema_da_colecao(CONFIG)["dataSchema"]["properties"])
    assert corpo2["pageToken"] == "p2"
    assert "/col-texto/" in texto
    assert (
        corpo3 is not None and "significado" not in corpo3["outputFields"]["dataFields"]
    )


class _ColecaoEmMemoria:
    """A coleção como o serviço a trata, por nome: `query` pagina por vídeo, `batchCreate`
    recusa nome que existe (409), `batchUpdate` troca o `data`. `falhar_em` leva a
    operação (ou qualquer uma, com `*`) a levantar depois de `n` chamadas dela, para
    simular uma queda no meio."""

    def __init__(self) -> None:
        self.objetos: dict[str, dict[str, Any]] = {}
        self.escritos = 0
        self.operacoes: list[str] = []
        self.falhar_em: tuple[str, int] | None = None

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        assert corpo is not None
        operacao = caminho.rsplit(":", 1)[1]
        if self.falhar_em and (
            (
                self.falhar_em[0] == operacao
                and self.operacoes.count(operacao) >= self.falhar_em[1]
            )
            or (self.falhar_em[0] == "*" and len(self.operacoes) >= self.falhar_em[1])
        ):
            self.falhar_em = None
            raise RuntimeError("queda no meio")
        self.operacoes.append(operacao)
        colecao = caminho.rsplit("/dataObjects", 1)[0]
        if operacao == "query":
            job = corpo["filter"]["job_id"]["$eq"]
            achados = [
                {"name": n, "data": d}
                for n, d in self.objetos.items()
                if d["job_id"] == job and n.startswith(colecao + "/dataObjects/")
            ]
            return {"dataObjects": achados}
        if operacao == "batchCreate":
            for r in corpo["requests"]:
                nome = f"{colecao}/dataObjects/{r['dataObjectId']}"
                if nome in self.objetos:
                    raise JaExiste(nome)
                self.objetos[nome] = r["dataObject"]["data"]
                self.escritos += 1
        elif operacao == "batchDelete":
            for r in corpo["requests"]:
                del self.objetos[r["name"]]
                self.escritos += 1
        elif operacao == "batchUpdate":
            for r in corpo["requests"]:
                assert r["updateMask"] == "data"
                self.objetos[r["dataObject"]["name"]] = r["dataObject"]["data"]
                self.escritos += 1
        return {}


def _video(n: int, **mudancas: Any) -> list[Registro]:
    """Um vídeo de `n` falas e `n` planos; `mudancas` troca campos de alguns ids."""
    registros = [_reg(f"j:fala:f{i}", texto=f"fala {i}") for i in range(n)]
    registros += [
        _reg(f"j:plano:p{i}", "plano", descricao=f"plano {i}", quadro=f"q{i}")
        for i in range(n)
    ]
    return [replace(r, **mudancas.get(r.id, {})) for r in registros]


def test_revisao_com_10_correcoes_grava_no_maximo_50_objetos() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(500))
    assert len(colecao.objetos) == 1000
    colecao.escritos = 0
    # 10 correções: 5 mudam o texto de uma fala (atualiza) e 5 mudam só as pessoas.
    mudancas = {f"j:fala:f{i}": {"texto": f"corrigida {i}"} for i in range(5)} | {
        f"j:fala:f{i}": {"pessoas": ["maria"]} for i in range(5, 10)
    }
    indice.gravar("j", _video(500, **mudancas))
    assert colecao.escritos == 5 + 5 <= 50
    assert len(colecao.objetos) == 1000


def test_gravar_de_novo_sem_mudanca_so_le() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(3))
    colecao.operacoes.clear()
    indice.gravar("j", _video(3))
    assert colecao.operacoes == ["query", "query"]


def test_gravar_apaga_o_que_sumiu_e_o_objeto_de_nome_que_nao_e_o_do_id() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(2))
    colecao.objetos[f"{CONFIG.caminho_da_colecao}/dataObjects/antigo"] = _lido(
        _reg("j:fala:f0", texto="fala 0")
    )
    colecao.objetos[f"{CONFIG.caminho_da_colecao}/dataObjects/outro"] = _lido(
        _reg("j:fala:velha")
    )
    indice.gravar("j", _video(2)[1:])
    ids = sorted(d["id"] for d in colecao.objetos.values())
    assert ids == ["j:fala:f1", "j:plano:p0", "j:plano:p1"]
    assert all("/m-j-" in n for n in colecao.objetos)


@pytest.mark.parametrize("operacao", ["batchDelete", "batchCreate", "batchUpdate"])
def test_falha_no_meio_e_nova_rodada_chegam_ao_mesmo_indice(operacao: str) -> None:
    mudancas = {
        "j:fala:f0": {"texto": "corrigida"},
        "j:fala:f1": {"pessoas": ["maria"]},
        "j:plano:p2": {"descricao": "outro plano"},
    }
    novo = _video(3, **mudancas)[1:]  # f0 some

    sem_falha = _ColecaoEmMemoria()
    _indice(sem_falha, _Relogio()).gravar("j", _video(3))
    _indice(sem_falha, _Relogio()).gravar("j", novo)

    com_falha = _ColecaoEmMemoria()
    indice = _indice(com_falha, _Relogio())
    indice.gravar("j", _video(3))
    com_falha.falhar_em = (operacao, com_falha.operacoes.count(operacao))
    with pytest.raises(RuntimeError, match="queda"):
        indice.gravar("j", novo)
    indice.gravar("j", novo)
    assert com_falha.objetos == sem_falha.objetos


@pytest.mark.parametrize("queda", range(1, 4))
def test_queda_no_meio_so_tira_da_busca_o_que_muda_de_significado(queda: int) -> None:
    # p0 muda a descrição (apaga e cria), f1 só as pessoas (atualiza), f2 sai, p3 é novo.
    # Só p0 pode faltar depois da queda.
    mudancas = {
        "j:plano:p0": {"descricao": "corrigida"},
        "j:fala:f1": {"pessoas": ["m"]},
    }
    novo = [r for r in _video(4, **mudancas) if r.id not in ("j:fala:f2", "j:fala:f3")]
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(3))
    antes = {d["id"] for d in colecao.objetos.values()}
    colecao.falhar_em = ("*", len(colecao.operacoes) + queda)
    with pytest.raises(RuntimeError, match="queda"):
        indice.gravar("j", novo)
    depois = {d["id"] for d in colecao.objetos.values()}
    fica = antes & {r.id for r in novo}
    assert fica - depois <= {"j:plano:p0"}
    indice.gravar("j", novo)
    assert {d["id"] for d in colecao.objetos.values()} == {r.id for r in novo}


def test_as_atualizacoes_tambem_passam_pelo_orcamento() -> None:
    relogio = _Relogio()
    orcamento = _OrcamentoFalso()
    colecao = _ColecaoEmMemoria()
    config = replace(CONFIG, cota_de_escrita=3000)

    def indice() -> AgentRetrieval:
        return AgentRetrieval(
            config,
            colecao,
            dormir=relogio.dormir,
            relogio=relogio,
            orcamento=orcamento,
        )

    indice().gravar("j", _video(5))
    assert [n for _, n in orcamento.historico] == [5, 5]
    pessoas = {f"j:fala:f{i}": {"pessoas": ["maria"]} for i in range(5)}
    indice().gravar("j", _video(5, **pessoas))
    assert colecao.operacoes[-1] == "batchUpdate"
    assert [n for _, n in orcamento.historico] == [5, 5, 5]


def test_atualizacoes_vao_em_lotes_de_ate_1000() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(1200)[:1200])
    pessoas = {f"j:fala:f{i}": {"pessoas": ["maria"]} for i in range(1200)}
    colecao.operacoes.clear()
    indice.gravar("j", _video(1200, **pessoas)[:1200])
    assert colecao.operacoes == ["query", "query", "batchUpdate", "batchUpdate"]


def test_objeto_novo_leva_sistema_e_lixeira_e_o_esquema_e_o_filtro_os_declaram() -> (
    None
):
    r = _reg("j:fala:f0", texto="oi", sistema="Playout")
    dados = _lido(r)
    assert dados["sistema"] == "Playout" and dados["na_lixeira"] is False
    # Sem sistema, o campo fica fora; a lixeira vai sempre, falsa inclusive.
    sem = _lido(_reg("j:fala:f1", texto="oi"))
    assert "sistema" not in sem and sem["na_lixeira"] is False
    propriedades = esquema_da_colecao(CONFIG)["dataSchema"]["properties"]
    assert propriedades["sistema"] == {"type": "string"}
    assert propriedades["na_lixeira"] == {"type": "boolean"}
    assert {"sistema", "na_lixeira"} <= set(CAMPOS_DE_FILTRO)
    assert _registro(dados) == r


def test_marcar_lixeira_atualiza_so_os_objetos_do_video_que_mudam() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(3))
    outro = [_reg("k:fala:f0", texto="x", job_id="k")]
    indice.gravar("k", outro)

    colecao.operacoes.clear()
    indice.marcar_lixeira("j", True)
    assert colecao.operacoes == ["query", "batchUpdate", "query", "batchUpdate"]
    assert {
        d["na_lixeira"] for d in colecao.objetos.values() if d["job_id"] == "j"
    } == {True}
    assert [
        d["na_lixeira"] for d in colecao.objetos.values() if d["job_id"] == "k"
    ] == [False]

    # De novo: nada a escrever. E o resto dos dados fica como estava.
    colecao.operacoes.clear()
    indice.marcar_lixeira("j", True)
    assert colecao.operacoes == ["query", "query"]
    indice.marcar_lixeira("j", False)
    restaurado = {d["id"]: d for d in colecao.objetos.values() if d["job_id"] == "j"}
    assert restaurado == {r.id: _lido(r) for r in _video(3)}


def test_marcar_lixeira_marca_o_objeto_de_antes_do_campo() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(1))
    for dados in colecao.objetos.values():
        del dados["na_lixeira"]
    indice.marcar_lixeira("j", False)
    assert all(d["na_lixeira"] is False for d in colecao.objetos.values())


def test_marcar_lixeira_devolve_inteiro_o_numero_que_voltou_como_float() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(1))
    for dados in colecao.objetos.values():
        dados["inicio_ms"] = float(dados["inicio_ms"])
    indice.marcar_lixeira("j", True)
    assert all(type(d["inicio_ms"]) is int for d in colecao.objetos.values())


def test_marcar_lixeira_divide_em_lotes_e_reserva_a_cota() -> None:
    colecao = _ColecaoEmMemoria()
    relogio = _Relogio()
    config = replace(CONFIG, cota_de_escrita=3000)
    indice = _indice(colecao, relogio, config)
    indice.gravar("j", _registros(1600))  # 1.600 objetos
    colecao.operacoes.clear()
    antes = relogio.agora
    indice.marcar_lixeira("j", True)
    assert colecao.operacoes.count("batchUpdate") == 2  # lotes de 1.000
    assert (
        relogio.agora > antes
    )  # 1.600 + 1.600 na coleção de texto passam de 90% da cota


def test_o_indice_que_ja_existe_com_outros_filtros_e_apontado_sem_apagar_nada() -> None:
    class Transporte:
        def __init__(self, filtros: list[str] | None) -> None:
            self.filtros = filtros
            self.chamadas: list[str] = []

        def __call__(
            self, metodo: str, caminho: str, corpo: dict[str, Any] | None
        ) -> dict[str, Any]:
            self.chamadas.append(metodo)
            return {} if self.filtros is None else {"filterFields": self.filtros}

    antigos = [c for c in CAMPOS_DE_FILTRO if c not in ("sistema", "na_lixeira")]
    antigo = Transporte(antigos)
    assert indices_com_filtros_diferentes(CONFIG, antigo) == {
        "ind-d": ["sistema", "na_lixeira"]
    }
    assert set(antigo.chamadas) == {"GET"}
    assert indices_com_filtros_diferentes(CONFIG, Transporte(CAMPOS_DE_FILTRO)) == {}
    assert indices_com_filtros_diferentes(CONFIG, Transporte(None)) == {}


def test_o_filtro_do_pedido_leva_sistema_e_lixeira() -> None:
    filtro = filtro_do_pedido(Filtros(sistema="Playout", na_lixeira=False))
    assert filtro == {
        "$and": [
            {"sistema": {"$eq": "Playout"}},
            {"na_lixeira": {"$eq": False}},
        ]
    }


def _sem_os_campos(colecao: _ColecaoEmMemoria) -> None:
    for dados in colecao.objetos.values():
        dados.pop("na_lixeira", None)
        dados.pop("sistema", None)


def test_preencher_filtros_da_aos_antigos_so_o_que_falta_e_repetir_nao_escreve() -> (
    None
):
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(3))
    indice.gravar("k", [_reg("k:fala:f0", texto="x", job_id="k")])
    _sem_os_campos(colecao)
    antes_de_k = [dict(d) for d in colecao.objetos.values() if d["job_id"] == "k"]

    colecao.operacoes.clear()
    assert indice.preencher_filtros("j", "Playout", True) == 6
    assert colecao.operacoes == ["query", "batchUpdate", "query", "batchUpdate"]
    do_j = [d for d in colecao.objetos.values() if d["job_id"] == "j"]
    assert {(d["sistema"], d["na_lixeira"]) for d in do_j} == {("Playout", True)}
    # O resto dos dados não muda, nem o `significado` (o vetor não se refaz).
    assert {d["id"]: d for d in do_j} == {
        r.id: _lido(replace(r, sistema="Playout", na_lixeira=True)) for r in _video(3)
    }
    assert [d for d in colecao.objetos.values() if d["job_id"] == "k"] == antes_de_k

    colecao.operacoes.clear()
    assert indice.preencher_filtros("j", "Playout", True) == 0
    assert colecao.operacoes == ["query", "query"]


def test_preencher_filtros_nao_troca_o_valor_que_a_lixeira_ja_pos() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(2))
    for dados in colecao.objetos.values():
        dados.pop("sistema", None)
    assert indice.preencher_filtros("j", None, True) == 0
    assert all(d["na_lixeira"] is False for d in colecao.objetos.values())
    # Job sem sistema: o campo não é escrito, e a carga não o procura de novo.
    assert all("sistema" not in d for d in colecao.objetos.values())


def test_preencher_filtros_e_retomavel_depois_de_uma_queda() -> None:
    colecao = _ColecaoEmMemoria()
    indice = _indice(colecao, _Relogio())
    indice.gravar("j", _video(5))
    _sem_os_campos(colecao)
    # Uma carga que parou no meio: metade dos objetos já tem os campos.
    for i, dados in enumerate(colecao.objetos.values()):
        if i % 2:
            dados["na_lixeira"] = False
            dados["sistema"] = "Playout"
    faltam = sum("na_lixeira" not in d for d in colecao.objetos.values())
    assert indice.preencher_filtros("j", "Playout", False) == faltam == 5
    assert all(d["na_lixeira"] is False for d in colecao.objetos.values())


def test_preencher_filtros_reserva_a_cota_de_escrita() -> None:
    colecao = _ColecaoEmMemoria()
    relogio = _Relogio()
    config = replace(CONFIG, cota_de_escrita=3000)
    indice = _indice(colecao, relogio, config)
    indice.gravar("j", _registros(1600))
    _sem_os_campos(colecao)
    antes = relogio.agora
    indice.preencher_filtros("j", "Playout", False)
    assert relogio.agora > antes


@pytest.mark.parametrize("ligados", [True, False])
@pytest.mark.parametrize("tipo", ["plano", "fala", "texto_na_tela", "objeto", None])
def test_buscar_roteia_tipo_e_so_embute_o_significado_dos_planos(
    ligados: bool, tipo: Any
) -> None:
    config = replace(CONFIG, indices_ligados=ligados)
    transporte = TransporteFalso(
        {"predictions": [{"embeddings": {"values": [0.1] * 256}}]}
    )
    AgentRetrieval(config, transporte).buscar(
        Consulta(texto="terno", significado="paletó", filtros=Filtros(tipo=tipo))
    )
    _esperar_o_cache()
    buscas = [(c, b) for _, c, b in transporte.chamadas if c.endswith(":batchSearch")]
    assert {c.split("/collections/")[1].split("/")[0] for c, _ in buscas} == (
        {"col-z"}
        if tipo == "plano"
        else {"col-texto"}
        if tipo
        else {"col-z", "col-texto"}
    )
    for _, corpo in buscas:
        assert corpo is not None
        assert "combine" not in corpo
        assert len(corpo["searches"]) == 1
    # Os planos vão em dois pedidos, um por busca (#568); a coleção de texto, em um.
    campos = [
        (("/col-texto/" in caminho), next(iter(corpo["searches"][0])))
        for caminho, corpo in buscas
        if corpo is not None
    ]
    significado = "semanticSearch" if ligados else "vectorSearch"
    assert sorted(campos) == sorted(
        (
            [(False, "textSearch"), (False, significado)]
            if tipo in (None, "plano")
            else []
        )
        + ([(True, "textSearch")] if tipo != "plano" else [])
    )
    assert sum(c.endswith(":predict") for _, c, _ in transporte.chamadas) == (
        1 if tipo in (None, "plano") else 0
    )


@pytest.mark.parametrize("ligados", [True, False])
@pytest.mark.parametrize("tipo", ["fala", "texto_na_tela", "objeto"])
def test_tipo_de_texto_sem_texto_devolve_vazio_sem_chamar_api(
    ligados: bool, tipo: Any
) -> None:
    transporte = TransporteFalso()
    assert (
        AgentRetrieval(replace(CONFIG, indices_ligados=ligados), transporte).buscar(
            Consulta(significado="terno", filtros=Filtros(tipo=tipo))
        )
        == []
    )
    assert transporte.chamadas == []


@pytest.mark.parametrize("ligados", [True, False])
def test_busca_livre_roda_as_colecoes_juntas_intercala_corta_e_so_filtra_o_vetor(
    ligados: bool,
) -> None:
    # Três pedidos juntos: texto e significado dos planos, e o da coleção de texto.
    barreira = threading.Barrier(3)
    chamados: list[str] = []

    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        if caminho.endswith(":predict"):
            return {"predictions": [{"embeddings": {"values": [0.1] * 256}}]}
        chamados.append(caminho)
        assert all(b["topK"] == 3 for b in _buscas(corpo).values())
        barreira.wait(timeout=2)
        if "/col-texto/" in caminho:
            achados = [_achado("t1", "oi"), _achado("t2", "olá")]
        elif "textSearch" in corpo["searches"][0]:
            achados = []
        else:
            achados = [
                _achado("longe", "plano distante", (1, 0.9)),
                _achado("p1", "plano perto", (1, 0.1)),
                _achado("p2", "outro plano", (1, 0.1)),
            ]
        return {"results": [{"results": achados}]}

    indice = AgentRetrieval(
        replace(
            CONFIG, indices_ligados=ligados, distancia_maxima=0.25, palavras_minimas=2
        ),
        transporte,
    )
    achados = indice.buscar(
        Consulta(texto="terno", significado="paletó", cortar_significado=True, limite=3)
    )
    assert len(chamados) == 3
    assert [r.id for r in achados] == ["p1", "t1", "p2"]


def test_gravar_divide_migra_os_antigos_e_texto_mudado_so_atualiza() -> None:
    transporte = _ColecaoEmMemoria()
    indice = AgentRetrieval(CONFIG, transporte)
    registros = [_reg("j:p", "plano", descricao="estúdio")] + [
        _reg(f"j:{tipo}", tipo, texto="terno")
        for tipo in ("fala", "texto_na_tela", "objeto")
    ]
    # Antes da migração os quatro tipos estavam na coleção de vetor.
    for r in registros:
        transporte.objetos[
            f"{CONFIG.caminho_da_colecao}/dataObjects/m-{r.id.replace(':', '-')}"
        ] = _lido(r) | {"significado": r.descricao or r.texto}
    indice.gravar("j", registros)
    assert len(transporte.objetos) == 4
    for nome, dados in transporte.objetos.items():
        assert ("/col-z/" in nome) == (dados["tipo"] == "plano")
        assert ("significado" in dados) == (dados["tipo"] == "plano")
    transporte.operacoes.clear()
    indice.gravar("j", registros)
    assert transporte.operacoes == ["query", "query"]
    transporte.operacoes.clear()
    indice.gravar(
        "j", [r if r.tipo == "plano" else replace(r, texto="paletó") for r in registros]
    )
    assert transporte.operacoes == ["query", "query", "batchUpdate"]
    assert all(
        d["texto"] == "paletó"
        for d in transporte.objetos.values()
        if d["tipo"] != "plano"
    )


@pytest.mark.parametrize("operacao", ["apagar", "marcar_lixeira", "preencher_filtros"])
def test_manutencao_e_orcamento_passam_pelas_duas_colecoes(operacao: str) -> None:
    reservas: list[tuple[str, int]] = []

    class OrcamentoPorColecao:
        def reservar(
            self, colecao: str, objetos: int, limite: float, agora: float
        ) -> float:
            reservas.append((colecao, objetos))
            return 0.0

    transporte = _ColecaoEmMemoria()
    indice = AgentRetrieval(
        replace(CONFIG, cota_de_escrita=3000),
        transporte,
        orcamento=OrcamentoPorColecao(),
    )
    indice.gravar("j", _video(1))
    assert reservas == [("col-z", 1), ("col-texto", 1)]
    reservas.clear()
    if operacao == "apagar":
        indice.apagar("j")
        assert transporte.objetos == {}
    elif operacao == "marcar_lixeira":
        indice.marcar_lixeira("j", True)
        assert all(d["na_lixeira"] for d in transporte.objetos.values())
    else:
        for dados in transporte.objetos.values():
            del dados["na_lixeira"]
        assert indice.preencher_filtros("j", "legado", True) == 2
        assert all(
            d["na_lixeira"] and d["sistema"] == "legado"
            for d in transporte.objetos.values()
        )
    assert reservas == [("col-z", 1), ("col-texto", 1)]


def test_ritmo_local_tambem_tem_uma_cota_por_colecao() -> None:
    relogio = _Relogio()
    indice = _indice(_ColecaoEmMemoria(), relogio, replace(CONFIG, cota_de_escrita=2))
    indice.gravar("j", _video(1))
    assert relogio.esperas == []


@pytest.mark.parametrize("ligados", [True, False])
def test_cria_as_duas_colecoes_texto_sem_vetor_significado_nem_indice(
    ligados: bool,
) -> None:
    transporte = TransporteFalso()
    criar_colecao(replace(CONFIG, indices_ligados=ligados), transporte)
    criacoes = [(c, b) for m, c, b in transporte.chamadas if "collectionId=" in c]
    assert len(criacoes) == 2
    caminho, esquema = criacoes[1]
    assert caminho.endswith("collectionId=col-texto")
    assert esquema is not None and "vectorSchema" not in esquema
    propriedades = esquema["dataSchema"]["properties"]
    assert "significado" not in propriedades
    assert set(CAMPOS_DE_FILTRO + ["texto_da_busca"]) <= set(propriedades)
    assert not any("/col-texto/indexes" in c for _, c, _ in transporte.chamadas)


def _esperar_o_cache() -> None:
    """O embedding do cache roda numa thread solta (`_buscar_na_colecao`); espera por ela."""
    for t in threading.enumerate():
        if t.name == "embedding-do-cache":
            t.join(5)


def _transporte_de_busca(chamadas: list[tuple[str, Any]]) -> Callable[..., Any]:
    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        chamadas.append((caminho, corpo))
        if caminho.endswith(":predict"):
            return {"predictions": [{"embeddings": {"values": [0.1] * 256}}]}
        return {}

    return transporte


def test_com_ann_vetor_fora_do_cache_vai_semantic_e_enche_o_cache_uma_vez() -> None:
    chamadas: list[tuple[str, Any]] = []
    indice = AgentRetrieval(CONFIG, _transporte_de_busca(chamadas))
    indice.buscar(Consulta(significado="paletó", filtros=Filtros(tipo="plano")))
    _esperar_o_cache()
    busca = next(c for p, c in chamadas if p.endswith(":batchSearch"))
    assert set(_buscas(busca)) == {"semanticSearch"}
    assert sum(p.endswith(":predict") for p, _ in chamadas) == 1


def test_com_ann_vetor_no_cache_vai_vector_search_com_index_hint() -> None:
    chamadas: list[tuple[str, Any]] = []
    indice = AgentRetrieval(CONFIG, _transporte_de_busca(chamadas))
    consulta = Consulta(significado="paletó", filtros=Filtros(tipo="plano"))
    indice.buscar(consulta)
    _esperar_o_cache()
    chamadas.clear()
    indice.buscar(consulta)
    assert [p for p, _ in chamadas if p.endswith(":predict")] == []
    (busca,) = _buscas(next(c for p, c in chamadas))
    corpo = _buscas(next(c for p, c in chamadas))[busca]
    assert busca == "vectorSearch"
    assert corpo["vector"] == {"values": [0.1] * 256}
    assert corpo["searchHint"]["indexHint"]["name"].endswith("/indexes/ind-d")
    assert "semanticSearch" not in str(corpo)


def test_com_ann_falha_do_embedding_do_cache_nao_derruba_a_busca() -> None:
    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        if caminho.endswith(":predict"):
            raise RuntimeError("429")
        return {}

    indice = AgentRetrieval(CONFIG, transporte)
    assert indice.buscar(Consulta(significado="x", filtros=Filtros(tipo="plano"))) == []


def test_com_ann_threads_juntas_embutem_o_texto_uma_vez() -> None:
    chamadas: list[tuple[str, Any]] = []
    indice = AgentRetrieval(CONFIG, _transporte_de_busca(chamadas))
    consulta = Consulta(significado="paletó", filtros=Filtros(tipo="plano"))
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: indice.buscar(consulta), range(4)))
    _esperar_o_cache()
    assert sum(p.endswith(":predict") for p, _ in chamadas) == 1


def test_aquecer_o_indice_toca_um_host_de_cada_servico() -> None:
    hosts: list[str] = []

    class Quente:
        aquecer = staticmethod(hosts.append)

        def __call__(self, metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
            return {}

    aquecer_o_indice(Quente(), CONFIG)
    assert hosts == [
        "vectorsearch.googleapis.com",
        f"{CONFIG.regiao}-aiplatform.googleapis.com",
    ]
    aquecer_o_indice(TransporteFalso(), CONFIG)  # sem `aquecer`: não faz nada


def test_com_ann_texto_ja_enchendo_nao_abre_outra_thread() -> None:
    liberar = threading.Event()
    chamadas: list[str] = []

    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        chamadas.append(caminho)
        if caminho.endswith(":predict"):
            liberar.wait(5)
            return {"predictions": [{"embeddings": {"values": [0.1] * 256}}]}
        return {}

    indice = AgentRetrieval(CONFIG, transporte)
    consulta = Consulta(significado="paletó", filtros=Filtros(tipo="plano"))
    for _ in range(10):
        indice.buscar(consulta)
    abertas = [t for t in threading.enumerate() if t.name == "embedding-do-cache"]
    liberar.set()
    _esperar_o_cache()
    assert len(abertas) == 1
    assert sum(c.endswith(":predict") for c in chamadas) == 1


def test_com_ann_thread_que_nao_inicia_libera_a_reserva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas: list[tuple[str, Any]] = []
    indice = AgentRetrieval(CONFIG, _transporte_de_busca(chamadas))

    def falha(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", falha)
    indice.buscar(Consulta(significado="paletó", filtros=Filtros(tipo="plano")))
    assert indice._enchendo == set()
