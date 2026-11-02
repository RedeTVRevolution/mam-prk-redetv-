"""Taxa de correção por tipo e por programa (#265): `GET /v1/qualidade/taxa-de-correcao`
e `make taxa-de-correcao`.

Numerador: as correções em vigor do tipo (aprovadas, ou de tipo que não exige aprovação,
e não desfeitas) criadas no período, sobre o JSON do modelo que está na decupagem do Job.
Denominador: os itens daquele tipo nas decupagens revisadas. Revisada é a decupagem de um
Job concluído que teve, no período, uma correção ou um pulso de revisão (#251): contar só
as que têm correção esconderia o vídeo que a pessoa abriu e deixou como estava, e o
modelo acertou. O item é o do tipo que a correção corrige (`pessoa`, `pauta`, `comercial`,
`plano`, `fala`, `texto_na_tela`); no `item.tempos`, que serve a qualquer um, são todos.
O tipo que acrescenta (`pauta.acrescentar`) tem como denominador os mesmos itens do tipo.

Uma linha por programa, versão do pipeline (`None` na decupagem anterior à versão) e tipo.
A taxa é `None` se o denominador é zero. Ambiente do comando: `GCP_PROJECT_ID`,
`BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`.
"""

import csv
import io
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel

from api.auth import ChamadorAutenticado, Usuario
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.correcoes import (
    CORRIGIVEIS,
    TIPOS,
    Correcao,
    RepositorioDeCorrecoes,
    estado_das,
    versao_do_modelo,
)
from api.jobs import (
    RepositorioDeJobs,
    ServicoIndisponivel,
    _confere_permissao,
    _tem_permissao,
)
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioDeRevisaoFirestore,
    RepositorioFirestore,
)
from api.reprocessar_versao import LeitorDeDecupagem
from api.revisao import RepositorioDeRevisao

log = logging.getLogger(__name__)

__all__ = [
    "COLUNAS_DO_CSV",
    "LinhaDaTaxa",
    "calcular",
    "criar_rotas_da_qualidade",
    "em_csv",
    "main",
]

TIPOS_DE_ITEM = ("pessoa", "pauta", "comercial", "plano", "fala", "texto_na_tela")
COLUNAS_DO_CSV = (
    "programa",
    "versao_pipeline",
    "tipo",
    "correcoes",
    "itens",
    "taxa_de_correcao",
)


class LinhaDaTaxa(BaseModel):
    programa: str | None
    versao_pipeline: str | None
    tipo: str
    correcoes: int
    itens: int
    taxa_de_correcao: float | None


def _itens_do_tipo(modelo: Mapping[str, Any], tipo: str) -> int:
    """Quantos itens do tipo do item que a correção do `tipo` corrige."""
    do_item = TIPOS[tipo].tipo_do_item
    return sum(
        _quantos(modelo, t) for t in (TIPOS_DE_ITEM if do_item is None else (do_item,))
    )


_CHAVE_DO_ITEM = {
    "pessoa": "pessoas",
    "pauta": "pautas",
    "comercial": "comerciais",
    "plano": "planos",
    "fala": "transcricao",
    "texto_na_tela": "textos_na_tela",
}


def _quantos(modelo: Mapping[str, Any], tipo_do_item: str) -> int:
    lista = modelo.get(_CHAVE_DO_ITEM[tipo_do_item], [])
    return sum(isinstance(i, dict) for i in lista) if isinstance(lista, list) else 0


def _no_periodo(quando: datetime, desde: datetime | None, ate: datetime | None) -> bool:
    return (desde is None or quando >= desde) and (ate is None or quando < ate)


