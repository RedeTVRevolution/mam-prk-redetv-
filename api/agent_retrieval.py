"""Adaptador do índice da busca no Agent Retrieval (#117, ADR 0006).

Projeto, região, coleção, índices e dimensão chegam por variável de ambiente (o
`infra/main.tf` as entrega); nada disso é escrito aqui. A rede fica atrás de
`Transporte`: aqui moram a montagem dos pedidos e a leitura das respostas, testadas sem
rede. Cada vetor tem o seu índice ANN (um índice cobre um só campo de vetor), implantado
junto com a coleção, e toda busca por vetor leva o `searchHint.indexHint` dele, porque o
KNN sem índice aceita no máximo 100 mil registros.

Os nomes dos campos do corpo REST seguem a documentação do Agent Retrieval de 30/10/2026;
quem confirma os nomes no ar é o #122 (`make medir-busca`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from time import sleep
from typing import Any, Protocol

import google.auth
import google.auth.transport.requests

from api.indice_da_busca import Consulta, Filtros, Registro

URL_BASE = "https://vectorsearch.googleapis.com/v1beta"
RECALL_ALVO = 0.95
REGISTROS_POR_LOTE = 200
CAMPO_DO_VETOR_DA_DESCRICAO = "descricao_vetor"
CAMPO_DO_VETOR_DO_QUADRO = "quadro_vetor"
# Onde a busca por texto procura.
CAMPOS_DE_TEXTO = ["texto", "descricao"]
# Declarados nos índices na criação: são eles que filtram junto com a busca.
CAMPOS_DE_FILTRO = [
    "tipo",
    "job_id",
    "programa",
    "data_de_exibicao",
    "pessoas",
    "categoria",
    "cor_base",
    "dono",
    "marca",
    "relacao",
]


class Transporte(Protocol):
    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Uma chamada REST; `caminho` é relativo à URL base."""
        ...


@dataclass(frozen=True)
class ConfigDaBusca:
    projeto: str
    regiao: str
    colecao: str
    indice_da_descricao: str
    indice_do_quadro: str
    dimensao: int

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> "ConfigDaBusca":
        """Levanta `KeyError` se faltar uma variável: sem ela a busca não tem onde ir."""
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            regiao=ambiente["BUSCA_REGIAO"],
            colecao=ambiente["BUSCA_COLECAO"],
            indice_da_descricao=ambiente["BUSCA_INDICE_DESCRICAO"],
            indice_do_quadro=ambiente["BUSCA_INDICE_QUADRO"],
            dimensao=int(ambiente["BUSCA_DIMENSAO"]),
        )

    @property
    def local(self) -> str:
        return f"projects/{self.projeto}/locations/{self.regiao}"

    @property
    def caminho_da_colecao(self) -> str:
        return f"{self.local}/collections/{self.colecao}"

    @property
    def indices(self) -> dict[str, str]:
        """O id do índice ANN de cada campo de vetor."""
        return {
            CAMPO_DO_VETOR_DA_DESCRICAO: self.indice_da_descricao,
            CAMPO_DO_VETOR_DO_QUADRO: self.indice_do_quadro,
        }

    def caminho_do_indice(self, campo: str) -> str:
        return f"{self.caminho_da_colecao}/indexes/{self.indices[campo]}"


def _dia(d: date) -> int:
    """A data como AAAAMMDD: os filtros de intervalo só valem para número."""
    return d.year * 10_000 + d.month * 100 + d.day


