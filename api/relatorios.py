"""A base dos relatórios sobre a cópia no BigQuery (#266, #267).

Cada relatório diz quais tipos de linha lê, as colunas que quer e como agrupa. Aqui ficam o
que é igual em todos: quem pode consultar, o filtro de programa e de data de exibição (no
BigQuery e na cópia em memória), a leitura da resposta (todas as páginas), o CSV e o erro
de uma consulta que não termina.
"""

import base64
import binascii
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Annotated, Any, Protocol

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from api.auth import ChamadorAutenticado, Usuario
from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaEmMemoria,
    LinhaDoMomento,
    Transporte,
    parametro,
    transporte_http,
)
from api.jobs import RepositorioDeJobs, _confere_permissao


def _exige_ver_o_relatorio(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: pessoa com `decupagem.ver`. A cópia não guarda o sistema dono do
    vídeo, então uma chave de sistema veria os vídeos dos outros: não consulta."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não consulta o relatório")
    _confere_permissao(request, chamador, "decupagem.ver")
    return chamador


PodeVerORelatorio = Annotated[Usuario, Depends(_exige_ver_o_relatorio)]


def confere_o_pedido[T](consulta: T | None, desde: date | None, ate: date | None) -> T:
    """A consulta configurada, ou o erro do pedido: 503 sem BigQuery, 422 com período invertido."""
    if consulta is None:
        raise HTTPException(503, "O BigQuery não está configurado neste ambiente")
    if desde and ate and desde > ate:
        raise HTTPException(422, "`desde` não pode ser depois de `ate`")
    return consulta


def ou_503[T](consultar: Callable[[], T]) -> T:
    """Uma consulta que não termina vira 503 com o motivo."""
    try:
        return consultar()
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


def em_paralelo(*chamadas: Callable[[], Any]) -> tuple[Any, ...]:
    """Roda as leituras independentes ao mesmo tempo e devolve os resultados na ordem dadas.
    Espera todas; se mais de uma falhar, levanta o erro da primeira da lista. Só para
    leituras: a escrita da auditoria fica síncrona, fora daqui."""
    with ThreadPoolExecutor(len(chamadas)) as pool:
        futuros = [pool.submit(c) for c in chamadas]
    return tuple(f.result() for f in futuros)


LIMITE_DA_PAGINA = 100  # o teto de `limite` nas listas paginadas dos relatórios


def posicao_do_cursor(cursor: str | None) -> int:
    """Quantos itens as páginas anteriores já trouxeram. O cursor é opaco para quem chama
    (a posição em base64): o relatório é uma soma, sem um documento onde ancorar como no
    acervo. Cursor que não decifra é 422, como lá."""
    if cursor is None:
        return 0
    try:
        texto = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        texto = ""
    # Até 9 dígitos: a posição, somada ao limite, cabe folgada no INT64 do BigQuery.
    if not (texto.isascii() and texto.isdigit() and len(texto) <= 9):
        raise HTTPException(422, "Cursor inválido")
    return int(texto)


def recorta[T](
    lidos: list[T], depois: int, limite: int
) -> tuple[list[T], dict[str, str]]:
    """A página e o cabeçalho do próximo cursor. `lidos` são até `limite + 1` itens a
    partir da posição `depois`: o que passa do limite diz que há mais."""
    if len(lidos) <= limite:
        return lidos, {}
    proximo = base64.urlsafe_b64encode(str(depois + limite).encode()).decode()
    return lidos[:limite], {"X-Proximo-Cursor": proximo.rstrip("=")}


def resposta_em_csv(texto: str, arquivo: str) -> Response:
    return Response(
        texto,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{arquivo}"'},
    )


def linhas_da_copia(
    copia: CopiaEmMemoria,
    tipos: Sequence[str],
    programa: str | None,
    desde: date | None,
    ate: date | None,
) -> Iterator[LinhaDoMomento]:
    """Dublê da consulta: os mesmos filtros do BigQuery sobre a cópia em memória."""
    for linhas in copia.por_job.values():
        for x in linhas:
            dia = x.data_de_exibicao
            if x.tipo not in tipos:
                continue
            if programa is not None and x.programa != programa:
                continue
            if (desde or ate) and dia is None:
                continue
            if (desde and dia and dia < desde) or (ate and dia and dia > ate):
                continue
            yield x


