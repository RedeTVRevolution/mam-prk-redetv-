"""Adaptadores de nuvem da E0: Firestore (Jobs) e Cloud Storage (upload)."""

import hashlib
import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import google.auth
import google.auth.transport.requests
import requests
from google.api_core.exceptions import AlreadyExists, NotFound
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
    PessoaDoCatalogo,
    PessoaInexistente,
    Rosto,
    corrigida,
    nomes_de_busca,
    novo_id,
)
from api.chaves import LimiteDeChavesAtivas, RegistroDeChave
from api.comparador import normalizar
from api.correcoes import CORRIGIVEIS, Correcao, CorrecaoJaExiste, em_ordem
from api.decupagem import Decupagem
from api.jobs import (
    PRAZO_DO_UPLOAD,
    CursorInvalido,
    Estado,
    FiltroDeJobs,
    Job,
    NomeDaEtapa,
    PaginaDeJobs,
    ServicoIndisponivel,
    casa_com_o_filtro,
)
from api.leitura_da_tela import LeituraDaTela
from api.nomes_a_buscar import NomesABuscar
from api.papeis import PAPEIS, Papel
from api.progresso_das_janelas import JanelaGravada
from api.rostos_dos_palpites import FotoAusente
from api.transcricao import Transcricao
from api.webhook import RegistroDeWebhook

COLECAO_DE_JOBS = "jobs"
COLECAO_DE_CHAVES = "chaves_de_api"
COLECAO_DE_WEBHOOKS = "webhooks"
COLECAO_DE_PAPEIS = "papeis_de_usuarios"
COLECAO_DE_CORRECOES = "correcoes"
COLECAO_DO_CATALOGO = "catalogo_de_pessoas"
COLECAO_DAS_SUGESTOES = "sugestoes_de_perfil"
COLECAO_DE_CONFIGURACAO = "configuracao"
COLECAO_DA_AUDITORIA = "auditoria"
DOCUMENTO_DA_APROVACAO = "aprovacao"
TAMANHO_DO_PEDACO = 256 * 1024


def objeto_do_proxy(job_id: str) -> str:
    return f"{job_id}/proxy.mp4"


def objeto_do_audio(job_id: str) -> str:
    return f"{job_id}/audio.wav"


def objeto_da_transcricao(job_id: str) -> str:
    return f"{job_id}/transcricao.json"


def prefixo_das_janelas(job_id: str) -> str:
    return f"{job_id}/janelas/"


def objeto_da_janela(job_id: str, indice: int) -> str:
    return f"{prefixo_das_janelas(job_id)}{indice:04d}.json"


def objeto_da_leitura_da_tela(job_id: str) -> str:
    return f"{job_id}/leitura_da_tela.json"


def objeto_da_decupagem(job_id: str) -> str:
    return f"{job_id}.json"


def objeto_do_quadro(job_id: str, caminho: str) -> str:
    """`caminho` é o do campo `quadro` da Decupagem (`quadros/plano-0.jpg`)."""
    return f"{job_id}/{caminho}"


def objeto_da_copia_limpa(job_id: str) -> str:
    return f"{job_id}/copia_limpa.mp4"


def objeto_da_comparacao(job_id: str) -> str:
    return f"{job_id}.comparacao.json"


def objeto_dos_nomes_a_buscar(job_id: str) -> str:
    return f"{job_id}.nomes_a_buscar.json"


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

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        # Como `transitar`, mas quem decide é `mudar`, que o Firestore pode repetir.
        referencia = self._colecao.document(job_id)

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

        resultado: Job | None = trocar_na_transacao(self._cliente.transaction())
        return resultado

    def obter(self, job_id: str) -> Job | None:
        doc = self._colecao.document(job_id).get()
        return Job(**(doc.to_dict() or {})) if doc.exists else None

    def listar(self) -> list[Job]:
        docs = self._colecao.order_by(
            "criado_em", direction=firestore.Query.DESCENDING
        ).stream()
        return [Job(**(doc.to_dict() or {})) for doc in docs]

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        # O Firestore corta o que dá com um índice composto (igualdades, `in`, uma
        # palavra do nome e, na ordem por exibição, o intervalo de datas, que só pode
        # estar no campo da ordem). O resto, e a conferência de tudo, é de `casa_com_o_filtro`.
        # Os índices estão no infra/main.tf.
        consulta: Any = self._colecao
        if filtro.programa is not None:
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
        # O desempate implícito é o id do documento, na mesma direção da ordem.
        consulta = consulta.order_by(campo, direction=firestore.Query.DESCENDING)
        if filtro.cursor is not None:
            ancora = self._colecao.document(filtro.cursor).get()
            if not ancora.exists:
                raise CursorInvalido
            consulta = consulta.start_after(ancora)
        jobs = (Job(**(doc.to_dict() or {})) for doc in consulta.stream())
        return PaginaDeJobs.de(
            (j for j in jobs if casa_com_o_filtro(j, filtro)), filtro.limite
        )


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


