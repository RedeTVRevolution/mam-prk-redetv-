"""Taxa de correção por tipo e por programa (#265): `GET /v1/qualidade/taxa-de-correcao`
e `make taxa-de-correcao`.

Numerador: as correções em vigor do tipo (aprovadas, ou de tipo que não exige aprovação,
e não desfeitas) que passaram a valer no período, sobre o JSON do modelo que está na
decupagem do Job. Passa a valer na aprovação, se exige aprovação, e na criação, se não
(a mesma data de `_em_ordem_de_vigencia`): a pendente aprovada depois do período conta
no período da aprovação, e um período fechado não muda de número. Conta correções, não
itens: duas na mesma pessoa contam duas, e a taxa pode passar de 1. A feita sobre um JSON
anterior a um reprocessamento sai, como no conjunto de regressão.

Denominador: os itens daquele tipo nas decupagens revisadas. Revisada é a decupagem de um
Job concluído que teve, no período, uma correção, uma aprovação ou um pulso de revisão
(#251): contar só as que têm correção esconderia o vídeo que a pessoa abriu e deixou como
estava, e o modelo acertou. A revisão guarda só o último pulso de cada pessoa no vídeo:
o vídeo revisado no período e reaberto depois dele, sem correção no período, fica de
fora. O item é o do tipo que a correção corrige (`pessoa`, `pauta`, `comercial`, `plano`,
`fala`, `texto_na_tela`); no `item.tempos`, que serve a qualquer um, são todos. O tipo
que acrescenta (`pauta.acrescentar`) tem como denominador os mesmos itens do tipo.

Uma linha por programa, versão do pipeline (`None` na decupagem anterior à versão) e tipo.
A taxa é `None` se o denominador é zero. Ambiente do comando: `GCP_PROJECT_ID`,
`BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`.
"""

import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.ambiente import FaltaNoAmbiente, exigir_do_ambiente
from api.auth import Usuario
from api.bancos import cliente_do_firestore
from api.correcoes import CORRIGIVEIS, Correcao, RepositorioDeCorrecoes
from api.csv_seguro import csv_em_texto
from api.erros import ServicoIndisponivel
from api.fuso import periodo_em_utc
from api.itens_da_decupagem import ItensDaDecupagem, contar_itens
from api.leitura_da_decupagem import AbreDecupagem
from api.modelo_do_job import RepositorioDeJobs
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioDeRevisaoFirestore,
    RepositorioFirestore,
)
from api.permissoes import exige_uma_de
from api.regras_das_correcoes import estado_das, reconciliar
from api.revisao import Medida, RepositorioDeRevisao
from api.texto_como_dado import LinhaDaConsulta
from api.tipos_da_taxa import LinhaDaTaxa

log = logging.getLogger(__name__)


class ContagemNaoLida(RuntimeError):
    """O Job do período cuja contagem não se lê, na rodada que não pode pular (#783)."""


__all__ = [
    "COLUNAS_DO_CSV",
    "LinhaDaTaxa",
    "calcular",
    "calcular_com_itens",
    "criar_rotas_da_qualidade",
    "em_csv",
    "main",
]

COLUNAS_DO_CSV = (
    "programa",
    "versao_pipeline",
    "tipo",
    "correcoes",
    "itens",
    "taxa_de_correcao",
)


def _no_periodo(quando: datetime, desde: datetime | None, ate: datetime | None) -> bool:
    return (desde is None or quando >= desde) and (ate is None or quando < ate)


def _itens_da_decupagem(decupagens: AbreDecupagem, job_id: str) -> ItensDaDecupagem:
    """A contagem tirada da decupagem inteira (o caminho de hoje do painel)."""
    return contar_itens(b"".join(decupagens.abrir_decupagem(job_id)))


def modelo_da_decupagem(decupagens: AbreDecupagem, job_id: str) -> dict[str, Any]:
    return json.loads(b"".join(decupagens.abrir_decupagem(job_id)))  # type: ignore[no-any-return]


def calcular(
    repositorio: RepositorioDeJobs,
    decupagens: AbreDecupagem,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
    desde: datetime | None = None,
    ate: datetime | None = None,
    programa: str | None = None,
) -> list[LinhaDaTaxa]:
    """As linhas do período `[desde, ate)`, em ordem de programa, versão e tipo."""
    por_job = calcular_com_itens(
        repositorio,
        lambda job_id: _itens_da_decupagem(decupagens, job_id),
        correcoes,
        revisao.todas(desde),
        desde,
        ate,
        programa,
        lambda job_id: modelo_da_decupagem(decupagens, job_id),
    )
    somas: dict[tuple[str | None, str | None, str], tuple[int, int]] = {}
    for _, linha in por_job:
        chave = (linha.programa, linha.versao_pipeline, linha.tipo)
        antes = somas.get(chave, (0, 0))
        somas[chave] = (antes[0] + linha.correcoes, antes[1] + linha.itens)
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


