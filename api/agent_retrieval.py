"""Adaptador do índice da busca no Agent Retrieval (#117, ADR 0006).

Projeto, região, coleção, índices e dimensão chegam por variável de ambiente (o
`infra/modulos/mam/main.tf` as entrega); nada disso é escrito aqui. A rede fica atrás de
`Transporte`: aqui moram a montagem dos pedidos e a leitura das respostas, testadas sem
rede. Cada vetor tem o seu índice ANN (um índice cobre um só campo de vetor), implantado
junto com a coleção, e toda busca por vetor leva o `searchHint.indexHint` dele, porque o
KNN sem índice aceita no máximo 100 mil registros. Com `BUSCA_INDICES_LIGADOS=false` (o
dev, por custo) não há índice ANN: a coleção nasce sem eles e a busca vai pelo KNN
(`knnHint` explícito, cosseno), com o embedding da consulta calculado aqui.

Os corpos REST seguem o documento de discovery da API (`v1beta`, revisão 20261022),
conferido no #122.
"""

import logging
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from time import monotonic, sleep
from typing import Any, Protocol

import google.auth
import google.auth.transport.requests

from api.comparador import normalizar
from api.indice_da_busca import Consulta, Filtros, Registro

log = logging.getLogger(__name__)

URL_BASE = "https://vectorsearch.googleapis.com/v1beta"
RECALL_ALVO = 0.95
# O KNN aceita até 100 mil registros; a gravação avisa ao passar deste limite (sem índice).
AVISO_DO_TETO_DO_KNN = 80_000
REGISTROS_POR_LOTE = 200
# O `gravar` escreve até esta fração da cota de escrita da coleção (`cota_de_escrita`):
# com 3.000 objetos por minuto, 13 lotes de 200. A folga cobre a diferença entre o
# relógio daqui e o do serviço (#411).
FRACAO_DA_COTA = 0.9
# As esperas, em segundos, antes de cada nova tentativa no 429 (cota esgotada): 315 s no
# total por chamada, dentro dos 1800 s do Job de indexação e do de purga. Só nos Jobs
# (`tentar_no_429`) e só as chamadas da gravação e da purga; a busca nunca espera.
ESPERAS_NO_429_S = (5.0, 10.0, 20.0, 40.0, 60.0, 60.0, 60.0, 60.0)
COM_NOVA_TENTATIVA = (
    "dataObjects:batchCreate",
    "dataObjects:batchDelete",
    "dataObjects:query",
)
# O máximo de nomes por `batchDelete` e de objetos por página do `query`.
OBJETOS_POR_PAGINA = 1000
# O embedding automático da descrição: texto multilíngue, reduzido à dimensão da coleção.
MODELO_DO_EMBEDDING = "gemini-embedding-001"
# Réplicas de cada índice ANN, cobradas por hora: uma basta para a PoC.
REPLICAS_DO_INDICE = 1
CAMPO_DO_VETOR_DA_DESCRICAO = "descricao_vetor"
CAMPO_DO_VETOR_DO_QUADRO = "quadro_vetor"
# Onde a busca por texto procura: a cópia de `texto` e `descricao` sem acento nem
# maiúscula, porque o `textSearch` compara com o texto gravado como está. A consulta
# vai normalizada também.
CAMPO_DO_TEXTO_DA_BUSCA = "texto_da_busca"
CAMPOS_DE_TEXTO = [CAMPO_DO_TEXTO_DA_BUSCA]
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
        """Uma chamada REST; `caminho` é relativo à URL base, salvo se for uma URL inteira."""
        ...