def consultar_no_bigquery(
    config: ConfigDoBigQuery,
    transporte: Transporte,
    *,
    colunas: str,
    tipos: Sequence[str],
    programa: str | None,
    desde: date | None,
    ate: date | None,
    unnest_das_pessoas: bool = False,
    condicoes: Sequence[str] = (),
    parametros: Sequence[dict[str, Any]] = (),
    depois_da_base: str | None = None,
) -> list[list[Any]]:
    """As linhas de `tipos` do programa e do período, com os valores como parâmetros.

    `colunas` é o que vai no SELECT (a tabela é `t`; com `unnest_das_pessoas`, as pessoas
    da linha são `p`). Devolve o texto de cada coluna, na ordem; o chamador converte.

    Com `depois_da_base`, essas linhas viram a CTE `base` e o texto dado vem logo depois
    de `WITH base AS (...)`: o BigQuery soma e devolve só o resultado somado. O texto
    começa com `,` (mais CTEs) ou com o `SELECT` final.
    """
    lista_de_tipos = ", ".join(f"'{t}'" for t in tipos)
    onde = [f"t.tipo IN ({lista_de_tipos})", *condicoes]
    parametros = list(parametros)
    if programa is not None:
        onde.append("t.programa = @programa")
        parametros.append(parametro("programa", programa))
    for nome, dia, comparacao in (("desde", desde, ">="), ("ate", ate, "<=")):
        if dia is not None:
            onde.append(f"t.data_de_exibicao {comparacao} @{nome}")
            parametros.append(parametro(nome, dia.isoformat(), "DATE"))
    tabela = f"`{config.projeto}.{config.dataset}.{config.tabela}` AS t"
    if unnest_das_pessoas:
        tabela += ", UNNEST(t.pessoas) AS p"
    sql = f"SELECT {colunas}\nFROM {tabela}\nWHERE {' AND '.join(onde)}"
    if depois_da_base is not None:
        sql = f"WITH base AS (\n{sql}\n)\n{depois_da_base}"
    return linhas_da_consulta(transporte, config.regiao, sql, parametros)


def linhas_da_consulta(
    transporte: Transporte,
    regiao: str,
    sql: str,
    parametros: Sequence[dict[str, Any]] = (),
    o_que: str = "relatório",
) -> list[list[Any]]:
    """Os valores de cada linha, em texto. Uma consulta que não termina no prazo falha alto
    com `RuntimeError`. O resultado que não cabe numa página (`maxResults` ou o limite de
    tamanho da resposta) vem nas páginas seguintes (`jobs.getQueryResults`); todas as
    linhas ficam na memória da instância, que é o teto que resta."""
    resposta = transporte(
        {
            "query": sql,
            "useLegacySql": False,
            "location": regiao,
            # Sem job quando o resultado cabe na resposta (~0,2 s a menos por consulta). Se
            # paginar, o BigQuery cria o job e devolve `jobReference` e `pageToken`.
            "jobCreationMode": "JOB_CREATION_OPTIONAL",
            "timeoutMs": 60_000,
            "maxResults": 100_000,
            "queryParameters": list(parametros),
        }
    )
    if not resposta.get("jobComplete", False):
        raise RuntimeError(f"a consulta do {o_que} não terminou no prazo")
    job = resposta.get("jobReference", {})
    linhas: list[list[Any]] = []
    while True:
        linhas += [
            [campo["v"] for campo in linha["f"]] for linha in resposta.get("rows", [])
        ]
        if not (token := resposta.get("pageToken")):
            return linhas
        if "jobId" not in job:
            raise RuntimeError(f"a consulta do {o_que} veio paginada sem o job")
        resposta = transporte(
            {
                "jobId": job["jobId"],
                "location": job.get("location", regiao),
                "pageToken": token,
                "maxResults": 100_000,
            }
        )


class _ComVideo(Protocol):
    job_id: str
    nome: str | None


def poe_o_nome_dos_videos(
    itens: Iterable[_ComVideo], repositorio: RepositorioDeJobs
) -> None:
    """Preenche o nome de cada vídeo do JSON, numa leitura em lote dos Jobs. O vídeo na
    lixeira fica sem nome: os números do passado não mudam, mas ele some (#144)."""
    itens = list(itens)
    jobs = repositorio.obter_varios({i.job_id for i in itens})
    nomes = {j.id: j.nome for j in jobs if j.lixeira is None}
    for item in itens:
        item.nome = nomes.get(item.job_id)


def config_e_transporte_do_ambiente(
    ambiente: Any,
) -> tuple[ConfigDoBigQuery, Transporte] | None:
    """Onde a cópia mora, ou `None` se o ambiente não diz."""
    if "BIGQUERY_DATASET" not in ambiente:
        return None
    config = ConfigDoBigQuery.do_ambiente(ambiente)
    return config, transporte_http(config.projeto)
