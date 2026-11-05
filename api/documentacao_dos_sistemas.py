"""O OpenAPI das rotas `/v1` que os sistemas da RedeTV usam (E7, #277).

O FastAPI gera o esquema; aqui ficam, por rota, a descrição, os exemplos de pedido e de
resposta e os erros possíveis, que o FastAPI não sabe. O arquivo publicado
(`docs/api/openapi.json`) sai de `python -m api.documentacao_dos_sistemas`
(`make atualizar-openapi`) e um teste confere que ele bate com o gerado.
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
_VALIDACAO = Erro(
    422,
    "Erro de validação",
    "Um parâmetro está fora do formato. Aqui `detail` é uma lista: leia `loc` (onde) "
    "e `msg` (por quê) em cada item.",
    exemplo=[
        {
            "type": "literal_error",
            "loc": ["query", "versao"],
            "msg": "Input should be 'modelo'",
            "input": "outra",
        }
    ],
)
_NAO_CONCLUIDO = Erro(
    409,
    "Job em <estado>, não concluido",
    "O Job ainda não terminou (ou falhou). Espere o webhook ou consulte `GET "
    "/v1/jobs/{job_id}` até o `estado` ser `concluido`.",
    exemplo="Job em analisando, não concluido",
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
    "versao_esquema": "1.4",
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
        "`aguardando_upload` com a `url_de_upload`: uma URL assinada, válida por 24 h, "
        "que abre um upload retomável no Cloud Storage (veja o guia). Escopo `criar`.\n\n"
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
                415,
                "Só video/mp4",
                'Mande `"tipo": "video/mp4"`. Não recodifique o arquivo.',
            ),
            Erro(
                422,
                "Tamanho fora do limite",
                "O `tamanho_bytes` é zero ou passa do máximo (4 GiB). Outros 422 deste "
                "pedido: `Data de exibição no futuro`, `Idempotency-Key inválida` e o "
                "`Erro de validação` dos campos (nome sem `.mp4`, nome com `/`, campo "
                "desconhecido, `programa` fora de `GET /v1/programas`, `data_exibicao` "
                "ausente ou fora de `AAAA-MM-DD`).",
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
        "Escopo `ler`. A lista não traz `cortes_ms`: só `GET /v1/jobs/{job_id}`.",
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
        (*_sem_chave("ler"), _NAO_ACHOU, _INDISPONIVEL),
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
        "Uma URL assinada, de 5 minutos, da cópia limpa do vídeo, com o nome original "
        "do arquivo. Só existe com o Job `concluido`; cada pedido fica na auditoria. "
        "Escopo `ler`.",
        {
            "url": "https://storage.googleapis.com/BUCKET/...",
            "expira_em": INSTANTE,
        },
        (*_sem_chave("ler"), _NAO_ACHOU, _NAO_CONCLUIDO, _INDISPONIVEL),
    ),
    Operacao(
        "GET",
        "/v1/jobs/{job_id}/decupagem",
        "Buscar a decupagem",
        "A Decupagem do vídeo em JSON (esquema 1.4): pautas, pessoas, planos, "
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
)


def _exemplo_em(resposta: dict[str, Any], exemplo: Any) -> None:
    conteudo = resposta.setdefault("content", {}).setdefault("application/json", {})
    conteudo["example"] = exemplo


def _documentar(operacao: dict[str, Any], doc: Operacao) -> None:
    operacao["summary"] = doc.resumo
    operacao["description"] = doc.descricao
    operacao["tags"] = ["sistemas"]
    if doc.pedido is not None:
        operacao["requestBody"]["content"]["application/json"]["example"] = doc.pedido
    respostas: dict[str, Any] = operacao["responses"]
    sucesso = doc.status or next(s for s in respostas if s.startswith("2"))
    respostas[sucesso]["description"] = "Sucesso"
    _exemplo_em(respostas[sucesso], doc.resposta)
    for erro in doc.erros:
        resposta: dict[str, Any] = {
            "description": f"{erro.detalhe}. {erro.acao}",
        }
        _exemplo_em(resposta, erro.corpo)
        esquema: dict[str, Any] = _REF_DO_ERRO
        if erro.status == 422 and "422" in respostas:
            # O mesmo 422 vem em texto (regra da rota) ou em lista (validação do FastAPI).
            validacao = respostas["422"]["content"]["application/json"]["schema"]
            esquema = (
                validacao
                if isinstance(erro.exemplo, list)
                else {"anyOf": [_REF_DO_ERRO, validacao]}
            )
        resposta["content"]["application/json"]["schema"] = esquema
        respostas[str(erro.status)] = resposta
    if "422" in respostas and not any(e.status == 422 for e in doc.erros):
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
