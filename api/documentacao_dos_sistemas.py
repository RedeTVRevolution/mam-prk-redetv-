"""O OpenAPI das rotas `/v1` que uma chave de API de sistema alcança (E7, #277, #382).

O FastAPI gera o esquema; aqui ficam, por rota, a descrição, os exemplos de pedido e de
resposta e os erros possíveis, que o FastAPI não sabe. O arquivo publicado
(`docs/api/openapi.json`) sai de `python -m api.documentacao_dos_sistemas`
(`make atualizar-openapi`) e um teste confere que ele bate com o gerado. Outro teste
percorre as rotas do app com uma chave e falha se alguma que a aceita não está em `OPERACOES`.
"""

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

ARQUIVO = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"

ID_DO_JOB = "5f0c2b6e8d3a4c1f9a7e0b2d4c6f8a1b"
# O erro com `detail` em texto; o 422 de validação do FastAPI traz uma lista.
ERRO_EM_TEXTO = "ErroEmTexto"
_REF_DO_ERRO = {"$ref": f"#/components/schemas/{ERRO_EM_TEXTO}"}
INSTANTE = "2026-11-03T21:14:05.120000Z"


@dataclass(frozen=True)
class Erro:
    status: int
    # O texto que a API devolve em `detail` (o que varia vai entre `<>`).
    detalhe: str
    acao: str
    # O `detail` de um caso real, quando `detalhe` tem o que varia; senão, o próprio.
    exemplo: Any = None
    # Resposta sem corpo (o 304): não há `detail` nem exemplo.
    sem_corpo: bool = False

    @property
    def corpo(self) -> dict[str, Any]:
        return {"detail": self.detalhe if self.exemplo is None else self.exemplo}


@dataclass(frozen=True)
class Operacao:
    metodo: str
    caminho: str
    resumo: str
    descricao: str
    resposta: Any
    erros: tuple[Erro, ...]
    pedido: Any = None
    # Só quando o código de sucesso não é o 200 do FastAPI por padrão (já vem do esquema).
    status: str | None = None
    # O corpo `multipart/form-data`, que o FastAPI não enxerga quando a rota o lê à mão.
    formulario: Any = None
    # Parâmetros que a rota lê do pedido sem declarar (cabeçalhos como `If-None-Match`).
    parametros: tuple[dict[str, Any], ...] = ()


def _sem_chave(escopo: str | None = None) -> tuple[Erro, ...]:
    erros = [
        Erro(
            401,
            "Not authenticated",
            "Mande a chave no cabeçalho `X-API-Key`. Chave inexistente, revogada ou "
            "com erro de digitação também dá 401.",
        )
    ]
    if escopo is not None:
        erros.append(
            Erro(
                403,
                f"Chave sem o escopo {escopo}",
                f"A chave não pode `{escopo}`. Peça uma chave com esse escopo.",
            )
        )
    return tuple(erros)


_INDISPONIVEL = Erro(
    503,
    "Serviço indisponível",
    "Falha passageira de um serviço de apoio. Repita com espera crescente "
    "(1 s, 2 s, 4 s...); a repetição é segura nas rotas de leitura e, no `POST /v1/jobs`, "
    "com o mesmo `Idempotency-Key`.",
)
_NAO_ACHOU = Erro(
    404,
    "Job não encontrado",
    "O id não existe ou o Job é de outro sistema. Cada chave só enxerga os próprios Jobs.",
)


def _validacao(
    tipo: str,
    onde: str,
    campo: str,
    msg: str,
    entrada: Any,
    ctx: dict[str, Any] | None = None,
) -> Erro:
    """O 422 do FastAPI para um parâmetro; `tipo` e `ctx` são os do Pydantic."""
    item = {"type": tipo, "loc": [onde, campo], "msg": msg, "input": entrada}
    if ctx is not None:
        item["ctx"] = ctx
    return Erro(
        422,
        "Erro de validação",
        "Um parâmetro está fora do formato. Aqui `detail` é uma lista: leia `loc` (onde) "
        "e `msg` (por quê) em cada item.",
        exemplo=[item],
    )


_PADRAO_DO_QUADRO = r"^[A-Za-z0-9][A-Za-z0-9_-]*\.jpg$"
_VALIDACAO = _validacao(
    "literal_error",
    "query",
    "versao",
    "Input should be 'modelo'",
    "outra",
    {"expected": "'modelo'"},
)

_NAO_CONCLUIDO = Erro(
    409,
    "Job em <estado>, não concluido",
    "O Job ainda não terminou (ou falhou). Espere o webhook ou consulte `GET "
    "/v1/jobs/{job_id}` até o `estado` ser `concluido`.",
    exemplo="Job em analisando, não concluido",
)
_NAO_ACHOU_A_PASSADA = Erro(
    404,
    "Passada não encontrada",
    "O Job não tem uma passada com esse id: pegue o id em `GET "
    "/v1/jobs/{job_id}/passadas`.",
)
_MUITA_CONSULTA = Erro(
    429,
    "Consultas demais; tente em um minuto",
    "O limite é de 30 consultas por minuto por chave (a busca por texto e a por imagem "
    "dividem o mesmo limite). Espere e repita.",
)
_DEMOROU = Erro(
    504,
    "A busca demorou demais",
    "A busca passou do tempo máximo. Repita; se persistir, simplifique a consulta.",
)
_CURSOR_DA_BUSCA = Erro(
    422,
    "Cursor inválido",
    "O `cursor` foi alterado, venceu (vale 15 min), é de outra chave ou de outra "
    "consulta: use o `X-Proximo-Cursor` da resposta anterior com a mesma consulta e os "
    "mesmos filtros, ou refaça a busca sem `cursor`.",
)
_PERIODO_INVERTIDO = Erro(
    422,
    "O início do período passa do fim",
    "`desde` é depois de `ate`. Troque os dois.",
)