@dataclass(frozen=True)
class ConfigDaBusca:
    projeto: str
    regiao: str
    colecao: str
    indice_da_descricao: str
    # None: o índice do quadro-chave está desligado (ADR 0006), e a busca por quadro também.
    indice_do_quadro: str | None
    dimensao: int
    # O corte do que vem só da busca por significado (`Consulta.cortar_significado`): a
    # distância de cosseno máxima e o mínimo de palavras do registro. Falas curtas ("ok.",
    # "Tchau,") ficam perto de qualquer consulta. None: sem corte.
    distancia_maxima: float | None = None
    palavras_minimas: int = 0
    # False: sem índice ANN nenhum (o dev, por custo; ADR 0006). As buscas por vetor vão
    # sem `searchHint`, pelo KNN, que aceita até 100 mil registros. O vetor do quadro e a
    # busca por quadro continuam presos a `indice_do_quadro`.
    indices_ligados: bool = True
    # A cota `data_object_writes` da coleção, em objetos por minuto, que vale para todos
    # os vídeos gravando juntos. None: o `gravar` não segura o ritmo (#411).
    cota_de_escrita: int | None = None

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> "ConfigDaBusca":
        """Levanta `KeyError` se faltar uma variável: sem ela a busca não tem onde ir.
        `BUSCA_INDICE_QUADRO` vazia desliga o índice do quadro-chave.
        `BUSCA_INDICES_LIGADOS=false` desliga os índices ANN; ausente ou vazia, ficam
        ligados, e outro valor que não `true` ou `false` levanta `ValueError`. O corte
        (`BUSCA_DISTANCIA_MAXIMA`, `BUSCA_PALAVRAS_MINIMAS`) só o serviço e o
        `make sondar-busca` recebem. `BUSCA_COTA_DE_ESCRITA` só quem grava; ausente ou
        vazia, sem ritmo."""
        distancia = ambiente.get("BUSCA_DISTANCIA_MAXIMA")
        cota = ambiente.get("BUSCA_COTA_DE_ESCRITA")
        ligados = (ambiente.get("BUSCA_INDICES_LIGADOS") or "true").strip().lower()
        if ligados not in ("true", "false"):
            raise ValueError(f"BUSCA_INDICES_LIGADOS inválida: {ligados!r}")
        if cota and int(cota) <= 0:
            # Gravaria um lote por minuto, sem aviso.
            raise ValueError(f"BUSCA_COTA_DE_ESCRITA inválida: {cota!r}")
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            regiao=ambiente["BUSCA_REGIAO"],
            colecao=ambiente["BUSCA_COLECAO"],
            indice_da_descricao=ambiente["BUSCA_INDICE_DESCRICAO"],
            indice_do_quadro=ambiente["BUSCA_INDICE_QUADRO"] or None,
            dimensao=int(ambiente["BUSCA_DIMENSAO"]),
            distancia_maxima=float(distancia) if distancia else None,
            palavras_minimas=int(ambiente.get("BUSCA_PALAVRAS_MINIMAS") or 0),
            indices_ligados=ligados == "true",
            cota_de_escrita=int(cota) if cota else None,
        )

    @property
    def local(self) -> str:
        return f"projects/{self.projeto}/locations/{self.regiao}"

    @property
    def caminho_da_colecao(self) -> str:
        return f"{self.local}/collections/{self.colecao}"

    @property
    def indices(self) -> dict[str, str]:
        """O id do índice ANN de cada campo de vetor ligado; nenhum sem `indices_ligados`."""
        if not self.indices_ligados:
            return {}
        indices = {CAMPO_DO_VETOR_DA_DESCRICAO: self.indice_da_descricao}
        if self.indice_do_quadro is not None:
            indices[CAMPO_DO_VETOR_DO_QUADRO] = self.indice_do_quadro
        return indices

    def caminho_do_indice(self, campo: str) -> str:
        return f"{self.caminho_da_colecao}/indexes/{self.indices[campo]}"


def _dia(d: date) -> int:
    """A data como AAAAMMDD: os filtros de intervalo só valem para número."""
    return d.year * 10_000 + d.month * 100 + d.day


