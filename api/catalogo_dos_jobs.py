"""Quem aparece em cada Job (#359): os `catalogo_id` da Decupagem corrigida, guardados no Job.

O impacto de uma pessoa ou marca do catálogo acha os vídeos por `array_contains` nesses
campos em vez de abrir todas as decupagens. Quem muda a Decupagem corrigida (a indexação, as
Correções, a fusão de pessoas) regrava os dois campos; só grava se mudaram.
"""

import logging
from typing import Any

from api.catalogo_apagado import ids_do_catalogo
from api.leitura_da_decupagem import LeituraDaDecupagem
from api.modelo_do_job import FiltroDeJobs, Job, RepositorioDeJobs

log = logging.getLogger(__name__)


def gravar_se_mudou(
    repositorio: "RepositorioDeJobs", job_id: str, entregue: dict[str, Any]
) -> bool:
    """Grava os dois campos no Job concluído, numa leitura só e atômica; `False` se não
    mudaram ou se o Job não está mais `concluido`. Levanta a falha do repositório."""
    pessoas = sorted(ids_do_catalogo(entregue, "pessoas"))
    marcas = sorted(ids_do_catalogo(entregue, "comerciais"))

    def mudar(job: "Job") -> dict[str, Any] | None:
        if job.estado != "concluido":
            return None
        if job.pessoas_do_catalogo == pessoas and job.marcas_do_catalogo == marcas:
            return None
        return {"pessoas_do_catalogo": pessoas, "marcas_do_catalogo": marcas}

    return repositorio.trocar(job_id, mudar) is not None


def gravar_catalogo_do_job(
    repositorio: "RepositorioDeJobs", job_id: str, entregue: dict[str, Any]
) -> None:
    """Como `gravar_se_mudou`, mas nunca levanta: uma falha vai ao log, para não
    transformar em erro uma Correção que já foi gravada."""
    try:
        gravar_se_mudou(repositorio, job_id, entregue)
    except Exception:
        log.exception("catálogo do Job %s não gravado", job_id)


def atualizar_catalogo_do_job(
    job: "Job",
    repositorio: "RepositorioDeJobs",
    leitura: LeituraDaDecupagem,
    lido: tuple[dict[str, Any], str] | None = None,
) -> None:
    """Lê a Decupagem corrigida (com `lido`, sem reabrir o modelo) e regrava os campos do
    Job; nunca levanta."""
    try:
        corrigida = leitura.corrigida(job.id, lido=lido)
    except Exception:
        log.exception("decupagem de %s não lida para o catálogo do Job", job.id)
        return
    gravar_catalogo_do_job(repositorio, job.id, corrigida)


def passar_pessoa_nos_jobs(
    repositorio: "RepositorioDeJobs", origem_id: str, destino_id: str | None
) -> bool:
    """Na fusão, os vídeos da origem (até os da lixeira) passam a listar o destino. Nunca
    levanta: diz se todos os Jobs foram trocados (sem destino, a origem só sai); o que falha fica com a origem, e a fusão
    pendente (ou a carga `make preencher-catalogo-dos-jobs`) o conserta."""

    def trocar(job: "Job") -> dict[str, Any] | None:
        if origem_id not in job.pessoas_do_catalogo:
            return None
        ids = {i for i in job.pessoas_do_catalogo if i != origem_id}
        if destino_id is not None:
            ids.add(destino_id)
        return {"pessoas_do_catalogo": sorted(ids)}

    try:
        filtro = FiltroDeJobs(pessoa_do_catalogo=origem_id, na_lixeira=None)
        for job in repositorio.consultar(filtro).jobs:
            repositorio.trocar(job.id, trocar)
    except Exception:
        log.exception("fusão %s -> %s não passou aos Jobs", origem_id, destino_id)
        return False
    return True
