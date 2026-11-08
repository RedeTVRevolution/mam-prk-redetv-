"""Jobs da E0: modelo, portas (Firestore e Storage) e rotas `/v1/jobs`."""

import hashlib
import itertools
import json
import logging
import re
import unicodedata
import uuid
import zlib
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import PurePath
from typing import Annotated, Any, Literal, Protocol, Self
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
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
from api.catalogo_apagado import (
    com_pessoas_fundidas,
    ids_do_catalogo,
    lido_em_lote,
    sem_catalogo_apagado,
)
from api.catalogo_dos_jobs import atualizar_catalogo_do_job
from api.ciclo_de_vida import (
    PRAZO_DO_REPROCESSAMENTO,
    JaTerminou,
    pedir_indexacao,
    transitar,
)
from api.ciclo_de_vida import cancelar as cancelar_job
from api.correcoes import (
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
    DocumentoDePapeis,
    Papel,
    Permissao,
    RepositorioDePapeis,
    papeis_do_usuario,
    permissoes_de,
)
from api.programas import RepositorioDeProgramas
from api.texto_como_dado import PADRAO_DA_LINHA, Linha, LinhaDaConsulta

TIPO_DO_VIDEO = "video/mp4"
TAMANHO_MAXIMO_PADRAO_BYTES = 4 * 1024**3
log = logging.getLogger(__name__)

# A URL que abre a sessão de upload (#369): curta, para não valer como credencial guardada.
# A sessão aberta continua valendo até o Job expirar (ou até 7 dias, o limite do Storage).
PRAZO_DA_URL_DE_UPLOAD = timedelta(minutes=15)
PRAZO_DO_JOB_SEM_UPLOAD = timedelta(hours=24)
VALIDADE_DA_REPRODUCAO = timedelta(minutes=10)
VALIDADE_DO_DOWNLOAD = timedelta(minutes=5)
# Capas e quadros (#408): um turno de trabalho, para a grade não pedir uma imagem já vencida.
VALIDADE_DA_IMAGEM = timedelta(hours=8)
# A URL do quadro se repete dentro da hora cheia (#409, `url_do_quadro`). A assinada no
# começo da janela vence antes, então o `expira_em` informado desconta a janela: nunca promete
# uma validade que a URL não tem.
JANELA_DA_URL_DO_QUADRO = timedelta(hours=1)
VALIDADE_INFORMADA_DA_IMAGEM = VALIDADE_DA_IMAGEM - JANELA_DA_URL_DO_QUADRO
# O "hoje" da data de exibição é o de Brasília, sem horário de verão desde 2019.
FUSO_DA_EMISSORA = timezone(timedelta(hours=-3))

# Teto de Jobs criados por hora (#371), contado no Firestore, então vale para todas as
# instâncias: uma chave vazada ou um sistema em laço não gasta GPU e Gemini sem limite.
# ponytail: o acervo em lote (#297) manda ~120 vídeos por dia, ~5 por hora de média; 200 por
# hora dá folga para ele despejar o dia inteiro de uma vez e ainda custa no máximo ~200
# vídeos por hora de um sistema com defeito. Pessoa envia à mão: 30 por hora é um vídeo a
# cada 2 minutos, mais que qualquer editor consegue subir.
TETO_POR_HORA_DO_SISTEMA = 200
TETO_POR_HORA_DA_PESSOA = 30
JANELA_DO_TETO = timedelta(hours=1)

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


# Teto de assinaturas de capa ao mesmo tempo na listagem do Acervo.
ASSINATURAS_SIMULTANEAS = 8


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
            dados["mes_exibicao"] = (
                data.isoformat()[:7] if isinstance(data, date) else data[:7]
            )
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


# Quantos ids a rota de andamento aceita por pedido.
LIMITE_DO_ANDAMENTO = 200


class JobResumido(BaseModel):
    """O que as listagens e o andamento mostram de um Job: sem `cortes_ms`, que só o
    detalhe traz (uma lista sem teto, de até ~100 KB por vídeo)."""

    id: str
    nome: str
    estado: Estado
    codigo_falha: CodigoDeFalha | None
    duracao_s: float | None
    timecode_origem: str | None = None
    taxa_de_quadros: float | None = None
    # URL assinada, de curta validade, do quadro de capa; a listagem e o detalhe a preenchem, o andamento não.
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
    reprocessavel_ate: datetime
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, job: Job) -> Self:
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
            reprocessavel_ate=job.criado_em + PRAZO_DO_REPROCESSAMENTO,
        )