def _data(dia: int) -> date:
    return date(dia // 10_000, dia // 100 % 100, dia % 100)


def filtro_do_pedido(f: Filtros) -> dict[str, Any] | None:
    """O filtro JSON. Nos campos de lista vai `$in` com um valor: servido pelo índice
    ANN, `$all` só vale no topo do filtro, e não dentro do `$and`."""
    condicoes: list[dict[str, Any]] = []

    def igual(campo: str, valor: str | None) -> None:
        if valor is not None:
            condicoes.append({campo: {"$eq": valor}})

    igual("tipo", f.tipo)
    igual("job_id", f.job_id)
    igual("programa", f.programa)
    igual("categoria", f.categoria)
    if f.cor_base is not None:
        condicoes.append({"cor_base": {"$in": [f.cor_base]}})
    igual("dono", f.dono)
    if f.pessoa is not None:
        condicoes.append({"pessoas": {"$in": [f.pessoa]}})
    igual("marca", f.marca)
    igual("relacao", f.relacao)
    if f.exibido_desde is not None:
        condicoes.append({"data_de_exibicao": {"$gte": _dia(f.exibido_desde)}})
    if f.exibido_ate is not None:
        condicoes.append({"data_de_exibicao": {"$lte": _dia(f.exibido_ate)}})
    return {"$and": condicoes} if condicoes else None


def pedido_de_busca(
    config: ConfigDaBusca,
    consulta: Consulta,
    vetor_do_significado: list[float] | None = None,
) -> dict[str, Any]:
    """O corpo do `batchSearch`: filtros, texto, significado e vetor, fundidos por RRF.

    As buscas por vetor (significado e quadro) levam o `indexHint` do índice ANN do seu
    campo. Com os índices desligados (`indices_ligados`) vão pelo KNN, com `knnHint`
    explícito (o serviço usaria um índice que ainda existisse) e `COSINE_DISTANCE` (o
    padrão do KNN é o produto escalar, que não serve a vetores sem norma 1). O
    `semanticSearch` não aceita `distanceMetric` e no KNN ordena por produto escalar: o
    significado vai então como `vectorSearch` com `vetor_do_significado`, o embedding da
    consulta (`AgentRetrieval.vetor_da_consulta`), obrigatório nesse caso. A busca por
    texto não é KNN e não usa índice de vetor. Só filtros não é busca: levanta
    `ValueError`.
    """
    comum: dict[str, Any] = {
        "topK": consulta.limite,
        "outputFields": {"dataFields": ["*"]},
    }
    filtro = filtro_do_pedido(consulta.filtros)
    if filtro is not None:
        comum["filter"] = filtro

    def no_indice(campo: str) -> dict[str, Any]:
        if not config.indices_ligados:
            return {
                **comum,
                "searchField": campo,
                "searchHint": {"knnHint": {}},
                "distanceMetric": "COSINE_DISTANCE",
            }
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
        texto = {"text": normalizar(consulta.texto), "fields": CAMPOS_DE_TEXTO}
        buscas.append({"textSearch": {**comum, "structuredQuery": {"text": texto}}})
    if consulta.significado and not config.indices_ligados:
        if vetor_do_significado is None:
            raise ValueError(
                "sem os índices ANN, o significado pede o vetor da consulta"
            )
        buscas.append(
            {
                "vectorSearch": {
                    **no_indice(CAMPO_DO_VETOR_DA_DESCRICAO),
                    "vector": {"values": vetor_do_significado},
                }
            }
        )
    elif consulta.significado:
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
        if config.indice_do_quadro is None:
            # Desligado, nenhum vetor de quadro é calculado na indexação
            # (`embedding_da_busca`): não há o que achar.
            raise ValueError("o índice do quadro-chave está desligado")
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
    if consulta.cortar_significado:
        # A distância de cada busca, mesmo depois da fusão: é ela que o corte lê.
        pedido["metadataOptions"] = {"searchSignalsEnabled": True}
    if len(buscas) > 1:
        pedido["combine"] = {
            "ranker": {"rrf": {"weights": [1.0] * len(buscas)}},
            "topK": consulta.limite,
            "outputFields": comum["outputFields"],
        }
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
        CAMPO_DO_TEXTO_DA_BUSCA: texto,
        "quadro": texto,
        "destaque": numero,
        # Só para o embedding automático, que recusa registro sem texto: a descrição do
        # plano ou o texto da fala, do texto na tela ou do objeto (ADR 0006).
        "significado": texto,
    }
    return {
        "dataSchema": {"type": "object", "properties": propriedades},
        "vectorSchema": {
            CAMPO_DO_VETOR_DA_DESCRICAO: {
                "denseVector": {
                    "dimensions": config.dimensao,
                    "vertexEmbeddingConfig": {
                        "modelId": MODELO_DO_EMBEDDING,
                        "textTemplate": "{significado}",
                        "taskType": "RETRIEVAL_DOCUMENT",
                    },
                }
            },
            CAMPO_DO_VETOR_DO_QUADRO: {"denseVector": {"dimensions": config.dimensao}},
        },
    }


