"""Cópia das decupagens no BigQuery (#260): um momento por linha, para os relatórios.

As linhas são o recorte do índice da busca (`registros_da_decupagem`) mais um momento por
comercial (marca e tipo de inserção). Cada gravação troca todas as linhas do Job num
único MERGE, então repetir dá o mesmo resultado e nunca deixa versões acumuladas.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import google.auth
import google.auth.transport.requests

from api.decupagem import Decupagem
from api.indice_da_busca import registros_da_decupagem

URL_BASE = "https://bigquery.googleapis.com/bigquery/v2"


@dataclass(frozen=True)
class PessoaDoMomento:
    id: str
    nome: str


@dataclass(frozen=True)
class LinhaDoMomento:
    job_id: str
    programa: str | None
    data_de_exibicao: date | None
    # plano, fala, texto_na_tela, objeto, comercial; e, por pessoa, aparicao,
    # mencao_na_fala e mencao_no_texto
    tipo: str
    inicio_ms: int
    fim_ms: int
    # Quem aparece no momento (do catálogo); no objeto, o dono.
    pessoas: list[PessoaDoMomento] = field(default_factory=list)
    marca: str | None = None
    tipo_de_insercao: str | None = None  # só no comercial
    texto: str | None = None
    versao_pipeline: str | None = None
    gravado_em: datetime | None = None


class CopiaDosMomentos(Protocol):
    def gravar(self, job_id: str, linhas: list[LinhaDoMomento]) -> None:
        """As linhas do vídeo; as que já havia dele saem."""


def linhas_da_decupagem(
    job_id: str,
    decupagem: Decupagem,
    programa: str | None,
    data_de_exibicao: date | None,
    gravado_em: datetime,
) -> list[LinhaDoMomento]:
    nomes = {p.catalogo_id: p.nome for p in decupagem.pessoas if p.catalogo_id}

    def pessoa(catalogo_id: str) -> PessoaDoMomento:
        return PessoaDoMomento(catalogo_id, nomes.get(catalogo_id, ""))

    base: dict[str, Any] = {
        "job_id": job_id,
        "programa": programa,
        "data_de_exibicao": data_de_exibicao,
        "versao_pipeline": decupagem.versao_pipeline,
        "gravado_em": gravado_em,
    }
    linhas = [
        LinhaDoMomento(
            tipo=r.tipo,
            inicio_ms=r.inicio_ms,
            fim_ms=r.fim_ms,
            pessoas=[pessoa(i) for i in (r.pessoas or ([r.dono] if r.dono else []))],
            marca=r.marca,
            texto=r.texto or r.descricao,
            **base,
        )
        for r in registros_da_decupagem(job_id, decupagem, programa, data_de_exibicao)
    ]
    linhas += [
        LinhaDoMomento(
            tipo="comercial",
            inicio_ms=c.inicio_ms,
            fim_ms=c.fim_ms,
            marca=c.marca,
            tipo_de_insercao=c.tipo,
            **base,
        )
        for c in decupagem.comerciais
    ]
    linhas += _linhas_das_pessoas(decupagem, base)
    return linhas


def _linhas_das_pessoas(
    decupagem: Decupagem, base: dict[str, Any]
) -> list[LinhaDoMomento]:
    """Uma linha por aparição e por menção de cada pessoa do catálogo (#266).

    É daqui que sai o tempo de tela: `aparicao` é a pessoa visível, e as menções na fala e
    no texto da tela ficam em tipos à parte, nunca somam tempo. Quem não está confirmado
    no catálogo (sem `catalogo_id`, ou só palpite) fica de fora dos relatórios.
    """
    linhas: list[LinhaDoMomento] = []
    for p in decupagem.pessoas:
        if not p.catalogo_id or p.estado_do_nome == "palpite":
            continue
        dona = [PessoaDoMomento(p.catalogo_id, p.nome)]
        momentos: list[tuple[str, Sequence[Any]]] = [
            ("aparicao", p.na_imagem),
            ("mencao_na_fala", p.citada_na_fala),
            ("mencao_no_texto", p.citada_no_texto),
        ]
        for tipo, intervalos in momentos:
            linhas += [
                LinhaDoMomento(
                    tipo=tipo,
                    inicio_ms=i.inicio_ms,
                    fim_ms=i.fim_ms,
                    pessoas=dona,
                    **base,
                )
                for i in intervalos
            ]
    return linhas


class CopiaEmMemoria:
    """Dublê da cópia: guarda as linhas de cada vídeo."""

    def __init__(self) -> None:
        self.por_job: dict[str, list[LinhaDoMomento]] = {}

    def gravar(self, job_id: str, linhas: list[LinhaDoMomento]) -> None:
        self.por_job[job_id] = list(linhas)

    def total(self) -> int:
        return sum(len(v) for v in self.por_job.values())


# O corpo de um POST em `projects/<projeto>/queries`; devolve a resposta em JSON.
Transporte = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ConfigDoBigQuery:
    projeto: str
    dataset: str
    tabela: str
    regiao: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDoBigQuery":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            tabela=ambiente["BIGQUERY_TABELA"],
            regiao=ambiente["BIGQUERY_REGIAO"],
        )


def _json_da_linha(linha: LinhaDoMomento) -> dict[str, Any]:
    dados = asdict(linha)
    dados["data_de_exibicao"] = (
        linha.data_de_exibicao.isoformat() if linha.data_de_exibicao else None
    )
    dados["gravado_em"] = linha.gravado_em.isoformat() if linha.gravado_em else None
    return dados


class CopiaBigQuery:
    """A cópia real: um único MERGE apaga as linhas do Job e insere as novas.

    Um comando só é atômico sem transação: duas transações que mudam a mesma tabela ao
    mesmo tempo se abortam, e os MERGE concorrentes entram na fila do BigQuery. Sem `insertAll`: o que entra pelo buffer de streaming não pode ser apagado por um tempo.
    """

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def gravar(self, job_id: str, linhas: list[LinhaDoMomento]) -> None:
        c = self._config
        tabela = f"`{c.projeto}.{c.dataset}.{c.tabela}`"
        consulta = f"""
MERGE {tabela} AS t
USING (
  SELECT
    JSON_VALUE(l, '$.job_id') AS job_id,
    JSON_VALUE(l, '$.programa') AS programa,
    DATE(JSON_VALUE(l, '$.data_de_exibicao')) AS data_de_exibicao,
    JSON_VALUE(l, '$.tipo') AS tipo,
    CAST(JSON_VALUE(l, '$.inicio_ms') AS INT64) AS inicio_ms,
    CAST(JSON_VALUE(l, '$.fim_ms') AS INT64) AS fim_ms,
    ARRAY(
      SELECT AS STRUCT JSON_VALUE(p, '$.id') AS id, JSON_VALUE(p, '$.nome') AS nome
      FROM UNNEST(JSON_QUERY_ARRAY(l, '$.pessoas')) AS p
    ) AS pessoas,
    JSON_VALUE(l, '$.marca') AS marca,
    JSON_VALUE(l, '$.tipo_de_insercao') AS tipo_de_insercao,
    JSON_VALUE(l, '$.texto') AS texto,
    JSON_VALUE(l, '$.versao_pipeline') AS versao_pipeline,
    TIMESTAMP(JSON_VALUE(l, '$.gravado_em')) AS gravado_em
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@linhas))) AS l
) AS s
ON FALSE
WHEN NOT MATCHED BY SOURCE AND t.job_id = @job_id THEN DELETE
WHEN NOT MATCHED THEN INSERT
  (job_id, programa, data_de_exibicao, tipo, inicio_ms, fim_ms, pessoas, marca,
   tipo_de_insercao, texto, versao_pipeline, gravado_em)
