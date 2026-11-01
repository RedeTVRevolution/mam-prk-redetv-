"""Dono do ciclo de vida do Job: toda mudança de `estado` passa por aqui.

Cada transição diz de qual estado sai e para qual vai, e só acontece se o Job
ainda estiver na origem. A troca condicional é atômica no repositório; quem a
pediu recebe `None` quando ela não aconteceu (por exemplo, o Job foi cancelado
no meio do caminho).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, get_args

# `api.jobs` usa este módulo nas rotas; aqui os tipos só servem à checagem.
if TYPE_CHECKING:
    from api.jobs import (
        CodigoDeFalha,
        Estado,
        Job,
        NomeDaEtapa,
        RepositorioDeJobs,
        ResultadoDaEtapa,
    )

TRANSICOES: dict[Estado, frozenset[Estado]] = {
    "aguardando_upload": frozenset({"validando", "falhou", "cancelado"}),
    "validando": frozenset({"analisando", "falhou", "cancelado"}),
    "analisando": frozenset({"concluido", "falhou", "cancelado"}),
    "concluido": frozenset(),
    "falhou": frozenset(),
    "cancelado": frozenset(),
}
FINAIS = frozenset(e for e, destinos in TRANSICOES.items() if not destinos)


class TransicaoProibida(Exception):
    def __init__(self, de: Estado, para: Estado) -> None:
        super().__init__(f"Transição fora da tabela: {de} → {para}")


class JaTerminou(Exception):
    """O Job está num estado final que não é `cancelado`."""

    def __init__(self, estado: Estado) -> None:
        super().__init__(estado)
        self.estado = estado


def transitar(
    repositorio: RepositorioDeJobs,
    job_id: str,
    de: Estado,
    para: Estado,
    agora: datetime,
    *,
    codigo_falha: CodigoDeFalha | None = None,
    sha256: str | None = None,
    duracao_s: float | None = None,
    cortes_ms: Sequence[int] | None = None,
    timecode_origem: str | None = None,
    taxa_de_quadros: float | None = None,
) -> Job | None:
    """O Job já em `para`, ou `None` se ele não estava mais em `de`."""
    if para not in TRANSICOES[de]:
        raise TransicaoProibida(de, para)
    mudancas: dict[str, Any] = {"estado": para, "atualizado_em": agora}
    if para == "concluido":
        # Quem indexa (api.indexacao) troca este estado ao terminar.
        from api.jobs import Indexacao

        mudancas["indexacao"] = Indexacao(estado="pendente", em=agora)
    if codigo_falha is not None:
        mudancas["codigo_falha"] = codigo_falha
    if sha256 is not None:
        mudancas["sha256"] = sha256
    if duracao_s is not None:
        mudancas["duracao_s"] = duracao_s
    if cortes_ms is not None:
        mudancas["cortes_ms"] = list(cortes_ms)
    if timecode_origem is not None:
        mudancas["timecode_origem"] = timecode_origem
    if taxa_de_quadros is not None:
        mudancas["taxa_de_quadros"] = taxa_de_quadros
    return repositorio.transitar(job_id, de, mudancas)


def cancelar(
    repositorio: RepositorioDeJobs, job_id: str, agora: datetime
) -> Job | None:
    """Cancela o Job; cancelar um já cancelado devolve o Job sem mudar nada."""
    while (job := repositorio.obter(job_id)) is not None:
        if job.estado == "cancelado":
            return job
        if job.estado in FINAIS:
            raise JaTerminou(job.estado)
        # Se o Job andou entre a leitura e a troca, lê de novo: os estados só avançam.
        if novo := transitar(repositorio, job_id, job.estado, "cancelado", agora):
            return novo
    return None


def _gravar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    mudar: Callable[[Job], dict[str, Any]],
    exige: Callable[[Job], bool] = lambda job: True,
) -> Job | None:
    """Grava a mudança de etapa sem mudar o `estado` do Job (nem exigir um).

    É a mesma troca condicional das transições, com o estado lido na hora: se o Job
    andou entre a leitura e a troca, lê de novo. `None` se o Job não existe ou não
    atende a `exige`.
    """
    while (job := repositorio.obter(job_id)) is not None and exige(job):
        if novo := repositorio.transitar(job_id, job.estado, mudar(job)):
            return novo
    return None


def iniciar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    etapa: NomeDaEtapa,
    agora: datetime,
) -> Job | None:
    """Abre a etapa (refazê-la, como no reprocessar, recomeça o relógio dela)."""
    from api.jobs import Etapa

    return _gravar_etapa(
        repositorio,
        job_id,
        lambda job: {
            "etapa_atual": etapa,
            "etapas": {**job.etapas, etapa: Etapa(inicio=agora)},
            "atualizado_em": agora,
        },
    )


def encerrar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    etapa: NomeDaEtapa,
    resultado: ResultadoDaEtapa,
    agora: datetime,
) -> Job | None:
    """Fecha a etapa com o resultado. `None` se o Job não existe ou a etapa não começou.

    A falha de uma etapa não muda o `estado` do Job: quem o derruba é a transição
    `analisando` → `falhou`; uma etapa depois do `concluido` só fica `falhou`.
    """

    def mudar(job: Job) -> dict[str, Any]:
        aberta = job.etapas[etapa]
        return {
            "etapa_atual": None if job.etapa_atual == etapa else job.etapa_atual,
            "etapas": {
                **job.etapas,
                etapa: aberta.model_copy(update={"fim": agora, "resultado": resultado}),
            },
            "atualizado_em": agora,
        }

    return _gravar_etapa(
        repositorio, job_id, mudar, exige=lambda job: etapa in job.etapas
    )


def rodar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    etapa: NomeDaEtapa,
    trabalho: Callable[[], str],
    *,
    bem_sucedido: str,
) -> str:
    """Roda `trabalho` entre o início e o fim da etapa; só o resultado `bem_sucedido` conclui.

    Qualquer outro resultado, ou uma exceção (que segue adiante), deixa a etapa `falhou`.
    """
    from api.jobs import agora_utc

    iniciar_etapa(repositorio, job_id, etapa, agora_utc())
    try:
        resultado = trabalho()
    except Exception:
        encerrar_etapa(repositorio, job_id, etapa, "falhou", agora_utc())
        raise
    encerrar_etapa(
        repositorio,
        job_id,
        etapa,
        "concluida" if resultado == bem_sucedido else "falhou",
        agora_utc(),
    )
    return resultado


# Falhas do próprio arquivo: refazer o processamento não as conserta.
FALHAS_DO_ARQUIVO: frozenset[CodigoDeFalha] = frozenset(
    {
        "formato_invalido",
        "arquivo_corrompido",
        "codec_nao_suportado",
        "duracao_excedida",
        "upload_expirado",
    }
)
# Job em `falhou` sem etapa `falhou` no registro (anterior ao #146): o código diz a etapa.
ETAPA_DA_FALHA: dict[CodigoDeFalha, NomeDaEtapa] = {
    "transcricao_falhou": "transcricao",
    "ocr_falhou": "leitura_da_tela",
    "analise_falhou": "analise",
}
# Depois do `concluido`, só estas etapas rodam: o Job e a Decupagem seguem como estão.
ETAPAS_DEPOIS_DO_CONCLUIDO: tuple[NomeDaEtapa, ...] = (
    "quadros_chave",
    "indexacao",
    "identificacao",
    "comparacao",
)

# Ainda fora do Workflows (#223): partir delas cairia na validação e rodaria tudo de novo.
ETAPAS_SEM_REPROCESSAR: frozenset[NomeDaEtapa] = frozenset(
    {"identificacao", "comparacao"}
)


class NaoReprocessavel(Exception):
    """O Job não pode ser reprocessado; a mensagem diz o porquê (vira 409)."""


def _ordem_das_etapas() -> tuple[NomeDaEtapa, ...]:
    from api.jobs import NomeDaEtapa

    return get_args(NomeDaEtapa)


def etapa_de_partida(job: Job) -> NomeDaEtapa:
    """A primeira etapa que falhou, de onde o reprocessamento recomeça."""
    if job.estado == "falhou":
        if job.codigo_falha in FALHAS_DO_ARQUIVO or job.codigo_falha is None:
            raise NaoReprocessavel(
                "A falha é do arquivo: é preciso enviar o vídeo de novo"
            )
    elif job.estado != "concluido":
        raise NaoReprocessavel(f"Job em {job.estado}, não reprocessável")
    falhas = [
        e
        for e in _ordem_das_etapas()
        if (r := job.etapas.get(e)) and r.resultado == "falhou"
    ]
    if falhas and falhas[0] in ETAPAS_SEM_REPROCESSAR:
        raise NaoReprocessavel(f"A etapa {falhas[0]} ainda não pode ser reprocessada")
    if job.estado == "falhou":
        partida = (
            falhas[0]
            if falhas
            else ETAPA_DA_FALHA.get(job.codigo_falha)
            if job.codigo_falha
            else None
        )
        if partida is None or partida == "validacao":
            raise NaoReprocessavel(
                "A falha é do arquivo: é preciso enviar o vídeo de novo"
            )
        return partida
    if not falhas or falhas[0] not in ETAPAS_DEPOIS_DO_CONCLUIDO:
        raise NaoReprocessavel("Job concluído sem etapa que tenha falhado")
    return falhas[0]


def reprocessar(
    repositorio: RepositorioDeJobs, job_id: str, agora: datetime
) -> tuple[Job, Job] | None:
    """Recomeça o Job da primeira etapa que falhou: devolve o Job de antes e o de depois.

    O `etapa_atual` do de depois é a etapa de partida.

    Um Job `falhou` passa a `analisando` (a transição fora da tabela de `TRANSICOES`,
    porque `falhou` segue final para o resto) e perde o `codigo_falha`; um `concluido`
    continua `concluido` e só a etapa volta a em andamento. Atômico: de dois pedidos
    para o mesmo Job, só um passa, o outro levanta `NaoReprocessavel`. `None` se o Job
    não existe. As etapas dali em diante perdem o registro antigo, porque vão rodar de novo.
    """
    from api.jobs import Etapa, Indexacao

    lido: list[Job] = []

    def mudar(job: Job) -> dict[str, Any]:
        lido[:] = [job]
        partida = etapa_de_partida(job)
        ordem = _ordem_das_etapas()
        etapas = {
            n: e for n, e in job.etapas.items() if ordem.index(n) < ordem.index(partida)
        }
        etapas[partida] = Etapa(inicio=agora)
        mudancas: dict[str, Any] = {
            "etapa_atual": partida,
            "etapas": etapas,
            "reprocessamentos": job.reprocessamentos + 1,
            "atualizado_em": agora,
        }
        if job.estado == "falhou":
            mudancas.update(estado="analisando", codigo_falha=None)
        if partida in ETAPAS_DEPOIS_DO_CONCLUIDO:
            # Quem indexa (api.indexacao) troca este estado ao terminar.
            mudancas["indexacao"] = Indexacao(estado="pendente", em=agora)
        return mudancas

    depois = repositorio.trocar(job_id, mudar)
    return (lido[0], depois) if depois is not None else None


def desfazer_reprocessamento(
    repositorio: RepositorioDeJobs, antes: Job, depois: Job, agora: datetime
) -> Job | None:
    """Devolve o Job ao que era antes do `reprocessar`, se ninguém mexeu nele desde então.

    Para quando o Workflows não pôde ser disparado: sem isto o Job ficaria `analisando`
    (ou com a etapa em andamento) sem nada rodando.
    """

    def mudar(job: Job) -> dict[str, Any] | None:
        if (job.reprocessamentos, job.etapa_atual) != (
            depois.reprocessamentos,
            depois.etapa_atual,
        ):
            return None
        voltam = (
            "estado",
            "codigo_falha",
            "etapa_atual",
            "etapas",
            "reprocessamentos",
            "indexacao",
        )
        return {
            **{campo: getattr(antes, campo) for campo in voltam},
            "atualizado_em": agora,
        }

    return repositorio.trocar(antes.id, mudar)
