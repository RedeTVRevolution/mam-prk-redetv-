from datetime import date
from typing import Any

import pytest

from api.agent_retrieval import (
    AgentRetrieval,
    ConfigDaBusca,
    JaExiste,
    apagar_colecao,
    criar_colecao,
    esquema_da_colecao,
    filtro_do_pedido,
    pedido_de_busca,
)
from api.indice_da_busca import Consulta, Filtros, Registro

CONFIG = ConfigDaBusca(
    projeto="proj-x", regiao="reg-y", colecao="col-z", indice="ind-w", dimensao=256
)


def test_config_vem_so_do_ambiente() -> None:
    ambiente = {
        "GCP_PROJECT_ID": "p",
        "BUSCA_REGIAO": "r",
        "BUSCA_COLECAO": "c",
        "BUSCA_INDICE": "i",
        "BUSCA_DIMENSAO": "128",
    }
    assert ConfigDaBusca.do_ambiente(ambiente) == ConfigDaBusca("p", "r", "c", "i", 128)
    with pytest.raises(KeyError):
        ConfigDaBusca.do_ambiente({})


def test_filtro_composto_junta_todos_os_campos_com_and() -> None:
    filtro = filtro_do_pedido(
        Filtros(tipo="objeto", categoria="roupa", cor_base="vermelho", dono="cat-1")
    )
    assert filtro == {
        "$and": [
            {"tipo": {"$eq": "objeto"}},
            {"categoria": {"$eq": "roupa"}},
            {"cor_base": {"$contains": "vermelho"}},
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
            {"pessoas": {"$contains": "cat-1"}},
            {"data_de_exibicao": {"$gte": "2026-01-02"}},
            {"data_de_exibicao": {"$lte": "2026-03-04"}},
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
    assert buscas["textSearch"]["searchText"] == "vestido vermelho"
    assert buscas["semanticSearch"]["searchText"] == "mulher de vestido de gala"
    assert buscas["semanticSearch"]["searchField"] == "descricao_vetor"
    assert buscas["vectorSearch"]["vector"] == {"values": [0.1, 0.2]}
    assert buscas["vectorSearch"]["searchField"] == "quadro_vetor"
    assert all(b["topK"] == 7 for b in buscas.values())
    filtro = {"$and": [{"tipo": {"$eq": "plano"}}]}
    assert all(b["filter"] == filtro for b in buscas.values())
    assert pedido["combine"] == {"ranker": {"rrf": {"weights": [1.0, 1.0, 1.0]}}}


def test_toda_busca_do_pedido_leva_o_index_hint_do_indice_ann() -> None:
    pedido = pedido_de_busca(
        CONFIG,
        Consulta(
            texto="a",
            significado="b",
            vetor_do_quadro=[0.0],
            filtros=Filtros(tipo="fala"),
        ),
    )
    nome = "projects/proj-x/locations/reg-y/collections/col-z/indexes/ind-w"
    for busca in _buscas(pedido).values():
        dica = busca["searchHint"]["indexHint"]
        assert dica == {"name": nome}
        assert busca["searchHint"]["targetRecall"] > 0


def test_so_filtros_vira_uma_busca_de_texto_vazia_com_index_hint() -> None:
    pedido = pedido_de_busca(CONFIG, Consulta(filtros=Filtros(tipo="objeto", dono="c")))
    [(chave, busca)] = _buscas(pedido).items()
    assert chave == "textSearch"
    assert busca["searchText"] == ""
    assert "indexHint" in busca["searchHint"]
    assert "combine" not in pedido


def test_esquema_da_colecao_tem_a_dimensao_e_os_campos_de_filtro() -> None:
    esquema = esquema_da_colecao(CONFIG)
    vetores = esquema["vectorSchema"]
    assert vetores["quadro_vetor"]["denseVector"]["dimensions"] == 256
    assert vetores["descricao_vetor"]["denseVector"]["dimensions"] == 256
    assert {"tipo", "cor_base", "dono", "categoria", "pessoas"} <= set(
        esquema["indice"]["filterFields"]
    )
    assert set(esquema["indice"]["filterFields"]) <= set(
        esquema["dataSchema"]["properties"]
    )


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
    [_, (metodo, caminho, corpo)] = transporte.chamadas
    assert (metodo, caminho.endswith("/dataObjects:batchCreate")) == ("POST", True)
    assert corpo is not None
    [pedido] = corpo["requests"]
    assert pedido["dataObjectId"] == "j-objeto-0"
    assert pedido["dataObject"]["data"]["cor_base"] == ["vermelho"]
    assert pedido["dataObject"]["data"]["data_de_exibicao"] == "2026-01-02"

    transporte.resposta = {"results": [{"dataObject": pedido["dataObject"]}]}
    [achado] = adaptador.buscar(Consulta(filtros=Filtros(dono="c")))
    assert achado == registro


def test_gravar_apaga_antes_os_registros_do_video() -> None:
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).gravar("j", [])
    [(metodo, caminho, corpo)] = transporte.chamadas
    assert metodo == "POST"
    assert caminho.endswith("/dataObjects:batchDelete")
    assert corpo == {"filter": {"job_id": {"$eq": "j"}}}


def test_caminho_leva_projeto_regiao_e_colecao_da_config() -> None:
    transporte = TransporteFalso()
    AgentRetrieval(CONFIG, transporte).apagar("j")
    [(_, caminho, _)] = transporte.chamadas
    assert (
        caminho
        == "projects/proj-x/locations/reg-y/collections/col-z/dataObjects:batchDelete"
    )


def test_criar_colecao_cria_a_colecao_e_o_indice_ann_com_os_campos_de_filtro() -> None:
    transporte = TransporteFalso()
    criar_colecao(CONFIG, transporte)
    [(m1, c1, corpo1), (m2, c2, corpo2)] = transporte.chamadas
    assert (m1, c1) == (
        "POST",
        "projects/proj-x/locations/reg-y/collections?collectionId=col-z",
    )
    assert corpo1 is not None and corpo1["dataSchema"]["properties"]["dono"]
    assert (m2, c2) == (
        "POST",
        "projects/proj-x/locations/reg-y/collections/col-z/indexes?indexId=ind-w",
    )
    assert corpo2 is not None and "dono" in corpo2["filterFields"]


def test_criar_colecao_e_idempotente() -> None:
    def ja_existe(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        raise JaExiste(caminho)

    criar_colecao(CONFIG, ja_existe)


def test_apagar_colecao_chama_delete() -> None:
    transporte = TransporteFalso()
    apagar_colecao(CONFIG, transporte)
    assert transporte.chamadas == [
        ("DELETE", "projects/proj-x/locations/reg-y/collections/col-z", None)
    ]