def indices_da_colecao(config: ConfigDaBusca) -> dict[str, dict[str, Any]]:
    """O corpo de cada índice ANN, pelo id: um campo de vetor, os de filtro e os guardados.
    Vazio com os índices desligados (`indices_ligados`)."""
    propriedades = esquema_da_colecao(config)["dataSchema"]["properties"]
    guardados = [p for p in propriedades if p != "significado"]
    return {
        indice: {
            "indexField": campo,
            # O embedding reduzido de dimensão não sai normalizado: o produto escalar
            # (o padrão) favoreceria os vetores mais longos.
            "distanceMetric": "COSINE_DISTANCE",
            "filterFields": CAMPOS_DE_FILTRO,
            "storeFields": guardados,
            "dedicatedInfrastructure": {
                "mode": "PERFORMANCE_OPTIMIZED",
                "autoscalingSpec": {
                    "minReplicaCount": REPLICAS_DO_INDICE,
                    "maxReplicaCount": REPLICAS_DO_INDICE,
                },
            },
        }
        for campo, indice in config.indices.items()
    }


class JaExiste(Exception):
    """O transporte levanta quando a coleção ou o índice já existe (HTTP 409)."""


class CotaEsgotada(RuntimeError):
    """O transporte levanta no HTTP 429 (RESOURCE_EXHAUSTED): a cota esgotou por ora."""


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


ORIENTACAO_DO_ESQUEMA = (
    "o PATCH só acrescenta propriedade; apague a coleção, rode "
    "`make criar-colecao-da-busca` e `make reindexar`"
)


class EsquemaIncompativel(RuntimeError):
    """A coleção no ar tem campo com tipo diferente ou que sobra: o PATCH não resolve."""


def _assinatura(propriedade: dict[str, Any]) -> tuple[Any, Any]:
    # A API pode devolver outros atributos; só o tipo conta.
    return propriedade.get("type"), propriedade.get("items", {}).get("type")


def _tipo(propriedade: dict[str, Any]) -> str:
    tipo, itens = _assinatura(propriedade)
    return f"{tipo}<{itens}>" if itens else str(tipo)


def comparar_esquema(
    config: ConfigDaBusca, no_ar: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """As propriedades do esquema que faltam na coleção `no_ar`. Tipo diferente ou campo
    que sobra na coleção não se resolve por PATCH: levanta EsquemaIncompativel nomeando o campo."""
    esperadas = esquema_da_colecao(config)["dataSchema"]["properties"]
    existentes = no_ar.get("dataSchema", {}).get("properties", {})
    for campo, propriedade in existentes.items():
        if campo not in esperadas:
            raise EsquemaIncompativel(
                f"coleção {config.colecao}: o campo {campo!r} sobra no esquema; {ORIENTACAO_DO_ESQUEMA}"
            )
        if _assinatura(propriedade) != _assinatura(esperadas[campo]):
            raise EsquemaIncompativel(
                f"coleção {config.colecao}: o campo {campo!r} é {_tipo(propriedade)} "
                f"e deveria ser {_tipo(esperadas[campo])}; {ORIENTACAO_DO_ESQUEMA}"
            )
    return {c: p for c, p in esperadas.items() if c not in existentes}


def conferir_esquema(config: ConfigDaBusca, transporte: Transporte) -> list[str]:
    """Os campos de `CAMPOS_DE_TEXTO` que faltam no esquema real da coleção."""
    no_ar = transporte("GET", config.caminho_da_colecao, None)
    existentes = no_ar.get("dataSchema", {}).get("properties", {})
    return [c for c in CAMPOS_DE_TEXTO if c not in existentes]


def _acrescentar_campos(
    config: ConfigDaBusca,
    transporte: Transporte,
    dormir: Callable[[float], None],
) -> list[str]:
    no_ar = transporte("GET", config.caminho_da_colecao, None)
    faltam = comparar_esquema(config, no_ar)
    if not faltam:
        return []
    # O PATCH com `updateMask=dataSchema` troca o esquema inteiro: parte do que está no ar.
    esquema = dict(no_ar.get("dataSchema", {"type": "object"}))
    esquema["properties"] = {**esquema.get("properties", {}), **faltam}
    operacao = transporte(
        "PATCH",
        f"{config.caminho_da_colecao}?updateMask=dataSchema",
        {"dataSchema": esquema},
    )
    esperar(operacao, transporte, dormir)
    return list(faltam)


def criar_colecao(
    config: ConfigDaBusca,
    transporte: Transporte,
    dormir: Callable[[float], None] = sleep,
) -> list[str]:
    """Cria a coleção e os índices ANN dela, um depois do outro, esperando cada um
    ficar pronto. Na coleção que já existe, acrescenta por PATCH as propriedades que
    faltam no esquema (devolvidas; os registros já gravados só são achados depois de
    `make reindexar`) e para com erro se o tipo difere ou se sobra campo. Não mexe nos
    índices que já existem."""
    acrescentados: list[str] = []
    try:
        operacao = transporte(
            "POST",
            f"{config.local}/collections?collectionId={config.colecao}",
            esquema_da_colecao(config),
        )
    except JaExiste:
        acrescentados = _acrescentar_campos(config, transporte, dormir)
    else:
        esperar(operacao, transporte, dormir)
    for indice, corpo in indices_da_colecao(config).items():
        try:
            operacao = transporte(
                "POST", f"{config.caminho_da_colecao}/indexes?indexId={indice}", corpo
            )
        except JaExiste:
            continue
        esperar(operacao, transporte, dormir)
    return acrescentados


def apagar_colecao(
    config: ConfigDaBusca,
    transporte: Transporte,
    dormir: Callable[[float], None] = sleep,
) -> None:
    """Apaga a coleção com os índices e os objetos dela e espera a operação terminar."""
    caminho = f"{config.caminho_da_colecao}?force=true"
    esperar(transporte("DELETE", caminho, None), transporte, dormir)


def _dados(r: Registro) -> dict[str, Any]:
    dados: dict[str, Any] = {
        "id": r.id,
        "tipo": r.tipo,
        "job_id": r.job_id,
        "inicio_ms": r.inicio_ms,
        "fim_ms": r.fim_ms,
        "pessoas": r.pessoas,
        "cor_base": r.cor_base,
        # Nunca vazio: o tipo é o último recurso.
        "significado": r.descricao or r.texto or r.tipo,
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
        "destaque": r.destaque,
    }
    # O que a tela mostra fica em `texto` e `descricao`; esta é só para o `textSearch`.
    if r.texto or r.descricao:
        opcionais[CAMPO_DO_TEXTO_DA_BUSCA] = normalizar(
            " ".join(p for p in (r.texto, r.descricao) if p)
        )
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
        destaque=dados.get("destaque"),
    )


