"""Adaptador do índice da busca no Agent Retrieval (#117, ADR 0006).

Projeto, região, coleção, índice e dimensão chegam por variável de ambiente (o
`infra/main.tf` as entrega); nada disso é escrito aqui. A rede fica atrás de
`Transporte`: aqui moram a montagem dos pedidos e a leitura das respostas, testadas sem
rede. A coleção nasce com o índice ANN implantado e todo pedido de busca leva o
`searchHint.indexHint` dele, porque o KNN sem índice aceita no máximo 100 mil registros.

Os nomes dos campos do corpo REST seguem a documentação do Agent Retrieval de 30/10/2026;
quem confirma os nomes no ar é o #122 (`make medir-busca`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import google.auth
import google.auth.transport.requests

from api.indice_da_busca import Consulta, Filtros, Registro

URL_BASE = "https://vectorsearch.googleapis.com/v1beta"
RECALL_ALVO = 0.95
CAMPO_DO_VETOR_DA_DESCRICAO = "descricao_vetor"
CAMPO_DO_VETOR_DO_QUADRO = "quadro_vetor"
# Declarados no índice na criação: é ele que filtra junto com a busca.
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
    indice: str
    dimensao: int

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> "ConfigDaBusca":
        """Levanta `KeyError` se faltar uma variável: sem ela a busca não tem onde ir."""
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            regiao=ambiente["BUSCA_REGIAO"],
            colecao=ambiente["BUSCA_COLECAO"],
            indice=ambiente["BUSCA_INDICE"],
            dimensao=int(ambiente["BUSCA_DIMENSAO"]),
        )

    @property
    def local(self) -> str:
        return f"projects/{self.projeto}/locations/{self.regiao}"

    @property
    def caminho_da_colecao(self) -> str:
        return f"{self.local}/collections/{self.colecao}"

    @property
    def caminho_do_indice(self) -> str:
        return f"{self.caminho_da_colecao}/indexes/{self.indice}"


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
        condicoes.append({"cor_base": {"$contains": f.cor_base}})
    igual("dono", f.dono)
    if f.pessoa is not None:
        condicoes.append({"pessoas": {"$contains": f.pessoa}})
    igual("marca", f.marca)
    igual("relacao", f.relacao)
    if f.exibido_desde is not None:
        condicoes.append({"data_de_exibicao": {"$gte": f.exibido_desde.isoformat()}})
    if f.exibido_ate is not None:
        condicoes.append({"data_de_exibicao": {"$lte": f.exibido_ate.isoformat()}})
    return {"$and": condicoes} if condicoes else None


def pedido_de_busca(config: ConfigDaBusca, consulta: Consulta) -> dict[str, Any]:
    """O corpo do `batchSearch`: filtros, texto, significado e vetor, fundidos por RRF."""
    comum: dict[str, Any] = {
        "topK": consulta.limite,
        "searchHint": {
            "indexHint": {"name": config.caminho_do_indice},
            "targetRecall": RECALL_ALVO,
        },
    }
    filtro = filtro_do_pedido(consulta.filtros)
    if filtro is not None:
        comum["filter"] = filtro

    buscas: list[dict[str, Any]] = []
    if consulta.texto:
        buscas.append({"textSearch": {**comum, "searchText": consulta.texto}})
    if consulta.significado:
        buscas.append(
            {
                "semanticSearch": {
                    **comum,
                    "searchText": consulta.significado,
                    "searchField": CAMPO_DO_VETOR_DA_DESCRICAO,
                    "taskType": "RETRIEVAL_QUERY",
                }
            }
        )
    if consulta.vetor_do_quadro is not None:
        buscas.append(
            {
                "vectorSearch": {
                    **comum,
                    "searchField": CAMPO_DO_VETOR_DO_QUADRO,
                    "vector": {"values": consulta.vetor_do_quadro},
                }
            }
        )
    if not buscas:
        # Só filtros: uma busca de texto vazia, para o pedido ainda usar o índice.
        buscas.append({"textSearch": {**comum, "searchText": ""}})
    pedido: dict[str, Any] = {"searches": buscas}
    if len(buscas) > 1:
        pedido["combine"] = {"ranker": {"rrf": {"weights": [1.0] * len(buscas)}}}
    return pedido


def esquema_da_colecao(config: ConfigDaBusca) -> dict[str, Any]:
    """O esquema dos dados, os vetores e o índice ANN (com os campos de filtro)."""
    texto = {"type": "string"}
    lista = {"type": "array", "items": {"type": "string"}}
    numero = {"type": "integer"}
    propriedades: dict[str, Any] = {
        "id": texto,
        "tipo": texto,
        "job_id": texto,
        "programa": texto,
        "data_de_exibicao": texto,
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
        "indice": {
            "filterFields": CAMPOS_DE_FILTRO,
            "indexedVectorFields": [
                CAMPO_DO_VETOR_DA_DESCRICAO,
                CAMPO_DO_VETOR_DO_QUADRO,
            ],
        },
    }


class JaExiste(Exception):
    """O transporte levanta quando a coleção ou o índice já existe (HTTP 409)."""


def criar_colecao(config: ConfigDaBusca, transporte: Transporte) -> None:
    """Cria a coleção e o índice ANN dela; não faz nada no que já existe."""
    esquema = esquema_da_colecao(config)
    indice = {"filterFields": esquema["indice"]["filterFields"], "denseScann": {}} | {
        "indexedVectorFields": esquema["indice"]["indexedVectorFields"]
    }
    colecao = {k: esquema[k] for k in ("dataSchema", "vectorSchema")}
    for caminho, corpo in (
        (f"{config.local}/collections?collectionId={config.colecao}", colecao),
        (
            f"{config.caminho_da_colecao}/indexes?indexId={config.indice}",
            indice,
        ),
    ):
        try:
            transporte("POST", caminho, corpo)
        except JaExiste:
            pass


def apagar_colecao(config: ConfigDaBusca, transporte: Transporte) -> None:
    transporte("DELETE", config.caminho_da_colecao, None)


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
        "data_de_exibicao": r.data_de_exibicao.isoformat()
        if r.data_de_exibicao
        else None,
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
        data_de_exibicao=date.fromisoformat(data) if data else None,
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
        for i in range(0, len(registros), 200):
            pedacos = registros[i : i + 200]
            self._chamar(
                "dataObjects:batchCreate", {"requests": [_criacao(r) for r in pedacos]}
            )

    def buscar(self, consulta: Consulta) -> list[Registro]:
        resposta = self._chamar(
            "dataObjects:batchSearch", pedido_de_busca(self._config, consulta)
        )
        return [_registro(r["dataObject"]["data"]) for r in resposta.get("results", [])]

    def total(self) -> int:
        resposta = self._chamar("dataObjects:aggregate", {"aggregate": "COUNT"})
        return int(resposta.get("count", 0))


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
