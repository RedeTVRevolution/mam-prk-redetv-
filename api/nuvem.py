"""Adaptadores de nuvem da E0: Firestore (Jobs) e Cloud Storage (upload)."""

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import google.auth
import google.auth.transport.requests
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.storage import Client as ClienteStorage

from api.chaves import LimiteDeChavesAtivas, RegistroDeChave
from api.correcoes import CORRIGIVEIS, Correcao, CorrecaoJaExiste, em_ordem
from api.jobs import (
    PRAZO_DO_UPLOAD,
    Estado,
    Job,
    ServicoIndisponivel,
)
from api.papeis import PAPEIS, Papel
from api.transcricao import Transcricao
from api.webhook import RegistroDeWebhook

COLECAO_DE_JOBS = "jobs"
COLECAO_DE_CHAVES = "chaves_de_api"
COLECAO_DE_WEBHOOKS = "webhooks"
COLECAO_DE_PAPEIS = "papeis_de_usuarios"
COLECAO_DE_CORRECOES = "correcoes"
COLECAO_DE_CONFIGURACAO = "configuracao"
DOCUMENTO_DA_APROVACAO = "aprovacao"
TAMANHO_DO_PEDACO = 256 * 1024


def objeto_do_proxy(job_id: str) -> str:
    return f"{job_id}/proxy.mp4"


def objeto_do_audio(job_id: str) -> str:
    return f"{job_id}/audio.wav"


def objeto_da_transcricao(job_id: str) -> str:
    return f"{job_id}/transcricao.json"


def objeto_da_decupagem(job_id: str) -> str:
    return f"{job_id}.json"


class RepositorioFirestore:
    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_JOBS
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def salvar(self, job: Job) -> None:
        self._colecao.document(job.id).set(job.model_dump())

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        # Lê, confere a origem e grava na mesma transação: um cancelamento que
        # chegue no meio faz o Firestore repetir a transação, que então vê o novo estado.
        referencia = self._colecao.document(job_id)

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

        resultado: Job | None = trocar(self._cliente.transaction())
        return resultado

    def obter(self, job_id: str) -> Job | None:
        doc = self._colecao.document(job_id).get()
        return Job(**(doc.to_dict() or {})) if doc.exists else None

    def listar(self) -> list[Job]:
        docs = self._colecao.order_by(
            "criado_em", direction=firestore.Query.DESCENDING
        ).stream()
        return [Job(**(doc.to_dict() or {})) for doc in docs]

    def listar_por_sistema(self, sistema: str) -> list[Job]:
        # Consulta filtrada no Firestore; em produção exige o índice composto
        # (sistema + criado_em), que o emulador dispensa.
        docs = (
            self._colecao.where(filter=FieldFilter("sistema", "==", sistema))
            .order_by("criado_em", direction=firestore.Query.DESCENDING)
            .stream()
        )
        return [Job(**(doc.to_dict() or {})) for doc in docs]


class RepositorioDeChavesFirestore:
    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_CHAVES
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def salvar(self, registro: RegistroDeChave) -> None:
        self._colecao.document(registro.id).set(registro.model_dump())

    def obter(self, chave_id: str) -> RegistroDeChave | None:
        doc = self._colecao.document(chave_id).get()
        return RegistroDeChave(**(doc.to_dict() or {})) if doc.exists else None

    def listar_por_sistema(self, sistema: str) -> list[RegistroDeChave]:
        docs = self._colecao.where(
            filter=FieldFilter("sistema", "==", sistema)
        ).stream()
        registros = [RegistroDeChave(**(doc.to_dict() or {})) for doc in docs]
        return sorted(registros, key=lambda r: r.criada_em)

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
            transacao.set(self._colecao.document(registro.id), registro.model_dump())

        gravar(self._cliente.transaction())


class RepositorioDeWebhooksFirestore:
    """Um documento por sistema, com o nome do sistema como id."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_WEBHOOKS
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def salvar(self, registro: RegistroDeWebhook) -> None:
        self._colecao.document(registro.sistema).set(registro.model_dump())

    def obter(self, sistema: str) -> RegistroDeWebhook | None:
        doc = self._colecao.document(sistema).get()
        return RegistroDeWebhook(**(doc.to_dict() or {})) if doc.exists else None


class RepositorioDePapeisFirestore:
    """Um documento por uid do Identity Platform, com a lista de papéis."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_PAPEIS
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def obter(self, uid: str) -> list[Papel] | None:
        doc = self._colecao.document(uid).get()
        if not doc.exists:
            return None
        # Papel desconhecido (digitado à mão, papel futuro) não dá permissão nem 500.
        guardados = (doc.to_dict() or {}).get("papeis", [])
        return [p for p in PAPEIS if p in guardados]

    def salvar(self, uid: str, papeis: list[Papel]) -> None:
        self._colecao.document(uid).set({"papeis": papeis})


class RepositorioDeCorrecoesFirestore:
    """Só acrescenta: `create` falha se o id já existe, então nada é sobrescrito."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_CORRECOES
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def acrescentar(self, correcao: Correcao) -> None:
        try:
            self._colecao.document(correcao.id).create(correcao.model_dump())
        except AlreadyExists:
            raise CorrecaoJaExiste(correcao.id) from None

    def listar(self, job_id: str) -> list[Correcao]:
        docs = self._colecao.where(filter=FieldFilter("job_id", "==", job_id)).stream()
        achadas = [Correcao(**(doc.to_dict() or {})) for doc in docs]
        return em_ordem(achadas)


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


def assinatura_pelo_iam() -> dict[str, Any]:
    """Assinatura pedida ao IAM pela conta do serviço, sem chave em arquivo."""
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credenciais.refresh(google.auth.transport.requests.Request())
    return {
        "service_account_email": credenciais.service_account_email,
        "access_token": credenciais.token,
    }


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

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        try:
            with blob.open("rb") as arquivo:
                while pedaco := arquivo.read(TAMANHO_DO_PEDACO):
                    yield pedaco
        except NotFound as e:
            raise ServicoIndisponivel from e


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


class ArmazenamentoStorage:
    """Upload, cancelamento do upload, reprodução e leitura da decupagem."""

    def __init__(
        self,
        cliente: ClienteStorage,
        bucket_de_quarentena: str,
        bucket_de_aceitos: str,
        bucket_de_decupagens: str,
        assinatura: Callable[[], dict[str, Any]] = assinatura_pelo_iam,
    ) -> None:
        self._cliente = cliente
        self._bucket = bucket_de_quarentena
        self._aceitos = bucket_de_aceitos
        self._decupagens = bucket_de_decupagens
        self._leitor = DecupagensStorage(
            cliente, bucket_de_aceitos, bucket_de_decupagens
        )
        self._assinatura = assinatura

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        blob = self._cliente.bucket(self._bucket).blob(job_id)
        url: str = blob.generate_signed_url(
            version="v4",
            expiration=PRAZO_DO_UPLOAD,
            method="POST",
            content_type=tipo,
            headers={
                "x-goog-resumable": "start",
                "x-upload-content-length": str(tamanho_bytes),
            },
            **self._assinatura(),
        )
        return url

    def cancelar_upload(self, job_id: str) -> None:
        """Apaga o objeto do Job da quarentena; o upload pode nem ter começado."""
        try:
            self._cliente.bucket(self._bucket).blob(job_id).delete()
        except NotFound:
            pass

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_do_proxy(job_id))
        url: str = blob.generate_signed_url(
            version="v4", expiration=validade, method="GET", **self._assinatura()
        )
        return url

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        return self._leitor.abrir_decupagem(job_id)
