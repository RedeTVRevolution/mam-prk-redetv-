"""Modelo do Job: estados, falhas, etapas, o `Job`, o filtro e a porta `RepositorioDeJobs`.

Sem FastAPI nem rotas, para `ciclo_de_vida`, `leitura_da_decupagem` e `catalogo_dos_jobs`
importarem o modelo sem ciclo com `api.jobs`.
"""

import itertools
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    model_validator,
)

from api.catalogo import EnvioParaLixeira
from api.dispositivo import Dispositivo
from api.texto import sem_acento

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

Estado = Literal[
    "aguardando_upload",
    "validando",
    "analisando",
    "concluido",
    "falhou",
    "cancelado",
]
# Estados em que o Job terminou. `FIM` dispara webhook e evento de uso; `FIM_OU_CANCELADO`
# é o que vai para a lixeira e para a lista do painel.
FIM: frozenset[Estado] = frozenset({"concluido", "falhou"})
FIM_OU_CANCELADO: frozenset[Estado] = FIM | {"cancelado"}
CodigoDeFalha = Literal[
    "formato_invalido",
    "arquivo_corrompido",
    "codec_nao_suportado",
    "duracao_excedida",
    "upload_expirado",
    # A validação ou a detecção de cortes estourou o tempo: não é defeito do arquivo, mas
    # o reprocessamento não recomeça pela validação; envie o mesmo arquivo de novo.
    "processamento_demorou_demais",
    "analise_falhou",
    "transcricao_falhou",
    "ocr_falhou",
    # O próprio Workflows caiu num erro que nenhum passo tratou (`marca_interrompido`).
    "processamento_interrompido",
]


EstadoDaIndexacao = Literal["pendente", "indexado", "falhou"]


class Indexacao(BaseModel):
    """Onde o Job está no índice da busca; uma falha dela não muda o `estado` do Job."""

    estado: EstadoDaIndexacao
    em: datetime
    # O começo da rodada que terminou em `em`: o que foi gravado até aqui entrou nela.
    desde: datetime | None = None


class RodadaDaIndexacao(BaseModel):
    """A execução que está indexando o vídeo agora (#419): quem a toma é a única que grava no
    índice, e o `id` separa a dela de uma que a substituiu depois de `em` vencer."""

    id: str
    em: datetime


EstadoDaCopia = Literal["pendente", "copiado", "falhou"]


class CopiaNoBigQuery(BaseModel):
    """Onde o Job está na cópia para o BigQuery (#260); falhar não muda o `estado` do Job."""

    estado: EstadoDaCopia
    em: datetime
    desde: datetime | None = None
    anos: list[int] = Field(default_factory=list)
    # Só fica completo depois do primeiro MERGE sem filtro, inclusive se não há data.
    particoes_conhecidas: bool = False


NomeDaEtapa = Literal[
    "validacao",
    "transcricao",
    "leitura_da_tela",
    "analise",
    # Depois do `concluido`, na ordem do Workflows. A identificação aprimora a Decupagem
    # no lugar (#221).
    "identificacao",
    "quadros_chave",
    "inventario_de_objetos",
    "indexacao",
]
# Etapas do #112 retiradas no #327; só os Jobs antigos ainda as trazem.
ETAPAS_QUE_SAIRAM = frozenset({"referencias", "comparacao"})
ResultadoDaEtapa = Literal["concluida", "falhou"]


class Etapa(BaseModel):
    """Uma etapa já iniciada do processamento; `fim` e `resultado` só depois que ela acaba."""

    inicio: datetime
    fim: datetime | None = None
    resultado: ResultadoDaEtapa | None = None
    # Só a transcrição e a leitura da tela (#239): onde rodaram e quantas vezes o Workflows
    # tentou o Job com GPU (a espera por falta de GPU ou de cota); `None` nas outras etapas
    # e em etapa anterior ao campo.
    dispositivo: Dispositivo | None = None
    tentativas_gpu: int | None = None


# O que a lista do acervo lê do Job: os campos do `JobResumido` (menos `enviado_por`, que vem
# de `sistema` e `criado_por_email`), os obrigatórios do `Job` e os que `casa_com_o_filtro`
# confere (#480). Fica de fora o que pesa: `cortes_ms`, os catálogos e o `sha256`.
CAMPOS_DA_LISTA = frozenset(
    {
        "id", "nome", "tamanho_bytes", "estado", "criado_por", "criado_em", "atualizado_em",
        "codigo_falha", "duracao_s", "timecode_origem", "taxa_de_quadros", "capa", "programa",
        "data_exibicao", "indexacao", "copia_bigquery", "etapa_atual", "etapas",
        "reprocessamentos", "inicio_da_passada", "criado_por_email", "sistema", "palavras", "lixeira",
    }
)  # fmt: skip


