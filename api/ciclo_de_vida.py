"""Dono do ciclo de vida do Job: toda mudança de `estado` passa por aqui.

Cada transição diz de qual estado sai e para qual vai, e só acontece se o Job
ainda estiver na origem. A troca condicional é atômica no repositório; quem a
pediu recebe `None` quando ela não aconteceu (por exemplo, o Job foi cancelado
no meio do caminho).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, get_args

from api.sinais import Registrar, imprimir, registro_da_falha_de_etapa

# `api.jobs` usa este módulo nas rotas; aqui os tipos só servem à checagem.
if TYPE_CHECKING:
    from api.jobs import (
        CodigoDeFalha,
        Estado,
        Indexacao,
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

# Manter em acordo com o age = 7 do bucket aceitos em infra/modulos/mam/main.tf.
PRAZO_DO_REPROCESSAMENTO = timedelta(days=7)


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
    versao_pipeline: str | None = None,
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
    if versao_pipeline is not None:
        mudancas["versao_pipeline"] = versao_pipeline
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
    registrar: Registrar = imprimir,
) -> str:
    """Roda `trabalho` entre o início e o fim da etapa; só o resultado `bem_sucedido` conclui.

    Qualquer outro resultado, ou uma exceção (que segue adiante), deixa a etapa `falhou`.
    """
    from api.jobs import agora_utc

    iniciar_etapa(repositorio, job_id, etapa, agora_utc())
    try:
        resultado = trabalho()
    except Exception:
        # A execução do Job falha e o Workflows loga a falha da etapa (`marca_fim`).
        encerrar_etapa(repositorio, job_id, etapa, "falhou", agora_utc())
        raise
    if resultado != bem_sucedido:
        registrar(registro_da_falha_de_etapa(etapa, job_id, f"resultado {resultado}"))
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
# Depois do `concluido`, só estas etapas rodam; a falha de uma não muda o estado do Job.
ETAPAS_DEPOIS_DO_CONCLUIDO: tuple[NomeDaEtapa, ...] = (
    "identificacao",
    "quadros_chave",
    "inventario_de_objetos",
    "indexacao",
)
# As que o Curador pode escolher num Job concluído, para refazer um vídeo bom.
ETAPAS_ESCOLHIVEIS: tuple[NomeDaEtapa, ...] = (
    "analise",
    "identificacao",
    "quadros_chave",
    "inventario_de_objetos",
    "indexacao",
)


class NaoReprocessavel(Exception):
    """O Job não pode ser reprocessado; a mensagem diz o porquê (vira 409)."""


def _ordem_das_etapas() -> tuple[NomeDaEtapa, ...]:
    from api.jobs import NomeDaEtapa

    return get_args(NomeDaEtapa)


def etapa_de_partida(job: Job, escolhida: str | None = None) -> NomeDaEtapa:
    """A primeira etapa que falhou, de onde o reprocessamento recomeça.

    Com `escolhida`, a etapa é a que a pessoa pediu, e só um Job `concluido` a aceita.
    """
    if escolhida is not None:
        if job.estado != "concluido":
            raise NaoReprocessavel(
                f"Só um vídeo concluído pode ser reprocessado a partir de uma etapa "
                f"escolhida; este está em {job.estado}"
            )
        if escolhida not in ETAPAS_ESCOLHIVEIS:
            raise NaoReprocessavel(
                "Etapa não permitida; escolha análise, identificação, quadros-chave, "
                "inventário de objetos ou indexação"
            )
        return escolhida
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
    if job.estado == "falhou":
        partida = (
            falhas[0]
            if falhas
            else ETAPA_DA_FALHA.get(job.codigo_falha)
            if job.codigo_falha
            else None
        )
        if partida is None and job.codigo_falha == "processamento_interrompido":
            # O Workflows caiu entre duas etapas, sem etapa em andamento para fechar:
            # recomeça da primeira que não concluiu.
            partida = next(
                (
                    e
                    for e in _ordem_das_etapas()
                    if not ((r := job.etapas.get(e)) and r.resultado == "concluida")
                ),
                None,
            )
        if partida == "validacao" and job.codigo_falha == "processamento_interrompido":
            raise NaoReprocessavel(
                "O processamento parou na validação do arquivo: envie o vídeo de novo"
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
    repositorio: RepositorioDeJobs,
    job_id: str,
    agora: datetime,
    etapa_escolhida: str | None = None,
) -> tuple[Job, Job] | None:
    """Recomeça o Job da primeira etapa que falhou: devolve o Job de antes e o de depois.

    O `etapa_atual` do de depois é a etapa de partida.

    Um Job `falhou` passa a `analisando` (a transição fora da tabela de `TRANSICOES`,
    porque `falhou` segue final para o resto) e perde o `codigo_falha`; um `concluido`
    continua `concluido` e só a etapa volta a em andamento. Atômico: de dois pedidos
    para o mesmo Job, só um passa, o outro levanta `NaoReprocessavel`. `None` se o Job
    não existe. As etapas dali em diante perdem o registro antigo, porque vão rodar de novo.

    Com `etapa_escolhida`, o Job `concluido` recomeça da etapa pedida: com a análise ele
    volta a `analisando` (a Decupagem antiga some até a nova análise terminar); com as
    outras continua `concluido`.
    """
    from api.jobs import Etapa, Indexacao

    lido: list[Job] = []

    def mudar(job: Job) -> dict[str, Any]:
        lido[:] = [job]
        if agora - job.criado_em >= PRAZO_DO_REPROCESSAMENTO:
            raise NaoReprocessavel(
                "O prazo de reprocessamento deste vídeo (7 dias após o envio) terminou: "
                "a cópia em alta resolução e o áudio não ficam guardados no MAM. "
                "Para reprocessar, envie o vídeo de novo a partir do arquivo da RedeTV."
            )
        partida = etapa_de_partida(job, etapa_escolhida)
        ordem = _ordem_das_etapas()
        etapas = {
            n: e for n, e in job.etapas.items() if ordem.index(n) < ordem.index(partida)
        }
        etapas[partida] = Etapa(inicio=agora)
        mudancas: dict[str, Any] = {
            "etapa_atual": partida,
            "etapas": etapas,
            "reprocessamentos": job.reprocessamentos + 1,
            "inicio_da_passada": agora,
            "atualizado_em": agora,
        }
        if job.estado == "falhou":
            mudancas.update(estado="analisando", codigo_falha=None)
        elif partida == "analise":
            mudancas["estado"] = "analisando"
        if partida in ETAPAS_DEPOIS_DO_CONCLUIDO or etapa_escolhida:
            # Quem indexa (api.indexacao) troca este estado ao terminar.
            mudancas["indexacao"] = Indexacao(estado="pendente", em=agora)
        return mudancas

    depois = repositorio.trocar(job_id, mudar)
    return (lido[0], depois) if depois is not None else None


# A correção manual (#289): de onde cada destino pode ser alcançado. A falha vale de
# qualquer estado não final; voltar a concluído, só de um Job que falhou ou que ficou
# em `analisando` sem nada rodando, e se a decupagem estiver completa.
DestinoDaCorrecao = Literal["concluido", "falhou"]
DESTINOS_DA_CORRECAO: dict[DestinoDaCorrecao, frozenset[Estado]] = {
    "falhou": frozenset(e for e in TRANSICOES if e not in FINAIS),
    "concluido": frozenset({"falhou", "analisando"}),
}


class EstadoNaoCorrigivel(Exception):
    """A correção manual do estado não vale; a mensagem diz o porquê (vira 409)."""


def corrigir_estado(
    repositorio: RepositorioDeJobs,
    job_id: str,
    destino: DestinoDaCorrecao,
    agora: datetime,
    *,
    decupagem_completa: bool = False,
) -> tuple[Job, Job] | None:
    """Põe o Job em `destino` à mão: devolve o Job de antes e o de depois.

    Fora da tabela de `TRANSICOES` de propósito: é a saída de emergência do
    Administrador (`falhou` e `concluido` seguem finais para o resto). Atômico, como o
    `reprocessar`. `None` se o Job não existe; `EstadoNaoCorrigivel` se não vale.

    Ao falhar, as etapas que ficaram em andamento fecham como `falhou`, e o
    `codigo_falha` vem da primeira delas, para o "reprocessar o que falhou" recomeçar
    dali (sem etapa aberta, ou com a validação aberta, a falha conta como do arquivo). Ao concluir, a indexação fica como
    estava: nada a dispara, e quem quer o vídeo na busca reprocessa a partir da
    indexação.
    """
    lido: list[Job] = []

    def mudar(job: Job) -> dict[str, Any]:
        lido[:] = [job]
        if job.estado not in DESTINOS_DA_CORRECAO[destino]:
            raise EstadoNaoCorrigivel(f"Job em {job.estado} não pode ir para {destino}")
        mudancas: dict[str, Any] = {"estado": destino, "atualizado_em": agora}
        if destino == "falhou":
            abertas = [
                n for n in _ordem_das_etapas() if (e := job.etapas.get(n)) and not e.fim
            ]
            mudancas["etapas"] = {
                nome: etapa.model_copy(update={"fim": agora, "resultado": "falhou"})
                if nome in abertas
                else etapa
                for nome, etapa in job.etapas.items()
            }
            codigos = [c for c, e in ETAPA_DA_FALHA.items() if e in abertas[:1]]
            if job.codigo_falha is None and codigos:
                mudancas["codigo_falha"] = codigos[0]
            return mudancas
        if not decupagem_completa:
            raise EstadoNaoCorrigivel(
                "Sem decupagem completa guardada, o Job não pode voltar a concluído"
            )
        mudancas["codigo_falha"] = None
        # A versão do Job pode ser de antes de um reprocessar que não concluiu: sem ela, o
        # `make reprocessar-versao` lê a da decupagem (#494).
        mudancas["versao_pipeline"] = None
        return mudancas

    depois = repositorio.trocar(job_id, mudar)
    return (lido[0], depois) if depois is not None else None


def desfazer_correcao(
    repositorio: RepositorioDeJobs, antes: Job, depois: Job, agora: datetime
) -> Job | None:
    """Devolve o Job ao que era antes do `corrigir_estado`, se ninguém mexeu nele desde
    então. Para quando a auditoria não pôde ser gravada: sem rastro, a correção não vale.
    """

    def mudar(job: Job) -> dict[str, Any] | None:
        if (job.estado, job.atualizado_em) != (depois.estado, depois.atualizado_em):
            return None
        voltam = ("estado", "codigo_falha", "etapas", "versao_pipeline")
        return {
            **{campo: getattr(antes, campo) for campo in voltam},
            "atualizado_em": agora,
        }

    return repositorio.trocar(antes.id, mudar)


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
            "inicio_da_passada",
            "indexacao",
        )
        return {
            **{campo: getattr(antes, campo) for campo in voltam},
            "atualizado_em": agora,
        }

    return repositorio.trocar(antes.id, mudar)


# Uma rodada que passou disso sem fechar caiu (o Job `mam-indexacao` morre em 30 min): a
# seguinte a substitui.
PRAZO_DA_RODADA = timedelta(minutes=40)


def pedir_indexacao(
    repositorio: RepositorioDeJobs, job_id: str, agora: datetime
) -> Job | None:
    """Incrementa a `versao_pedida` do Job concluído e põe a indexação em `pendente` (#419).

    Quem pede (aprovar a revisão, trocar o nome do programa) dispara o `mam-indexacao` depois.
    `None` se o Job não existe ou saiu de `concluido`.
    """

    def mudar(job: Job) -> dict[str, Any] | None:
        from api.jobs import Indexacao

        if job.estado != "concluido":
            return None
        return {
            "versao_pedida": max(job.versao_pedida, job.versao_indexada) + 1,
            "indexacao": Indexacao(estado="pendente", em=agora),
        }

    return repositorio.trocar(job_id, mudar)


def tomar_a_rodada(
    repositorio: RepositorioDeJobs,
    job_id: str,
    agora: datetime,
    rodada_id: str,
    *,
    so_se_pedida: bool = False,
    so_copia: bool = False,
) -> Job | None:
    """Toma a vez de indexar o vídeo e devolve o Job lido, com a `versao_pedida` a alcançar.

    `None`, sem gravar nada, se o Job não está `concluido`, se outra execução está indexando
    (ela pega na volta o que se pediu depois) ou, com `so_se_pedida`, se não há pedido
    pendente: `indexacao` em `pendente` (o fim da análise) ou `versao_pedida` à frente da
    `versao_indexada`. Sem `so_se_pedida` (`make reindexar`), sempre há uma versão a mais.
    Com `so_copia`, só toma a exclusão, sem pedir uma versão da busca.
    """

    def mudar(job: Job) -> dict[str, Any] | None:
        from api.jobs import RodadaDaIndexacao

        if job.estado != "concluido":
            return None
        r = job.rodada_da_indexacao
        if r is not None and agora - r.em < PRAZO_DA_RODADA:
            return None
        pedida = job.versao_pedida > job.versao_indexada or (
            job.indexacao is not None and job.indexacao.estado == "pendente"
        )
        if so_se_pedida and not pedida:
            return None
        mudancas: dict[str, Any] = {
            "rodada_da_indexacao": RodadaDaIndexacao(id=rodada_id, em=agora),
        }
        if not so_copia:
            mudancas["versao_pedida"] = max(job.versao_pedida, job.versao_indexada + 1)
        return mudancas

    return repositorio.trocar(job_id, mudar)


def fechar_a_rodada(
    repositorio: RepositorioDeJobs,
    job_id: str,
    rodada_id: str,
    alvo: int,
    *,
    indexado: bool,
    indexacao: Indexacao | None,
    agora: datetime,
    so_copia: bool = False,
) -> Job | None:
    """Fecha a rodada de `rodada_id`, que mirava `alvo`; devolve o Job gravado.

    Com `indexado`, a `versao_indexada` chega a `alvo`; se pediram mais enquanto isso, a
    rodada segue aberta (`rodada_da_indexacao` não vem vazia) e a `indexacao` continua
    `pendente`: quem chamou indexa de novo. Sem `indexado`, ou sem pedido novo, solta a vez e
    grava `indexacao`. `None` se a rodada não é mais desta execução (venceu e outra tomou) ou
    o Job sumiu. Com `so_copia`, só solta a exclusão, preservando a fila da busca.
    """

    def mudar(job: Job) -> dict[str, Any] | None:
        from api.jobs import RodadaDaIndexacao

        r = job.rodada_da_indexacao
        if r is None or r.id != rodada_id:
            return None
        if so_copia:
            return {"rodada_da_indexacao": None}
        if not indexado:
            return {"rodada_da_indexacao": None, "indexacao": indexacao}
        indexada = max(job.versao_indexada, alvo)
        if job.versao_pedida > indexada:
            return {
                "versao_indexada": indexada,
                "rodada_da_indexacao": RodadaDaIndexacao(id=rodada_id, em=agora),
            }
        return {
            "versao_indexada": indexada,
            "rodada_da_indexacao": None,
            "indexacao": indexacao,
        }

    return repositorio.trocar(job_id, mudar)