class JobPublico(JobResumido):
    """O detalhe de um Job: o resumo mais os cortes de câmera."""

    # Cortes de câmera, em ms: os riscos da régua do Visualizador.
    cortes_ms: list[int] | None = None


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


class DownloadDoVideo(Reproducao):
    aviso: str = (
        "A cópia em alta resolução está no arquivo da RedeTV. "
        "Este download é a versão de 480p processada pelo MAM."
    )


ARQUIVO_DO_QUADRO = r"^[A-Za-z0-9][A-Za-z0-9_-]*\.jpg$"
# O id do Job no corpo do lote: sem "/", que o Firestore leria como caminho e derrubaria o lote.
ID_DO_JOB_NO_LOTE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
# Quadros por pedido em lote (#481): uma página da busca tem bem menos.
LIMITE_DE_QUADROS_EM_LOTE = 100


class ParDeQuadro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: Annotated[str, StringConstraints(pattern=ID_DO_JOB_NO_LOTE, max_length=128)]
    arquivo: Annotated[
        str, StringConstraints(pattern=ARQUIVO_DO_QUADRO, max_length=200)
    ]


class PedidoDeQuadros(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quadros: Annotated[list[ParDeQuadro], Field(max_length=LIMITE_DE_QUADROS_EM_LOTE)]


class QuadroDoLote(BaseModel):
    job: str
    arquivo: str
    url: str | None
    expira_em: datetime | None


class TipoNaoSuportado(Exception):
    """Corpo com tipo diferente de video/mp4: vira 415, antes de qualquer 422."""


class NovoJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, Linha(255, min_length=1)]
    tamanho_bytes: Annotated[int, Field(strict=True)]
    tipo: Literal["video/mp4"]
    programa: Annotated[str, Linha(100)] | None = (
        None  # o nome de um programa cadastrado
    )
    # Obrigatória (#365): a tabela de momentos é dividida por ela.
    data_exibicao: date

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
        if not (isinstance(valor, str) and len(valor) == 10):
            raise ValueError("data_exibicao deve ser texto AAAA-MM-DD")
        return valor


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
# Candidatos que um pedido paginado examina no Firestore antes de devolver a página que
# tiver, com o cursor (pode vir vazia); só vale com `limite`.
TETO_DE_CANDIDATOS = 2000


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
    pessoa_do_catalogo: str | None = None  # só os vídeos em que a pessoa aparece
    marca_do_catalogo: str | None = None  # só os vídeos em que a marca aparece
    ordem: Ordem = "enviado"
    limite: int | None = None  # `None`: a lista inteira, sem cursor e sem teto
    cursor: str | None = None  # id do último Job examinado na página anterior
    # Só a lista do acervo: lê os campos do `JobResumido` (e os que o filtro confere), não o
    # Job inteiro. O Job vem incompleto, então quem o regrava não pode pedir isto (#480).
    so_os_da_lista: bool = False


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

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        """Os Jobs que existem entre `job_ids`, numa leitura em lote, em qualquer ordem."""
        ...

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

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
        """Quantos Jobs `criado_por` criou de `desde` em diante (lixeira inclusive)."""
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
        """URL assinada de leitura do proxy 480p, que o navegador baixa como `nome`."""
        ...

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        """URL assinada de leitura do JPEG de `caminho` (o campo `quadro` da Decupagem)."""
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

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        return [self._jobs[i] for i in dict.fromkeys(job_ids) if i in self._jobs]

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
        return paginar_em_python(
            (j for j in self._jobs.values() if casa_com_o_filtro(j, filtro)),
            filtro,
            self._jobs.get,
        )

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
        return sum(
            1
            for j in self._jobs.values()
            if j.criado_por == criado_por and j.criado_em >= desde
        )


class RepositorioIndisponivel:
    def salvar(self, job: Job) -> None:
        raise ServicoIndisponivel

    def criar(self, job: Job) -> bool:
        raise ServicoIndisponivel

    def obter(self, job_id: str) -> Job | None:
        raise ServicoIndisponivel

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
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

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
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

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        raise ServicoIndisponivel


