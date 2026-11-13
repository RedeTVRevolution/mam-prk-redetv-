"""Quem aparece em cada Job (#359): os `catalogo_id` da Decupagem corrigida, guardados no Job.

O impacto de uma pessoa ou marca do catálogo acha os vídeos por `array_contains` nesses
campos em vez de abrir todas as decupagens. Quem muda a Decupagem corrigida (a indexação, as
Correções, a fusão de pessoas) regrava os dois campos; só grava se mudaram.
"""

import logging
from typing import TYPE_CHECKING, Any

from api.leitura_da_decupagem import LeituraDaDecupagem

if TYPE_CHECKING:
    from api.jobs import Job, RepositorioDeJobs

log = logging.getLogger(__name__)


def ids_do_catalogo(entregue: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Os ids das pessoas e das marcas do catálogo na Decupagem corrigida, sem repetir."""

    def ids(chave: str) -> list[str]:
        achados = {
            item["catalogo_id"]
            for item in entregue.get(chave) or []
            if isinstance(item, dict) and item.get("catalogo_id")
        }
        return sorted(achados)

    return ids("pessoas"), ids("comerciais")


def gravar_se_mudou(
    repositorio: "RepositorioDeJobs", job_id: str, entregue: dict[str, Any]
) -> bool:
    """Grava os dois campos no Job concluído, numa leitura só e atômica; `False` se não
    mudaram ou se o Job não está mais `concluido`. Levanta a falha do repositório."""
    pessoas, marcas = ids_do_catalogo(entregue)

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
) -> None:
    """Relê a Decupagem corrigida e regrava os campos do Job; nunca levanta."""
    try:
        corrigida = leitura.corrigida(job.id)
    except Exception:
        log.exception("decupagem de %s não lida para o catálogo do Job", job.id)
        return
    gravar_catalogo_do_job(repositorio, job.id, corrigida)


def passar_pessoa_nos_jobs(
    repositorio: "RepositorioDeJobs", origem_id: str, destino_id: str
) -> None:
    """Na fusão, os vídeos da origem (até os da lixeira) passam a listar o destino. Nunca
    levanta: o Job que falha fica com a origem, e a carga (`make preencher-catalogo-dos-jobs`)
    o conserta."""
    from api.jobs import FiltroDeJobs

    def trocar(job: "Job") -> dict[str, Any] | None:
        if origem_id not in job.pessoas_do_catalogo:
            return None
        ids = {destino_id, *(i for i in job.pessoas_do_catalogo if i != origem_id)}
        return {"pessoas_do_catalogo": sorted(ids)}

    try:
        filtro = FiltroDeJobs(pessoa_do_catalogo=origem_id, na_lixeira=None)
        for job in repositorio.consultar(filtro).jobs:
            repositorio.trocar(job.id, trocar)
    except Exception:
        log.exception("fusão %s -> %s não passou aos Jobs", origem_id, destino_id)
