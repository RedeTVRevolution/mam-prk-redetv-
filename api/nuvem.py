"""Adaptadores de nuvem da E0: Firestore (Jobs) e Cloud Storage (upload)."""

import functools
import json
import logging
import random
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import google.auth
import google.auth.transport.requests
import requests
from google.api_core.exceptions import Aborted, AlreadyExists, NotFound
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.storage import Client as ClienteStorage

from api.auditoria import (
    FiltroDeAuditoria,
    PaginaDeAuditoria,
    RegistroDeAuditoria,
    campo_da_pessoa,
)
from api.auditoria import (
    casa_com_o_filtro as casa_com_o_filtro_da_auditoria,
)
from api.auditoria import (
    pagina_de as pagina_da_auditoria,
)
from api.catalogo import (
    EnvioParaLixeira,
    FusaoDaPessoa,
    PessoaDoCatalogo,
    PessoaInexistente,
    RenomeacaoDaPessoa,
    Rosto,
    corrigida,
    nomes_de_busca,
    novo_id,
    visivel,
)
from api.chaves import LimiteDeChavesAtivas, RegistroDeChave
from api.clientes_de_nuvem import ESCOPO_DA_NUVEM, sessao_autenticada
from api.comparador import normalizar
from api.correcoes import CORRIGIVEIS, Correcao, CorrecaoJaExiste, em_ordem
from api.decupagem import Decupagem
from api.florence import ObjetosDaDecupagem
from api.idempotencia import (
    Reserva,
    conferir,
    id_da_reserva,
    nova_reserva,
)
from api.itens_da_decupagem import contar_itens, objeto_dos_itens
from api.jobs import (
    JANELA_DA_URL_DO_QUADRO,
    PRAZO_DA_URL_DE_UPLOAD,
    TETO_DE_CANDIDATOS,
    CursorInvalido,
    Estado,
    FiltroDeJobs,
    Job,
    NomeDaEtapa,
    PaginaDeJobs,
    RepositorioDeJobs,
    ServicoIndisponivel,
    casa_com_o_filtro,
    disposicao_do_nome,
    paginar_em_python,
)
from api.leitura_da_tela import LeituraDaTela
from api.lixeira import ArquivosContados
from api.marcas import MarcaDoCatalogo, MarcaInexistente, nomes_de_busca_da_marca
from api.papeis import PAPEIS, DocumentoDePapeis, Papel
from api.programas import (
    NomeEmUso,
    Programa,
    ProgramaInexistente,
    TrocaSubstituida,
    troca_vale,
)
from api.progresso_das_janelas import JanelaGravada, ler_janela_gravada
from api.revisao import Medida, Pulso
from api.revisao import aplicar as aplicar_o_pulso
from api.texto_como_dado import id_conferido, tem_controle
from api.tipos_de_objeto import LIMITE_PADRAO, TipoDeObjeto, somar_por_chave
from api.transcricao import Transcricao
from api.usuarios import ContaDoIdentityPlatform, EmailJaCadastrado
from api.webhook import RegistroDeWebhook

COLECAO_DE_JOBS = "jobs"
# O que a lista do acervo lê do Job: os campos do `JobResumido` (menos `enviado_por`, que vem
# de `sistema` e `criado_por_email`), os obrigatórios do `Job` e os que `casa_com_o_filtro`
# confere (#480). Fica de fora o que pesa: `cortes_ms`, os catálogos e o `sha256`.
_CAMPOS_DA_LISTA = frozenset(
    {
        "id", "nome", "tamanho_bytes", "estado", "criado_por", "criado_em", "atualizado_em",
        "codigo_falha", "duracao_s", "timecode_origem", "taxa_de_quadros", "capa", "programa",
        "data_exibicao", "indexacao", "copia_bigquery", "etapa_atual", "etapas",
        "reprocessamentos", "inicio_da_passada", "criado_por_email", "sistema", "palavras", "lixeira",
    }
)  # fmt: skip
# Candidatos mínimos por leitura quando a página já está cheia e falta achar o próximo aprovado.
LOTE_MINIMO_DE_CANDIDATOS = 25
COLECAO_DE_CHAVES = "chaves_de_api"
COLECAO_DE_WEBHOOKS = "webhooks"
COLECAO_DE_IDEMPOTENCIA = "chaves_de_idempotencia"
COLECAO_DAS_LISTAS_DA_BUSCA = "listas_da_busca"
COLECAO_DE_PAPEIS = "papeis_de_usuarios"
COLECAO_DE_CORRECOES = "correcoes"
COLECAO_DO_CATALOGO = "catalogo_de_pessoas"
COLECAO_DO_CATALOGO_DE_MARCAS = "catalogo_de_marcas"
COLECAO_DOS_PROGRAMAS = "programas"
COLECAO_DE_CONFIGURACAO = "configuracao"
COLECAO_DA_AUDITORIA = "auditoria"
COLECAO_DA_REVISAO = "tempo_de_revisao"
COLECAO_DOS_TIPOS_DE_OBJETO = "tipos_de_objeto"
COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB = "tipos_de_objeto_por_job"
DOCUMENTO_DA_APROVACAO = "aprovacao"
TAMANHO_DO_PEDACO = 256 * 1024
_LOTE_DE_LEITURA = 500

log = logging.getLogger(__name__)


def _documento(colecao: Any, id: str) -> Any:
    """O documento `id` da coleção; o id não sai do próprio nível (`ValueError`)."""
    return colecao.document(id_conferido(id))


def _lidos_em_lote(cliente: Any, colecao: Any, ids: Iterable[str]) -> Iterator[Any]:
    """Os documentos que existem entre os `ids` (sem repetir), lidos em lotes de
    `_LOTE_DE_LEITURA` com `get_all`."""
    referencias = [_documento(colecao, i) for i in dict.fromkeys(ids)]
    for inicio in range(0, len(referencias), _LOTE_DE_LEITURA):
        lote = referencias[inicio : inicio + _LOTE_DE_LEITURA]
        yield from (d for d in cliente.get_all(lote) if d.exists)


def objeto_do_proxy(job_id: str) -> str:
    return f"{id_conferido(job_id)}/proxy.mp4"


def objeto_do_audio(job_id: str) -> str:
    return f"{id_conferido(job_id)}/audio.wav"


def objeto_da_transcricao(job_id: str) -> str:
    return f"{id_conferido(job_id)}/transcricao.json"


def prefixo_das_janelas(job_id: str) -> str:
    return f"{id_conferido(job_id)}/janelas/"


def objeto_da_janela(job_id: str, indice: int) -> str:
    return f"{prefixo_das_janelas(job_id)}{indice:04d}.json"


def objeto_da_leitura_da_tela(job_id: str) -> str:
    return f"{id_conferido(job_id)}/leitura_da_tela.json"


def objeto_do_resultado_dos_objetos(job_id: str) -> str:
    return f"{id_conferido(job_id)}/objetos/florence.json"


def objeto_da_decupagem(job_id: str) -> str:
    return f"{id_conferido(job_id)}.json"


def objeto_do_quadro(job_id: str, caminho: str) -> str:
    """`caminho` é o do campo `quadro` da Decupagem (`quadros/plano-0.jpg`)."""
    if (
        not caminho
        or ".." in caminho
        or caminho.startswith("/")
        or "\\" in caminho
        or tem_controle(caminho)
    ):
        raise ValueError("caminho de quadro inválido")
    return f"{id_conferido(job_id)}/{caminho}"


def objeto_da_copia_limpa(job_id: str) -> str:
    return f"{id_conferido(job_id)}/copia_limpa.mp4"


TENTATIVAS_SOB_DISPUTA = 8
# A espera dobra a cada rodada até o teto (0,05 s, 0,1, 0,2, 0,4, 0,8, 1, 1, 1): no pior
# caso, cerca de 4,5 s antes do 503. Com espera que cresce devagar, os perdedores
# voltam juntos e disputam de novo (#384).
ESPERA_BASE_SOB_DISPUTA = 0.05
TETO_DA_ESPERA_SOB_DISPUTA = 1.0


def espera_sob_disputa(rodada: int) -> float:
    """Espera aleatória (jitter) de 0 até a base dobrada a cada rodada, com teto."""
    limite = min(TETO_DA_ESPERA_SOB_DISPUTA, ESPERA_BASE_SOB_DISPUTA * 2**rodada)
    return random.uniform(0, limite)


def _repetir_sob_disputa[T](
    na_transacao: Callable[[Any], T], cliente: firestore.Client
) -> T:
    # Com muitas chamadas no mesmo documento, o Firestore esgota as tentativas da
    # transação (ValueError causado por Aborted). Quem perde começa de novo, depois de
    # uma espera aleatória, e lê o estado que o vencedor deixou. Outro ValueError (um
    # Job que não passa no modelo, por exemplo) não é disputa e sobe na hora.
    for rodada in range(TENTATIVAS_SOB_DISPUTA):
        try:
            return na_transacao(cliente.transaction())
        except (ValueError, Aborted) as erro:
            if isinstance(erro, ValueError) and not isinstance(erro.__cause__, Aborted):
                raise
            time.sleep(espera_sob_disputa(rodada))
    raise ServicoIndisponivel("Firestore disputado: tente de novo")