def expirar_uploads(
    repositorio: RepositorioDeJobs, armazenamento: Armazenamento, agora: datetime
) -> list[str]:
    """Falha os Jobs sem upload completo há 24 h ou mais e cancela a sessão de upload."""
    expirados: list[str] = []
    for job in repositorio.listar():
        if (
            job.estado != "aguardando_upload"
            or agora - job.criado_em < PRAZO_DO_JOB_SEM_UPLOAD
        ):
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
            expirados.append(job.id)
            try:
                armazenamento.cancelar_upload(job.id)
            except Exception:
                # Não segura os outros Jobs: o ciclo de vida da quarentena apaga o objeto.
                log.exception("não consegui apagar o upload do Job %s", job.id)
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
    guardado: DocumentoDePapeis | None = getattr(
        request.state, "papeis_guardados", None
    )
    if guardado is not None and guardado.uid == pessoa.uid:
        # Lido pelo middleware neste pedido; só vale para quem pediu.
        guardados = guardado.papeis
    else:
        papeis: RepositorioDePapeis = request.app.state.papeis
        guardados = papeis.obter(pessoa.uid)
    return papeis_do_usuario(
        guardados,
        pessoa.email,
        pessoa.email_verificado,
        request.app.state.admins,
    )


def _tem_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> bool:
    return permissao in permissoes_de(papeis_da_pessoa(request, pessoa))


def _enxerga(chamador: Chamador, job: Job | None) -> Job:
    """O job, ou 404 se não existe ou é de outro sistema (ou de uma pessoa), para uma chave."""
    if job is None or _de_outro_sistema(chamador, job):
        raise HTTPException(404, "Job não encontrado")
    return job


def _de_outro_sistema(chamador: Chamador, job: Job) -> bool:
    """Se a chave de sistema não enxerga o Job (é de outro sistema ou de uma pessoa)."""
    return isinstance(chamador, Sistema) and job.sistema != chamador.sistema