def calcular_com_itens(
    repositorio: RepositorioDeJobs,
    itens_do_job: Callable[[str], ItensDaDecupagem],
    correcoes: RepositorioDeCorrecoes,
    medidas: Iterable[Medida],
    desde: datetime | None = None,
    ate: datetime | None = None,
    programa: str | None = None,
    modelo_do_job: Callable[[str], dict[str, Any]] | None = None,
    estrito: bool = False,
) -> list[tuple[str, LinhaDaTaxa]]:
    """O cálculo por Job, com a contagem de itens vinda de `itens_do_job` (a decupagem
    inteira, ou o objeto de contagem gravado com ela, #455). `medidas` são as de revisão já
    lidas (`revisao.todas(desde)` ou mais): quem calcula vários períodos lê uma vez. `itens_do_job` levanta
    `ServicoIndisponivel`, `ValueError`, `KeyError` ou `TypeError` se não lê.

    `modelo_do_job` (o JSON da decupagem) só é chamado para o Job que tem correção em vigor
    feita sobre outra versão do JSON, para a `reconciliar` dizer quais casam com a atual
    (#571). Sem ele, essas ficam fora.

    Job cuja contagem ou decupagem não se lê sai com aviso; com `estrito` (a tabela diária,
    que apagaria as linhas dele) levanta `ContagemNaoLida`."""
    pulsados = {m.job_id for m in medidas if _no_periodo(m.ultimo_pulso, desde, ate)}
    # Só os vídeos com correção ou pulso no período; o acervo não é percorrido.
    candidatos = pulsados | correcoes.jobs_com_correcao(desde, ate)
    linhas: list[tuple[str, LinhaDaTaxa]] = []
    for job in sorted(repositorio.obter_varios(candidatos), key=lambda j: j.id):
        if job.estado != "concluido" or (programa and job.programa != programa):
            continue
        feitas = correcoes.listar(job.id)
        if job.id not in pulsados and not any(
            (c.tipo in CORRIGIVEIS or c.aprova) and _no_periodo(c.criada_em, desde, ate)
            for c in feitas
        ):
            continue
        try:
            contagem = itens_do_job(job.id)
        except (ServicoIndisponivel, ValueError, KeyError, TypeError) as e:
            if estrito:
                raise ContagemNaoLida(f"contagem de {job.id} não lida") from e
            log.warning("decupagem de %s não lida: fora da taxa", job.id)
            continue
        try:
            # `ServicoIndisponivel` da leitura do JSON escapa: a tabela não troca o dado
            # certo por um incompleto, e a próxima execução tenta de novo.
            reconciliadas = _reconciliadas(
                job.id, feitas, contagem.versao_do_modelo, desde, ate, modelo_do_job
            )
            vigor = _em_vigor_no_periodo(
                feitas, contagem.versao_do_modelo, desde, ate, reconciliadas
            )
            do_job: dict[str, tuple[int, int]] = {}
            sem_contagem: list[str] = []
            n_por_tipo = Counter(c.tipo for c in vigor)
            for tipo in CORRIGIVEIS:
                try:
                    itens = contagem.itens_do_tipo(tipo)
                except KeyError:
                    # Contagem gravada antes do tipo existir, sem irmão (#740): só a linha
                    # dele sai; um 0 tiraria o tipo do denominador sem aviso.
                    sem_contagem.append(tipo)
                    continue
                do_job[tipo] = (n_por_tipo[tipo], itens)
            if sem_contagem:
                log.warning("contagem de %s sem %s: fora da taxa", job.id, sem_contagem)
        except (ValueError, KeyError, TypeError) as e:
            if estrito:
                raise ContagemNaoLida(f"decupagem de {job.id} não lida") from e
            log.warning("decupagem de %s não lida: fora da taxa", job.id)
            continue
        for tipo, (n, itens) in do_job.items():
            linhas.append(
                (
                    job.id,
                    LinhaDaTaxa(
                        programa=job.programa,
                        versao_pipeline=contagem.versao_pipeline or None,
                        tipo=tipo,
                        correcoes=n,
                        itens=itens,
                        taxa_de_correcao=round(n / itens, 4) if itens else None,
                    ),
                )
            )
    return linhas


