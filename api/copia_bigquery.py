"""Cópia das decupagens no BigQuery (#260): um momento por linha, para os relatórios.

As linhas são o recorte do índice da busca (`registros_da_decupagem`) mais um momento por
comercial (marca e tipo de inserção). Cada gravação troca todas as linhas do Job num
único MERGE, então repetir dá o mesmo resultado e nunca deixa versões acumuladas.
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from time import monotonic, sleep
from typing import Any, Protocol

from api.clientes_de_nuvem import sessao_autenticada
from api.decupagem import Decupagem
from api.indice_da_busca import registros_da_decupagem

URL_BASE = "https://bigquery.googleapis.com/bigquery/v2"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PessoaDoMomento:
    id: str
    # O nome não é gravado (#417): o relatório lê o nome do catálogo pelo `id`. A coluna
    # fica na tabela e vem vazia.
    nome: str = ""


@dataclass(frozen=True)
class LinhaDoMomento:
    job_id: str
    programa: str | None
    data_de_exibicao: date | None
    # plano, fala, texto_na_tela, objeto, comercial, pauta; e, por pessoa, aparicao,
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
    # A duração do vídeo todo, igual em todas as linhas dele (o sinal por programa, #287,
    # divide os eventos por ela).
    duracao_do_video_ms: int | None = None
    # Só no objeto: o tipo da lista fechada (#544), ao lado do texto bruto em `texto`.
    tipo_canonico: str | None = None


class CopiaDosMomentos(Protocol):
    def gravar(
        self,
        job_id: str,
        linhas: list[LinhaDoMomento],
        *,
        anos: list[int] | None = None,
    ) -> None:
        """As linhas do vídeo; as que já havia dele saem."""


def linhas_da_decupagem(
    job_id: str,
    decupagem: Decupagem,
    programa: str | None,
    data_de_exibicao: date | None,
    gravado_em: datetime,
) -> list[LinhaDoMomento]:
    base: dict[str, Any] = {
        "job_id": job_id,
        "programa": programa,
        "data_de_exibicao": data_de_exibicao,
        "versao_pipeline": decupagem.versao_pipeline,
        "gravado_em": gravado_em,
        "duracao_do_video_ms": decupagem.video.duracao_ms,
    }
    linhas = [
        LinhaDoMomento(
            tipo=r.tipo,
            inicio_ms=r.inicio_ms,
            fim_ms=r.fim_ms,
            pessoas=[
                PessoaDoMomento(i) for i in (r.pessoas or ([r.dono] if r.dono else []))
            ],
            marca=r.marca,
            texto=r.texto or r.descricao,
            tipo_canonico=r.tipo_canonico,
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
    linhas += [
        LinhaDoMomento(
            tipo="pauta",
            inicio_ms=p.inicio_ms,
            fim_ms=p.fim_ms,
            texto=p.titulo,
            **base,
        )
        for p in decupagem.pautas
    ]
    linhas += _linhas_das_pessoas(decupagem, base)
    return linhas


# Os tipos das linhas por pessoa, na ordem aparição, menção na fala, menção no texto.
TIPOS_DAS_PESSOAS = ("aparicao", "mencao_na_fala", "mencao_no_texto")


def _linhas_das_pessoas(
    decupagem: Decupagem, base: dict[str, Any]
) -> list[LinhaDoMomento]:
    """Uma linha por aparição e por menção de cada pessoa do catálogo (#266).

    É daqui que sai o tempo de tela: `aparicao` é a pessoa visível, e as menções na fala e
    no texto da tela ficam em tipos à parte, nunca somam tempo. Quem não está confirmado
    no catálogo (sem `catalogo_id`, palpite ou sem a identificação) fica de fora.
    """
    linhas: list[LinhaDoMomento] = []
    for p in decupagem.pessoas:
        if not p.catalogo_id or p.estado_do_nome != "confirmado":
            continue
        dona = [PessoaDoMomento(p.catalogo_id)]
        intervalos_por_tipo: tuple[Sequence[Any], ...] = (
            p.na_imagem,
            p.citada_na_fala,
            p.citada_no_texto,
        )
        for tipo, intervalos in zip(
            TIPOS_DAS_PESSOAS, intervalos_por_tipo, strict=True
        ):
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

    def gravar(
        self,
        job_id: str,
        linhas: list[LinhaDoMomento],
        *,
        anos: list[int] | None = None,
    ) -> None:
        self.por_job[job_id] = list(linhas)

    def total(self) -> int:
        return sum(len(v) for v in self.por_job.values())


# O corpo de um POST em `projects/<projeto>/queries` (`jobs.query`); devolve a resposta em
# JSON. Com `jobId`, é a próxima página de uma consulta (`jobs.getQueryResults`, um GET em
# `queries/<jobId>`) e o resto do dicionário vai na URL.
# Com `jobReference`, consulta o estado (`jobs.get`); com `cancelar`, pede o cancelamento.
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

    def gravar(
        self,
        job_id: str,
        linhas: list[LinhaDoMomento],
        *,
        anos: list[int] | None = None,
    ) -> None:
        c = self._config
        tabela = f"`{c.projeto}.{c.dataset}.{c.tabela}`"
        filtro = ""
        parametros = []
        if anos is not None:
            predicados = ["t.data_de_exibicao IS NULL"]
            for ano in sorted(set(anos)):
                predicados.append(
                    f"t.data_de_exibicao BETWEEN @inicio_{ano} AND @fim_{ano}"
                )
                parametros += [
                    parametro(f"inicio_{ano}", f"{ano:04}-01-01", "DATE"),
                    parametro(f"fim_{ano}", f"{ano:04}-12-31", "DATE"),
                ]
            filtro = f" AND ({' OR '.join(predicados)})"
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
    TIMESTAMP(JSON_VALUE(l, '$.gravado_em')) AS gravado_em,
    CAST(JSON_VALUE(l, '$.duracao_do_video_ms') AS INT64) AS duracao_do_video_ms,
    JSON_VALUE(l, '$.tipo_canonico') AS tipo_canonico
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@linhas))) AS l
) AS s
ON FALSE
WHEN NOT MATCHED BY SOURCE AND t.job_id = @job_id{filtro} THEN DELETE
WHEN NOT MATCHED THEN INSERT
  (job_id, programa, data_de_exibicao, tipo, inicio_ms, fim_ms, pessoas, marca,
   tipo_de_insercao, texto, versao_pipeline, gravado_em, duracao_do_video_ms,
   tipo_canonico)
VALUES
  (s.job_id, s.programa, s.data_de_exibicao, s.tipo, s.inicio_ms, s.fim_ms, s.pessoas,
   s.marca, s.tipo_de_insercao, s.texto, s.versao_pipeline, s.gravado_em,
   s.duracao_do_video_ms, s.tipo_canonico)
"""
        inicio = monotonic()
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 120_000,
                "queryParameters": [
                    parametro("job_id", job_id),
                    parametro(
                        "linhas",
                        json.dumps(
                            [_json_da_linha(x) for x in linhas], ensure_ascii=False
                        ),
                    ),
                    *parametros,
                ],
            }
        )
        if resposta.get("jobComplete", False):
            return
        referencia = resposta.get("jobReference")
        if not referencia:
            raise RuntimeError(f"cópia de {job_id} sem referência do MERGE")
        referencia = {"location": c.regiao, **referencia}
        cancelamento_pedido = False
        while True:
            if monotonic() - inicio >= 900:
                # O ano já foi registrado; a próxima cópia limpa até um commit atrasado.
                raise RuntimeError(f"cópia de {job_id} não terminou no prazo")
            if monotonic() - inicio >= 300 and not cancelamento_pedido:
                try:
                    self._transporte({"jobReference": referencia, "cancelar": True})
                    cancelamento_pedido = True
                except Exception:
                    log.exception("cancelamento do MERGE de %s não confirmado", job_id)
            try:
                estado = self._transporte({"jobReference": referencia})["status"]
            except Exception:
                # Uma falha de transporte não prova que o MERGE parou de poder gravar.
                log.exception("estado do MERGE de %s não confirmado", job_id)
            else:
                if estado["state"] == "DONE":
                    if estado.get("errorResult"):
                        raise RuntimeError(
                            f"cópia de {job_id} falhou: {estado['errorResult']}"
                        )
                    return
            sleep(5)