def _criacao(r: Registro) -> dict[str, Any]:
    objeto: dict[str, Any] = {"data": _dados(r)}
    if r.vetor_do_quadro is not None:
        objeto["vectors"] = {
            CAMPO_DO_VETOR_DO_QUADRO: {"dense": {"values": r.vetor_do_quadro}}
        }
    # O id do objeto é RFC 1035: começa por letra (o job_id pode começar por dígito) e
    # não aceita ":".
    return {"dataObjectId": "m-" + r.id.replace(":", "-"), "dataObject": objeto}


class AgentRetrieval:
    def __init__(
        self,
        config: ConfigDaBusca,
        transporte: Transporte,
        *,
        tentar_no_429: bool = False,
        dormir: Callable[[float], None] = sleep,
        relogio: Callable[[], float] = monotonic,
    ) -> None:
        """`tentar_no_429` só nos Jobs (indexação, `make reindexar`, purga): o serviço
        web não segura a thread da busca esperando a cota, e o 429 volta na hora."""
        self._config = config
        self._transporte = transporte
        self._tentar_no_429 = tentar_no_429
        self._dormir = dormir
        self._relogio = relogio
        # Os lotes do `gravar` no último minuto, (quando, objetos): o ritmo vale entre os
        # vídeos que o mesmo processo grava (o `make reindexar` de todos).
        self._escritas: deque[tuple[float, int]] = deque()
        # Uma busca do usuário repete o mesmo texto em várias cláusulas (a livre e a de cada
        # pessoa na imagem): cada texto é embutido uma vez só, até 256 textos.
        self._vetores: dict[str, list[float]] = {}

    def _chamar(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        """Com `tentar_no_429`, as chamadas de `COM_NOVA_TENTATIVA` esperam e tentam de
        novo no 429: a cota de escrita é da coleção, e dois vídeos indexando juntos a
        dividem (#411)."""
        url = f"{self._config.caminho_da_colecao}/{caminho}"
        tenta = self._tentar_no_429 and caminho in COM_NOVA_TENTATIVA
        esperas = ESPERAS_NO_429_S if tenta else ()
        for espera in esperas:
            try:
                return self._transporte("POST", url, corpo)
            except CotaEsgotada:
                log.warning(
                    "%s: cota esgotada, nova tentativa em %.0f s", caminho, espera
                )
                self._dormir(espera)
        return self._transporte("POST", url, corpo)

    def _no_ritmo(self, objetos: int) -> None:
        """Espera até os objetos gravados nos últimos 60 s, mais estes, caberem na fração
        `FRACAO_DA_COTA` da cota de escrita. Sem cota configurada, não espera."""
        if self._config.cota_de_escrita is None:
            return
        limite = self._config.cota_de_escrita * FRACAO_DA_COTA
        while True:
            agora = self._relogio()
            while self._escritas and self._escritas[0][0] <= agora - 60:
                self._escritas.popleft()
            gravados = sum(n for _, n in self._escritas)
            if not self._escritas or gravados + objetos <= limite:
                self._escritas.append((agora, objetos))
                return
            self._dormir(self._escritas[0][0] + 60 - agora)

    def apagar(self, job_id: str) -> None:
        """O `batchDelete` só aceita nomes: junta os do vídeo, página a página, e apaga."""
        pedido: dict[str, Any] = {
            "filter": {"job_id": {"$eq": job_id}},
            "pageSize": OBJETOS_POR_PAGINA,
        }
        nomes: list[str] = []
        while True:
            pagina = self._chamar("dataObjects:query", pedido)
            nomes += [o["name"] for o in pagina.get("dataObjects", [])]
            if not pagina.get("nextPageToken"):
                break
            pedido = pedido | {"pageToken": pagina["nextPageToken"]}
        for i in range(0, len(nomes), OBJETOS_POR_PAGINA):
            lote = nomes[i : i + OBJETOS_POR_PAGINA]
            self._chamar(
                "dataObjects:batchDelete", {"requests": [{"name": n} for n in lote]}
            )

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        try:
            self._gravar_uma_vez(job_id, registros)
        except JaExiste:
            # Um lote já estava lá: reenviado depois de uma resposta perdida, gravado em
            # parte, ou de outra indexação do mesmo vídeo (os ids são fixos). O `apagar`
            # tira só o que existe; o vídeo entra de novo inteiro, uma vez (#411).
            log.warning("%s: 409 na gravação, apagando e gravando de novo", job_id)
            self._gravar_uma_vez(job_id, registros)
        if not self._config.indices_ligados:
            self._avisar_do_teto_do_knn()

    def _gravar_uma_vez(self, job_id: str, registros: list[Registro]) -> None:
        self.apagar(job_id)
        for i in range(0, len(registros), REGISTROS_POR_LOTE):
            pedacos = registros[i : i + REGISTROS_POR_LOTE]
            self._no_ritmo(len(pedacos))
            self._chamar(
                "dataObjects:batchCreate", {"requests": [_criacao(r) for r in pedacos]}
            )

    def _avisar_do_teto_do_knn(self) -> None:
        """Sem índice ANN a busca é KNN, que recusa mais de 100 mil registros: o aviso vem
        antes. Uma falha da contagem não pode derrubar a indexação."""
        try:
            registros = self.total()
        except Exception:
            log.exception("contagem da coleção para o aviso do teto do KNN falhou")
            return
        if registros > AVISO_DO_TETO_DO_KNN:
            log.warning(
                "a coleção tem %d registros e o KNN, sem índice ANN, aceita no máximo "
                "100 mil: ligue indices_da_busca_ligados, aplique e rode o "
                "make criar-colecao-da-busca antes de chegar lá",
                registros,
            )

    def vetor_da_consulta(self, texto: str) -> list[float]:
        """O embedding da consulta, o mesmo modelo, tarefa e dimensão com que o
        `semanticSearch` o calcula, na região da busca. Medido no dev (5/11/2026): a
        distância de cada posição do top-50 coincide com a do ANN. Sem retry: a chamada
        tem cota regional e um 429 sobe como erro da busca."""
        # `get`, não `in` e depois `[]`: outra thread pode limpar o cache no meio.
        guardado = self._vetores.get(texto)
        if guardado is not None:
            return guardado
        resposta = self._transporte(
            "POST",
            f"https://{self._config.regiao}-aiplatform.googleapis.com/v1/projects/"
            f"{self._config.projeto}/locations/{self._config.regiao}/publishers/google/"
            f"models/{MODELO_DO_EMBEDDING}:predict",
            {
                "instances": [{"content": texto, "task_type": "RETRIEVAL_QUERY"}],
                "parameters": {"outputDimensionality": self._config.dimensao},
            },
        )
        valores = [float(v) for v in resposta["predictions"][0]["embeddings"]["values"]]
        if len(valores) != self._config.dimensao:
            raise ValueError(
                f"o embedding veio com dimensão {len(valores)}, e a coleção tem "
                f"{self._config.dimensao}"
            )
        if len(self._vetores) >= 256:
            self._vetores.clear()
        self._vetores[texto] = valores
        return valores

    def buscar(self, consulta: Consulta) -> list[Registro]:
        # Sem índice ANN a consulta vira vetor aqui (`pedido_de_busca`).
        vetor = (
            self.vetor_da_consulta(consulta.significado)
            if consulta.significado and not self._config.indices_ligados
            else None
        )
        resposta = self._chamar(
            "dataObjects:batchSearch", pedido_de_busca(self._config, consulta, vetor)
        )
        # Uma lista de resultados por busca; com o RRF, uma lista só, já fundida.
        registros = [
            (_registro(r["dataObject"]["data"]), r)
            for lista in resposta.get("results", [])
            for r in lista.get("results", [])
        ]
        if consulta.cortar_significado and consulta.significado:
            # A busca por significado vem depois da por texto (`pedido_de_busca`).
            busca = 1 if consulta.texto else 0
            registros = [(r, x) for r, x in registros if self._perto(r, x, busca)]
        return [r for r, _ in registros]

    def _perto(self, r: Registro, resultado: dict[str, Any], busca: int) -> bool:
        """Achado por outra busca, ou perto o bastante e com palavras bastantes.

        ponytail: corte fixo, calibrado em 3 vídeos do dev; com a API de Ranking no ar,
        o corte passa a ser a nota dela."""
        distancias = {
            d["searchIndex"]: d["distance"]
            for d in resultado.get("searchResultMetadata", {}).get(
                "searchDistances", []
            )
        }
        if any(i != busca for i in distancias):
            return True
        distancia = distancias.get(busca, resultado.get("distance"))
        maxima = self._config.distancia_maxima
        return (
            maxima is None or (distancia is not None and distancia <= maxima)
        ) and len(
            (r.descricao or r.texto or "").split()
        ) >= self._config.palavras_minimas

    def vetores_dos_planos(self, job_id: str) -> dict[int, list[float]]:
        """Os planos do vídeo com o vetor do quadro, lidos página a página (#271)."""
        pedido: dict[str, Any] = {
            "filter": {
                "$and": [{"job_id": {"$eq": job_id}}, {"tipo": {"$eq": "plano"}}]
            },
            "outputFields": {
                "dataFields": ["id"],
                "vectorFields": [CAMPO_DO_VETOR_DO_QUADRO],
            },
            "pageSize": OBJETOS_POR_PAGINA,
        }
        vetores: dict[int, list[float]] = {}
        while True:
            pagina = self._chamar("dataObjects:query", pedido)
            for o in pagina.get("dataObjects", []):
                valores = (
                    o.get("vectors", {})
                    .get(CAMPO_DO_VETOR_DO_QUADRO, {})
                    .get("dense", {})
                ).get("values")
                if valores:
                    n = int(o["data"]["id"].rsplit(":", 1)[1])
                    vetores[n] = [float(v) for v in valores]
            if not pagina.get("nextPageToken"):
                return vetores
            pedido = pedido | {"pageToken": pagina["nextPageToken"]}

    def total(self) -> int:
        resposta = self._chamar("dataObjects:aggregate", {"aggregate": "COUNT"})
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
        # `caminho` é relativo à URL base, salvo o embedding da consulta (outro serviço).
        url = caminho if caminho.startswith("https://") else f"{URL_BASE}/{caminho}"
        resposta = sessao.request(  # type: ignore[no-untyped-call]
            metodo, url, json=corpo, timeout=60
        )
        if resposta.status_code == 409:
            raise JaExiste(caminho)
        if resposta.status_code == 429:
            raise CotaEsgotada(f"{metodo} {caminho}: HTTP 429: {resposta.text[:2000]}")
        if not resposta.ok:
            # A mensagem do serviço diz qual campo ele recusou.
            raise RuntimeError(
                f"{metodo} {caminho}: HTTP {resposta.status_code}: {resposta.text[:2000]}"
            )
        return dict(resposta.json()) if resposta.content else {}

    return chamar