# Limites do Firestore depois de expandir a consulta em forma normal disjuntiva:
# disjunções (o produto dos `in`) e componentes (filtros e ordenações de todas elas).
MAXIMO_DE_DISJUNCOES = 30
MAXIMO_DE_COMPONENTES = 100


def meses_do_periodo(de: date, ate: date) -> list[str]:
    """Os meses (`AAAA-MM`) que o período toca, do primeiro ao último."""
    meses, ano, mes = [], de.year, de.month
    while (ano, mes) <= (ate.year, ate.month):
        meses.append(f"{ano:04d}-{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def _cabe_no_firestore(
    filtro: FiltroDeJobs, meses: int, programas: int, datas: int = 0
) -> bool:
    """Se a consulta com `meses`, `programas` (0 = fora da consulta) e `datas` (as pontas
    do período na ordem por exibição) cabe nos tetos do Firestore."""
    disjuncoes = max(1, meses) * max(1, len(filtro.estados)) * max(1, programas)
    filtros = (
        (filtro.programa is not None or programas > 0)
        + (filtro.sistema is not None)
        + bool(filtro.estados)
        + bool(filtro.palavras)
        + bool(meses)
        + datas
    )
    # Mais a ordem pelo campo e o desempate implícito pelo id: contar os dois deixa folga, e
    # errar para menos faria o Firestore recusar a lista.
    componentes = disjuncoes * (filtros + 2)
    return disjuncoes <= MAXIMO_DE_DISJUNCOES and componentes <= MAXIMO_DE_COMPONENTES


def plano_da_consulta(
    filtro: FiltroDeJobs, por_mes: bool
) -> tuple[list[str] | None, list[str]]:
    """Os meses (`mes_exibicao in`, só na ordem por envio com `por_mes`) e os programas
    (`programa in`) que vão ao Firestore; o que não cabe nos tetos fica em
    `casa_com_o_filtro`. Sai primeiro o mês, depois os programas."""
    programas = sorted(filtro.programas) if len(filtro.programas) > 1 else []
    meses = None
    if (
        por_mes
        and filtro.ordem == "enviado"
        and filtro.exibicao_de is not None
        and filtro.exibicao_ate is not None
    ):
        meses = meses_do_periodo(filtro.exibicao_de, filtro.exibicao_ate)
        if _cabe_no_firestore(filtro, len(meses), len(programas)):
            return meses, programas
        meses = None
    datas = (
        (filtro.exibicao_de is not None) + (filtro.exibicao_ate is not None)
        if filtro.ordem == "exibicao"
        else 0
    )
    if programas and not _cabe_no_firestore(filtro, 0, len(programas), datas):
        programas = []
    return meses, programas


def meses_para_o_firestore(filtro: FiltroDeJobs) -> list[str] | None:
    """Os meses do período, se a consulta com `mes_exibicao in [...]` cabe nos limites do
    Firestore; `None` se faltar uma ponta do período ou algum limite estourar (a lista cai
    então no filtro de datas em Python)."""
    return plano_da_consulta(filtro, True)[0]


def listagem_por_mes_do_ambiente(ambiente: Mapping[str, str]) -> bool:
    """`LISTAGEM_POR_MES`: ausente ou vazia, desligada; outro valor que não `true` ou
    `false` levanta `ValueError`, em vez de deixar a lista no caminho de hoje sem aviso."""
    valor = (ambiente.get("LISTAGEM_POR_MES") or "false").strip().lower()
    if valor not in ("true", "false"):
        raise ValueError(f"LISTAGEM_POR_MES inválida: {valor!r}")
    return valor == "true"