VALUES
  (s.job_id, s.programa, s.data_de_exibicao, s.tipo, s.inicio_ms, s.fim_ms, s.pessoas,
   s.marca, s.tipo_de_insercao, s.texto, s.versao_pipeline, s.gravado_em)
"""
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 120_000,
                "queryParameters": [
                    _parametro("job_id", job_id),
                    _parametro(
                        "linhas",
                        json.dumps(
                            [_json_da_linha(x) for x in linhas], ensure_ascii=False
                        ),
                    ),
                ],
            }
        )
        if not resposta.get("jobComplete", False):
            raise RuntimeError(f"cópia de {job_id} não terminou no prazo")


def _parametro(nome: str, valor: str, tipo: str = "STRING") -> dict[str, Any]:
    return {
        "name": nome,
        "parameterType": {"type": tipo},
        "parameterValue": {"value": valor},
    }


def transporte_http(projeto: str) -> Transporte:
    """O transporte real: REST com as credenciais padrão (ADC) de quem roda."""
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    sessao = google.auth.transport.requests.AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]

    def chamar(corpo: dict[str, Any]) -> dict[str, Any]:
        resposta = sessao.post(
            f"{URL_BASE}/projects/{projeto}/queries", json=corpo, timeout=150
        )
        if not resposta.ok:
            raise RuntimeError(
                f"BigQuery: HTTP {resposta.status_code}: {resposta.text[:2000]}"
            )
        return dict(resposta.json())

    return chamar


def copia_do_ambiente(ambiente: Any) -> CopiaBigQuery | None:
    """A cópia configurada, ou `None` se o ambiente não diz onde ela mora."""
    if "BIGQUERY_DATASET" not in ambiente:
        return None
    config = ConfigDoBigQuery.do_ambiente(ambiente)
    return CopiaBigQuery(config, transporte_http(config.projeto))