_JOB = {
    "id": ID_DO_JOB,
    "nome": "TARD_20261103_BLU.mp4",
    "estado": "concluido",
    "codigo_falha": None,
    "duracao_s": 598.4,
    "cortes_ms": [0, 4200, 9800],
    "timecode_origem": None,
    "taxa_de_quadros": 29.97,
    "capa_url": None,
    "programa": "TV Fama",
    "data_exibicao": "2026-11-03",
    "indexacao": None,
    "copia_bigquery": None,
    "etapa_atual": None,
    "etapas": [
        {
            "inicio": "2026-11-03T21:02:10.000000Z",
            "fim": "2026-11-03T21:02:40.000000Z",
            "resultado": "concluida",
            "dispositivo": None,
            "tentativas_gpu": None,
            "nome": "validacao",
        }
    ],
    "reprocessamentos": 0,
    "enviado_por": {"tipo": "sistema", "nome": "sistema-legado"},
    "criado_em": "2026-11-03T21:00:00.000000Z",
    "reprocessavel_ate": "2026-11-10T21:00:00.000000Z",
    "atualizado_em": INSTANTE,
}

_NOVO_JOB = {
    "nome": "TARD_20261103_BLU.mp4",
    "tamanho_bytes": 734003200,
    "tipo": "video/mp4",
    "programa": "TV Fama",
    "data_exibicao": "2026-11-03",
}

_DECUPAGEM = {
    "versao_esquema": "1.5",
    "versao_decupagem": "9c1f4e0a7b3d2c68a5f0e9d1b4c7a8e2f3d6b0c9a1e4f7d2b5c8a0e3f6d9b2c1",
    "video": {"sha256": "a" * 64, "duracao_ms": 598400},
    "programa": {
        "resumo": "Edição de terça com bastidores e notícias de famosos.",
        "blocos": [{"inicio_ms": 0, "fim_ms": 9800, "titulo": "Abertura"}],
    },
    "pautas": [
        {
            "id": "pauta-1",
            "inicio_ms": 9800,
            "fim_ms": 120000,
            "titulo": "Bastidores da novela",
            "resumo": "A apresentadora recebe o elenco no estúdio.",
        }
    ],
    "pessoas": [
        {
            "id": "pessoa-1",
            "nome": "Fulana de Tal",
            "na_imagem": [{"inicio_ms": 0, "fim_ms": 9800, "evidencia": "rosto"}],
            "citada_na_fala": [],
            "citada_no_texto": [],
        }
    ],
    "planos": [
        {
            "id": "plano-1",
            "inicio_ms": 0,
            "fim_ms": 4200,
            "ambiente": "estúdio",
            "plano_limpo": False,
        }
    ],
    "comerciais": [],
    "transcricao": [
        {
            "inicio_ms": 1200,
            "fim_ms": 3900,
            "locutor": "pessoa-1",
            "texto": "Boa noite, bem-vindos ao programa.",
        }
    ],
}

_JOB_NO_ANDAMENTO = {
    k: v for k, v in _JOB.items() if k not in ("cortes_ms", "capa_url")
}