def criar_rotas(
    repositorio: RepositorioDeJobs,
    armazenamento: Armazenamento,
    tamanho_maximo_bytes: int,
    relogio: Callable[[], datetime],
    correcoes: RepositorioDeCorrecoes,
    aprovacao: RepositorioDeAprovacao,
    catalogo: Catalogo,
    marcas: CatalogoDeMarcas,
    programas: RepositorioDeProgramas,
    disparo_da_indexacao: DisparoDaIndexacao,
    acessos: AcessosAoVideo,
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
        idempotency_key: Annotated[
            str | None, Header(max_length=200, pattern=PADRAO_DA_LINHA)
        ] = None,
    ) -> JobCriado:
        if not 0 < novo.tamanho_bytes <= tamanho_maximo_bytes:
            raise HTTPException(422, "Tamanho fora do limite")
        if novo.programa is not None:
            validos = sorted(p.nome for p in programas.listar())
            if novo.programa not in validos:
                raise HTTPException(
                    422,
                    "programa sem perfil; programas válidos: " + ", ".join(validos),
                )
        if isinstance(chamador, Sistema):
            criado_por, sistema = f"sistema:{chamador.sistema}", chamador.sistema
            email = None
        else:
            criado_por, sistema, email = chamador.uid, None, chamador.email or None
        agora = relogio()
        if novo.data_exibicao > agora.astimezone(FUSO_DA_EMISSORA).date():
            raise HTTPException(422, "Data de exibição no futuro")
        job_id, nova, escopo, job_gravado = uuid.uuid4().hex, True, "", False
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
            job_id, job_gravado = reserva.job_id, reserva.job_gravado
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
        # Repetição de Job apagado: na lixeira, ou purgado (reserva marcada sem Job).
        if (existente is not None and existente.lixeira is not None) or (
            existente is None and job_gravado
        ):
            raise HTTPException(410, "Este Job foi apagado")
        # O teto só barra Job novo: a repetição de um Job que já existe devolve o mesmo
        # Job, e a reserva feita aqui deixa a repetição depois da espera criá-lo.
        if existente is None:
            teto = (
                TETO_POR_HORA_DO_SISTEMA
                if sistema is not None
                else TETO_POR_HORA_DA_PESSOA
            )
            if repositorio.contar_criados(criado_por, agora - JANELA_DO_TETO) >= teto:
                # 3600 s é o limite de cima: a vaga abre quando o Job mais antigo da
                # janela sai dela, o que pode ser antes.
                raise HTTPException(
                    429,
                    f"Teto de {teto} Jobs por hora atingido",
                    headers={"Retry-After": str(int(JANELA_DO_TETO.total_seconds()))},
                )
        criou = existente is None and repositorio.criar(job)
        if existente is not None:
            job = existente
        elif not criou:
            job = repositorio.obter(job.id) or job
        # Marca antes de registrar o evento: uma falha no registro não deixa o Job sem marca.
        if idempotency_key is not None and not job_gravado:
            chaves_de_idempotencia.marcar_job_gravado(escopo, idempotency_key)
        if criou:
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

    def _url_da_capa(job: Job) -> str | None:
        if job.capa is None:
            return None
        return armazenamento.url_do_quadro(job.id, job.capa, VALIDADE_DA_IMAGEM)

    def _com_capa(job: Job) -> JobResumido:
        publico = JobResumido.de(job)
        publico.capa_url = _url_da_capa(job)
        return publico

    def _sem_capa(job: Job) -> dict[str, Any]:
        return JobResumido.de(job).model_dump(mode="json", exclude={"capa_url"})

    @rotas.get("", response_model=list[JobResumido])
    def listar(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        programa: Annotated[str | None, LinhaDaConsulta(100)] = None,
        estado: Annotated[list[Estado] | None, Query()] = None,
        exibicao_de: date | None = None,
        exibicao_ate: date | None = None,
        q: Annotated[str | None, LinhaDaConsulta(300)] = None,
        sistema: Annotated[str | None, LinhaDaConsulta(100)] = None,
        ordem: Ordem = "enviado",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_MAXIMO)] = None,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
        capa: bool = True,
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
            so_os_da_lista=True,
        )
        try:
            pagina = repositorio.consultar(filtro)
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        if capa:
            # As capas são assinadas em paralelo, com teto de chamadas simultâneas.
            with ThreadPoolExecutor(ASSINATURAS_SIMULTANEAS) as assinando:
                publicos = list(assinando.map(_com_capa, pagina.jobs))
            corpo = [p.model_dump(mode="json") for p in publicos]
        else:
            # Quem só conta (o aviso "Finalizando" da busca) não paga as assinaturas.
            corpo = [_sem_capa(j) for j in pagina.jobs]
        cabecalhos = (
            {"X-Proximo-Cursor": pagina.proximo_cursor} if pagina.proximo_cursor else {}
        )
        return JSONResponse(corpo, headers=cabecalhos)

    @rotas.get("/andamento", response_model=list[JobResumido])
    def andamento(
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        ids: Annotated[
            str,
            LinhaDaConsulta(
                8000,
                description=f"Até {LIMITE_DO_ANDAMENTO} ids, separados por vírgula",
            ),
        ],
    ) -> Response:
        """O estado de vários Jobs numa leitura só, para a tela atualizar o que está em
        andamento: o detalhe sem capa e sem `cortes_ms`. Quem não existe ou não se
        enxerga é omitido."""
        pedidos = [i for i in (p.strip() for p in ids.split(",")) if i]
        if len(pedidos) > LIMITE_DO_ANDAMENTO:
            raise HTTPException(422, f"No máximo {LIMITE_DO_ANDAMENTO} ids")
        posicao = {id_: n for n, id_ in enumerate(dict.fromkeys(pedidos))}
        jobs = repositorio.obter_varios(posicao)
        pode_ver_lixeira = isinstance(chamador, Usuario) and _tem_permissao(
            request, chamador, "lixeira.gerir"
        )
        visiveis = [
            j
            for j in jobs
            if (j.lixeira is None or pode_ver_lixeira)
            and not _de_outro_sistema(chamador, j)
        ]
        visiveis.sort(key=lambda j: posicao[j.id])
        corpo = [_sem_capa(j) for j in visiveis]
        return JSONResponse(corpo)

    @rotas.get("/{job_id}", response_model=JobPublico)
    def ler(
        job_id: str,
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Response:
        job = _enxerga(chamador, repositorio.obter(job_id))
        publico = JobPublico.de(job)
        publico.capa_url = _url_da_capa(job)
        etag = _etag(publico)
        cabecalhos = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if _casa_etag(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=cabecalhos)
        return JSONResponse(publico.model_dump(mode="json"), headers=cabecalhos)

    def obter_concluido(job_id: str, chamador: Chamador) -> Job:
        return _concluido(chamador, repositorio.obter(job_id))

    def _concluido(chamador: Chamador, lido: Job | None) -> Job:
        job = _enxerga(chamador, lido)
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
    ) -> DownloadDoVideo:
        job = obter_concluido(job_id, chamador)
        nome = f"{PurePath(job.nome).stem}.480p.mp4"
        url = armazenamento.url_de_download(job.id, nome, VALIDADE_DO_DOWNLOAD)
        # O registro vem antes da resposta: sem ele a URL não sai (503).
        acessos.baixou(chamador, job, "video.baixado")
        return DownloadDoVideo(url=url, expira_em=relogio() + VALIDADE_DO_DOWNLOAD)

    @rotas.post("/quadros")
    def quadros_em_lote(
        pedido: PedidoDeQuadros,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> list[QuadroDoLote]:
        """As URLs assinadas dos quadros de uma página da busca, numa chamada só: cada Job
        é lido uma vez e o papel, uma vez. O par de Job que não existe, não se enxerga, está
        na lixeira ou não concluiu volta sem URL, sem derrubar o lote."""
        jobs = {
            j.id: j
            for j in repositorio.obter_varios(
                dict.fromkeys(p.job for p in pedido.quadros)
            )
        }
        expira_em = relogio() + VALIDADE_INFORMADA_DA_IMAGEM
        resposta: list[QuadroDoLote] = []
        for par in pedido.quadros:
            job = jobs.get(par.job)
            visivel = (
                job is not None
                and job.estado == "concluido"
                and job.lixeira is None
                and not _de_outro_sistema(chamador, job)
            )
            url = (
                armazenamento.url_do_quadro(
                    par.job, caminho_do_quadro(par.arquivo), VALIDADE_DA_IMAGEM
                )
                if visivel
                else None
            )
            resposta.append(
                QuadroDoLote(
                    job=par.job,
                    arquivo=par.arquivo,
                    url=url,
                    expira_em=expira_em if url else None,
                )
            )
        return resposta

    @rotas.get("/{job_id}/quadros/{arquivo}")
    def quadro(
        job_id: str,
        arquivo: Annotated[str, Path(pattern=ARQUIVO_DO_QUADRO)],
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Reproducao:
        # O Job que a dependência da lixeira já leu neste pedido (None se não existe).
        if hasattr(request.state, "job_lido"):
            job = _concluido(chamador, request.state.job_lido)
        else:
            job = obter_concluido(job_id, chamador)
        url = armazenamento.url_do_quadro(
            job.id, caminho_do_quadro(arquivo), VALIDADE_DA_IMAGEM
        )
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_INFORMADA_DA_IMAGEM)

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
        # Pessoas e marcas distintas da Decupagem, numa leitura em lote cada.
        pessoa = lido_em_lote(
            ids_do_catalogo(entregue, "pessoas"), catalogo.obter_varios, catalogo.obter
        )
        marca = lido_em_lote(
            ids_do_catalogo(entregue, "comerciais"), marcas.obter_varios, marcas.obter
        )
        entregue = com_pessoas_fundidas(entregue, pessoa)
        entregue = sem_catalogo_apagado(
            entregue,
            lambda id: (p := pessoa(id)) is not None and p.lixeira is None,
            lambda id: (m := marca(id)) is not None and m.lixeira is None,
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
        _atualizar_catalogo_do_job(job)
        return {"id": correcao.id, "versao_decupagem": versao_atual}

    def _atualizar_catalogo_do_job(job: Job) -> None:
        """Regrava no Job quem aparece na Decupagem entregue; nunca levanta (#359)."""
        atualizar_catalogo_do_job(
            job, repositorio, armazenamento, correcoes, catalogo.obter
        )

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
        _atualizar_catalogo_do_job(job)
        return {"id": registro.id}

    @rotas.post("/{job_id}/revisao/aprovar", status_code=202)
    def aprovar_revisao(
        job_id: str,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        """Fecha a revisão: pede a indexação e a dispara em segundo plano. As ações da
        revisão só gravam Correções; o índice e o BigQuery mudam aqui. O estado vai a
        `pendente` já, para a tela acompanhar até `indexado`; se o disparo falha, a
        `indexacao` volta ao que era (503), para o `pendente` não ficar preso sem execução
        nenhuma. A `versao_pedida` fica: o próximo disparo (ou uma rodada em curso) a atende."""
        job = obter_concluido(job_id, autor)
        anterior = job.indexacao
        if pedir_indexacao(repositorio, job.id, relogio()) is None:
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
        _atualizar_catalogo_do_job(job)
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
        _atualizar_catalogo_do_job(job)
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