class CatalogoFirestore:
    """Um documento por pessoa, com o id estável como chave. `nomes_de_busca`
    (nome e apelidos normalizados) é o índice de `achar`."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DO_CATALOGO
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def _gravar(self, pessoa: PessoaDoCatalogo) -> PessoaDoCatalogo:
        self._colecao.document(pessoa.id).set(
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
        doc = self._colecao.document(id).get()
        return self._pessoa(id, doc.to_dict() or {}) if doc.exists else None

    def achar(self, nome: str) -> list[PessoaDoCatalogo]:
        consulta = self._colecao.where(
            filter=FieldFilter("nomes_de_busca", "array_contains", normalizar(nome))
        )
        return [self._pessoa(d.id, d.to_dict() or {}) for d in consulta.stream()]

    def todas(self) -> list[PessoaDoCatalogo]:
        return [self._pessoa(d.id, d.to_dict() or {}) for d in self._colecao.stream()]

    def acrescentar(
        self, nome: str, papel: str, apelidos: list[str]
    ) -> PessoaDoCatalogo:
        return self._gravar(
            PessoaDoCatalogo(
                id=novo_id(), nome=nome, papel=papel, apelidos=list(apelidos)
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
        referencia = self._colecao.document(id)
        if not referencia.get().exists:
            raise PessoaInexistente(id)
        referencia.delete()


class SugestoesFirestore:
    """Nomes sugeridos para o perfil de um programa (#111). Um documento por programa
    e nome, de id estável: sugerir de novo não duplica."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DAS_SUGESTOES
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def sugerir(self, programa: str, nome: str, busca: str, quando: datetime) -> None:
        chave = hashlib.sha256(f"{programa}\n{normalizar(nome)}".encode()).hexdigest()
        self._colecao.document(chave).set(
            {"programa": programa, "nome": nome, "busca": busca, "quando": quando}
        )

    def do_programa(self, programa: str) -> list[str]:
        consulta = self._colecao.where(filter=FieldFilter("programa", "==", programa))
        return [(d.to_dict() or {})["nome"] for d in consulta.stream()]


class ReferenciasStorage:
    """As fotos de referência, no bucket delas (`BUCKET_REFERENCIAS`)."""

    def __init__(self, cliente: ClienteStorage, bucket: str) -> None:
        self._cliente = cliente
        self._bucket = bucket

    def gravar(self, objeto: str, jpeg: bytes) -> None:
        tipo = "application/json" if objeto.endswith(".json") else "image/jpeg"
        self._cliente.bucket(self._bucket).blob(objeto).upload_from_string(
            jpeg, content_type=tipo
        )

    def apagar(self, objeto: str) -> None:
        try:
            self._cliente.bucket(self._bucket).blob(objeto).delete()
        except NotFound:
            pass

    def ler(self, objeto: str) -> bytes:
        try:
            blob = self._cliente.bucket(self._bucket).blob(objeto)
            conteudo: bytes = blob.download_as_bytes()
            return conteudo
        except NotFound as e:
            raise FotoAusente(objeto) from e


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


class RepositorioDeAuditoriaFirestore:
    """Só acrescenta: `create` falha se o id já existe, e não há como alterar nem apagar."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DA_AUDITORIA
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        self._colecao.document(registro.id).create(registro.model_dump())

    def consultar(self, filtro: FiltroDeAuditoria) -> PaginaDeAuditoria:
        # Igualdades (pessoa, alvo, ação) mais intervalo e ordem em `quando`: os
        # índices compostos estão no infra/main.tf.
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
        if filtro.de is not None:
            consulta = consulta.where(filter=FieldFilter("quando", ">=", filtro.de))
        if filtro.ate is not None:
            consulta = consulta.where(filter=FieldFilter("quando", "<=", filtro.ate))
        # O desempate implícito é o id do documento, na mesma direção da ordem.
        consulta = consulta.order_by("quando", direction=firestore.Query.DESCENDING)
        if filtro.cursor is not None:
            ancora = self._colecao.document(filtro.cursor).get()
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
            credenciais, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            sessao: Any = google.auth.transport.requests.AuthorizedSession
            self._sessao = sessao(credenciais)
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

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        try:
            return Decupagem.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_da_copia_limpa(job_id))
        try:
            blob.download_to_filename(str(destino))
        except NotFound:
            return False
        return True

    def gravar_comparacao(self, job_id: str, conteudo: str) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_da_comparacao(job_id)
        ).upload_from_string(conteudo, content_type="application/json")

    def gravar_nomes_a_buscar(self, job_id: str, conteudo: str) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_dos_nomes_a_buscar(job_id)
        ).upload_from_string(conteudo, content_type="application/json")


class NomesABuscarStorage:
    """A lista de nomes que a identificação deixou para o Job de referências, no bucket
    das decupagens (só leitura)."""

    def __init__(self, cliente: ClienteStorage, bucket_de_decupagens: str) -> None:
        self._cliente = cliente
        self._decupagens = bucket_de_decupagens

    def ler_nomes_a_buscar(self, job_id: str) -> NomesABuscar | None:
        blob = self._cliente.bucket(self._decupagens).blob(
            objeto_dos_nomes_a_buscar(job_id)
        )
        try:
            return NomesABuscar.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None


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
        gravadas = [
            JanelaGravada.model_validate_json(blob.download_as_bytes())
            for blob in self._cliente.list_blobs(
                self._aceitos, prefix=prefixo_das_janelas(job_id)
            )
        ]
        return {g.indice: g for g in gravadas}

    def gravar(self, job_id: str, janela: JanelaGravada) -> None:
        self._cliente.bucket(self._aceitos).blob(
            objeto_da_janela(job_id, janela.indice)
        ).upload_from_string(janela.model_dump_json(), content_type="application/json")


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


class QuadrosStorage(DecupagensStorage):
    """Os JPEGs dos quadros-chave no bucket das decupagens, além da cópia limpa e da Decupagem."""

    def gravar_quadro(self, job_id: str, caminho: str, jpeg: bytes) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_do_quadro(job_id, caminho)
        ).upload_from_string(jpeg, content_type="image/jpeg")


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

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        blob = self._cliente.bucket(self._decupagens).blob(
            objeto_do_quadro(job_id, caminho)
        )
        url: str = blob.generate_signed_url(
            version="v4", expiration=validade, method="GET", **self._assinatura()
        )
        return url

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        return self._leitor.abrir_decupagem(job_id)