ID_DA_PASSADA = "gemini-3.1-pro-20261104"
_RESUMO_DA_PASSADA = {
    "id": ID_DA_PASSADA,
    "job_id": ID_DO_JOB,
    "modelo": "gemini-3.1-pro",
    "criada_em": "2026-11-04T12:00:00.000000Z",
    "custo": {
        "tokens_de_entrada": 1250000,
        "tokens_de_saida": 38000,
        "preco_por_milhao_de_entrada": 2.0,
        "preco_por_milhao_de_saida": 12.0,
        "usd": 2.956,
    },
    "etapas": [{"nome": "analise", "segundos": 212.4}],
}
_ITEM_DA_COMPARACAO = {
    "identidade": "pessoa-1",
    "inicio_ms": 0,
    "fim_ms": 9800,
    "detalhe": None,
    "marca": "igual",
    "motivos": [],
}
_MOMENTO = {
    "tipo": "plano",
    "inicio_ms": 9800,
    "fim_ms": 14200,
    "motivo": "Fulana de Tal recebe o elenco no estúdio.",
    "destaques": [{"inicio": 0, "fim": 12}],
    "quadro_url": None,
    "quadro": "quadros/plano-6.jpg",
}
_BUSCA = {
    "entendida": {
        "evidencias": [],
        "programa": None,
        "desde": None,
        "ate": None,
        "termo_da_foto": None,
    },
    # `dict(...)`: a chave entre aspas casaria com um nome da busca no checador de nomes.
    "videos": [
        dict(  # noqa: C408
            job_id=ID_DO_JOB,
            nome="TARD_20261103_BLU.mp4",
            programa="TV Fama",
            data_exibicao="2026-11-03",
            duracao_s=598.4,
            n_momentos=1,
            momentos=[_MOMENTO],
        )
    ],
    "sem_aparicoes": [],
    "plano_b": False,
    "facetas": {
        "programa": [{"valor": "TV Fama", "rotulo": "TV Fama", "videos": 1}],
        "mes": [{"valor": "2026-11", "rotulo": "novembro de 2026", "videos": 1}],
        "pessoa": [
            {"valor": "pessoa-1", "rotulo": "Fulana de Tal", "videos": 1},
        ],
        "marca": [],
        "tipo": [{"valor": "plano", "rotulo": "plano", "videos": 1}],
    },
    "quadros_expiram_em": INSTANTE,
}
_PARAMETROS_DO_PERIODO = (
    "Os filtros `programa`, `desde` e `ate` (datas `AAAA-MM-DD` de exibição) "
    "restringem os vídeos; `sem_periodo=true` inclui os vídeos sem data de exibição."
)
_BUSCA_DO_SISTEMA = (
    "A chave só acha os vídeos do próprio sistema. Cada momento traz `quadro`, o "
    "caminho do quadro no vídeo (`quadros/plano-6.jpg`): peça a URL em `GET "
    "/v1/jobs/{job_id}/quadros/{arquivo}`, com o nome do arquivo (`plano-6.jpg`). O "
    "`quadro_url` assinado é obsoleto e vai sair da resposta. O resultado vem em "
    "páginas de `limite` vídeos, até uns 500: o cabeçalho `X-Proximo-Cursor` traz o "
    "`cursor` da página seguinte e some na última. Repita a mesma consulta com ele "
    "em até 15 min; a ordem é a da 1ª página. Escopo `ler`."
)