class RepositorioFirestore:
    def __init__(
        self,
        cliente: firestore.Client,
        colecao: str = COLECAO_DE_JOBS,
        listagem_por_mes: bool = False,
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)
        # Só depois de `make gravar-mes-nos-jobs`: Job sem `mes_exibicao` some do filtro.
        self._listagem_por_mes = listagem_por_mes

    def salvar(self, job: Job) -> None:
        _documento(self._colecao, job.id).set(job.model_dump())

    def criar(self, job: Job) -> bool:
        # `Aborted` não diz que outro gravou: o documento estava travado e o `create`
        # pode ter perdido para outro que também aborta. Repete até um gravar
        # (`AlreadyExists` para os outros).
        for rodada in range(TENTATIVAS_SOB_DISPUTA):
            try:
                _documento(self._colecao, job.id).create(job.model_dump())
            except AlreadyExists:
                return False
            except Aborted:
                time.sleep(espera_sob_disputa(rodada))
                continue
            return True
        raise ServicoIndisponivel("Firestore disputado: tente de novo")

    def _sob_disputa(self, na_transacao: Callable[[Any], Job | None]) -> Job | None:
        return _repetir_sob_disputa(na_transacao, self._cliente)

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        # Lê, confere a origem e grava na mesma transação: um cancelamento que
        # chegue no meio faz o Firestore repetir a transação, que então vê o novo estado.
        referencia = _documento(self._colecao, job_id)

        @firestore.transactional
        def trocar(transacao: Any) -> Job | None:
            doc = referencia.get(transaction=transacao)
            if not doc.exists:
                return None
            job = Job(**(doc.to_dict() or {}))
            if job.estado != de:
                return None
            novo = job.model_copy(update=mudancas)
            transacao.set(referencia, novo.model_dump())
            return novo

        return self._sob_disputa(trocar)

    def acrescentar_ano_da_copia(self, job_id: str, ano: int) -> None:
        _documento(self._colecao, job_id).update(
            {"copia_bigquery.anos": firestore.ArrayUnion([ano])}
        )

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        # Como `transitar`, mas quem decide é `mudar`, que o Firestore pode repetir.
        referencia = _documento(self._colecao, job_id)

        @firestore.transactional
        def trocar_na_transacao(transacao: Any) -> Job | None:
            doc = referencia.get(transaction=transacao)
            if not doc.exists:
                return None
            job = Job(**(doc.to_dict() or {}))
            mudancas = mudar(job)
            if mudancas is None:
                return None
            novo = job.model_copy(update=mudancas)
            transacao.set(referencia, novo.model_dump())
            return novo

        return self._sob_disputa(trocar_na_transacao)

    def remover(self, job_id: str) -> None:
        _documento(self._colecao, job_id).delete()

    def obter(self, job_id: str) -> Job | None:
        doc = _documento(self._colecao, job_id).get()
        return Job(**(doc.to_dict() or {})) if doc.exists else None

    def obter_fila_gpu(self) -> dict[str, Any]:
        doc = self._cliente.collection("fila_gpu").document("vagas").get()
        return doc.to_dict() or {}

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        # Em lotes: sem período, a taxa pede todos os vídeos revisados do acervo, e
        # um pedido só com dezenas de milhares de referências arrisca o prazo.
        return [
            Job(**(doc.to_dict() or {}))
            for doc in _lidos_em_lote(self._cliente, self._colecao, job_ids)
        ]

    def listar(self) -> list[Job]:
        docs = self._colecao.order_by(
            "criado_em", direction=firestore.Query.DESCENDING
        ).stream()
        return [Job(**(doc.to_dict() or {})) for doc in docs]

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
        # Índice composto `criado_por` + `criado_em` em infra/modulos/mam/teto_de_criacao.tf (#371).
        consulta: Any = self._colecao.where(
            filter=FieldFilter("criado_por", "==", criado_por)
        ).where(filter=FieldFilter("criado_em", ">=", desde))
        return int(consulta.count().get()[0][0].value)

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        # O Firestore corta o que dá com um índice composto (igualdades, `in`, uma
        # palavra do nome e, na ordem por exibição, o intervalo de datas, que só pode
        # estar no campo da ordem; na ordem por envio, com `listagem_por_mes`, os meses do
        # período em `mes_exibicao`). O resto, e a conferência de tudo, é de `casa_com_o_filtro`.
        # Os índices estão no infra/modulos/mam/main.tf e no listagem_por_mes.tf.
        if filtro.sha256 is not None:
            return self._consultar_pelo_arquivo(filtro)
        if (
            filtro.pessoa_do_catalogo is not None
            or filtro.marca_do_catalogo is not None
        ):
            return self._consultar_pelo_catalogo(filtro)
        if filtro.na_lixeira is True:
            return self._consultar_a_lixeira(filtro)
        consulta: Any = self._colecao
        meses, programas = plano_da_consulta(filtro, self._listagem_por_mes)
        if programas:
            consulta = consulta.where(filter=FieldFilter("programa", "in", programas))
        elif len(filtro.programas) == 1:
            (unico,) = filtro.programas
            consulta = consulta.where(filter=FieldFilter("programa", "==", unico))
        elif filtro.programa is not None:
            consulta = consulta.where(
                filter=FieldFilter("programa", "==", filtro.programa)
            )
        if filtro.sistema is not None:
            consulta = consulta.where(
                filter=FieldFilter("sistema", "==", filtro.sistema)
            )
        if filtro.estados:
            consulta = consulta.where(
                filter=FieldFilter("estado", "in", sorted(filtro.estados))
            )
        if filtro.palavras:
            consulta = consulta.where(
                filter=FieldFilter("palavras", "array_contains", filtro.palavras[0])
            )
        campo = "criado_em" if filtro.ordem == "enviado" else "data_exibicao"
        if filtro.ordem == "exibicao":
            if filtro.exibicao_de is not None:
                consulta = consulta.where(
                    filter=FieldFilter(campo, ">=", filtro.exibicao_de.isoformat())
                )
            if filtro.exibicao_ate is not None:
                consulta = consulta.where(
                    filter=FieldFilter(campo, "<=", filtro.exibicao_ate.isoformat())
                )
        elif meses:
            # Igualdade aceita a ordem por `criado_em`; o dia exato fica em `casa_com_o_filtro`.
            consulta = consulta.where(filter=FieldFilter("mes_exibicao", "in", meses))
        return self._ordenar_e_ler(consulta, campo, filtro)

    def _consultar_a_lixeira(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        # A ordem é a do envio à lixeira: o Firestore só devolve documentos que têm o
        # campo da ordem, e fora da lixeira `lixeira` é `null`. Os outros filtros ficam
        # em `casa_com_o_filtro`, para não pedir índice composto com `lixeira.em`.
        return self._ordenar_e_ler(self._colecao, "lixeira.em", filtro)

    def _ordenar_e_ler(
        self, consulta: Any, campo: str, filtro: FiltroDeJobs
    ) -> PaginaDeJobs:
        # O desempate implícito é o id do documento, na mesma direção da ordem.
        consulta = consulta.order_by(campo, direction=firestore.Query.DESCENDING)
        if filtro.cursor is not None:
            ancora = _documento(self._colecao, filtro.cursor).get()
            if not ancora.exists:
                raise CursorInvalido
            consulta = consulta.start_after(ancora)
        if filtro.so_os_da_lista:
            consulta = consulta.select(sorted(_CAMPOS_DA_LISTA | {campo.split(".")[0]}))
        if filtro.limite is None:
            # Lista inteira: o consumidor interno não segue cursor, então não há teto.
            jobs = (Job(**(doc.to_dict() or {})) for doc in consulta.stream())
            return PaginaDeJobs([j for j in jobs if casa_com_o_filtro(j, filtro)])
        return self._ler_em_lotes(consulta, filtro, filtro.limite)

    @staticmethod
    def _ler_em_lotes(consulta: Any, filtro: FiltroDeJobs, limite: int) -> PaginaDeJobs:
        # Lotes com `.limit()` até haver um aprovado além da página (a prova de que há mais).
        # O cursor é o último candidato examinado que fica na página, aprovado ou não: o
        # próximo pedido recomeça logo depois dele, sem pular nem repetir. No teto, devolve
        # o que tem (talvez nada) e o cursor do último examinado.
        aprovados: list[Job] = []
        examinados = 0
        ultimo_id: str | None = None
        ultimo_doc: Any = None
        while examinados < TETO_DE_CANDIDATOS:
            pedir = min(
                max(limite + 1 - len(aprovados), LOTE_MINIMO_DE_CANDIDATOS),
                TETO_DE_CANDIDATOS - examinados,
            )
            corrente = (
                consulta if ultimo_doc is None else consulta.start_after(ultimo_doc)
            )
            docs = list(corrente.limit(pedir).stream())
            for doc in docs:
                job = Job(**(doc.to_dict() or {}))
                if casa_com_o_filtro(job, filtro):
                    if len(aprovados) == limite:
                        return PaginaDeJobs(aprovados, ultimo_id)
                    aprovados.append(job)
                ultimo_id, ultimo_doc = job.id, doc
                examinados += 1
            if len(docs) < pedir:
                return PaginaDeJobs(aprovados)
        return PaginaDeJobs(aprovados, ultimo_id)

    def _consultar_pelo_catalogo(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        # Só um `array_contains` (índice automático) vai ao Firestore: lê os vídeos da
        # pessoa ou da marca, não o acervo. O resto do filtro, a ordem e o cursor ficam
        # em Python, sem índice composto.
        if filtro.pessoa_do_catalogo is not None:
            consulta = self._colecao.where(
                filter=FieldFilter(
                    "pessoas_do_catalogo", "array_contains", filtro.pessoa_do_catalogo
                )
            )
        else:
            consulta = self._colecao.where(
                filter=FieldFilter(
                    "marcas_do_catalogo", "array_contains", filtro.marca_do_catalogo
                )
            )
        jobs = (Job(**(doc.to_dict() or {})) for doc in consulta.stream())
        return paginar_em_python(
            (j for j in jobs if casa_com_o_filtro(j, filtro)), filtro, self.obter
        )

    def _consultar_pelo_arquivo(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        # Poucos Jobs por arquivo: só a igualdade no `sha256` (índice automático) vai ao
        # Firestore; o resto do filtro, a ordem e o cursor ficam em Python, sem índice
        # composto.
        consulta = self._colecao.where(
            filter=FieldFilter("sha256", "==", filtro.sha256)
        )
        jobs = (Job(**(doc.to_dict() or {})) for doc in consulta.stream())
        return paginar_em_python(
            (j for j in jobs if casa_com_o_filtro(j, filtro)), filtro, self.obter
        )


class RepositorioDeChavesFirestore:
    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_CHAVES
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def salvar(self, registro: RegistroDeChave) -> None:
        _documento(self._colecao, registro.id).set(registro.model_dump())

    def obter(self, chave_id: str) -> RegistroDeChave | None:
        doc = _documento(self._colecao, chave_id).get()
        return RegistroDeChave(**(doc.to_dict() or {})) if doc.exists else None

    def listar_por_sistema(self, sistema: str) -> list[RegistroDeChave]:
        docs = self._colecao.where(
            filter=FieldFilter("sistema", "==", sistema)
        ).stream()
        registros = [RegistroDeChave(**(doc.to_dict() or {})) for doc in docs]
        return sorted(registros, key=lambda r: r.criada_em)

    def listar(self) -> list[RegistroDeChave]:
        registros = [
            RegistroDeChave(**(doc.to_dict() or {})) for doc in self._colecao.stream()
        ]
        return sorted(registros, key=lambda r: r.criada_em, reverse=True)

    def salvar_nova(self, registro: RegistroDeChave, maximo_ativas: int) -> None:
        # A contagem roda dentro da transação: dois comandos simultâneos
        # conflitam e o Firestore repete o perdedor. Filtra as ativas aqui, e
        # não com `revogada_em == None` na consulta: chaves gravadas antes do
        # campo existir não o têm, e o Firestore não as casaria com null.
        @firestore.transactional
        def gravar(transacao: Any) -> None:
            docs = self._colecao.where(
                filter=FieldFilter("sistema", "==", registro.sistema)
            ).stream(transaction=transacao)
            ativas = [
                r
                for r in (RegistroDeChave(**(d.to_dict() or {})) for d in docs)
                if r.ativa
            ]
            if len(ativas) >= maximo_ativas:
                raise LimiteDeChavesAtivas(registro.sistema)
            transacao.set(_documento(self._colecao, registro.id), registro.model_dump())

        gravar(self._cliente.transaction())


class RepositorioDeIdempotenciaFirestore:
    """Um documento por reserva; o `expira_em` é o campo da política de TTL (48 h)."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_IDEMPOTENCIA
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def reservar(
        self, escopo: str, chave: str, impressao: str, job_id: str, agora: datetime
    ) -> tuple[Reserva, bool]:
        referencia = self._colecao.document(id_da_reserva(escopo, chave))
        criada = nova_reserva(impressao, job_id, agora)
        # `create` é atômico e não disputa transação: com muitas chamadas simultâneas na
        # mesma chave (o cliente que repete em paralelo), uma cria e as outras leem. Uma
        # transação aqui esgotaria as tentativas sob essa disputa e daria 500. Se o
        # Firestore aborta o `create` por disputa (`Aborted`), espera um pouco e tenta o
        # `create` de novo, até criar ou receber `AlreadyExists` e ler a que ficou.
        for rodada in range(TENTATIVAS_SOB_DISPUTA):
            try:
                referencia.create(criada.model_dump())
                return criada, True
            except AlreadyExists:
                pass
            except Aborted:
                time.sleep(espera_sob_disputa(rodada))
                continue
            doc = referencia.get()
            if doc.exists:
                existente = Reserva(**(doc.to_dict() or {}))
                if existente.expira_em > agora:
                    conferir(existente, impressao)
                    return existente, False
            break
        else:
            raise ServicoIndisponivel("Firestore disputado: tente de novo")
        # Vencida (o TTL do Firestore demora a apagar) ou apagada agora: troca pela nova,
        # na transação, para quem chegar junto ver a que ficou.

        @firestore.transactional
        def trocar_a_vencida(transacao: Any) -> tuple[Reserva, bool]:
            atual = referencia.get(transaction=transacao)
            if atual.exists:
                existente = Reserva(**(atual.to_dict() or {}))
                if existente.expira_em > agora:
                    conferir(existente, impressao)
                    return existente, False
            transacao.set(referencia, criada.model_dump())
            return criada, True

        # Várias repetições na mesma reserva vencida disputam a transação.
        resultado: tuple[Reserva, bool] = _repetir_sob_disputa(
            trocar_a_vencida, self._cliente
        )
        return resultado

    def marcar_job_gravado(self, escopo: str, chave: str) -> None:
        referencia = self._colecao.document(id_da_reserva(escopo, chave))
        # As repetições em paralelo leem a reserva enquanto ela é marcada: o Firestore
        # aborta o `update` por disputa (`Aborted`), e ele é repetido como o `create`.
        for rodada in range(TENTATIVAS_SOB_DISPUTA):
            try:
                referencia.update({"job_gravado": True})
            except NotFound:
                return  # a reserva venceu e o TTL a apagou
            except Aborted:
                time.sleep(espera_sob_disputa(rodada))
                continue
            return
        raise ServicoIndisponivel("Firestore disputado: tente de novo")


class ListasDaBuscaFirestore:
    """Um documento por busca paginada (#426); o `expira_em` é o campo da política de TTL."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DAS_LISTAS_DA_BUSCA
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def gravar(self, documento: dict[str, Any]) -> str:
        referencia = self._colecao.document()  # id aleatório de 20 letras e números
        referencia.set(documento)
        return str(referencia.id)

    def ler(self, id: str) -> dict[str, Any] | None:
        doc = _documento(self._colecao, id).get()
        return (doc.to_dict() or {}) if doc.exists else None


class RepositorioDeWebhooksFirestore:
    """Um documento por sistema, com o nome do sistema como id."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_WEBHOOKS
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def salvar(self, registro: RegistroDeWebhook) -> None:
        _documento(self._colecao, registro.sistema).set(registro.model_dump())

    def obter(self, sistema: str) -> RegistroDeWebhook | None:
        doc = _documento(self._colecao, sistema).get()
        return RegistroDeWebhook(**(doc.to_dict() or {})) if doc.exists else None


class RepositorioDePapeisFirestore:
    """Um documento por uid do Identity Platform, com a lista de papéis."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_PAPEIS
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def ler(self, uid: str) -> DocumentoDePapeis:
        doc = _documento(self._colecao, uid).get()
        dados = (doc.to_dict() or {}) if doc.exists else {}
        papeis: list[Papel] | None = None
        # Sem `papeis` (só a marca `desativada`): a conta segue sem papéis guardados.
        # Papel desconhecido (digitado à mão, papel futuro) não dá permissão nem 500.
        if "papeis" in dados:
            papeis = [p for p in PAPEIS if p in dados["papeis"]]
        return DocumentoDePapeis(uid, dados.get("desativada") is True, papeis)

    def obter(self, uid: str) -> list[Papel] | None:
        return self.ler(uid).papeis

    def salvar(self, uid: str, papeis: list[Papel]) -> None:
        # merge: não apaga a marca `desativada`.
        _documento(self._colecao, uid).set({"papeis": papeis}, merge=True)

    def desativada(self, uid: str) -> bool:
        return self.ler(uid).desativada

    def marcar_desativada(self, uid: str, desativada: bool) -> None:
        _documento(self._colecao, uid).set({"desativada": desativada}, merge=True)


class ContasIdentityPlatform:
    """As contas do Identity Platform pela API REST de administração (`accounts`).
    Não tem teste contra a nuvem; o corpo dos pedidos e a leitura da resposta têm."""

    def __init__(self, projeto: str, sessao: Any | None = None) -> None:
        self._base = f"https://identitytoolkit.googleapis.com/v1/projects/{projeto}"
        self._cabecalhos = {
            "x-goog-user-project": projeto,
            "X-Firebase-Locale": "pt-BR",
        }
        self._sessao = sessao

    def _http(self) -> Any:
        if self._sessao is None:
            self._sessao = sessao_autenticada()
        return self._sessao

    def _chamar(self, metodo: str, sufixo: str, **argumentos: Any) -> Any:
        resposta = self._http().request(
            metodo,
            f"{self._base}/accounts{sufixo}",
            headers=self._cabecalhos,
            timeout=30,
            **argumentos,
        )
        if not resposta.ok:
            raise requests.HTTPError(resposta.text, response=resposta)
        return resposta.json() if resposta.content else {}

    @staticmethod
    def _conta(usuario: Mapping[str, Any]) -> ContaDoIdentityPlatform:
        def instante(ms: Any) -> datetime | None:
            return (
                datetime.fromtimestamp(int(ms) / 1000, tz=UTC)
                if ms and int(ms) > 0
                else None
            )

        return ContaDoIdentityPlatform(
            uid=usuario["localId"],
            email=usuario.get("email", ""),
            nome=usuario.get("displayName", ""),
            email_verificado=usuario.get("emailVerified") is True,
            criada_em=instante(usuario.get("createdAt")),
            ultimo_acesso=instante(usuario.get("lastLoginAt")),
            bloqueada=usuario.get("disabled") is True,
        )

    def listar(self) -> list[ContaDoIdentityPlatform]:
        contas: list[ContaDoIdentityPlatform] = []
        pagina: str | None = None
        while True:
            parametros: dict[str, Any] = {"maxResults": 500}
            if pagina:
                parametros["nextPageToken"] = pagina
            dados = self._chamar("GET", ":batchGet", params=parametros)
            contas += [self._conta(u) for u in dados.get("users", [])]
            pagina = dados.get("nextPageToken")
            if not pagina:
                return contas

    def obter(self, uid: str) -> ContaDoIdentityPlatform | None:
        dados = self._chamar("POST", ":lookup", json={"localId": [uid]})
        usuarios = dados.get("users", [])
        return self._conta(usuarios[0]) if usuarios else None

    def criar(self, email: str, nome: str) -> ContaDoIdentityPlatform:
        # E-mail verificado: quem define a senha pelo link prova que é dono dele, e o
        # cadastro do MFA exige e-mail verificado. A senha é aleatória e descartada.
        try:
            dados = self._chamar(
                "POST",
                "",
                json={
                    "email": email,
                    "displayName": nome,
                    "emailVerified": True,
                    "password": secrets.token_urlsafe(32) + "Aa1!",
                },
            )
        except requests.HTTPError as erro:
            if "EMAIL_EXISTS" in str(erro):
                raise EmailJaCadastrado(email) from None
            raise
        conta = self.obter(dados["localId"])
        assert conta is not None
        return conta

    def enviar_link_de_senha(self, email: str) -> None:
        self._chamar(
            "POST",
            ":sendOobCode",
            json={"requestType": "PASSWORD_RESET", "email": email},
        )

    def bloquear(self, uid: str, bloqueada: bool) -> None:
        corpo: dict[str, Any] = {"localId": uid, "disableUser": bloqueada}
        if bloqueada:
            # Tokens de atualização emitidos antes deste instante deixam de valer.
            corpo["validSince"] = str(int(datetime.now(UTC).timestamp()))
        self._chamar("POST", ":update", json=corpo)


class CatalogoFirestore:
    """Um documento por pessoa, com o id estável como chave. `nomes_de_busca`
    (nome e apelidos normalizados) é o índice de `achar`."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DO_CATALOGO
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def _gravar(self, pessoa: PessoaDoCatalogo) -> PessoaDoCatalogo:
        _documento(self._colecao, pessoa.id).set(
            {
                **pessoa.model_dump(exclude={"id"}),
                "nomes_de_busca": nomes_de_busca(pessoa),
            }
        )
        return pessoa

    @staticmethod
    def _pessoa(id: str, dados: dict[str, Any]) -> PessoaDoCatalogo:
        dados = {k: v for k, v in dados.items() if k != "nomes_de_busca"}
        return PessoaDoCatalogo(id=id, **dados)

    def obter(self, id: str) -> PessoaDoCatalogo | None:
        doc = _documento(self._colecao, id).get()
        return self._pessoa(id, doc.to_dict() or {}) if doc.exists else None

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        return {
            d.id: self._pessoa(d.id, d.to_dict() or {})
            for d in _lidos_em_lote(self._cliente, self._colecao, ids)
        }

    def achar(self, nome: str) -> list[PessoaDoCatalogo]:
        consulta = self._colecao.where(
            filter=FieldFilter("nomes_de_busca", "array_contains", normalizar(nome))
        )
        achadas = [self._pessoa(d.id, d.to_dict() or {}) for d in consulta.stream()]
        return [p for p in achadas if visivel(p)]

    def _lidas(self) -> list[PessoaDoCatalogo]:
        return [self._pessoa(d.id, d.to_dict() or {}) for d in self._colecao.stream()]

    def todas(self) -> list[PessoaDoCatalogo]:
        return [p for p in self._lidas() if visivel(p)]

    def na_lixeira(self) -> list[PessoaDoCatalogo]:
        return [p for p in self._lidas() if p.lixeira is not None]

    def definir_lixeira(
        self, id: str, envio: EnvioParaLixeira | None
    ) -> PessoaDoCatalogo:
        atual = self.obter(id)
        if atual is None:
            raise PessoaInexistente(id)
        return self._gravar(atual.model_copy(update={"lixeira": envio}))

    def definir_fusao(self, id: str, fusao: FusaoDaPessoa | None) -> PessoaDoCatalogo:
        atual = self.obter(id)
        if atual is None:
            raise PessoaInexistente(id)
        return self._gravar(atual.model_copy(update={"fundida": fusao}))

    def definir_renomeacao(
        self, id: str, renomeacao: RenomeacaoDaPessoa | None
    ) -> PessoaDoCatalogo:
        atual = self.obter(id)
        if atual is None:
            raise PessoaInexistente(id)
        return self._gravar(atual.model_copy(update={"renomeacao": renomeacao}))

    def acrescentar(
        self,
        nome: str,
        papel: str,
        apelidos: list[str],
        *,
        a_revisar: bool = False,
        autor: str | None = None,
    ) -> PessoaDoCatalogo:
        return self._gravar(
            PessoaDoCatalogo(
                id=novo_id(),
                nome=nome,
                papel=papel,
                apelidos=list(apelidos),
                a_revisar=a_revisar,
                acrescentada_por=autor,
            )
        )

    def corrigir(
        self,
        id: str,
        *,
        nome: str | None = None,
        papel: str | None = None,
        apelidos: list[str] | None = None,
    ) -> PessoaDoCatalogo:
        atual = self.obter(id)
        if atual is None:
            raise PessoaInexistente(id)
        return self._gravar(corrigida(atual, nome, papel, apelidos))

    def definir_rostos(self, id: str, rostos: list[Rosto]) -> PessoaDoCatalogo:
        atual = self.obter(id)
        if atual is None:
            raise PessoaInexistente(id)
        return self._gravar(atual.model_copy(update={"rostos": list(rostos)}))

    def apagar(self, id: str) -> None:
        referencia = _documento(self._colecao, id)
        if not referencia.get().exists:
            raise PessoaInexistente(id)
        referencia.delete()


class ProgramasFirestore:
    """Um documento por programa, com o id estável como chave. O nome é único sem
    diferença de maiúsculas; a conferência lê antes de gravar, e a tela de edição
    é de poucas pessoas, então a corrida entre duas gravações é aceita."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DOS_PROGRAMAS
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def listar(self) -> list[Programa]:
        lidos = [
            Programa(id=d.id, **(d.to_dict() or {})) for d in self._colecao.stream()
        ]
        return sorted(lidos, key=lambda p: p.nome.casefold())

    def obter(self, id: str) -> Programa | None:
        doc = _documento(self._colecao, id).get()
        return Programa(id=id, **(doc.to_dict() or {})) if doc.exists else None

    def _conferir_nome(self, programa: Programa) -> None:
        if any(
            p.id != programa.id and p.nome.casefold() == programa.nome.casefold()
            for p in self.listar()
        ):
            raise NomeEmUso(programa.nome)

    def salvar(self, programa: Programa, *, com_renomeacao: bool = False) -> None:
        self._conferir_nome(programa)
        # Com merge, o campo que não vai fica como está: o andamento é da tarefa.
        fora = {"id"} if com_renomeacao else {"id", "renomeacao"}
        _documento(self._colecao, programa.id).set(
            programa.model_dump(exclude=fora), merge=True
        )

    def trocar(
        self, id: str, mudar: Callable[[Programa], Programa | None]
    ) -> Programa | None:
        # Como `RepositorioFirestore.trocar`: `mudar` decide, e o Firestore pode repeti-la.
        referencia = _documento(self._colecao, id)

        @firestore.transactional
        def trocar_na_transacao(transacao: Any) -> Programa | None:
            doc = referencia.get(transaction=transacao)
            if not doc.exists:
                return None
            atual = Programa(id=id, **(doc.to_dict() or {}))
            novo = mudar(atual)
            if novo is None:
                return None
            if novo.nome.casefold() != atual.nome.casefold():
                self._conferir_nome(novo)
            transacao.set(referencia, novo.model_dump(exclude={"id"}))
            return novo

        resultado: Programa | None = _repetir_sob_disputa(
            trocar_na_transacao, self._cliente
        )
        return resultado

    def levar_o_nome_ao_job(
        self, programa_id: str, troca_id: str, job_id: str, jobs: RepositorioDeJobs
    ) -> Job | None:
        # Os Jobs estão no mesmo Firestore: a transação lê o programa e o Job juntos.
        if not isinstance(jobs, RepositorioFirestore):
            raise TypeError("os Jobs precisam estar no Firestore")
        programa_ref = _documento(self._colecao, programa_id)
        job_ref = _documento(self._cliente.collection(jobs._colecao.id), job_id)

        @firestore.transactional
        def levar(transacao: Any) -> Job | None:
            lido = programa_ref.get(transaction=transacao)
            doc = job_ref.get(transaction=transacao)
            programa = (
                Programa(id=programa_id, **(lido.to_dict() or {}))
                if lido.exists
                else None
            )
            if programa is None or not troca_vale(programa, troca_id):
                raise TrocaSubstituida(troca_id)  # a transação sai sem gravar
            if not doc.exists:
                return None
            job = Job(**(doc.to_dict() or {}))
            if job.programa == programa.nome:
                return job
            novo = job.model_copy(update={"programa": programa.nome})
            transacao.set(job_ref, novo.model_dump())
            return novo

        resultado: Job | None = _repetir_sob_disputa(levar, self._cliente)
        return resultado

    def apagar(self, id: str) -> None:
        if not _documento(self._colecao, id).get().exists:
            raise ProgramaInexistente(id)
        _documento(self._colecao, id).delete()


class CatalogoDeMarcasFirestore:
    """Um documento por marca, com o id estável como chave. `nomes_de_busca` (nome e
    apelidos normalizados) é o índice de `achar`."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DO_CATALOGO_DE_MARCAS
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    @staticmethod
    def _marca(id: str, dados: dict[str, Any]) -> MarcaDoCatalogo:
        dados = {k: v for k, v in dados.items() if k != "nomes_de_busca"}
        return MarcaDoCatalogo(id=id, **dados)

    def obter(self, id: str) -> MarcaDoCatalogo | None:
        doc = _documento(self._colecao, id).get()
        return self._marca(id, doc.to_dict() or {}) if doc.exists else None

    def obter_varios(self, ids: Iterable[str]) -> dict[str, MarcaDoCatalogo]:
        return {
            d.id: self._marca(d.id, d.to_dict() or {})
            for d in _lidos_em_lote(self._cliente, self._colecao, ids)
        }

    def achar(self, nome: str, *, com_lixeira: bool = False) -> list[MarcaDoCatalogo]:
        consulta = self._colecao.where(
            filter=FieldFilter("nomes_de_busca", "array_contains", normalizar(nome))
        )
        achadas = [self._marca(d.id, d.to_dict() or {}) for d in consulta.stream()]
        return [m for m in achadas if com_lixeira or m.lixeira is None]

    def _lidas(self) -> list[MarcaDoCatalogo]:
        return [self._marca(d.id, d.to_dict() or {}) for d in self._colecao.stream()]

    def todas(self) -> list[MarcaDoCatalogo]:
        return [m for m in self._lidas() if m.lixeira is None]

    def na_lixeira(self) -> list[MarcaDoCatalogo]:
        # No servidor: roda a cada relatório e busca, não pode ler o catálogo inteiro.
        consulta = self._colecao.where(filter=FieldFilter("lixeira", "!=", None))
        return [self._marca(d.id, d.to_dict() or {}) for d in consulta.stream()]

    def _gravar(self, marca: MarcaDoCatalogo) -> MarcaDoCatalogo:
        _documento(self._colecao, marca.id).set(
            {
                **marca.model_dump(exclude={"id"}),
                "nomes_de_busca": nomes_de_busca_da_marca(marca),
            }
        )
        return marca

    def definir_lixeira(
        self, id: str, envio: EnvioParaLixeira | None
    ) -> MarcaDoCatalogo:
        atual = self.obter(id)
        if atual is None:
            raise MarcaInexistente(id)
        return self._gravar(atual.model_copy(update={"lixeira": envio}))

    def apagar(self, id: str) -> None:
        referencia = _documento(self._colecao, id)
        if not referencia.get().exists:
            raise MarcaInexistente(id)
        referencia.delete()

    def acrescentar(
        self,
        nome: str,
        apelidos: list[str],
        *,
        a_revisar: bool = False,
        autor: str | None = None,
    ) -> MarcaDoCatalogo:
        marca = MarcaDoCatalogo(
            id=novo_id(),
            nome=nome,
            apelidos=list(apelidos),
            a_revisar=a_revisar,
            acrescentada_por=autor,
        )
        return self._gravar(marca)


# ponytail: a busca lê até este tanto de tipos do prefixo; acima disso, o corte é pela chave
# e não pelas ocorrências (um prefixo com mais de 200 tipos distintos).
TETO_DA_BUSCA_DE_TIPOS = 200


class TiposDeObjetoFirestore:
    """Um documento por tipo normalizado, com o `total` somado dos jobs, e a contribuição de
    cada job em outra coleção: trocar a do job aplica só a diferença (`Increment`), sem
    duplicar. A busca filtra só pela faixa do prefixo da chave e ordena pela própria chave,
    o que não pede índice composto; a ordem por ocorrências é em Python."""

    def __init__(
        self,
        cliente: firestore.Client,
        colecao: str = COLECAO_DOS_TIPOS_DE_OBJETO,
        colecao_por_job: str = COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB,
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)
        self._por_job = cliente.collection(colecao_por_job)

    def registrar(self, job_id: str, contagens: Mapping[str, int]) -> None:
        novas = somar_por_chave(contagens)
        referencia = _documento(self._por_job, job_id)

        # Ler a contribuição antiga e aplicar o delta na mesma transação: dois reindexares
        # do mesmo job ao mesmo tempo não somam a diferença duas vezes.
        @firestore.transactional
        def trocar(transacao: Any) -> None:
            antigo = referencia.get(transaction=transacao)
            antes: dict[str, int] = (
                (antigo.to_dict() or {}).get("totais", {}) if antigo.exists else {}
            )
            for chave in novas.keys() | antes.keys():
                tipo, n = novas.get(chave, ("", 0))
                delta = n - antes.get(chave, 0)
                if delta == 0:
                    continue
                dados: dict[str, Any] = {
                    "chave": chave,
                    "total": firestore.Increment(delta),
                }
                if tipo:
                    dados["tipo"] = tipo
                transacao.set(
                    self._colecao.document(quote(chave, safe="")), dados, merge=True
                )
            transacao.set(
                referencia, {"totais": {chave: n for chave, (_, n) in novas.items()}}
            )

        trocar(self._cliente.transaction())

    def purgar(self, job_id: str) -> bool:
        """Subtrai a contribuição antes de apagar; repetir não subtrai duas vezes."""
        referencia = _documento(self._por_job, job_id)
        existia = referencia.get().exists
        self.registrar(job_id, {})
        referencia.delete()
        return bool(existia)

    def buscar(self, q: str, limite: int = LIMITE_PADRAO) -> list[TipoDeObjeto]:
        prefixo = normalizar(q)
        consulta = self._colecao.where(filter=FieldFilter("chave", ">=", prefixo))
        consulta = consulta.where(filter=FieldFilter("chave", "<", prefixo + "\uf8ff"))
        achados = [
            d.to_dict() or {}
            for d in consulta.order_by("chave").limit(TETO_DA_BUSCA_DE_TIPOS).stream()
        ]
        vivos = [d for d in achados if d.get("total", 0) > 0 and d.get("tipo")]
        vivos.sort(key=lambda d: (-d["total"], d["chave"]))
        return [{"tipo": d["tipo"], "ocorrencias": d["total"]} for d in vivos[:limite]]


class ReferenciasStorage:
    """As fotos de referência, no bucket delas (`BUCKET_REFERENCIAS`)."""

    def __init__(self, cliente: ClienteStorage, bucket: str) -> None:
        self._cliente = cliente
        self._bucket = bucket

    def contar_prefixo(self, prefixo: str) -> int:
        return sum(1 for _ in self._cliente.list_blobs(self._bucket, prefix=prefixo))

    def apagar(self, objeto: str) -> None:
        try:
            self._cliente.bucket(self._bucket).blob(objeto).delete()
        except NotFound:
            pass

    def apagar_prefixo(self, prefixo: str) -> None:
        for blob in self._cliente.list_blobs(self._bucket, prefix=prefixo):
            try:
                blob.delete()
            except NotFound:
                pass


class RepositorioDeCorrecoesFirestore:
    """Só acrescenta: `create` falha se o id já existe, então nada é sobrescrito."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_CORRECOES
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def acrescentar(self, correcao: Correcao) -> None:
        try:
            _documento(self._colecao, correcao.id).create(correcao.model_dump())
        except AlreadyExists:
            raise CorrecaoJaExiste(correcao.id) from None

    def listar(self, job_id: str) -> list[Correcao]:
        docs = self._colecao.where(filter=FieldFilter("job_id", "==", job_id)).stream()
        achadas = [Correcao(**(doc.to_dict() or {})) for doc in docs]
        return em_ordem(achadas)

    def jobs_com_correcao(
        self, desde: datetime | None = None, ate: datetime | None = None
    ) -> set[str]:
        consulta: Any = self._colecao
        if desde is not None:
            consulta = consulta.where(filter=FieldFilter("criada_em", ">=", desde))
        if ate is not None:
            consulta = consulta.where(filter=FieldFilter("criada_em", "<", ate))
        return {
            (d.to_dict() or {})["job_id"] for d in consulta.select(["job_id"]).stream()
        }

    def purgar(self, job_id: str) -> None:
        for doc in self._colecao.where(
            filter=FieldFilter("job_id", "==", job_id)
        ).stream():
            doc.reference.delete()


class RepositorioDeAprovacaoFirestore:
    """Um documento com a lista de tipos de correção que exigem aprovação."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_CONFIGURACAO
    ) -> None:
        self._documento = cliente.collection(colecao).document(DOCUMENTO_DA_APROVACAO)

    def tipos(self) -> frozenset[str]:
        doc = self._documento.get()
        if not doc.exists:
            return frozenset()
        # Tipo desconhecido (digitado à mão) não exige nada.
        guardados = (doc.to_dict() or {}).get("tipos", [])
        return frozenset(t for t in CORRIGIVEIS if t in guardados)

    def definir(self, tipos: frozenset[str]) -> None:
        self._documento.set({"tipos": sorted(tipos)})

    def mudar(self, tipo: str, exige_aprovacao: bool) -> None:
        operacao = firestore.ArrayUnion if exige_aprovacao else firestore.ArrayRemove
        self._documento.set({"tipos": operacao([tipo])}, merge=True)


class RepositorioDeAuditoriaFirestore:
    """Só acrescenta: `create` falha se o id já existe, e não há como alterar nem apagar."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DA_AUDITORIA
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        _documento(self._colecao, registro.id).create(registro.model_dump())

    def consultar(self, filtro: FiltroDeAuditoria) -> PaginaDeAuditoria:
        # Igualdades (pessoa, alvo, ação) mais intervalo e ordem em `quando`: os
        # índices compostos estão no infra/modulos/mam/main.tf.
        consulta: Any = self._colecao
        if filtro.pessoa is not None:
            campo, valor = campo_da_pessoa(filtro.pessoa)
            consulta = consulta.where(filter=FieldFilter(campo, "==", valor))
        if filtro.alvo_id is not None:
            consulta = consulta.where(
                filter=FieldFilter("alvo_id", "==", filtro.alvo_id)
            )
        if filtro.acao is not None:
            consulta = consulta.where(filter=FieldFilter("acao", "==", filtro.acao))
        if filtro.acoes is not None:
            # O `in` usa os mesmos índices da igualdade.
            consulta = consulta.where(
                filter=FieldFilter("acao", "in", list(filtro.acoes))
            )
        if filtro.de is not None:
            consulta = consulta.where(filter=FieldFilter("quando", ">=", filtro.de))
        if filtro.ate is not None:
            consulta = consulta.where(filter=FieldFilter("quando", "<=", filtro.ate))
        # O desempate implícito é o id do documento, na mesma direção da ordem.
        consulta = consulta.order_by("quando", direction=firestore.Query.DESCENDING)
        if filtro.cursor is not None:
            ancora = _documento(self._colecao, filtro.cursor).get()
            if not ancora.exists:
                raise CursorInvalido
            consulta = consulta.start_after(ancora)
        registros = (
            RegistroDeAuditoria(**(doc.to_dict() or {})) for doc in consulta.stream()
        )
        return pagina_da_auditoria(
            (r for r in registros if casa_com_o_filtro_da_auditoria(r, filtro)),
            filtro.limite,
        )


class RepositorioDeRevisaoFirestore:
    """Um documento por vídeo e pessoa (`<job>:<uid>`); o pulso é aplicado numa transação."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DA_REVISAO
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def aplicar(self, pulso: Pulso, limite_s: float) -> Medida:
        # Cada parte conferida à parte: juntas podem passar do teto de um id só.
        referencia = self._colecao.document(
            f"{id_conferido(pulso.job_id)}:{id_conferido(pulso.uid)}"
        )

        @firestore.transactional
        def gravar(transacao: Any) -> Medida:
            doc = referencia.get(transaction=transacao)
            atual = Medida(**(doc.to_dict() or {})) if doc.exists else None
            medida = aplicar_o_pulso(atual, pulso, limite_s)
            transacao.set(referencia, medida.model_dump())
            return medida

        resultado: Medida = gravar(self._cliente.transaction())
        return resultado

    def do_video(self, job_id: str) -> list[Medida]:
        docs = self._colecao.where(filter=FieldFilter("job_id", "==", job_id)).stream()
        return sorted(
            (Medida(**(d.to_dict() or {})) for d in docs), key=lambda m: m.email
        )

    def todas(self, desde: datetime | None = None) -> list[Medida]:
        consulta: Any = self._colecao
        if desde is not None:
            consulta = consulta.where(filter=FieldFilter("ultimo_pulso", ">=", desde))
        return sorted(
            (Medida(**(d.to_dict() or {})) for d in consulta.stream()),
            key=lambda m: (m.job_id, m.email),
        )


class DisparoPeloWorkflows:
    """Começa uma execução do Workflows da validação a partir de uma etapa.

    O argumento (`job_id` e `etapa_inicial`) é o que o workflow reconhece como
    reprocessamento, no lugar do evento do Eventarc. A conta da API só tem a
    permissão de iniciar execuções.
    """

    def __init__(
        self, projeto: str, regiao: str, workflow: str, sessao: Any = None
    ) -> None:
        self._url = (
            "https://workflowexecutions.googleapis.com/v1/projects/"
            f"{projeto}/locations/{regiao}/workflows/{workflow}/executions"
        )
        self._sessao = sessao

    def _sessao_autenticada(self) -> Any:
        if self._sessao is None:
            self._sessao = sessao_autenticada()
        return self._sessao

    def iniciar(self, job_id: str, etapa: NomeDaEtapa) -> None:
        argumento = json.dumps({"job_id": job_id, "etapa_inicial": etapa})
        try:
            resposta = self._sessao_autenticada().post(
                self._url, json={"argument": argumento}, timeout=30
            )
            resposta.raise_for_status()
        except requests.RequestException as e:
            # Vira 503 na rota, que antes devolve o Job ao que era.
            raise ServicoIndisponivel from e


class DisparoDaIndexacaoNoCloudRun:
    """Roda o Job `mam-indexacao` com `JOB_ID`, pela API REST do Cloud Run, sem esperar
    o fim: a resposta do `:run` é a operação, e a reindexação segue sozinha."""

    def __init__(self, projeto: str, regiao: str, job: str, sessao: Any = None) -> None:
        self._url = (
            f"https://run.googleapis.com/v2/projects/{projeto}/locations/{regiao}"
            f"/jobs/{job}:run"
        )
        self._sessao = sessao

    def _sessao_autenticada(self) -> Any:
        if self._sessao is None:
            self._sessao = sessao_autenticada()
        return self._sessao

    def iniciar(self, job_id: str) -> None:
        corpo = {
            "overrides": {
                "containerOverrides": [
                    {
                        "env": [
                            {"name": "JOB_ID", "value": job_id},
                            # Só o disparo da API alerta a falha (o Workflow a conta).
                            {"name": "ORIGEM_DO_DISPARO", "value": "api"},
                        ]
                    }
                ]
            }
        }
        try:
            resposta = self._sessao_autenticada().post(
                self._url, json=corpo, timeout=30
            )
            resposta.raise_for_status()
        except requests.RequestException as e:
            raise ServicoIndisponivel from e


class AssinaturaPeloIam:
    """Assinatura pedida ao IAM pela conta do serviço, sem chave em arquivo. A credencial
    é uma por processo e só se renova quando expira (`valid`); a trava evita que várias
    threads (as capas do Acervo assinam em paralelo) renovem ao mesmo tempo."""

    def __init__(
        self,
        obter_credenciais: Callable[[], Any] | None = None,
        requisicao: Callable[[], Any] | None = None,
    ) -> None:
        self._obter = obter_credenciais or self._credenciais_do_ambiente
        self._requisicao = requisicao or google.auth.transport.requests.Request
        self._credenciais: Any = None
        self._trava = threading.Lock()

    @staticmethod
    def _credenciais_do_ambiente() -> Any:
        credenciais, _ = google.auth.default(scopes=[ESCOPO_DA_NUVEM])
        return credenciais

    def __call__(self) -> dict[str, Any]:
        with self._trava:
            if self._credenciais is None:
                self._credenciais = self._obter()
            if not self._credenciais.valid:
                self._credenciais.refresh(self._requisicao())
            return {
                "service_account_email": self._credenciais.service_account_email,
                "access_token": self._credenciais.token,
            }


assinatura_pelo_iam = AssinaturaPeloIam()


def _gravar_os_itens(
    cliente: ClienteStorage, bucket: str, job_id: str, conteudo: str
) -> None:
    """A contagem de itens por tipo (#455) vai junto com a decupagem e é refeita a cada
    gravação, reprocessamento incluído. Decupagem ilegível fica sem contagem: a taxa a pula."""
    try:
        itens = contar_itens(conteudo.encode())
    except (ValueError, TypeError, KeyError):
        log.warning("decupagem de %s sem contagem de itens: ilegível", job_id)
        return
    cliente.bucket(bucket).blob(objeto_dos_itens(job_id)).upload_from_string(
        itens.em_json(), content_type="application/json"
    )


class DecupagensStorage:
    """A Decupagem no Cloud Storage e o proxy que o Gemini lê: o mesmo adaptador grava e lê."""

    def __init__(
        self, cliente: ClienteStorage, bucket_de_aceitos: str, bucket_de_decupagens: str
    ) -> None:
        self._cliente = cliente
        self._aceitos = bucket_de_aceitos
        self._decupagens = bucket_de_decupagens

    def uri_do_proxy(self, job_id: str) -> str:
        return f"gs://{self._aceitos}/{objeto_do_proxy(job_id)}"

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_da_decupagem(job_id)
        ).upload_from_string(conteudo, content_type="application/json")
        _gravar_os_itens(self._cliente, self._decupagens, job_id, conteudo)

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        try:
            with blob.open("rb") as arquivo:
                while pedaco := arquivo.read(TAMANHO_DO_PEDACO):
                    yield pedaco
        except NotFound as e:
            raise ServicoIndisponivel from e

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        try:
            return Decupagem.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return bytes(
            self._cliente.bucket(self._decupagens)
            .blob(objeto_do_quadro(job_id, caminho))
            .download_as_bytes()
        )

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_da_copia_limpa(job_id))
        try:
            blob.download_to_filename(str(destino))
        except NotFound:
            return False
        return True


class TranscricoesStorage:
    """O áudio e a transcrição, ao lado do proxy no bucket de aceitos."""

    def __init__(self, cliente: ClienteStorage, bucket_de_aceitos: str) -> None:
        self._cliente = cliente
        self._aceitos = bucket_de_aceitos

    def baixar_audio(self, job_id: str, destino: Path) -> bool:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_do_audio(job_id))
        try:
            blob.download_to_filename(str(destino))
        except NotFound:
            return False
        return True

    def gravar_transcricao(self, job_id: str, transcricao: Transcricao) -> None:
        self._cliente.bucket(self._aceitos).blob(
            objeto_da_transcricao(job_id)
        ).upload_from_string(
            transcricao.model_dump_json(), content_type="application/json"
        )

    def ler_transcricao(self, job_id: str) -> Transcricao | None:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_da_transcricao(job_id))
        try:
            return Transcricao.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None


class JanelasStorage:
    """O progresso das janelas de análise, um objeto por janela no bucket de aceitos."""

    def __init__(self, cliente: ClienteStorage, bucket_de_aceitos: str) -> None:
        self._cliente = cliente
        self._aceitos = bucket_de_aceitos

    def ler(self, job_id: str) -> dict[int, JanelaGravada]:
        lidas = [
            ler_janela_gravada(job_id, blob.download_as_bytes())
            for blob in self._cliente.list_blobs(
                self._aceitos, prefix=prefixo_das_janelas(job_id)
            )
        ]
        return {g.indice: g for g in lidas if g is not None}

    def gravar(self, job_id: str, janela: JanelaGravada) -> None:
        self._cliente.bucket(self._aceitos).blob(
            objeto_da_janela(job_id, janela.indice)
        ).upload_from_string(janela.model_dump_json(), content_type="application/json")

    def apagar(self, job_id: str) -> None:
        for blob in self._cliente.list_blobs(
            self._aceitos, prefix=prefixo_das_janelas(job_id)
        ):
            blob.delete()


class LeiturasStorage:
    """O proxy que o OCR lê e a leitura da tela, no bucket de aceitos."""

    def __init__(self, cliente: ClienteStorage, bucket_de_aceitos: str) -> None:
        self._cliente = cliente
        self._aceitos = bucket_de_aceitos

    def baixar_proxy(self, job_id: str, destino: Path) -> None:
        self._cliente.bucket(self._aceitos).blob(
            objeto_do_proxy(job_id)
        ).download_to_filename(str(destino))

    def gravar_leitura(self, job_id: str, leitura: LeituraDaTela) -> None:
        self._cliente.bucket(self._aceitos).blob(
            objeto_da_leitura_da_tela(job_id)
        ).upload_from_string(leitura.model_dump_json(), content_type="application/json")

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None:
        blob = self._cliente.bucket(self._aceitos).blob(
            objeto_da_leitura_da_tela(job_id)
        )
        try:
            return LeituraDaTela.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None


class ObjetosStorage:
    """Os Jobs de objetos só tocam o bucket das decupagens: o da GPU lê a Decupagem e os quadros
    e grava o resultado bruto; o do inventário (CPU) lê o resultado e regrava a Decupagem."""

    def __init__(self, cliente: ClienteStorage, bucket_de_decupagens: str) -> None:
        self._cliente = cliente
        self._decupagens = bucket_de_decupagens

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        try:
            return Decupagem.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return bytes(
            self._cliente.bucket(self._decupagens)
            .blob(objeto_do_quadro(job_id, caminho))
            .download_as_bytes()
        )

    def gravar_resultado(
        self, job_id: str, resultado: ObjetosDaDecupagem, destino: str | None
    ) -> None:
        self._cliente.bucket(self._decupagens).blob(
            destino or objeto_do_resultado_dos_objetos(job_id)
        ).upload_from_string(
            # Sem `segundos` (só a medição do #329 os grava), o JSON é o de antes.
            resultado.model_dump_json(
                exclude={"segundos"} if resultado.segundos is None else None
            ),
            content_type="application/json",
        )

    def ler_resultado(
        self, job_id: str, destino: str | None = None
    ) -> ObjetosDaDecupagem | None:
        blob = self._cliente.bucket(self._decupagens).blob(
            destino or objeto_do_resultado_dos_objetos(job_id)
        )
        try:
            return ObjetosDaDecupagem.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_da_decupagem(job_id)
        ).upload_from_string(conteudo, content_type="application/json")
        _gravar_os_itens(self._cliente, self._decupagens, job_id, conteudo)

    def gravar_texto(self, objeto: str, conteudo: str) -> None:
        """Um JSON solto no bucket das decupagens (a medição do Florence-2, #329)."""
        self._cliente.bucket(self._decupagens).blob(objeto).upload_from_string(
            conteudo, content_type="application/json"
        )

    def ler_texto(self, objeto: str) -> str | None:
        """Lê um JSON solto; só a ausência devolve None."""
        try:
            return bytes(
                self._cliente.bucket(self._decupagens).blob(objeto).download_as_bytes()
            ).decode("utf-8")
        except NotFound:
            return None


# O navegador guarda o quadro por 1 dia (#410); `private` deixa fora os caches compartilhados.
# O `make cache-dos-quadros` aplica o mesmo valor aos quadros já gravados.
CACHE_DO_QUADRO = "private, max-age=86400"


class QuadrosStorage(DecupagensStorage):
    """Os JPEGs dos quadros-chave no bucket das decupagens, além da cópia limpa e da Decupagem."""

    def gravar_quadro(self, job_id: str, caminho: str, jpeg: bytes) -> None:
        blob = self._cliente.bucket(self._decupagens).blob(
            objeto_do_quadro(job_id, caminho)
        )
        blob.cache_control = CACHE_DO_QUADRO
        blob.upload_from_string(jpeg, content_type="image/jpeg")


class ArquivosNoStorage:
    """Quantos arquivos do Job há nos buckets, para o impacto da lixeira."""

    def __init__(
        self, cliente: ClienteStorage, bucket_de_aceitos: str, bucket_de_decupagens: str
    ) -> None:
        self._cliente = cliente
        self._aceitos = bucket_de_aceitos
        self._decupagens = bucket_de_decupagens

    def _existe(self, bucket: str, objeto: str) -> int:
        return int(self._cliente.bucket(bucket).blob(objeto).exists())

    def contar(self, job_id: str) -> ArquivosContados:
        quadros = self._cliente.list_blobs(
            self._decupagens, prefix=objeto_do_quadro(job_id, "quadros/")
        )
        return ArquivosContados(
            decupagem=self._existe(self._decupagens, objeto_da_decupagem(job_id)),
            copia_limpa=self._existe(self._aceitos, objeto_da_copia_limpa(job_id)),
            proxy=self._existe(self._aceitos, objeto_do_proxy(job_id)),
            quadros=sum(1 for _ in quadros),
        )

    def apagar(self, job_id: str) -> None:
        # A regra de 7 dias do bucket pode apagar a cópia limpa ou o áudio entre a
        # listagem e o `delete()`: o objeto que sumiu já está apagado (#502).
        for bucket in (self._aceitos, self._decupagens):
            for blob in self._cliente.list_blobs(bucket, prefix=f"{job_id}/"):
                try:
                    blob.delete()
                except NotFound:
                    pass
        for objeto in (objeto_da_decupagem(job_id), f"{job_id}.comparacao.json"):
            try:
                self._cliente.bucket(self._decupagens).blob(objeto).delete()
            except NotFound:
                pass


# Quadros guardados por instância: uns 50 por página da grade, com folga para o acervo.
QUADROS_ASSINADOS_GUARDADOS = 4096


class ArmazenamentoStorage:
    """Upload, cancelamento do upload, reprodução e leitura da decupagem."""

    def __init__(
        self,
        cliente: ClienteStorage,
        bucket_de_quarentena: str,
        bucket_de_aceitos: str,
        bucket_de_decupagens: str,
        assinatura: Callable[[], dict[str, Any]] = assinatura_pelo_iam,
        relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._cliente = cliente
        self._bucket = bucket_de_quarentena
        self._aceitos = bucket_de_aceitos
        self._decupagens = bucket_de_decupagens
        self._leitor = DecupagensStorage(
            cliente, bucket_de_aceitos, bucket_de_decupagens
        )
        self._assinatura = assinatura
        self._relogio = relogio
        self._quadro_na_janela = functools.lru_cache(QUADROS_ASSINADOS_GUARDADOS)(
            self._assinar_quadro
        )

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        blob = self._cliente.bucket(self._bucket).blob(id_conferido(job_id))
        url: str = blob.generate_signed_url(
            version="v4",
            expiration=PRAZO_DA_URL_DE_UPLOAD,
            method="POST",
            content_type=tipo,
            headers={
                # Objeto escrito uma vez só (#369): com o objeto já existente, a abertura leva 412.
                "x-goog-if-generation-match": "0",
                "x-goog-resumable": "start",
                "x-upload-content-length": str(tamanho_bytes),
            },
            **self._assinatura(),
        )
        return url

    def cancelar_upload(self, job_id: str) -> None:
        """Apaga o objeto do Job da quarentena; o upload pode nem ter começado."""
        try:
            self._cliente.bucket(self._bucket).blob(id_conferido(job_id)).delete()
        except NotFound:
            pass

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_do_proxy(job_id))
        url: str = blob.generate_signed_url(
            version="v4", expiration=validade, method="GET", **self._assinatura()
        )
        return url

    def url_de_download(self, job_id: str, nome: str, validade: timedelta) -> str:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_do_proxy(job_id))
        url: str = blob.generate_signed_url(
            version="v4",
            expiration=validade,
            method="GET",
            response_disposition=f"attachment; {disposicao_do_nome(nome)}",
            **self._assinatura(),
        )
        return url

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return bytes(
            self._cliente.bucket(self._decupagens)
            .blob(objeto_do_quadro(job_id, caminho))
            .download_as_bytes()
        )

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        """A mesma URL para o mesmo quadro dentro da janela; um quadro regravado no meio
        dela aparece antigo até a janela virar (aceito no #409)."""
        # ponytail: o lru_cache não junta dois pedidos simultâneos do mesmo quadro ainda fora
        # do cache: os dois assinam, e um guarda a URL. Custa uma ida a mais ao IAM e um download
        # a mais no navegador, só na primeira carga. Trava por chave se a medição no dev pedir.
        janela = self._relogio().timestamp() // JANELA_DA_URL_DO_QUADRO.total_seconds()
        return self._quadro_na_janela(job_id, caminho, validade, janela)

    def _assinar_quadro(
        self, job_id: str, caminho: str, validade: timedelta, janela: float
    ) -> str:
        blob = self._cliente.bucket(self._decupagens).blob(
            objeto_do_quadro(job_id, caminho)
        )
        url: str = blob.generate_signed_url(
            version="v4", expiration=validade, method="GET", **self._assinatura()
        )
        return url

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        return self._leitor.abrir_decupagem(job_id)