def _reconciliadas(
    job_id: str,
    todas: list[Correcao],
    versao: str,
    desde: datetime | None,
    ate: datetime | None,
    modelo_do_job: Callable[[str], dict[str, Any]] | None,
) -> set[str]:
    """Os ids das feitas sobre outro JSON que a `reconciliar` (a regra que as aplica no
    vídeo) casa com o atual. Só lê a decupagem se alguma de outra versão pode contar:
    casável (em vigor e na fila, como a `reconciliar` a vê) e que passou a valer no período."""
    estado = estado_das(todas)
    a_valer = _em_vigor_no_periodo(todas, versao, desde, ate, {c.id for c in todas})
    if modelo_do_job is None or not any(
        c.ancora.versao != versao and estado.casavel(c.id) for c in a_valer
    ):
        return set()
    return {c.id for c in reconciliar(modelo_do_job(job_id), versao, todas).casadas}


def _em_vigor_no_periodo(
    todas: list[Correcao],
    versao: str,
    desde: datetime | None,
    ate: datetime | None,
    reconciliadas: AbstractSet[str] = frozenset(),
) -> list[Correcao]:
    """As em vigor segundo o histórico inteiro (o desfazer pode ser de fora do
    período), feitas sobre este JSON do modelo (ou reconciliadas com ele) e que passaram
    a valer no período."""
    estado = estado_das(todas)
    aprovada_em = {c.aprova: c.criada_em for c in todas if c.aprova}
    return [
        c
        for c in todas
        if c.tipo in CORRIGIVEIS
        and estado.em_vigor(c.id)
        and (c.ancora.versao == versao or c.id in reconciliadas)
        and _no_periodo(aprovada_em.get(c.id, c.criada_em), desde, ate)
    ]


def em_csv(linhas: list[LinhaDaTaxa]) -> str:
    return csv_em_texto(
        COLUNAS_DO_CSV,
        [
            [
                linha.programa or "",
                linha.versao_pipeline or "",
                linha.tipo,
                linha.correcoes,
                linha.itens,
                "" if linha.taxa_de_correcao is None else linha.taxa_de_correcao,
            ]
            for linha in linhas
        ],
    )


def _periodo(
    desde: date | None, ate: date | None
) -> tuple[datetime | None, datetime | None]:
    """Os dias `desde` e `ate` (de São Paulo, os dois inclusive) como `[desde, ate)` em UTC."""
    if desde and ate and desde > ate:
        raise ValueError("`desde` depois de `ate`")
    return periodo_em_utc(desde, ate)


class TaxaDeCorrecao(BaseModel):
    desde: date | None
    ate: date | None
    programa: str | None
    linhas: list[LinhaDaTaxa]


def criar_rotas_da_qualidade(
    repositorio: RepositorioDeJobs,
    decupagens: AbreDecupagem,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
) -> APIRouter:
    rotas = APIRouter(prefix="/qualidade")

    @rotas.get("/taxa-de-correcao")
    def taxa_de_correcao(
        _pessoa: Annotated[
            Usuario,
            Depends(
                exige_uma_de(
                    "correcao.aprovar",
                    "auditoria.ver",
                    "Chave de sistema não consulta a taxa de correção",
                )
            ),
        ],
        desde: date | None = None,
        ate: date | None = None,
        programa: Annotated[str | None, LinhaDaConsulta(100)] = None,
    ) -> TaxaDeCorrecao:
        """`desde` e `ate` são dias de São Paulo, os dois inclusive."""
        try:
            inicio, fim = _periodo(desde, ate)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return TaxaDeCorrecao(
            desde=desde,
            ate=ate,
            programa=programa,
            linhas=calcular(
                repositorio, decupagens, correcoes, revisao, inicio, fim, programa
            ),
        )

    return rotas


def main(
    argumentos: list[str],
    ambiente: Mapping[str, str] = os.environ,
    escrever: Callable[[str], None] = print,
) -> int:
    """Argumentos: `DESDE`, `ATE` (dias ISO, inclusive) e `PROGRAMA`, todos opcionais."""
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        decupagens = DecupagensStorage.do_ambiente(ambiente)
        pedidos = [*argumentos, "", "", ""][:3]
        inicio, fim = _periodo(
            date.fromisoformat(pedidos[0]) if pedidos[0] else None,
            date.fromisoformat(pedidos[1]) if pedidos[1] else None,
        )
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    banco = cliente_do_firestore(projeto)
    linhas = calcular(
        RepositorioFirestore(banco),
        decupagens,
        RepositorioDeCorrecoesFirestore(banco),
        RepositorioDeRevisaoFirestore(banco),
        inicio,
        fim,
        pedidos[2] or None,
    )
    escrever(em_csv(linhas).rstrip("\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