OPERACOES: tuple[Operacao, ...] = (
    Operacao(
        "GET",
        "/v1/eu",
        "Quem sou eu",
        "Devolve o sistema dono da chave e os escopos que ela tem (`criar`, `ler` e "
        "`cancelar`). É o jeito mais barato de conferir que a chave de teste funciona.",
        {"sistema": "sistema-legado", "escopos": ["cancelar", "criar", "ler"]},
        _sem_chave(),
    ),
    Operacao(
        "GET",
        "/v1/programas",
        "Programas aceitos",
        "Os nomes de programa que o campo `programa` do envio aceita, em ordem "
        "alfabética. Exige um dos escopos `criar` ou `ler`.",
        ["TV Fama"],
        (
            *_sem_chave("criar ou ler"),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "POST",
        "/v1/jobs",
        "Registrar um vídeo",
        "Registra o pedido de decupagem de um MP4 e devolve o Job em "
        "`aguardando_upload` com a `url_de_upload`: uma URL assinada, válida por 15 min, "
        "que abre um upload retomável no Cloud Storage (veja o guia); o `POST` que abre a sessão "
        "leva o cabeçalho `x-goog-if-generation-match: 0`. Escopo `criar`.\n\n"
        "O cabeçalho `Idempotency-Key` (até 255 caracteres ASCII imprimíveis) torna o "
        "pedido repetível: a repetição com o mesmo corpo, em até 48 h, devolve o mesmo "
        "Job com **200** (e não 202), e `url_de_upload` pode vir `null` se o upload já "
        "foi feito. A mesma chave com outro corpo dá 409. A chave vale por sistema.\n\n"
        "O `nome` termina em `.mp4` e o `tipo` é sempre `video/mp4`; arquivos `.mov` "
        "não são aceitos, mesmo com conteúdo MP4: envie com nome `.mp4`.",
        {
            **_JOB,
            "estado": "aguardando_upload",
            "etapas": [],
            "duracao_s": None,
            "cortes_ms": None,
            "taxa_de_quadros": None,
            "criado_em": INSTANTE,
            "reprocessavel_ate": "2026-11-10T21:14:05.120000Z",
            "url_de_upload": "https://storage.googleapis.com/BUCKET/"
            + ID_DO_JOB
            + "?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Signature=...",
        },
        (
            *_sem_chave("criar"),
            Erro(
                409,
                "Idempotency-Key já usada com outro corpo",
                "Use uma chave nova para um pedido novo; a antiga é lembrada por 48 h.",
            ),
            Erro(
                410,
                "Este Job foi apagado",
                "A repetição com o mesmo `Idempotency-Key` de um Job que foi para a "
                "lixeira ou foi purgado não devolve nem recria o Job. Para enviar o "
                "vídeo de novo, use uma chave nova.",
            ),
            Erro(
                429,
                "Teto de 200 Jobs por hora atingido",
                "A chave criou 200 Jobs na última hora (o teto de uma pessoa é 30). O "
                "cabeçalho `Retry-After` traz os segundos de espera (3600, o pior caso): "
                "espere esse tempo, mande menos vídeos por hora e repita com o mesmo "
                "`Idempotency-Key`.",
            ),
            Erro(
                415,
                "Só video/mp4",
                'Mande `"tipo": "video/mp4"`. Não recodifique o arquivo.',
            ),
            Erro(
                422,
                "Tamanho fora do limite",
                "O `tamanho_bytes` é zero ou passa do máximo (4 GiB).",
            ),
            Erro(
                422,
                "Data de exibição no futuro",
                "A `data_exibicao` é depois de hoje (Brasília). Mande a data em que o "
                "programa foi ao ar.",
            ),
            Erro(
                422,
                "Idempotency-Key inválida",
                "O cabeçalho `Idempotency-Key` está vazio, passa de 255 caracteres ou "
                "tem caractere que não é ASCII imprimível. Use um UUID.",
            ),
            Erro(
                422,
                "Erro de validação",
                "Um campo do corpo está fora do formato (nome sem `.mp4`, nome com `/`, "
                "campo desconhecido, `programa` fora de `GET /v1/programas`, "
                "`data_exibicao` ausente ou fora de `AAAA-MM-DD`). Aqui `detail` é uma "
                "lista: leia `loc` (onde) e `msg` (por quê) em cada item.",
                exemplo=[
                    {
                        "type": "missing",
                        "loc": ["body", "data_exibicao"],
                        "msg": "Field required",
                        "input": {"nome": "TARD_20261103_BLU.mp4"},
                    }
                ],
            ),
            _INDISPONIVEL,
        ),
        pedido=_NOVO_JOB,
        status="202",
    ),
    Operacao(
        "GET",
        "/v1/jobs",
        "Listar os Jobs do sistema",
        "Lista os Jobs da chave (nunca os de outro sistema), do mais recente ao mais "
        "antigo, com filtros opcionais: `programa`, `estado` (repetível), `exibicao_de`, "
        "`exibicao_ate`, `q` (palavras do nome), `ordem` (`enviado` ou `exibicao`). Com "
        "`limite` (1 a 200) a lista vem em páginas: o cabeçalho `X-Proximo-Cursor` traz "
        "o `cursor` da página seguinte e some na última. Sem `limite`, vem tudo. "
        "Escopo `ler`. A lista não traz `cortes_ms`: só `GET /v1/jobs/{job_id}`. "
        "Com `capa=false` a seleção é a mesma, mas sem `capa_url` (as capas não são "
        "assinadas): serve para quem só conta os Jobs.",
        [{k: v for k, v in _JOB.items() if k != "cortes_ms"}],
        (
            *_sem_chave("ler"),
            Erro(
                422,
                "Cursor inválido",
                "Use o `X-Proximo-Cursor` da resposta anterior, sem mudar os filtros. "
                "Também dá `Erro de validação` se um parâmetro estiver fora do formato.",
            ),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}",
        "Ler um Job",
        "O estado do Job, as etapas já iniciadas e, se falhou, o `codigo_falha`. É o "
        "que se consulta para acompanhar o processamento. A resposta traz `ETag`: "
        "mande-o em `If-None-Match` e, se nada mudou, vem `304` sem corpo. "
        "Escopo `ler`.",
        _JOB,
        (
            *_sem_chave("ler"),
            Erro(
                304,
                "Não mudou",
                "O `If-None-Match` casa com o `ETag` atual: nada mudou desde a última "
                "leitura e a resposta vem sem corpo. Use a cópia que você guardou.",
                sem_corpo=True,
            ),
            _NAO_ACHOU,
            _INDISPONIVEL,
        ),
        parametros=(
            {
                "name": "If-None-Match",
                "in": "header",
                "required": False,
                "description": "O `ETag` da última leitura. Se o Job não mudou, a "
                "resposta é `304` sem corpo.",
                "schema": {"type": "string"},
            },
        ),
    ),
    Operacao(
        "DELETE",
        "/v1/jobs/{job_id}",
        "Cancelar um Job",
        "Cancela um Job que ainda não terminou: apaga o que foi enviado e o Job vai a "
        "`cancelado`. Job em `concluido`, `falhou` ou `cancelado` não se cancela. "
        "Escopo `cancelar`.",
        {**_JOB, "estado": "cancelado", "etapas": [], "duracao_s": None},
        (
            *_sem_chave("cancelar"),
            _NAO_ACHOU,
            Erro(
                409,
                "Job em <estado>, não cancelável",
                "O Job já terminou; não há o que cancelar.",
                exemplo="Job em concluido, não cancelável",
            ),
            _INDISPONIVEL,
        ),
        status="202",
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/reproducao",
        "URL para reproduzir o vídeo",
        "Uma URL assinada, de 10 minutos, do proxy de reprodução do vídeo (para um "
        "player). Só existe com o Job `concluido`. Escopo `ler`.",
        {
            "url": "https://storage.googleapis.com/BUCKET/...",
            "expira_em": INSTANTE,
        },
        (*_sem_chave("ler"), _NAO_ACHOU, _NAO_CONCLUIDO, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/download",
        "URL para baixar o vídeo",
        "Uma URL assinada, de 5 minutos, do proxy de 480p, com o nome do arquivo "
        "sem extensão seguido de `.480p.mp4`. A resposta traz o aviso de que a cópia "
        "em alta resolução está no arquivo da RedeTV. Só existe com o Job `concluido`; "
        "cada pedido fica na auditoria antes da resposta. "
        "Escopo `ler`.",
        {
            "url": "https://storage.googleapis.com/BUCKET/...",
            "expira_em": INSTANTE,
            "aviso": (
                "A cópia em alta resolução está no arquivo da RedeTV. "
                "Este download é a versão de 480p processada pelo MAM."
            ),
        },
        (*_sem_chave("ler"), _NAO_ACHOU, _NAO_CONCLUIDO, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/decupagem",
        "Buscar a decupagem",
        "A Decupagem do vídeo em JSON (esquema 1.5): pautas, pessoas, planos, "
        "comerciais, transcrição e textos na tela, todos com tempos em milissegundos. "
        "Já traz as correções dos revisores; `versao_decupagem` identifica essa "
        "versão. Com `?versao=modelo` vem o que o modelo gerou, sem correções. A "
        "resposta vai comprimida (gzip) se o cliente mandar `Accept-Encoding: gzip`. "
        "Só existe com o Job `concluido`. Escopo `ler`. O exemplo abaixo está resumido.",
        _DECUPAGEM,
        (*_sem_chave("ler"), _NAO_ACHOU, _NAO_CONCLUIDO, _VALIDACAO, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/decupagem/download",
        "Baixar a decupagem como arquivo",
        "A mesma Decupagem entregue, indentada e com `Content-Disposition: attachment` "
        "(nome do vídeo terminado em `.decupagem.json`), para salvar em disco. Só "
        "existe com o Job `concluido`; cada pedido fica na auditoria. Escopo `ler`.",
        _DECUPAGEM,
        (*_sem_chave("ler"), _NAO_ACHOU, _NAO_CONCLUIDO, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/andamento",
        "Estado de vários Jobs de uma vez",
        "O estado de até 200 Jobs numa leitura só (`ids` separados por vírgula), para "
        "atualizar o que está em andamento sem uma chamada por Job: o mesmo detalhe de "
        "`GET /v1/jobs/{job_id}`, sem `capa_url` e sem `cortes_ms`. Id que não existe "
        "ou é de outro sistema é omitido da lista, sem erro. Escopo `ler`.",
        [_JOB_NO_ANDAMENTO],
        (
            *_sem_chave("ler"),
            Erro(
                422,
                "No máximo 200 ids",
                "Peça até 200 ids por chamada; divida o resto em outras.",
            ),
            _validacao("missing", "query", "ids", "Field required", None),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/quadros/{arquivo}",
        "URL de um quadro do vídeo",
        "Uma URL assinada de um quadro JPEG do vídeo, válida até o `expira_em` (7 horas ou mais). O `arquivo` é o "
        "nome que a busca devolve em `quadro` (`quadros/plano-6.jpg` vira `plano-6.jpg`). "
        "Só existe com o Job `concluido`. Escopo `ler`.",
        {
            "url": "https://storage.googleapis.com/BUCKET/...",
            "expira_em": INSTANTE,
        },
        (
            *_sem_chave("ler"),
            _NAO_ACHOU,
            _NAO_CONCLUIDO,
            _validacao(
                "string_pattern_mismatch",
                "path",
                "arquivo",
                f"String should match pattern '{_PADRAO_DO_QUADRO}'",
                "x",
                {"pattern": _PADRAO_DO_QUADRO},
            ),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "POST",
        "/v1/jobs/quadros",
        "URLs de vários quadros de uma vez",
        "As URLs assinadas de até 100 quadros (pares `job` e `arquivo`, o nome que a busca "
        "devolve em `quadro`) numa chamada só, no lugar de uma por quadro. Cada Job é lido "
        "uma vez. Job que não existe, é de outro sistema, está na lixeira ou ainda não "
        "`concluiu` volta com `url` e `expira_em` nulos, sem derrubar o lote. Escopo `ler`.",
        [
            {
                "job": "6f1c2a",
                "arquivo": "plano-6.jpg",
                "url": "https://storage.googleapis.com/BUCKET/...",
                "expira_em": INSTANTE,
            },
            {
                "job": "fantasma",
                "arquivo": "plano-0.jpg",
                "url": None,
                "expira_em": None,
            },
        ],
        (
            *_sem_chave("ler"),
            Erro(
                422,
                "Erro de validação",
                "Mais de 100 pares, ou um `arquivo` fora do formato. Aqui `detail` é uma "
                "lista: leia `loc` e `msg`. Peça até 100 pares por chamada.",
                exemplo=[
                    {
                        "type": "too_long",
                        "loc": ["body", "quadros"],
                        "msg": "List should have at most 100 items after validation, not 101",
                        "input": "[...]",
                        "ctx": {
                            "field_type": "List",
                            "max_length": 100,
                            "actual_length": 101,
                        },
                    }
                ],
            ),
            _INDISPONIVEL,
        ),
        pedido={"quadros": [{"job": "6f1c2a", "arquivo": "plano-6.jpg"}]},
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/passadas",
        "Listar as passadas do Job",
        "As passadas do vídeo: análises extras que o time do MAM rodou, com outro "
        "modelo, para comparar com a decupagem entregue. Cada item traz o modelo, o "
        "custo e o tempo por etapa, sem a decupagem. Do mais antigo ao mais novo; "
        "lista vazia se não há. Escopo `ler`.",
        [_RESUMO_DA_PASSADA],
        (*_sem_chave("ler"), _NAO_ACHOU, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/passadas/{passada_id}",
        "Ler uma passada",
        "Uma passada inteira: o resumo (modelo, custo, etapas) e a Decupagem que ela "
        "gerou, no mesmo esquema da entregue. Não recebe correções. Escopo `ler`. O "
        "exemplo abaixo está resumido.",
        {
            **_RESUMO_DA_PASSADA,
            "decupagem": {
                k: v for k, v in _DECUPAGEM.items() if k != "versao_decupagem"
            },
        },
        (*_sem_chave("ler"), _NAO_ACHOU, _NAO_ACHOU_A_PASSADA, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/passadas/{passada_id}/comparacao",
        "Comparar a passada com a decupagem do Job",
        "A decupagem do modelo do Job (lado `a`, sem correções) contra a passada (lado "
        "`b`), em seis requisitos (`famosos`, `mencoes`, `pautas`, `broll_limpos`, "
        "`broll_descricoes` e `comerciais`). Cada item vem marcado `igual`, `difere` "
        "(com os `motivos`) ou `so_aqui`. Traz também o custo e o tempo de cada lado. "
        "Só existe com o Job `concluido`. Escopo `ler`. O exemplo abaixo está resumido.",
        {
            "passada_id": ID_DA_PASSADA,
            "modelo": "gemini-3.1-pro",
            "modelo_do_job": "gemini-3.1-flash",
            "duracao_ms": 598400,
            "a": {
                "custo_usd": None,
                "custo_por_hora_usd": None,
                "tempo_total_s": 180.2,
                "etapas": [{"nome": "analise", "segundos": 150.0}],
            },
            "b": {
                "custo_usd": 2.956,
                "custo_por_hora_usd": 17.78,
                "tempo_total_s": 212.4,
                "etapas": [{"nome": "analise", "segundos": 212.4}],
            },
            "requisitos": [
                {
                    "nome": "famosos",
                    "a": [_ITEM_DA_COMPARACAO],
                    "b": [_ITEM_DA_COMPARACAO],
                }
            ],
        },
        (
            *_sem_chave("ler"),
            _NAO_ACHOU,
            _NAO_CONCLUIDO,
            _NAO_ACHOU_A_PASSADA,
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "GET",
        "/v1/objetos/tipos",
        "Tipos de objeto conhecidos",
        "Os tipos de objeto que as decupagens já têm (`camisa`, `bolsa`...), do mais "
        "frequente ao menos, com quantas ocorrências cada um. `q` filtra pelo começo do "
        "nome; sem `q`, vêm os mais frequentes. Escopo `ler`.",
        [{"tipo": "camisa", "ocorrencias": 412}, {"tipo": "bolsa", "ocorrencias": 97}],
        (
            *_sem_chave("ler"),
            _validacao(
                "string_too_long",
                "query",
                "q",
                "String should have at most 100 characters",
                "x" * 101,
                {"max_length": 100},
            ),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "GET",
        "/v1/catalogo/pessoas",
        "Achar pessoas no catálogo",
        "As pessoas do catálogo cujo nome ou apelido casa com `q` pelo começo das palavras "
        "(sem diferença de maiúsculas ou acento, e com tolerância a um erro de digitação), "
        "para achar o `id` que se usa na busca. "
        "`a_revisar` marca a que ainda espera revisão de um curador. Escopo `ler`.",
        [
            {
                "id": "pessoa-1",
                "nome": "Fulana de Tal",
                "papel": "apresentadora",
                "rotulo": "Fulana de Tal (apresentadora)",
                "a_revisar": False,
            }
        ],
        (
            *_sem_chave("ler"),
            _validacao("missing", "query", "q", "Field required", None),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "GET",
        "/v1/catalogo/marcas",
        "Achar marcas no catálogo",
        "As marcas do catálogo cujo nome ou apelido casa com `q` pelo começo das palavras "
        "(sem diferença de maiúsculas ou acento, e com tolerância a um erro de digitação). "
        "`a_revisar` marca a que ainda espera revisão de um curador. Escopo `ler`.",
        [{"id": "marca-1", "nome": "Marca Exemplo", "a_revisar": False}],
        (
            *_sem_chave("ler"),
            _validacao("missing", "query", "q", "Field required", None),
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "GET",
        "/v1/busca",
        "Buscar momentos por texto",
        "Procura nos vídeos do sistema: pessoas, falas, textos na tela, objetos e "
        "marcas. `q` é a frase em português, saneada e buscada inteira, sem interpretação "
        "pelo Gemini nem Model Armor. Aspas delimitam uma frase exata; nomes inteiros do "
        "catálogo acrescentam cláusulas de pessoa. Filtros: `ev` (repetível: `imagem`, "
        "`citada`, `fala`, `gc`, `objeto`, `marca`), `tipo` (`plano`, `fala`, "
        "`texto_na_tela`, `objeto`), `pessoa`, `marca`, `ordem` (`relevancia` ou "
        "`data`) e `limite` (1 a 50 vídeos). "
        + _PARAMETROS_DO_PERIODO
        + " "
        + _BUSCA_DO_SISTEMA
        + " Limite de 30 consultas por minuto por chave. `ev` restringe também o texto "
        "livre: `imagem` busca planos, `fala` falas e `gc` textos na tela; sem `ev`, todos "
        "os tipos entram. `entendida` traz os filtros aplicados e `plano_b` fica `false`, "
        "mantido por compatibilidade.",
        _BUSCA,
        (
            *_sem_chave("ler"),
            _PERIODO_INVERTIDO,
            _validacao("missing", "query", "q", "Field required", None),
            _CURSOR_DA_BUSCA,
            _MUITA_CONSULTA,
            _DEMOROU,
            _INDISPONIVEL,
        ),
    ),
    Operacao(
        "POST",
        "/v1/busca/imagem",
        "Buscar momentos por imagem",
        "Acha os momentos do objeto que aparece na foto: o modelo da consulta dá o nome do "
        "objeto (e no máximo uma característica) e a busca segue como se esse termo tivesse "
        "sido digitado, sem segunda chamada ao Gemini nem Model Armor; o termo vem em "
        "`entendida.termo_da_foto`. O corpo é "
        "`multipart/form-data` com o arquivo no campo `arquivo` (JPEG ou PNG, até 5 MB e 25 "
        "milhões de pixels; o `Content-Length` é obrigatório). A foto só passa pela memória "
        "e pelo modelo: não é guardada. "
        + _PARAMETROS_DO_PERIODO
        + " "
        + _BUSCA_DO_SISTEMA
        + " Divide com a busca por texto o limite de 30 consultas por minuto.",
        _BUSCA,
        (
            *_sem_chave("ler"),
            Erro(
                411,
                "Envie o tamanho do pedido",
                "Mande o cabeçalho `Content-Length` (um cliente comum já manda).",
            ),
            _PERIODO_INVERTIDO,
            Erro(
                422,
                "A imagem passa do tamanho máximo",
                "O arquivo passa de 5 MB. Reduza a foto.",
            ),
            Erro(
                422,
                "A imagem passa do tamanho máximo em pixels",
                "A foto passa de 25 milhões de pixels. Reduza a foto.",
            ),
            Erro(
                422,
                "Envie uma imagem JPEG ou PNG válida",
                "O arquivo não é JPEG nem PNG, ou está corrompido, ou o multipart está "
                "malformado.",
            ),
            Erro(
                422,
                "Envie a imagem no campo arquivo",
                "O multipart não tem o campo `arquivo`.",
            ),
            _CURSOR_DA_BUSCA,
            _MUITA_CONSULTA,
            Erro(
                503,
                "A busca por imagem não está disponível agora",
                "O modelo que descreve a foto está desligado ou fora do ar, ou não achou "
                "objeto na foto. Repita com espera crescente ou tente outra foto.",
            ),
            _DEMOROU,
        ),
        formulario={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "arquivo": {
                                "type": "string",
                                "format": "binary",
                                "description": "A foto: JPEG ou PNG, até 5 MB.",
                            }
                        },
                        "required": ["arquivo"],
                    }
                }
            },
        },
    ),
    Operacao(
        "GET",
        "/v1/correcoes/catalogo",
        "Vocabulários das decupagens",
        "Os valores que os campos fixos da decupagem aceitam, com o rótulo em "
        "português: tipos de comercial e de texto na tela, tons da pauta, fontes do "
        "nome, categorias e cores de objeto, relações, e os limites de tamanho dos "
        "textos. Serve para ler os códigos que a decupagem traz. `tipos` lista os "
        "tipos de Correção que os revisores aplicam; a chave de sistema só lê. Qualquer "
        "escopo serve. O exemplo abaixo está resumido.",
        {
            "tipos": [{"valor": "pessoa.renomear", "rotulo": "Renomear pessoa"}],
            "tipos_de_comercial": [{"valor": "testemunhal", "rotulo": "testemunhal"}],
            "tipos_de_texto_na_tela": [{"valor": "gc", "rotulo": "gc"}],
            "tons_da_pauta": [{"valor": "polemico", "rotulo": "polêmico"}],
            "fontes_do_nome": [{"valor": "rosto", "rotulo": "rosto"}],
            "categorias_de_objeto": [{"valor": "calcado", "rotulo": "calçado"}],
            "cores_base": [{"valor": "vermelho", "rotulo": "vermelho"}],
            "relacoes_do_objeto": [{"valor": "veste", "rotulo": "veste"}],
            "limites": {"nome": 200, "texto": 2000, "motivo": 500},
            "prefixos": {"acrescentado": "acr-", "nao_identificado": "nid-"},
        },
        (*_sem_chave(),),
    ),
)


def _exemplo_em(resposta: dict[str, Any], exemplo: Any) -> None:
    conteudo = resposta.setdefault("content", {}).setdefault("application/json", {})
    conteudo["example"] = exemplo


def _esquema_do_erro(erros: list[Erro], respostas: dict[str, Any]) -> dict[str, Any]:
    em_lista = [isinstance(e.exemplo, list) for e in erros]
    if erros[0].status != 422 or "422" not in respostas:
        return _REF_DO_ERRO
    # O mesmo 422 vem em texto (regra da rota) ou em lista (validação do FastAPI).
    validacao = respostas["422"]["content"]["application/json"]["schema"]
    if all(em_lista):
        return validacao  # type: ignore[no-any-return]
    return {"anyOf": [_REF_DO_ERRO, validacao]}


def _resposta_de_erro(erros: list[Erro], respostas: dict[str, Any]) -> dict[str, Any]:
    resposta: dict[str, Any] = {
        "description": "\n\n".join(f"{e.detalhe}. {e.acao}" for e in erros)
    }
    if erros[0].sem_corpo:
        # O 304 não leva corpo; o `ETag` segue como na resposta de sucesso.
        resposta["headers"] = {
            "ETag": {"description": "A versão atual.", "schema": {"type": "string"}}
        }
        return resposta
    if len(erros) == 1:
        _exemplo_em(resposta, erros[0].corpo)
    else:
        # Vários erros com o mesmo status: um exemplo nomeado para cada.
        resposta["content"] = {
            "application/json": {
                "examples": {
                    e.detalhe: {"summary": e.detalhe, "value": e.corpo} for e in erros
                }
            }
        }
    resposta["content"]["application/json"]["schema"] = _esquema_do_erro(
        erros, respostas
    )
    return resposta


def _documentar(operacao: dict[str, Any], doc: Operacao) -> None:
    operacao["summary"] = doc.resumo
    operacao["description"] = doc.descricao
    operacao["tags"] = ["sistemas"]
    if doc.pedido is not None:
        operacao["requestBody"]["content"]["application/json"]["example"] = doc.pedido
    if doc.formulario is not None:
        operacao["requestBody"] = doc.formulario
    if doc.parametros:
        operacao["parameters"] = [*operacao.get("parameters", []), *doc.parametros]
    respostas: dict[str, Any] = operacao["responses"]
    sucesso = doc.status or next(s for s in respostas if s.startswith("2"))
    respostas[sucesso]["description"] = "Sucesso"
    _exemplo_em(respostas[sucesso], doc.resposta)
    por_status: dict[int, list[Erro]] = {}
    for erro in doc.erros:
        por_status.setdefault(erro.status, []).append(erro)
    for status, erros in por_status.items():
        respostas[str(status)] = _resposta_de_erro(erros, respostas)
    if "422" in respostas and 422 not in por_status:
        del respostas["422"]
    operacao["responses"] = dict(sorted(respostas.items()))


def _referencias(no: Any, achadas: set[str]) -> None:
    if isinstance(no, dict):
        for chave, valor in no.items():
            if chave == "$ref" and isinstance(valor, str):
                achadas.add(valor.rsplit("/", 1)[-1])
            else:
                _referencias(valor, achadas)
    elif isinstance(no, list):
        for item in no:
            _referencias(item, achadas)


def esquema_dos_sistemas(app: FastAPI) -> dict[str, Any]:
    """O OpenAPI do app só com as rotas dos sistemas, documentadas."""
    completo = copy.deepcopy(app.openapi())
    caminhos: dict[str, Any] = {}
    for doc in OPERACOES:
        operacao = completo["paths"][doc.caminho][doc.metodo.lower()]
        _documentar(operacao, doc)
        caminhos.setdefault(doc.caminho, {})[doc.metodo.lower()] = operacao
    esquemas: dict[str, Any] = completo.get("components", {}).get("schemas", {})
    esquemas[ERRO_EM_TEXTO] = {
        "title": ERRO_EM_TEXTO,
        "type": "object",
        "properties": {"detail": {"type": "string", "title": "Detail"}},
        "required": ["detail"],
    }
    usados: set[str] = set()
    _referencias(caminhos, usados)
    novos = set(usados)
    while novos:
        achadas: set[str] = set()
        for nome in novos:
            _referencias(esquemas[nome], achadas)
        novos = achadas - usados
        usados |= achadas
    return {
        "openapi": completo["openapi"],
        "info": {
            "title": "MAM RedeTV: API para os sistemas",
            "version": "1",
            "description": "Rotas `/v1` que os sistemas da RedeTV chamam com uma chave de "
            "API no cabeçalho `X-API-Key`. O passo a passo está em `docs/api/guia.md`.",
        },
        "paths": caminhos,
        "components": {
            "schemas": {n: esquemas[n] for n in sorted(usados)},
            "securitySchemes": {
                "ChaveDeApi": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            },
        },
        "security": [{"ChaveDeApi": []}],
    }


def json_do_esquema(app: FastAPI) -> str:
    return json.dumps(esquema_dos_sistemas(app), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    from api.main import criar_app

    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json_do_esquema(criar_app()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
