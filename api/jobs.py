"""Jobs da E0: modelo, portas (Firestore e Storage) e rotas `/v1/jobs`."""

import hashlib
import itertools
import json
import re
import unicodedata
import uuid
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from api.auth import (
    Chamador,
    ChamadorAutenticado,
    Escopo,
    Sistema,
    Usuario,
)
from api.catalogo import Catalogo, EnvioParaLixeira
from api.catalogo_apagado import com_pessoas_fundidas, sem_catalogo_apagado
from api.ciclo_de_vida import JaTerminou, transitar
from api.ciclo_de_vida import cancelar as cancelar_job
from api.correcoes import (
    LIMITE_DO_NOME,
    Autoria,
    CatalogoIdInvalido,
    Correcao,
    CorrecaoInexistente,
    CorrecaoJaExiste,
    EstruturaInvalida,
    ItemDaFila,
    ItemDoHistorico,
    ItemInexistente,
    NaoCandidato,
    NaoDesfazivel,
    NaoNaFila,
    NaoPendente,
    NovaCorrecao,
    NovaReaplicacao,
    NovaRecusa,
    NovaResolucao,
    NovoDesfazer,
    RepositorioDeAprovacao,
    RepositorioDeCorrecoes,
    TemposInvalidos,
    VersaoDesatualizada,
    com_o_estado_na_busca,
    corrigir,
    decidir,
    decupagem_entregue,
    descartar,
    desfazer,
    fila,
    historico,
    reaplicar,
    versao_do_modelo,
)
from api.decupagem import caminho_do_quadro
from api.eventos_de_uso import Eventos, SemEventos, quem_do_chamador, registrar
from api.idempotencia import (
    TAMANHO_MAXIMO_DA_CHAVE,
    ChaveReusadaComOutroCorpo,
    RepositorioDeIdempotencia,
    RepositorioDeIdempotenciaEmMemoria,
    impressao_do_corpo,
)
from api.marcas import CatalogoDeMarcas
from api.papeis import (
    Papel,
    Permissao,
    RepositorioDePapeis,
    papeis_do_usuario,
    permissoes_de,
)
from api.programas import PERFIS
from api.sugestoes import (
    MOTIVO_CONFIRMADA,
    MOTIVO_CORRIGIDA,
    Proposta,
    RepositorioDeSugestoes,
    Sugestao,
    com_o_valor_do_editor,
    sugestoes_abertas,
)

TIPO_DO_VIDEO = "video/mp4"
TAMANHO_MAXIMO_PADRAO_BYTES = 4 * 1024**3
PRAZO_DO_UPLOAD = timedelta(hours=24)
VALIDADE_DA_REPRODUCAO = timedelta(minutes=10)
VALIDADE_DO_DOWNLOAD = timedelta(minutes=5)
# O "hoje" da data de exibição é o de Brasília, sem horário de verão desde 2019.
FUSO_DA_EMISSORA = timezone(timedelta(hours=-3))

