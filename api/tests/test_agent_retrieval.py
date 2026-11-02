from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from api.agent_retrieval import (
    AgentRetrieval,
    ConfigDaBusca,
    JaExiste,
    apagar_colecao,
    criar_colecao,
    esperar,
    esquema_da_colecao,
    filtro_do_pedido,
    indices_da_colecao,
    pedido_de_busca,
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
        "text": {"text": "vestido vermelho", "fields": ["texto", "descricao"]}
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


def test_criar_colecao_e_idempotente() -> None:
    def ja_existe(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        raise JaExiste(caminho)

    criar_colecao(CONFIG, ja_existe, _nao_dorme)


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