def _data(dia: int) -> date:
    return date(dia // 10_000, dia // 100 % 100, dia % 100)


def filtro_do_pedido(f: Filtros) -> dict[str, Any] | None:
    condicoes: list[dict[str, Any]] = []

    def igual(campo: str, valor: str | None) -> None:
        if valor is not None:
            condicoes.append({campo: {"$eq": valor}})

    igual("tipo", f.tipo)
    igual("job_id", f.job_id)
    igual("programa", f.programa)
    igual("categoria", f.categoria)
    if f.cor_base is not None:
        condicoes.append({"cor_base": {"$all": [f.cor_base]}})
    igual("dono", f.dono)
    if f.pessoa is not None:
        condicoes.append({"pessoas": {"$all": [f.pessoa]}})
    igual("marca", f.marca)
    igual("relacao", f.relacao)
    if f.exibido_desde is not None:
        condicoes.append({"data_de_exibicao": {"$gte": _dia(f.exibido_desde)}})
    if f.exibido_ate is not None:
        condicoes.append({"data_de_exibicao": {"$lte": _dia(f.exibido_ate)}})
    return {"$and": condicoes} if condicoes else None


def pedido_de_busca(config: ConfigDaBusca, consulta: Consulta) -> dict[str, Any]:
    """O corpo do `batchSearch`: filtros, texto, significado e vetor, fundidos por RRF.

    As buscas por vetor (significado e quadro) levam o `indexHint` do índice ANN do seu
    campo; a busca por texto não é KNN e não usa índice de vetor. Só filtros não é busca:
    levanta `ValueError`.
    """
    comum: dict[str, Any] = {
        "topK": consulta.limite,
        "outputFields": {"dataFields": "*"},
    }
    filtro = filtro_do_pedido(consulta.filtros)
    if filtro is not None:
        comum["filter"] = filtro

    def no_indice(campo: str) -> dict[str, Any]:
        return {
            **comum,
            "searchField": campo,
            "searchHint": {
                "indexHint": {
                    "name": config.caminho_do_indice(campo),
                    "denseScannParams": {"targetRecall": RECALL_ALVO},
                }
            },
        }

    buscas: list[dict[str, Any]] = []
    if consulta.texto:
        texto = {"text": consulta.texto, "fields": CAMPOS_DE_TEXTO}
        buscas.append({"textSearch": {**comum, "structuredQuery": {"text": texto}}})
    if consulta.significado:
        buscas.append(
            {
                "semanticSearch": {
                    **no_indice(CAMPO_DO_VETOR_DA_DESCRICAO),
                    "searchText": consulta.significado,
                    "taskType": "RETRIEVAL_QUERY",
                }
            }
        )
    if consulta.vetor_do_quadro is not None:
        buscas.append(
            {
                "vectorSearch": {
                    **no_indice(CAMPO_DO_VETOR_DO_QUADRO),
                    "vector": {"values": consulta.vetor_do_quadro},
                }
            }
        )
    if not buscas:
        raise ValueError("a busca precisa de texto, significado ou vetor do quadro")
    pedido: dict[str, Any] = {"searches": buscas}
    if len(buscas) > 1:
        pedido["combine"] = {"ranker": {"rrf": {"weights": [1.0] * len(buscas)}}}
    return pedido


def esquema_da_colecao(config: ConfigDaBusca) -> dict[str, Any]:
    """O esquema dos dados e dos vetores da coleção."""
    texto = {"type": "string"}
    lista = {"type": "array", "items": {"type": "string"}}
    numero = {"type": "integer"}
    propriedades: dict[str, Any] = {
        "id": texto,
        "tipo": texto,
        "job_id": texto,
        "programa": texto,
        "data_de_exibicao": numero,  # AAAAMMDD
        "inicio_ms": numero,
        "fim_ms": numero,
        "pessoas": lista,
        "categoria": texto,
        "tipo_do_objeto": texto,
        "cor_base": lista,
        "cor": texto,
        "marca": texto,
        "dono": texto,
        "relacao": texto,
        "texto": texto,
        "descricao": texto,
        "quadro": texto,
    }
    return {
        "dataSchema": {"type": "object", "properties": propriedades},
        "vectorSchema": {
            CAMPO_DO_VETOR_DA_DESCRICAO: {
                "denseVector": {
                    "dimensions": config.dimensao,
                    "vertexEmbeddingConfig": {"textTemplate": "{descricao}"},
                }
            },
            CAMPO_DO_VETOR_DO_QUADRO: {"denseVector": {"dimensions": config.dimensao}},
        },
    }


def indices_da_colecao(config: ConfigDaBusca) -> dict[str, dict[str, Any]]:
    """O corpo de cada índice ANN, pelo id: um campo de vetor, os de filtro e os guardados."""
    guardados = list(esquema_da_colecao(config)["dataSchema"]["properties"])
    return {
        indice: {
            "indexField": campo,
            "filterFields": CAMPOS_DE_FILTRO,
            "storeFields": guardados,
        }
        for campo, indice in config.indices.items()
    }


class JaExiste(Exception):
    """O transporte levanta quando a coleção ou o índice já existe (HTTP 409)."""


def esperar(
    operacao: dict[str, Any],
    transporte: Transporte,
    dormir: Callable[[float], None] = sleep,
    intervalo_s: float = 10.0,
) -> None:
    """Espera a operação de longa duração (criar ou apagar coleção e índice) terminar."""
    while not operacao.get("done", True):
        dormir(intervalo_s)
        operacao = transporte("GET", operacao["name"], None)
    if "error" in operacao:
        raise RuntimeError(f"operação {operacao.get('name')}: {operacao['error']}")


def criar_colecao(
    config: ConfigDaBusca,
    transporte: Transporte,
    dormir: Callable[[float], None] = sleep,
) -> None:
    """Cria a coleção e os índices ANN dela, um depois do outro, esperando cada um
    ficar pronto; não faz nada no que já existe."""
    pedidos = [
        (
            f"{config.local}/collections?collectionId={config.colecao}",
            esquema_da_colecao(config),
        )
    ] + [
        (f"{config.caminho_da_colecao}/indexes?indexId={indice}", corpo)
        for indice, corpo in indices_da_colecao(config).items()
    ]
    for caminho, corpo in pedidos:
        try:
            operacao = transporte("POST", caminho, corpo)
        except JaExiste:
            continue
        esperar(operacao, transporte, dormir)


def apagar_colecao(
    config: ConfigDaBusca,
    transporte: Transporte,
    dormir: Callable[[float], None] = sleep,
) -> None:
    """Apaga a coleção (e os índices dela) e espera a operação terminar."""
    esperar(transporte("DELETE", config.caminho_da_colecao, None), transporte, dormir)


def _dados(r: Registro) -> dict[str, Any]:
    dados: dict[str, Any] = {
        "id": r.id,
        "tipo": r.tipo,
        "job_id": r.job_id,
        "inicio_ms": r.inicio_ms,
        "fim_ms": r.fim_ms,
        "pessoas": r.pessoas,
        "cor_base": r.cor_base,
    }
    opcionais = {
        "programa": r.programa,
        "data_de_exibicao": _dia(r.data_de_exibicao) if r.data_de_exibicao else None,
        "categoria": r.categoria,
        "tipo_do_objeto": r.tipo_do_objeto,
        "cor": r.cor,
        "marca": r.marca,
        "dono": r.dono,
        "relacao": r.relacao,
        "texto": r.texto,
        "descricao": r.descricao,
        "quadro": r.quadro,
    }
    return dados | {k: v for k, v in opcionais.items() if v is not None}


def _registro(dados: dict[str, Any]) -> Registro:
    data = dados.get("data_de_exibicao")
    return Registro(
        id=dados["id"],
        tipo=dados["tipo"],
        job_id=dados["job_id"],
        inicio_ms=dados["inicio_ms"],
        fim_ms=dados["fim_ms"],
        programa=dados.get("programa"),
        data_de_exibicao=_data(int(data)) if data else None,
        pessoas=dados.get("pessoas", []),
        categoria=dados.get("categoria"),
        tipo_do_objeto=dados.get("tipo_do_objeto"),
        cor_base=dados.get("cor_base", []),
        cor=dados.get("cor"),
        marca=dados.get("marca"),
        dono=dados.get("dono"),
        relacao=dados.get("relacao"),
        texto=dados.get("texto"),
        descricao=dados.get("descricao"),
        quadro=dados.get("quadro"),
    )


def _criacao(r: Registro) -> dict[str, Any]:
    objeto: dict[str, Any] = {"data": _dados(r)}
    if r.vetor_do_quadro is not None:
        objeto["vectors"] = {
            CAMPO_DO_VETOR_DO_QUADRO: {"dense": {"values": r.vetor_do_quadro}}
        }
    # O id do objeto não aceita ":".
    return {"dataObjectId": r.id.replace(":", "-"), "dataObject": objeto}


class AgentRetrieval:
    def __init__(self, config: ConfigDaBusca, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def _chamar(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        return self._transporte(
            "POST", f"{self._config.caminho_da_colecao}/{caminho}", corpo
        )

    def apagar(self, job_id: str) -> None:
        self._chamar("dataObjects:batchDelete", {"filter": {"job_id": {"$eq": job_id}}})

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        self.apagar(job_id)
        for i in range(0, len(registros), REGISTROS_POR_LOTE):
            pedacos = registros[i : i + REGISTROS_POR_LOTE]
            self._chamar(
                "dataObjects:batchCreate", {"requests": [_criacao(r) for r in pedacos]}
            )

    def buscar(self, consulta: Consulta) -> list[Registro]:
        resposta = self._chamar(
            "dataObjects:batchSearch", pedido_de_busca(self._config, consulta)
        )
        return [_registro(r["dataObject"]["data"]) for r in resposta.get("results", [])]

    def total(self) -> int:
        resposta = self._chamar("dataObjects:aggregate", {"aggregate": "count"})
        return sum(int(r.get("count", 0)) for r in resposta.get("aggregateResults", []))


def transporte_http() -> Transporte:
    """O transporte real: REST com as credenciais padrão (ADC) de quem roda."""
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = google.auth.transport.requests.AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]

    def chamar(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        resposta = sessao.request(  # type: ignore[no-untyped-call]
            metodo, f"{URL_BASE}/{caminho}", json=corpo, timeout=60
        )
        if resposta.status_code == 409:
            raise JaExiste(caminho)
        resposta.raise_for_status()
        return dict(resposta.json()) if resposta.content else {}

    return chamar