def parametro(nome: str, valor: str, tipo: str = "STRING") -> dict[str, Any]:
    return {
        "name": nome,
        "parameterType": {"type": tipo},
        "parameterValue": {"value": valor},
    }


def transporte_http(projeto: str) -> Transporte:
    """O transporte real: REST com as credenciais padrão (ADC) de quem roda."""
    sessao = sessao_autenticada("https://www.googleapis.com/auth/bigquery")

    def chamar(corpo: dict[str, Any]) -> dict[str, Any]:
        url = f"{URL_BASE}/projects/{projeto}/queries"
        if "jobReference" in corpo:
            referencia = corpo["jobReference"]
            url = (
                f"{URL_BASE}/projects/{referencia['projectId']}"
                f"/jobs/{referencia['jobId']}"
            )
            parametros = {"location": referencia["location"]}
            if corpo.get("cancelar"):
                resposta = sessao.post(f"{url}/cancel", params=parametros, timeout=150)
            else:
                resposta = sessao.get(url, params=parametros, timeout=150)
        elif "jobId" in corpo:
            pagina = dict(corpo)
            url += f"/{pagina.pop('jobId')}"
            resposta = sessao.get(url, params=pagina, timeout=150)
        else:
            resposta = sessao.post(url, json=corpo, timeout=150)
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