class Job(BaseModel):
    id: str
    nome: str
    tamanho_bytes: int
    sha256: str | None = None
    duracao_s: float | None = None
    # Cortes de câmera da validação, em ms; `None` em Job anterior à detecção.
    cortes_ms: list[int] | None = None
    # Timecode inicial da faixa `tmcd` do arquivo; `None` sem a faixa, fora do
    # formato ou em Job anterior ao campo.
    timecode_origem: str | None = None
    # Quadros por segundo do vídeo (ffprobe); `None` em Job anterior ao campo.
    taxa_de_quadros: float | None = None
    # Caminho do quadro de capa (`quadros/plano-1.jpg`), escolhido ao tirar os
    # quadros-chave; `None` sem planos com quadro e em Job anterior ao campo.
    capa: str | None = None
    estado: Estado
    codigo_falha: CodigoDeFalha | None = None
    criado_por: str
    # E-mail de quem criou; `None` em Job de sistema e em Job anterior ao campo.
    criado_por_email: str | None = None
    sistema: str | None = None
    programa: str | None = None
    # Palavras normalizadas do nome do arquivo, para a busca por nome (o Firestore
    # não busca por trecho); vazio em Job anterior ao campo.
    palavras: list[str] = []
    # Dia em que o programa foi ao ar; `None` em Job anterior ao campo.
    data_exibicao: date | None = None
    # Mês de `data_exibicao` (`AAAA-MM`), sempre derivado dela ao montar o Job: a lista por
    # envio filtra o período por aqui no Firestore, onde um intervalo em `data_exibicao`
    # não cabe com a ordem por `criado_em` (#479). `None` sem data; em Job anterior ao
    # campo, só `make gravar-mes-nos-jobs` o grava.
    mes_exibicao: str | None = None
    # A `versao_pipeline` da Decupagem, gravada ao concluir a análise: o reprocessar por versão
    # lê daqui, sem abrir as decupagens (#494). `anterior` se a decupagem não tem o campo.
    # `None` até concluir, depois de uma correção à mão para concluído e em Job anterior ao
    # campo, até `make gravar-versao-nos-jobs`.
    versao_pipeline: str | None = None
    # `None` até o Job concluir (e em Job anterior ao campo).
    indexacao: Indexacao | None = None
    # Quantas vezes se pediu a indexação do vídeo e até qual pedido ela já chegou (#419): aprovar a
    # revisão, trocar o nome do programa e o `make` da indexação só incrementam `versao_pedida`; o
    # `mam-indexacao` reindexa até `versao_indexada` alcançá-la. Zero nos dois em Job anterior.
    versao_pedida: int = 0
    versao_indexada: int = 0
    # `None` sem execução indexando; ver `api.ciclo_de_vida.tomar_a_rodada`.
    rodada_da_indexacao: RodadaDaIndexacao | None = None
    # `None` até a primeira cópia (e onde o BigQuery não está configurado).
    copia_bigquery: CopiaNoBigQuery | None = None
    # A etapa em andamento; `None` entre etapas, com o Job parado e em Job anterior ao campo.
    etapa_atual: NomeDaEtapa | None = None
    # Só as etapas iniciadas, por nome; vazio em Job anterior ao campo. Quem grava é
    # `api.ciclo_de_vida` (e o Workflows, com o mesmo formato).
    etapas: dict[NomeDaEtapa, Etapa] = {}
    # Quantas vezes o Job foi reprocessado a partir da etapa que falhou (#147).
    reprocessamentos: int = 0
    # Início da passada atual; `None` em Job anterior ao campo.
    inicio_da_passada: datetime | None = None
    # Em qual `reprocessamentos` o fim `falhou` deste Job já foi avisado (webhook e evento de
    # uso) por `api.fim_do_job`, o caminho do `falhou` que o Workflows grava; `None` se nunca.
    fim_avisado_no_reprocessamento: int | None = None
    # `None` fora da lixeira. Na lixeira o Job só o Administrador enxerga; nada é apagado.
    lixeira: EnvioParaLixeira | None = None
    # Os `catalogo_id` que aparecem na Decupagem entregue (Correções aplicadas, pessoas
    # fundidas resolvidas): o impacto de uma pessoa ou marca do catálogo acha os vídeos
    # por aqui, sem abrir todas as decupagens (#359). Vazios em Job anterior ao campo
    # até rodar `make preencher-catalogo-dos-jobs`.
    pessoas_do_catalogo: list[str] = []
    marcas_do_catalogo: list[str] = []
    criado_em: datetime
    atualizado_em: datetime

    @field_serializer("data_exibicao")
    def _data_como_texto(self, data: date | None) -> str | None:
        # O Firestore não guarda `date`; o Pydantic a lê de volta do texto ISO.
        return data.isoformat() if data else None

    @model_validator(mode="before")
    @classmethod
    def _sem_as_etapas_que_sairam(cls, dados: Any) -> Any:
        # Jobs gravados antes do #327 trazem as etapas `referencias` e `comparacao`, que
        # deixaram de existir; elas somem na leitura em vez de derrubar o Job.
        if not isinstance(dados, dict):
            return dados
        dados = dict(dados)
        data = dados.get("data_exibicao")
        if isinstance(data, date | str):
            dados["mes_exibicao"] = mes_da_data(data)
        etapas = dados.get("etapas")
        if isinstance(etapas, dict):
            dados["etapas"] = {
                n: e for n, e in etapas.items() if n not in ETAPAS_QUE_SAIRAM
            }
        if dados.get("etapa_atual") in ETAPAS_QUE_SAIRAM:
            dados["etapa_atual"] = None
        return dados