def calcular(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
    desde: datetime | None = None,
    ate: datetime | None = None,
    programa: str | None = None,
) -> list[LinhaDaTaxa]:
    """As linhas do período `[desde, ate)`, em ordem de programa, versão e tipo."""
    pulsados = {
        m.job_id
        for m in revisao.todas(desde)
        if _no_periodo(m.ultimo_pulso, desde, ate)
    }
    # (programa, versão, tipo) -> [correções, itens]
    somas: dict[tuple[str | None, str | None, str], list[int]] = {}
    for job in repositorio.listar():
        if job.estado != "concluido" or (programa and job.programa != programa):
            continue
        feitas = correcoes.listar(job.id)
        no_periodo = [c for c in feitas if _no_periodo(c.criada_em, desde, ate)]
        if job.id not in pulsados and not any(
            c.tipo in CORRIGIVEIS for c in no_periodo
        ):
            continue
        try:
            conteudo = b"".join(decupagens.abrir_decupagem(job.id))
            modelo = json.loads(conteudo)
            versao = versao_do_modelo(conteudo)
            versao_pipeline = modelo.get("versao_pipeline")
            vigor = _em_vigor_no_periodo(feitas, no_periodo, versao)
            for tipo in CORRIGIVEIS:
                soma = somas.setdefault(
                    (job.programa, versao_pipeline or None, tipo), [0, 0]
                )
                soma[0] += sum(c.tipo == tipo for c in vigor)
                soma[1] += _itens_do_tipo(modelo, tipo)
        except (ServicoIndisponivel, ValueError, KeyError, TypeError):
            log.warning("decupagem de %s não lida: fora da taxa", job.id)
    return [
        LinhaDaTaxa(
            programa=p,
            versao_pipeline=v,
            tipo=t,
            correcoes=n,
            itens=itens,
            taxa_de_correcao=round(n / itens, 4) if itens else None,
        )
        for (p, v, t), (n, itens) in sorted(
            somas.items(), key=lambda kv: tuple(x or "" for x in kv[0])
        )
    ]


def _em_vigor_no_periodo(
    todas: list[Correcao], no_periodo: list[Correcao], versao: str
) -> list[Correcao]:
    """Do período, as em vigor segundo o histórico inteiro (o desfazer ou a aprovação
    pode ser de fora do período) e feitas sobre este JSON do modelo."""
    estado = estado_das(todas)
    return [
        c
        for c in no_periodo
        if c.tipo in CORRIGIVEIS and estado.em_vigor(c.id) and c.ancora.versao == versao
    ]


def em_csv(linhas: list[LinhaDaTaxa]) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(COLUNAS_DO_CSV)
    for linha in linhas:
        escritor.writerow(
            [
                linha.programa or "",
                linha.versao_pipeline or "",
                linha.tipo,
                linha.correcoes,
                linha.itens,
                "" if linha.taxa_de_correcao is None else linha.taxa_de_correcao,
            ]
        )
    return saida.getvalue()


def _inicio_do_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min, UTC)


def _exige_ver_a_taxa(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: pessoa com `correcao.aprovar` ou `auditoria.ver`; sistema não consulta."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não consulta a taxa de correção")
    if not _tem_permissao(request, chamador, "correcao.aprovar"):
        _confere_permissao(request, chamador, "auditoria.ver")
    return chamador


class TaxaDeCorrecao(BaseModel):
    desde: date | None
    ate: date | None
    programa: str | None
    linhas: list[LinhaDaTaxa]


def criar_rotas_da_qualidade(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
) -> APIRouter:
    rotas = APIRouter(prefix="/qualidade")

    @rotas.get("/taxa-de-correcao")
    def taxa_de_correcao(
        _pessoa: Annotated[Usuario, Depends(_exige_ver_a_taxa)],
        desde: date | None = None,
        ate: date | None = None,
        programa: str | None = None,
    ) -> TaxaDeCorrecao:
        """`desde` e `ate` são dias (UTC), os dois inclusive."""
        if desde and ate and desde > ate:
            raise HTTPException(422, "`desde` depois de `ate`")
        return TaxaDeCorrecao(
            desde=desde,
            ate=ate,
            programa=programa,
            linhas=calcular(
                repositorio,
                decupagens,
                correcoes,
                revisao,
                _inicio_do_dia(desde) if desde else None,
                _inicio_do_dia(ate) + timedelta(days=1) if ate else None,
                programa,
            ),
        )

    return rotas


def _dia(texto: str) -> date:
    return date.fromisoformat(texto)


def main(
    argumentos: list[str],
    ambiente: Mapping[str, str] = os.environ,
    escrever: Callable[[str], None] = print,
) -> int:
    """Argumentos: `DESDE`, `ATE` (dias ISO, inclusive) e `PROGRAMA`, todos opcionais."""
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
        pedidos = [*argumentos, "", "", ""][:3]
        desde = _dia(pedidos[0]) if pedidos[0] else None
        ate = _dia(pedidos[1]) if pedidos[1] else None
        if desde and ate and desde > ate:
            raise ValueError("DESDE depois de ATE")
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    banco = firestore.Client(project=projeto)
    linhas = calcular(
        RepositorioFirestore(banco),
        DecupagensStorage(ClienteStorage(project=projeto), aceitos, decupagens),
        RepositorioDeCorrecoesFirestore(banco),
        RepositorioDeRevisaoFirestore(banco),
        _inicio_do_dia(desde) if desde else None,
        _inicio_do_dia(ate) + timedelta(days=1) if ate else None,
        pedidos[2] or None,
    )
    escrever(em_csv(linhas).rstrip("\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