Estado = Literal[
    "aguardando_upload",
    "validando",
    "analisando",
    "concluido",
    "falhou",
    "cancelado",
]
CodigoDeFalha = Literal[
    "formato_invalido",
    "arquivo_corrompido",
    "codec_nao_suportado",
    "duracao_excedida",
    "upload_expirado",
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


EstadoDaCopia = Literal["pendente", "copiado", "falhou"]


class CopiaNoBigQuery(BaseModel):
    """Onde o Job está na cópia para o BigQuery (#260); falhar não muda o `estado` do Job."""

    estado: EstadoDaCopia
    em: datetime
    desde: datetime | None = None


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
DispositivoDaEtapa = Literal["gpu", "cpu"]


class Etapa(BaseModel):
    """Uma etapa já iniciada do processamento; `fim` e `resultado` só depois que ela acaba."""

    inicio: datetime
    fim: datetime | None = None
    resultado: ResultadoDaEtapa | None = None
    # Só a transcrição e a leitura da tela (#239): onde rodaram e quantas vezes o Workflows
    # tentou o Job com GPU (a espera por falta de GPU ou de cota); `None` nas outras etapas
    # e em etapa anterior ao campo.
    dispositivo: DispositivoDaEtapa | None = None
    tentativas_gpu: int | None = None


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
    # `None` até o Job concluir (e em Job anterior ao campo).
    indexacao: Indexacao | None = None
    # `None` até a primeira cópia (e onde o BigQuery não está configurado).
    copia_bigquery: CopiaNoBigQuery | None = None
    # A etapa em andamento; `None` entre etapas, com o Job parado e em Job anterior ao campo.
    etapa_atual: NomeDaEtapa | None = None
    # Só as etapas iniciadas, por nome; vazio em Job anterior ao campo. Quem grava é
    # `api.ciclo_de_vida` (e o Workflows, com o mesmo formato).
    etapas: dict[NomeDaEtapa, Etapa] = {}
    # Quantas vezes o Job foi reprocessado a partir da etapa que falhou (#147).
    reprocessamentos: int = 0
    # `None` fora da lixeira. Na lixeira o Job só o Administrador enxerga; nada é apagado.
    lixeira: EnvioParaLixeira | None = None
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
        etapas = dados.get("etapas")
        if isinstance(etapas, dict):
            dados["etapas"] = {
                n: e for n, e in etapas.items() if n not in ETAPAS_QUE_SAIRAM
            }
        if dados.get("etapa_atual") in ETAPAS_QUE_SAIRAM:
            dados["etapa_atual"] = None
        return dados


def palavras_do_nome(nome: str) -> list[str]:
    """Palavras do nome do arquivo, sem maiúsculas nem acentos.

    Quebra em tudo que não é letra nem dígito (`_`, `-`, `.`, espaço, parênteses...).
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c)
    )
    palavras = [p for p in re.split(r"[\W_]+", sem_acento.casefold()) if p]
    return list(dict.fromkeys(palavras))


class EnviadoPor(BaseModel):
    tipo: Literal["pessoa", "sistema"]
    # O e-mail da pessoa (`None` em Job antigo) ou o nome do sistema.
    nome: str | None


class EtapaPublica(Etapa):
    nome: NomeDaEtapa


class JobPublico(BaseModel):
    """O que a API mostra de um Job; o SHA-256 e o tamanho ficam no armazenamento."""

    id: str
    nome: str
    estado: Estado
    codigo_falha: CodigoDeFalha | None
    duracao_s: float | None
    # Cortes de câmera, em ms: os riscos da régua do Visualizador.
    cortes_ms: list[int] | None = None
    timecode_origem: str | None = None
    taxa_de_quadros: float | None = None
    # URL assinada, de curta validade, do quadro de capa; só a listagem a preenche.
    capa_url: str | None = None
    programa: str | None = None
    data_exibicao: date | None = None
    indexacao: Indexacao | None = None
    copia_bigquery: CopiaNoBigQuery | None = None
    etapa_atual: NomeDaEtapa | None = None
    # As etapas iniciadas, da primeira à última.
    etapas: list[EtapaPublica] = []
    reprocessamentos: int = 0
    enviado_por: EnviadoPor
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, job: Job) -> "JobPublico":
        campos = set(cls.model_fields) - {"enviado_por", "etapas"}
        enviado_por = (
            EnviadoPor(tipo="sistema", nome=job.sistema)
            if job.sistema is not None
            else EnviadoPor(tipo="pessoa", nome=job.criado_por_email)
        )
        etapas = sorted(job.etapas.items(), key=lambda par: par[1].inicio)
        return cls(
            **job.model_dump(include=campos),
            etapas=[EtapaPublica(nome=n, **e.model_dump()) for n, e in etapas],
            enviado_por=enviado_por,
        )


def _etag(publico: JobPublico) -> str:
    conteudo = publico.model_dump_json().encode()
    return f'"{hashlib.sha256(conteudo).hexdigest()[:32]}"'


def disposicao_do_nome(nome: str) -> str:
    """O parâmetro `filename` do `Content-Disposition`: um nome em ASCII para os
    navegadores antigos e o nome inteiro em UTF-8 (RFC 6266)."""
    ascii_ = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    simples = re.sub(r"[^A-Za-z0-9._ -]", "_", ascii_)
    return f"filename=\"{simples}\"; filename*=UTF-8''{quote(nome, safe='')}"


def _casa_etag(if_none_match: str | None, etag: str) -> bool:
    """Comparação fraca do RFC 9110 §13.1.2: lista por vírgulas, `W/` ignorado, `*` casa."""
    if if_none_match is None:
        return False
    candidatos = [c.strip().removeprefix("W/") for c in if_none_match.split(",")]
    return "*" in candidatos or etag in candidatos


class JobCriado(JobPublico):
    # `None` na repetição de um envio cujo upload já passou da espera.
    url_de_upload: str | None


AcaoDeDownload = Literal["video.baixado", "decupagem.baixada"]


class AcessosAoVideo(Protocol):
    """Porta para o registro de quem abriu e quem baixou o vídeo (`api.acessos`)."""

    def abriu(self, chamador: Chamador, job: Job) -> None:
        """Registra a abertura; no máximo uma por pessoa e vídeo a cada 30 minutos."""
        ...

    def baixou(
        self,
        chamador: Chamador,
        job: Job,
        acao: AcaoDeDownload,
    ) -> None:
        """Registra o download; `ServicoIndisponivel` se não gravou."""
        ...


class Reproducao(BaseModel):
    url: str
    expira_em: datetime


class TipoNaoSuportado(Exception):
    """Corpo com tipo diferente de video/mp4: vira 415, antes de qualquer 422."""


class NovoJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    tamanho_bytes: Annotated[int, Field(strict=True)]
    tipo: Literal["video/mp4"]
    programa: str | None = None  # um nome de `programas.toml`
    data_exibicao: date | None = None

    @model_validator(mode="before")
    @classmethod
    def _tipo_antes_do_resto(cls, corpo: Any) -> Any:
        # Exceção fora de ValueError atravessa o Pydantic, e o 415 não vira 422
        # quando o nome ou o tamanho também estão errados (um .mov, por exemplo).
        if (
            isinstance(corpo, dict)
            and "tipo" in corpo
            and corpo["tipo"] != TIPO_DO_VIDEO
        ):
            raise TipoNaoSuportado
        return corpo

    @field_validator("nome")
    @classmethod
    def _nome_de_arquivo_mp4(cls, nome: str) -> str:
        if any(c in nome for c in "/\\") or any(ord(c) < 32 for c in nome):
            raise ValueError("nome com caminho ou caractere de controle")
        if not nome.lower().endswith(".mp4"):
            raise ValueError("nome sem extensão .mp4")
        return nome

    @field_validator("data_exibicao", mode="before")
    @classmethod
    def _data_so_como_texto(cls, valor: Any) -> Any:
        # O Pydantic leria um número como timestamp e aceitaria data com hora
        # zerada; aqui só vale "AAAA-MM-DD".
        if valor is not None and not (isinstance(valor, str) and len(valor) == 10):
            raise ValueError("data_exibicao deve ser texto AAAA-MM-DD")
        return valor

    @field_validator("programa")
    @classmethod
    def _programa_com_perfil(cls, programa: str | None) -> str | None:
        if programa is not None and programa not in PERFIS:
            validos = ", ".join(sorted(PERFIS))
            raise ValueError(f"programa sem perfil; programas válidos: {validos}")
        return programa


class ServicoIndisponivel(Exception):
    """Porta ainda sem adaptador real."""


class DisparoDaIndexacao(Protocol):
    """Começa a reindexação do vídeo fora do pedido HTTP (Job `mam-indexacao`, com `JOB_ID`).
    Levanta `ServicoIndisponivel` se não conseguiu."""

    def iniciar(self, job_id: str) -> None: ...


class DisparoDaIndexacaoIndisponivel:
    def iniciar(self, job_id: str) -> None:
        raise ServicoIndisponivel


class CursorInvalido(Exception):
    """O cursor não aponta para um Job que exista."""


Ordem = Literal["enviado", "exibicao"]
LIMITE_MAXIMO = 200


@dataclass(frozen=True)
class FiltroDeJobs:
    """Os filtros do acervo; todos opcionais e combináveis."""

    programa: str | None = None
    estados: frozenset[Estado] = frozenset()
    exibicao_de: date | None = None
    exibicao_ate: date | None = None
    palavras: tuple[str, ...] = ()  # já normalizadas: todas precisam estar no nome
    sistema: str | None = None
    # `False`: só os Jobs fora da lixeira (o acervo); `True`: só os que estão nela;
    # `None`: os dois (para achar o mesmo arquivo, esteja onde estiver).
    na_lixeira: bool | None = False
    sha256: str | None = None  # só os Jobs do mesmo arquivo
    ordem: Ordem = "enviado"
    limite: int | None = None  # `None`: a lista inteira, sem cursor
    cursor: str | None = None  # id do último Job da página anterior


@dataclass(frozen=True)
class PaginaDeJobs:
    jobs: list[Job]
    proximo_cursor: str | None = None

    @classmethod
    def de(cls, jobs: Iterable[Job], limite: int | None) -> "PaginaDeJobs":
        """Corta os Jobs já filtrados e em ordem; só lê um além do limite."""
        if limite is None:
            return cls(list(jobs))
        lidos = list(itertools.islice(jobs, limite + 1))
        if len(lidos) <= limite:
            return cls(lidos)
        pagina = lidos[:limite]
        return cls(pagina, pagina[-1].id)


def casa_com_o_filtro(job: Job, filtro: FiltroDeJobs) -> bool:
    """Todos os filtros menos ordem e paginação."""
    if filtro.na_lixeira is not None and (job.lixeira is not None) != filtro.na_lixeira:
        return False
    if filtro.sha256 is not None and job.sha256 != filtro.sha256:
        return False
    if filtro.programa is not None and job.programa != filtro.programa:
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
    return all(p in job.palavras for p in filtro.palavras)


def chave_de_ordem(job: Job, ordem: Ordem) -> tuple[Any, ...]:
    """Maior primeiro. Na exibição, quem não tem data fica no fim; o id desempata."""
    if ordem == "exibicao":
        return (job.data_exibicao is not None, job.data_exibicao or date.min, job.id)
    return (job.criado_em, job.id)


class RepositorioDeJobs(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, job: Job) -> None: ...

    def criar(self, job: Job) -> bool:
        """Grava só se o id não existe; `False` se já existia (não regrava)."""
        ...

    def obter(self, job_id: str) -> Job | None: ...

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        """Aplica `mudancas` só se o Job ainda estiver em `de`; atômica.

        Devolve o Job gravado, ou `None` se ele não existe ou já saiu de `de`.
        Quem decide as transições é `api.ciclo_de_vida`; use `transitar` de lá.
        """
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


class Armazenamento(Protocol):
    """Porta para o Cloud Storage; os testes usam uma versão falsa."""

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        """URL assinada para iniciar um upload retomável na quarentena, presa ao tipo e ao tamanho."""
        ...

    def cancelar_upload(self, job_id: str) -> None: ...

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        """URL assinada de leitura do proxy de reprodução, válida por `validade`."""
        ...

    def url_de_download(self, job_id: str, nome: str, validade: timedelta) -> str:
        """URL assinada de leitura da cópia limpa, que o navegador baixa como `nome`."""
        ...

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        """URL assinada de leitura do JPEG de `caminho` (o campo `quadro` da Decupagem)."""
        ...

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        """O JPEG de `caminho`, para o vetor multimodal da indexação (#268)."""
        ...

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        """O JSON da decupagem, em pedaços."""
        ...


class RepositorioEmMemoria:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def salvar(self, job: Job) -> None:
        self._jobs[job.id] = job

    def criar(self, job: Job) -> bool:
        return self._jobs.setdefault(job.id, job) is job

    def obter(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.estado != de:
            return None
        self._jobs[job_id] = job.model_copy(update=mudancas)
        return self._jobs[job_id]

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        job = self._jobs.get(job_id)
        mudancas = mudar(job) if job is not None else None
        if job is None or mudancas is None:
            return None
        self._jobs[job_id] = job.model_copy(update=mudancas)
        return self._jobs[job_id]

    def remover(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    def listar(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.criado_em, reverse=True)

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        corte = None
        if filtro.cursor is not None:
            ancora = self._jobs.get(filtro.cursor)
            if ancora is None:
                raise CursorInvalido
            corte = chave_de_ordem(ancora, filtro.ordem)
        jobs = sorted(
            (
                j
                for j in self._jobs.values()
                if casa_com_o_filtro(j, filtro)
                and (corte is None or chave_de_ordem(j, filtro.ordem) < corte)
            ),
            key=lambda j: chave_de_ordem(j, filtro.ordem),
            reverse=True,
        )
        return PaginaDeJobs.de(jobs, filtro.limite)


class RepositorioIndisponivel:
    def salvar(self, job: Job) -> None:
        raise ServicoIndisponivel

    def criar(self, job: Job) -> bool:
        raise ServicoIndisponivel

    def obter(self, job_id: str) -> Job | None:
        raise ServicoIndisponivel

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        raise ServicoIndisponivel

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        raise ServicoIndisponivel

    def remover(self, job_id: str) -> None:
        raise ServicoIndisponivel

    def listar(self) -> list[Job]:
        raise ServicoIndisponivel

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        raise ServicoIndisponivel


class ArmazenamentoIndisponivel:
    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        raise ServicoIndisponivel

    def cancelar_upload(self, job_id: str) -> None:
        raise ServicoIndisponivel

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        raise ServicoIndisponivel

    def url_de_download(self, job_id: str, nome: str, validade: timedelta) -> str:
        raise ServicoIndisponivel

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        raise ServicoIndisponivel

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        raise ServicoIndisponivel

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        raise ServicoIndisponivel


def expirar_uploads(
    repositorio: RepositorioDeJobs, armazenamento: Armazenamento, agora: datetime
) -> list[str]:
    """Falha os Jobs sem upload completo há 24 h ou mais e cancela a sessão de upload."""
    expirados: list[str] = []
    for job in repositorio.listar():
        if job.estado != "aguardando_upload" or agora - job.criado_em < PRAZO_DO_UPLOAD:
            continue
        # Primeiro a transição: se o Job andou nesse meio-tempo, o upload é dele.
        if transitar(
            repositorio,
            job.id,
            "aguardando_upload",
            "falhou",
            agora,
            codigo_falha="upload_expirado",
        ):
            armazenamento.cancelar_upload(job.id)
            expirados.append(job.id)
    return expirados


def agora_utc() -> datetime:
    return datetime.now(UTC)


def _aceita_gzip(accept_encoding: str) -> bool:
    """`gzip` (ou `*`) no `Accept-Encoding`, sem `q=0`."""
    for opcao in accept_encoding.split(","):
        nome, *parametros = (parte.strip() for parte in opcao.split(";"))
        if nome.lower() not in ("gzip", "*"):
            continue
        for parametro in parametros:
            chave, _, valor = parametro.partition("=")
            if chave.strip().lower() == "q":
                try:
                    return float(valor) > 0
                except ValueError:
                    return False
        return True
    return False


def _comprimir(pedacos: Iterator[bytes]) -> Iterator[bytes]:
    compressor = zlib.compressobj(wbits=31)
    for pedaco in pedacos:
        if dados := compressor.compress(pedaco):
            yield dados
    yield compressor.flush()


# Permissão que a pessoa precisa para cada escopo de chave. Cancelar exige a de enviar.
PERMISSAO_DO_ESCOPO: dict[Escopo, Permissao] = {
    "criar": "video.enviar",
    "ler": "decupagem.ver",
    "cancelar": "video.enviar",
}


def _confere_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> None:
    """403 se a pessoa não tem a permissão por nenhum dos seus papéis."""
    if not _tem_permissao(request, pessoa, permissao):
        raise HTTPException(403, f"Sem a permissão {permissao}")


def _exige(escopo: Escopo) -> Callable[[Request, Chamador], Chamador]:
    """Dependência: chave sem o escopo, ou pessoa sem a permissão, recebe 403."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> Chamador:
        if isinstance(chamador, Sistema):
            if escopo not in chamador.escopos:
                raise HTTPException(403, f"Chave sem o escopo {escopo}")
            return chamador
        _confere_permissao(request, chamador, PERMISSAO_DO_ESCOPO[escopo])
        return chamador

    return verificar


def _chave_com_algum(*escopos: Escopo) -> Callable[[Chamador], Chamador]:
    """Dependência: chave sem nenhum dos escopos recebe 403; pessoa passa."""

    def verificar(chamador: ChamadorAutenticado) -> Chamador:
        if isinstance(chamador, Sistema) and not set(escopos) & set(chamador.escopos):
            raise HTTPException(403, f"Chave sem o escopo {' ou '.join(escopos)}")
        return chamador

    return verificar


def _exige_editar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `decupagem.editar`; chave de sistema não corrige."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não corrige a decupagem")
    _confere_permissao(request, chamador, "decupagem.editar")
    return chamador


def _exige_aprovar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `correcao.aprovar` (o Curador)."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não aprova correções")
    _confere_permissao(request, chamador, "correcao.aprovar")
    return chamador


def papeis_da_pessoa(request: Request, pessoa: Usuario) -> list[Papel]:
    """Os papéis efetivos, num ponto só para o `/v1/eu` e as rotas nunca discordarem."""
    papeis: RepositorioDePapeis = request.app.state.papeis
    return papeis_do_usuario(
        papeis.obter(pessoa.uid),
        pessoa.email,
        pessoa.email_verificado,
        request.app.state.admins,
    )


def _tem_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> bool:
    return permissao in permissoes_de(papeis_da_pessoa(request, pessoa))


def _enxerga(chamador: Chamador, job: Job | None) -> Job:
    """O job, ou 404 se não existe ou é de outro sistema (ou de uma pessoa), para uma chave."""
    if job is None or (
        isinstance(chamador, Sistema) and job.sistema != chamador.sistema
    ):
        raise HTTPException(404, "Job não encontrado")
    return job


class AceiteDaSugestao(BaseModel):
    """Corpo opcional do aceite: o "outro nome" (ou o título da pauta) do editor."""

    valor: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, max_length=LIMITE_DO_NOME),
        ]
        | None
    ) = None


def _correcao_da_proposta(proposta: Proposta, motivo: str, versao: str) -> NovaCorrecao:
    try:
        return NovaCorrecao(
            tipo=proposta.tipo,
            item_id=proposta.item_id,
            valor=proposta.valor,
            catalogo_id=proposta.catalogo_id,
            ocorrencia=proposta.ocorrencia,
            motivo=motivo,
            versao=versao,
        )
    except ValidationError as erro:
        raise HTTPException(422, "Valor inválido para a correção proposta") from erro


def criar_rotas(
    repositorio: RepositorioDeJobs,
    armazenamento: Armazenamento,
    tamanho_maximo_bytes: int,
    relogio: Callable[[], datetime],
    correcoes: RepositorioDeCorrecoes,
    aprovacao: RepositorioDeAprovacao,
    catalogo: Catalogo,
    marcas: CatalogoDeMarcas,
    sugestoes: RepositorioDeSugestoes,
    disparo_da_indexacao: DisparoDaIndexacao,
    acessos: AcessosAoVideo,
    tipos_de_objeto: Callable[[], list[str]] = list,
    idempotencia: RepositorioDeIdempotencia | None = None,
    eventos: Eventos | None = None,
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")
    publicador = eventos or SemEventos()
    chaves_de_idempotencia = idempotencia or RepositorioDeIdempotenciaEmMemoria()

    @rotas.post("", status_code=202)
    def criar(
        novo: NovoJob,
        chamador: Annotated[Chamador, Depends(_exige("criar"))],
        resposta: Response,
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> JobCriado:
        if not 0 < novo.tamanho_bytes <= tamanho_maximo_bytes:
            raise HTTPException(422, "Tamanho fora do limite")
        if isinstance(chamador, Sistema):
            criado_por, sistema = f"sistema:{chamador.sistema}", chamador.sistema
            email = None
        else:
            criado_por, sistema, email = chamador.uid, None, chamador.email or None
        agora = relogio()
        if (
            novo.data_exibicao is not None
            and novo.data_exibicao > agora.astimezone(FUSO_DA_EMISSORA).date()
        ):
            raise HTTPException(422, "Data de exibição no futuro")
        job_id, nova = uuid.uuid4().hex, True
        if idempotency_key is not None:
            if not (
                0 < len(idempotency_key) <= TAMANHO_MAXIMO_DA_CHAVE
                and idempotency_key.isascii()
                and idempotency_key.isprintable()
            ):
                raise HTTPException(422, "Idempotency-Key inválida")
            # A reserva é de quem chama: o mesmo texto em outro sistema é outra chave.
            escopo = (
                f"sistema:{sistema}" if sistema is not None else f"pessoa:{criado_por}"
            )
            try:
                reserva, nova = chaves_de_idempotencia.reservar(
                    escopo,
                    idempotency_key,
                    impressao_do_corpo(novo.model_dump(mode="json")),
                    job_id,
                    agora,
                )
            except ChaveReusadaComOutroCorpo:
                raise HTTPException(
                    409, "Idempotency-Key já usada com outro corpo"
                ) from None
            # Só o id vem da reserva: a repetição que grava o Job (o processo caiu entre
            # reservar e gravar) o cria com a hora de agora, para o prazo do upload
            # contar de quando a URL é dada.
            job_id = reserva.job_id
        job = Job(
            id=job_id,
            nome=novo.nome,
            tamanho_bytes=novo.tamanho_bytes,
            estado="aguardando_upload",
            criado_por=criado_por,
            criado_por_email=email,
            sistema=sistema,
            palavras=palavras_do_nome(novo.nome),
            programa=novo.programa,
            data_exibicao=novo.data_exibicao,
            criado_em=agora,
            atualizado_em=agora,
        )
        # A repetição lê antes de gravar (muitas ao mesmo tempo brigariam pelo mesmo
        # documento), e `criar` não regrava: a que chega antes de a primeira gravar não
        # desfaz o estado do Job.
        existente = None if nova else repositorio.obter(job.id)
        if existente is not None:
            job = existente
        elif not repositorio.criar(job):
            job = repositorio.obter(job.id) or job
        else:
            registrar(
                publicador,
                "envio",
                quem_do_chamador(chamador),
                agora,
                job_id=job.id,
                programa=job.programa,
                tamanho_bytes=job.tamanho_bytes,
            )
        if not nova:
            resposta.status_code = 200
        url = None
        if job.estado == "aguardando_upload":
            url = armazenamento.url_de_upload(job.id, job.tamanho_bytes, novo.tipo)
        return JobCriado(**JobPublico.de(job).model_dump(), url_de_upload=url)

    def _com_capa(job: Job) -> JobPublico:
        publico = JobPublico.de(job)
        if job.capa is not None:
            publico.capa_url = armazenamento.url_do_quadro(
                job.id, job.capa, VALIDADE_DA_REPRODUCAO
            )
        return publico

    @rotas.get("", response_model=list[JobPublico])
    def listar(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        programa: str | None = None,
        estado: Annotated[list[Estado] | None, Query()] = None,
        exibicao_de: date | None = None,
        exibicao_ate: date | None = None,
        q: str | None = None,
        sistema: str | None = None,
        ordem: Ordem = "enviado",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_MAXIMO)] = None,
        cursor: str | None = None,
    ) -> Response:
        if isinstance(chamador, Sistema):
            # Uma chave só vê os próprios Jobs; pedir os de outro sistema não acha nada.
            if sistema not in (None, chamador.sistema):
                return JSONResponse([])
            sistema = chamador.sistema
        filtro = FiltroDeJobs(
            programa=programa,
            estados=frozenset(estado or ()),
            exibicao_de=exibicao_de,
            exibicao_ate=exibicao_ate,
            palavras=tuple(palavras_do_nome(q or "")),
            sistema=sistema,
            ordem=ordem,
            limite=limite,
            cursor=cursor,
        )
        try:
            pagina = repositorio.consultar(filtro)
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        corpo = [_com_capa(j).model_dump(mode="json") for j in pagina.jobs]
        cabecalhos = (
            {"X-Proximo-Cursor": pagina.proximo_cursor} if pagina.proximo_cursor else {}
        )
        return JSONResponse(corpo, headers=cabecalhos)

    @rotas.get("/{job_id}", response_model=JobPublico)
    def ler(
        job_id: str,
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Response:
        job = _enxerga(chamador, repositorio.obter(job_id))
        publico = JobPublico.de(job)
        etag = _etag(publico)
        cabecalhos = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if _casa_etag(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=cabecalhos)
        return JSONResponse(publico.model_dump(mode="json"), headers=cabecalhos)

    def obter_concluido(job_id: str, chamador: Chamador) -> Job:
        job = _enxerga(chamador, repositorio.obter(job_id))
        if job.estado != "concluido":
            raise HTTPException(409, f"Job em {job.estado}, não concluido")
        return job

    @rotas.delete("/{job_id}", status_code=202)
    def cancelar(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("cancelar"))]
    ) -> JobPublico:
        _enxerga(chamador, repositorio.obter(job_id))
        try:
            job = cancelar_job(repositorio, job_id, relogio())
        except JaTerminou as terminou:
            raise HTTPException(
                409, f"Job em {terminou.estado}, não cancelável"
            ) from None
        return JobPublico.de(_enxerga(chamador, job))

    @rotas.get("/{job_id}/reproducao")
    def reproducao(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("ler"))]
    ) -> Reproducao:
        job = obter_concluido(job_id, chamador)
        url = armazenamento.url_de_reproducao(job.id, VALIDADE_DA_REPRODUCAO)
        acessos.abriu(chamador, job)
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_DA_REPRODUCAO)

    @rotas.get("/{job_id}/download")
    def baixar_video(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("ler"))]
    ) -> Reproducao:
        job = obter_concluido(job_id, chamador)
        url = armazenamento.url_de_download(job.id, job.nome, VALIDADE_DO_DOWNLOAD)
        # O registro vem antes da resposta: sem ele a URL não sai (503).
        acessos.baixou(chamador, job, "video.baixado")
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_DO_DOWNLOAD)

    @rotas.get("/{job_id}/quadros/{arquivo}")
    def quadro(
        job_id: str,
        arquivo: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*\.jpg$")],
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Reproducao:
        job = obter_concluido(job_id, chamador)
        url = armazenamento.url_do_quadro(
            job.id, caminho_do_quadro(arquivo), VALIDADE_DA_REPRODUCAO
        )
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_DA_REPRODUCAO)

    def _resposta(corpo: Iterator[bytes], request: Request) -> StreamingResponse:
        cabecalhos = {"Vary": "Accept-Encoding"}
        if _aceita_gzip(request.headers.get("accept-encoding", "")):
            cabecalhos["Content-Encoding"] = "gzip"
            corpo = _comprimir(corpo)
        return StreamingResponse(
            corpo, media_type="application/json", headers=cabecalhos
        )

    def _ler_modelo(job_id: str) -> tuple[dict[str, Any], str]:
        """O JSON do modelo e a versão (SHA-256 dos bytes guardados)."""
        conteudo = b"".join(armazenamento.abrir_decupagem(job_id))
        return json.loads(conteudo), versao_do_modelo(conteudo)

    def _ler_correcoes(job_id: str) -> list[Correcao]:
        return correcoes.listar(job_id)

    def _entregue(job: Job) -> dict[str, Any]:
        """A Decupagem entregue, com as Correções aplicadas."""
        modelo, versao_atual = _ler_modelo(job.id)
        entregue = decupagem_entregue(modelo, versao_atual, _ler_correcoes(job.id))
        entregue = com_pessoas_fundidas(entregue, catalogo.obter)
        entregue = sem_catalogo_apagado(
            entregue,
            lambda id: (p := catalogo.obter(id)) is not None and p.lixeira is None,
            lambda id: (m := marcas.obter(id)) is not None and m.lixeira is None,
        )
        return entregue

    @rotas.get("/{job_id}/decupagem")
    def decupagem(
        job_id: str,
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        versao: Literal["modelo"] | None = None,
    ) -> StreamingResponse:
        job = obter_concluido(job_id, chamador)
        if versao == "modelo":
            pedacos = iter(armazenamento.abrir_decupagem(job.id))
            # Lê o primeiro pedaço antes do 200: uma falha ao abrir vira 503, não um JSON cortado.
            pedacos = itertools.chain([next(pedacos, b"")], pedacos)
            return _resposta(pedacos, request)
        return _resposta(iter([json.dumps(_entregue(job)).encode()]), request)

    @rotas.get("/{job_id}/decupagem/download")
    def baixar_decupagem(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("ler"))]
    ) -> Response:
        job = obter_concluido(job_id, chamador)
        # Indentado como o arquivo que a tela baixava (`web/src/baixar.ts`).
        corpo = json.dumps(_entregue(job), indent=2, ensure_ascii=False).encode()
        acessos.baixou(chamador, job, "decupagem.baixada")
        nome = re.sub(r"\.mp4$", "", job.nome, flags=re.IGNORECASE) + ".decupagem.json"
        return Response(
            corpo,
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; {disposicao_do_nome(nome)}",
                "Cache-Control": "private, no-store",
            },
        )

    def _espera_curador(request: Request, autor: Usuario, tipo: str) -> bool:
        """Só a correção de quem não é Curador, num tipo da lista, espera decisão."""
        return tipo in aprovacao.tipos() and not _tem_permissao(
            request, autor, "correcao.aprovar"
        )

    def _autoria(autor: Usuario) -> Autoria:
        return Autoria(autor.uid, autor.email, relogio())

    def _gravar_correcao(
        job: Job,
        modelo: dict[str, Any],
        versao_atual: str,
        request: Request,
        novo: NovaCorrecao,
        autor: Usuario,
    ) -> Correcao:
        correcao = _conferir_correcao(job, modelo, versao_atual, request, novo, autor)
        correcoes.acrescentar(correcao)
        return correcao

    def _conferir_correcao(
        job: Job,
        modelo: dict[str, Any],
        versao_atual: str,
        request: Request,
        novo: NovaCorrecao,
        autor: Usuario,
    ) -> Correcao:
        """O registro da correção, ainda não gravado; 409 ou 422 se ela não vale."""
        try:
            return corrigir(
                modelo,
                versao_atual,
                _ler_correcoes(job.id),
                novo,
                job.id,
                _autoria(autor),
                exige_aprovacao=_espera_curador(request, autor, novo.tipo),
                catalogo=catalogo,
                marcas=marcas,
            )
        except VersaoDesatualizada:
            raise HTTPException(
                409, "A decupagem mudou: recarregue e corrija de novo"
            ) from None
        except ItemInexistente:
            raise HTTPException(422, "Item inexistente") from None
        except TemposInvalidos:
            raise HTTPException(422, "Tempos além da duração do vídeo") from None
        except EstruturaInvalida as erro:
            raise HTTPException(422, str(erro)) from None
        except CatalogoIdInvalido:
            raise HTTPException(422, "catalogo_id não é o desse nome") from None

    @rotas.post("/{job_id}/correcoes", status_code=201)
    def corrigir_decupagem(
        job_id: str,
        request: Request,
        novo: NovaCorrecao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        correcao = _gravar_correcao(job, modelo, versao_atual, request, novo, autor)
        _registrar_correcao(autor, job, correcao)
        return {"id": correcao.id, "versao_decupagem": versao_atual}

    def _registrar_correcao(autor: Usuario, job: Job, correcao: Correcao) -> None:
        registrar(
            publicador,
            "correcao",
            quem_do_chamador(autor),
            relogio(),
            job_id=job.id,
            programa=job.programa,
            tipo_de_correcao=correcao.tipo,
        )

    def _sugestoes_abertas(
        job: Job,
    ) -> tuple[list[Sugestao], dict[str, Any], str]:
        modelo, versao_atual = _ler_modelo(job.id)
        entregue = decupagem_entregue(modelo, versao_atual, _ler_correcoes(job.id))
        abertas = sugestoes_abertas(
            entregue, catalogo, sugestoes.decididas(job.id), tipos_de_objeto
        )
        return abertas, modelo, versao_atual

    def _a_sugestao(abertas: list[Sugestao], sugestao_id: str) -> Sugestao:
        achada = next((s for s in abertas if s.id == sugestao_id), None)
        if achada is None:
            raise HTTPException(404, "Sugestão não encontrada")
        return achada

    @rotas.get("/{job_id}/sugestoes")
    def sugestoes_do_video(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[Sugestao]:
        return _sugestoes_abertas(obter_concluido(job_id, autor))[0]

    @rotas.post("/{job_id}/sugestoes/{sugestao_id}/aceitar", status_code=201)
    def aceitar_sugestao(
        job_id: str,
        sugestao_id: str,
        request: Request,
        autor: Annotated[Usuario, Depends(_exige_editar)],
        corpo: AceiteDaSugestao | None = None,
    ) -> dict[str, Any]:
        job = obter_concluido(job_id, autor)
        abertas, modelo, versao_atual = _sugestoes_abertas(job)
        sugestao = _a_sugestao(abertas, sugestao_id)
        valor = corpo.valor if corpo else None
        if valor is not None:
            if not valor:
                raise HTTPException(422, "O valor não pode ser vazio")
            sugestao = com_o_valor_do_editor(sugestao, valor)
        elif sugestao.tipo == "pauta_do_trecho":
            raise HTTPException(422, "A pauta pede um título")
        motivo = MOTIVO_CORRIGIDA if valor is not None else MOTIVO_CONFIRMADA
        # Confere todas antes de gravar a primeira: o aceite não fica pela metade.
        gravadas = [
            _conferir_correcao(
                job,
                modelo,
                versao_atual,
                request,
                _correcao_da_proposta(proposta, motivo, versao_atual),
                autor,
            )
            for proposta in [sugestao.correcao, *sugestao.depois]
        ]
        for correcao in gravadas:
            correcoes.acrescentar(correcao)
            _registrar_correcao(autor, job, correcao)
        sugestoes.registrar(job.id, sugestao.id, sugestao.tipo, "aceita")
        return {"id": gravadas[0].id, "ids": [c.id for c in gravadas]}

    @rotas.post("/{job_id}/sugestoes/{sugestao_id}/recusar", status_code=204)
    def recusar_sugestao(
        job_id: str,
        sugestao_id: str,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> Response:
        job = obter_concluido(job_id, autor)
        sugestao = _a_sugestao(_sugestoes_abertas(job)[0], sugestao_id)
        sugestoes.registrar(job.id, sugestao.id, sugestao.tipo, "recusada")
        return Response(status_code=204)

    @rotas.get("/{job_id}/correcoes")
    def historico_de_correcoes(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[ItemDoHistorico]:
        job = obter_concluido(job_id, autor)
        indexacao = job.indexacao
        return com_o_estado_na_busca(
            historico(_ler_correcoes(job.id)),
            indexacao.estado if indexacao else None,
            (indexacao.desde or indexacao.em) if indexacao else None,
        )

    @rotas.post("/{job_id}/correcoes/{correcao_id}/desfazer", status_code=201)
    def desfazer_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovoDesfazer,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            registro = desfazer(
                modelo,
                versao_atual,
                _ler_correcoes(job.id),
                correcao_id,
                corpo.motivo,
                job.id,
                _autoria(autor),
            )
            correcoes.acrescentar(registro)
        except CorrecaoInexistente:
            raise HTTPException(404, "Correção não encontrada") from None
        except (NaoDesfazivel, CorrecaoJaExiste):
            raise HTTPException(
                409,
                "Correção já desfeita, saiu da fila, não é uma renomeação"
                " ou não casa com a versão atual",
            ) from None
        _registrar_correcao(autor, job, registro)
        return {"id": registro.id}

    @rotas.post("/{job_id}/revisao/aprovar", status_code=202)
    def aprovar_revisao(
        job_id: str,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        """Fecha a revisão: dispara uma reindexação só, em segundo plano. As ações da
        revisão só gravam Correções; o índice e o BigQuery mudam aqui. O estado vai a
        `pendente` já, para a tela acompanhar até `indexado`; se o disparo falha, volta
        ao que era (503), para o `pendente` não ficar preso sem execução nenhuma."""
        job = obter_concluido(job_id, autor)
        anterior = job.indexacao
        if (
            repositorio.transitar(
                job.id,
                "concluido",
                {"indexacao": Indexacao(estado="pendente", em=relogio())},
            )
            is None
        ):
            raise HTTPException(409, "O vídeo saiu de concluído")
        try:
            disparo_da_indexacao.iniciar(job.id)
        except Exception:
            repositorio.transitar(job.id, "concluido", {"indexacao": anterior})
            raise
        return {"indexacao": "pendente"}

    @rotas.get("/{job_id}/fila")
    def fila_de_revisao(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[ItemDaFila]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        return fila(modelo, versao_atual, _ler_correcoes(job.id))

    def _tirar_da_fila(
        job_id: str,
        autor: Usuario,
        resolver: Callable[
            [dict[str, Any], str, list[Correcao], str, Autoria], Correcao
        ],
    ) -> dict[str, str]:
        """`resolver` é `reaplicar` ou `descartar` já com o pedido da rota; recebe
        o modelo, a versão, as Correções, o Job e a autoria."""
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            registro = resolver(
                modelo, versao_atual, _ler_correcoes(job.id), job.id, _autoria(autor)
            )
            correcoes.acrescentar(registro)
        except CorrecaoInexistente:
            raise HTTPException(404, "Correção não encontrada") from None
        except NaoCandidato:
            raise HTTPException(422, "O item não é candidato desta correção") from None
        except TemposInvalidos:
            raise HTTPException(422, "Tempos além da duração do vídeo") from None
        except (NaoNaFila, CorrecaoJaExiste):
            raise HTTPException(409, "A correção não está mais na fila") from None
        _registrar_correcao(autor, job, registro)
        return {"id": registro.id}

    @rotas.post("/{job_id}/fila/{correcao_id}/reaplicar", status_code=201)
    def reaplicar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaReaplicacao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        # Não espera o Curador: só reaponta uma correção que já valia (pendente
        # não vai para a fila), e a original sai da fila quando ela nasce.
        return _tirar_da_fila(
            job_id,
            autor,
            lambda modelo, versao, todas, job, autoria: reaplicar(
                modelo,
                versao,
                todas,
                correcao_id,
                corpo.item_id,
                corpo.motivo,
                job,
                autoria,
            ),
        )

    @rotas.post("/{job_id}/fila/{correcao_id}/descartar", status_code=201)
    def descartar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaResolucao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        return _tirar_da_fila(
            job_id,
            autor,
            lambda modelo, versao, todas, job, autoria: descartar(
                modelo, versao, todas, correcao_id, corpo.motivo, job, autoria
            ),
        )

    def _decidir(
        job_id: str,
        correcao_id: str,
        autor: Usuario,
        aprovada: bool,
        motivo: str = "",
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        try:
            registro = decidir(
                _ler_correcoes(job.id),
                correcao_id,
                aprovada,
                motivo,
                job.id,
                _autoria(autor),
            )
            correcoes.acrescentar(registro)
        except CorrecaoInexistente:
            raise HTTPException(404, "Correção não encontrada") from None
        except (NaoPendente, CorrecaoJaExiste):
            raise HTTPException(409, "A correção não está pendente") from None
        _registrar_correcao(autor, job, registro)
        return {"id": registro.id}

    @rotas.post("/{job_id}/correcoes/{correcao_id}/aprovar", status_code=201)
    def aprovar_correcao(
        job_id: str,
        correcao_id: str,
        autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> dict[str, str]:
        return _decidir(job_id, correcao_id, autor, True)

    @rotas.post("/{job_id}/correcoes/{correcao_id}/recusar", status_code=201)
    def recusar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaRecusa,
        autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> dict[str, str]:
        return _decidir(job_id, correcao_id, autor, False, corpo.motivo)

    return rotas