def mes_da_data(data: date | str) -> str:
    """`AAAA-MM` da data de exibição (`date` ou texto ISO): o `mes_exibicao` do Job."""
    return data.isoformat()[:7] if isinstance(data, date) else data[:7]


def palavras_do_nome(nome: str) -> list[str]:
    """Palavras do nome do arquivo, sem maiúsculas nem acentos.

    Quebra em tudo que não é letra nem dígito (`_`, `-`, `.`, espaço, parênteses...).
    """
    palavras = [p for p in re.split(r"[\W_]+", sem_acento(nome).casefold()) if p]
    return list(dict.fromkeys(palavras))


class CursorInvalido(Exception):
    """O cursor não aponta para um Job que exista."""


Ordem = Literal["enviado", "exibicao"]


@dataclass(frozen=True)
class FiltroDeJobs:
    """Os filtros do acervo; todos opcionais e combináveis."""

    # Os programas do filtro (o `GET /v1/jobs` do Acervo); imutável porque o filtro é a chave do
    # cache da lista sem capa. Vazio: todos.
    programas: frozenset[str] = frozenset()
    estados: frozenset[Estado] = frozenset()
    exibicao_de: date | None = None
    exibicao_ate: date | None = None
    # Dia do envio (`criado_em`) no fuso de São Paulo, as duas pontas inclusive.
    enviado_de: date | None = None
    enviado_ate: date | None = None
    palavras: tuple[str, ...] = ()  # já normalizadas: todas precisam estar no nome
    sistema: str | None = None
    # `False`: só os Jobs fora da lixeira (o acervo); `True`: só os que estão nela;
    # `None`: os dois (para achar o mesmo arquivo, esteja onde estiver).
    na_lixeira: bool | None = False
    sha256: str | None = None  # só os Jobs do mesmo arquivo
    pessoa_do_catalogo: str | None = None  # só os vídeos em que a pessoa aparece
    marca_do_catalogo: str | None = None  # só os vídeos em que a marca aparece
    ordem: Ordem = "enviado"
    limite: int | None = None  # `None`: a lista inteira, sem cursor e sem teto
    cursor: str | None = None  # id do último Job examinado na página anterior
    # Só a lista do acervo: lê os campos do `JobResumido` (e os que o filtro confere), não o
    # Job inteiro. O Job vem incompleto, então quem o regrava não pode pedir isto (#480).
    so_os_da_lista: bool = False


def um_alem_do_limite[T: _ComId](
    itens: Iterable[T], limite: int | None
) -> tuple[list[T], str | None]:
    """Corta os itens já filtrados e em ordem; só lê um além do limite. Devolve a página e o
    cursor (o id do último), ou `None` quando não há próxima."""
    if limite is None:
        return list(itens), None
    lidos = list(itertools.islice(itens, limite + 1))
    if len(lidos) <= limite:
        return lidos, None
    pagina = lidos[:limite]
    return pagina, pagina[-1].id


class _ComId(Protocol):
    @property
    def id(self) -> str: ...


@dataclass(frozen=True)
class PaginaDeJobs:
    jobs: list[Job]
    proximo_cursor: str | None = None

    @classmethod
    def de(cls, jobs: Iterable[Job], limite: int | None) -> "PaginaDeJobs":
        """Corta os Jobs já filtrados e em ordem; só lê um além do limite."""
        return cls(*um_alem_do_limite(jobs, limite))


def casa_com_o_filtro(job: Job, filtro: FiltroDeJobs) -> bool:
    """Todos os filtros menos ordem e paginação."""
    if filtro.na_lixeira is not None and (job.lixeira is not None) != filtro.na_lixeira:
        return False
    if filtro.sha256 is not None and job.sha256 != filtro.sha256:
        return False
    if (
        filtro.pessoa_do_catalogo is not None
        and filtro.pessoa_do_catalogo not in job.pessoas_do_catalogo
    ):
        return False
    if (
        filtro.marca_do_catalogo is not None
        and filtro.marca_do_catalogo not in job.marcas_do_catalogo
    ):
        return False
    if filtro.programas and job.programa not in filtro.programas:
        return False
    if filtro.sistema is not None and job.sistema != filtro.sistema:
        return False
    if filtro.estados and job.estado not in filtro.estados:
        return False
    if filtro.exibicao_de is not None or filtro.exibicao_ate is not None:
        if job.data_exibicao is None:
            return False
        if filtro.exibicao_de and job.data_exibicao < filtro.exibicao_de:
            return False
        if filtro.exibicao_ate and job.data_exibicao > filtro.exibicao_ate:
            return False
    if filtro.enviado_de is not None or filtro.enviado_ate is not None:
        dia = job.criado_em.astimezone(SAO_PAULO).date()
        if filtro.enviado_de and dia < filtro.enviado_de:
            return False
        if filtro.enviado_ate and dia > filtro.enviado_ate:
            return False
    return all(p in job.palavras for p in filtro.palavras)


def chave_de_ordem(job: Job, ordem: Ordem) -> tuple[Any, ...]:
    """Maior primeiro. Na exibição, quem não tem data fica no fim; o id desempata."""
    if ordem == "exibicao":
        return (job.data_exibicao is not None, job.data_exibicao or date.min, job.id)
    return (job.criado_em, job.id)


def paginar_em_python(
    jobs: Iterable[Job], filtro: FiltroDeJobs, obter: Callable[[str], Job | None]
) -> PaginaDeJobs:
    """Ordena e pagina Jobs já filtrados; `obter` acha o Job do cursor."""
    corte = None
    if filtro.cursor is not None:
        ancora = obter(filtro.cursor)
        if ancora is None:
            raise CursorInvalido
        corte = chave_de_ordem(ancora, filtro.ordem)
    ordenados = sorted(
        (j for j in jobs if corte is None or chave_de_ordem(j, filtro.ordem) < corte),
        key=lambda j: chave_de_ordem(j, filtro.ordem),
        reverse=True,
    )
    return PaginaDeJobs.de(ordenados, filtro.limite)


class RepositorioDeJobs(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, job: Job) -> None: ...

    def criar(self, job: Job) -> bool:
        """Grava só se o id não existe; `False` se já existia (não regrava)."""
        ...

    def obter(self, job_id: str) -> Job | None: ...

    def obter_fila_gpu(self) -> dict[str, Any]:
        """O documento `fila_gpu/vagas`; vazio quando ainda não existe."""
        ...

    def obter_varios(
        self, job_ids: Iterable[str], so_a_lista: bool = False
    ) -> list[Job]:
        """Os Jobs que existem entre `job_ids`, numa leitura em lote, em qualquer ordem.
        `so_a_lista` lê só `CAMPOS_DA_LISTA` (sem `cortes_ms` e catálogos): só para quem
        não regrava o Job."""
        ...

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        """Aplica `mudancas` só se o Job ainda estiver em `de`; atômica.

        Devolve o Job gravado, ou `None` se ele não existe ou já saiu de `de`.
        Quem decide as transições é `api.ciclo_de_vida`; use `transitar` de lá.
        """
        ...

    def acrescentar_ano_da_copia(self, job_id: str, ano: int) -> None:
        """Acrescenta o ano possível da cópia atomicamente, sem remover os anteriores."""
        ...

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        """Lê o Job, pede a `mudar` as mudanças e as grava, tudo atômico.

        `mudar` devolve `None` para recusar (nada é gravado); ela pode rodar mais de
        uma vez, então não pode ter efeito de fora. Devolve o Job gravado, ou `None`
        se ele não existe ou `mudar` recusou. Quem decide é `api.ciclo_de_vida`.
        """
        ...

    def remover(self, job_id: str) -> None:
        """Apaga o Job. Só a purga (`api.purga`) chama; não há erro se ele não existe."""
        ...

    def listar(self) -> list[Job]:
        """Do mais recente para o mais antigo."""
        ...

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        """Filtra, ordena e pagina. Levanta `CursorInvalido` se o cursor não existe."""
        ...

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
        """Quantos Jobs `criado_por` criou de `desde` em diante (lixeira inclusive)."""
        ...


def agora_utc() -> datetime:
    return datetime.now(UTC)
