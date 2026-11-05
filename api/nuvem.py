"""Adaptadores de nuvem da E0: Firestore (Jobs) e Cloud Storage (upload)."""

import json
import random
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
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
from api.avaliacao import Avaliacao
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
    disposicao_do_nome,
)
from api.leitura_da_tela import LeituraDaTela
from api.lixeira import ArquivosContados
from api.marcas import MarcaDoCatalogo, MarcaInexistente, nomes_de_busca_da_marca
from api.papeis import PAPEIS, Papel
from api.progresso_das_janelas import JanelaGravada, ler_janela_gravada
from api.revisao import Medida, Pulso
from api.revisao import aplicar as aplicar_o_pulso
from api.sugestoes import ContagemDoTipo, Decisao, TipoDeSugestao, contar
from api.tipos_de_objeto import LIMITE_PADRAO, TipoDeObjeto, somar_por_chave
from api.transcricao import Transcricao
from api.usuarios import ContaDoIdentityPlatform, EmailJaCadastrado
from api.webhook import RegistroDeWebhook

COLECAO_DE_JOBS = "jobs"
COLECAO_DE_CHAVES = "chaves_de_api"
COLECAO_DE_WEBHOOKS = "webhooks"
COLECAO_DE_IDEMPOTENCIA = "chaves_de_idempotencia"
COLECAO_DE_PAPEIS = "papeis_de_usuarios"
COLECAO_DE_CORRECOES = "correcoes"
COLECAO_DO_CATALOGO = "catalogo_de_pessoas"
COLECAO_DO_CATALOGO_DE_MARCAS = "catalogo_de_marcas"
COLECAO_DAS_DECISOES_DE_SUGESTAO = "decisoes_de_sugestao"
COLECAO_DE_CONFIGURACAO = "configuracao"
COLECAO_DA_AUDITORIA = "auditoria"
COLECAO_DA_REVISAO = "tempo_de_revisao"
COLECAO_DAS_AVALIACOES = "avaliacoes"
COLECAO_DOS_TIPOS_DE_OBJETO = "tipos_de_objeto"
COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB = "tipos_de_objeto_por_job"
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


def objeto_do_resultado_dos_objetos(job_id: str) -> str:
    return f"{job_id}/objetos/florence.json"


def objeto_da_decupagem(job_id: str) -> str:
    return f"{job_id}.json"


def objeto_do_quadro(job_id: str, caminho: str) -> str:
    """`caminho` é o do campo `quadro` da Decupagem (`quadros/plano-0.jpg`)."""
    return f"{job_id}/{caminho}"


def objeto_da_copia_limpa(job_id: str) -> str:
    return f"{job_id}/copia_limpa.mp4"


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


class RepositorioFirestore:
    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_JOBS
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def salvar(self, job: Job) -> None:
        self._colecao.document(job.id).set(job.model_dump())

    def criar(self, job: Job) -> bool:
        # `Aborted` não diz que outro gravou: o documento estava travado e o `create`
        # pode ter perdido para outro que também aborta. Repete até um gravar
        # (`AlreadyExists` para os outros).
        for rodada in range(TENTATIVAS_SOB_DISPUTA):
            try:
                self._colecao.document(job.id).create(job.model_dump())
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

        return self._sob_disputa(trocar)

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

        return self._sob_disputa(trocar_na_transacao)

    def remover(self, job_id: str) -> None:
        self._colecao.document(job_id).delete()

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
        # Os índices estão no infra/modulos/mam/main.tf.
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
            transacao.set(self._colecao.document(registro.id), registro.model_dump())

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
        dados = (doc.to_dict() or {}) if doc.exists else {}
        if "papeis" not in dados:
            # Só a marca `desativada`: a conta segue sem papéis guardados.
            return None
        # Papel desconhecido (digitado à mão, papel futuro) não dá permissão nem 500.
        return [p for p in PAPEIS if p in dados["papeis"]]

    def salvar(self, uid: str, papeis: list[Papel]) -> None:
        # merge: não apaga a marca `desativada`.
        self._colecao.document(uid).set({"papeis": papeis}, merge=True)

    def desativada(self, uid: str) -> bool:
        doc = self._colecao.document(uid).get()
        return doc.exists and (doc.to_dict() or {}).get("desativada") is True

    def marcar_desativada(self, uid: str, desativada: bool) -> None:
        self._colecao.document(uid).set({"desativada": desativada}, merge=True)


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
            credenciais, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self._sessao = google.auth.transport.requests.AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]
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
        referencia = self._colecao.document(id)
        if not referencia.get().exists:
            raise PessoaInexistente(id)
        referencia.delete()


class CatalogoDeMarcasFirestore:
    """Um documento por marca, com o id estável como chave. `nomes_de_busca` (nome e
    apelidos normalizados) é o índice de `achar`."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DO_CATALOGO_DE_MARCAS
    ) -> None:
        self._colecao = cliente.collection(colecao)

    @staticmethod
    def _marca(id: str, dados: dict[str, Any]) -> MarcaDoCatalogo:
        dados = {k: v for k, v in dados.items() if k != "nomes_de_busca"}
        return MarcaDoCatalogo(id=id, **dados)

    def obter(self, id: str) -> MarcaDoCatalogo | None:
        doc = self._colecao.document(id).get()
        return self._marca(id, doc.to_dict() or {}) if doc.exists else None

    def achar(self, nome: str) -> list[MarcaDoCatalogo]:
        consulta = self._colecao.where(
            filter=FieldFilter("nomes_de_busca", "array_contains", normalizar(nome))
        )
        achadas = [self._marca(d.id, d.to_dict() or {}) for d in consulta.stream()]
        return [m for m in achadas if m.lixeira is None]

    def _lidas(self) -> list[MarcaDoCatalogo]:
        return [self._marca(d.id, d.to_dict() or {}) for d in self._colecao.stream()]

    def todas(self) -> list[MarcaDoCatalogo]:
        return [m for m in self._lidas() if m.lixeira is None]

    def na_lixeira(self) -> list[MarcaDoCatalogo]:
        return [m for m in self._lidas() if m.lixeira is not None]

    def _gravar(self, marca: MarcaDoCatalogo) -> MarcaDoCatalogo:
        self._colecao.document(marca.id).set(
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
        referencia = self._colecao.document(id)
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
        referencia = self._por_job.document(job_id)

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

    def conhecidos(self) -> list[str]:
        """A coleção inteira: a busca corta em `TETO_DA_BUSCA_DE_TIPOS` pela ordem da
        chave, e a regra das sugestões precisa de todos."""
        achados = (d.to_dict() or {} for d in self._colecao.stream())
        return [d["tipo"] for d in achados if d.get("total", 0) > 0 and d.get("tipo")]


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
            self._colecao.document(correcao.id).create(correcao.model_dump())
        except AlreadyExists:
            raise CorrecaoJaExiste(correcao.id) from None

    def listar(self, job_id: str) -> list[Correcao]:
        docs = self._colecao.where(filter=FieldFilter("job_id", "==", job_id)).stream()
        achadas = [Correcao(**(doc.to_dict() or {})) for doc in docs]
        return em_ordem(achadas)

    def purgar(self, job_id: str) -> None:
        for doc in self._colecao.where(
            filter=FieldFilter("job_id", "==", job_id)
        ).stream():
            doc.reference.delete()


class RepositorioDeSugestoesFirestore:
    """Uma decisão do editor por vídeo e sugestão (a chave é `<job>:<sugestão>`): decidir
    de novo a mesma sugestão troca a decisão, não soma outra."""

    def __init__(
        self,
        cliente: firestore.Client,
        colecao: str = COLECAO_DAS_DECISOES_DE_SUGESTAO,
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def registrar(
        self, job_id: str, sugestao_id: str, tipo: TipoDeSugestao, decisao: Decisao
    ) -> None:
        self._colecao.document(f"{job_id}:{sugestao_id}").set(
            {
                "job_id": job_id,
                "sugestao_id": sugestao_id,
                "tipo": tipo,
                "decisao": decisao,
            }
        )

    def decididas(self, job_id: str) -> set[str]:
        consulta = self._colecao.where(filter=FieldFilter("job_id", "==", job_id))
        return {(d.to_dict() or {})["sugestao_id"] for d in consulta.stream()}

    def contagem(self) -> dict[str, ContagemDoTipo]:
        docs = [d.to_dict() or {} for d in self._colecao.stream()]
        return contar((d["tipo"], d["decisao"]) for d in docs)


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
        self._colecao.document(registro.id).create(registro.model_dump())

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


class RepositorioDeRevisaoFirestore:
    """Um documento por vídeo e pessoa (`<job>:<uid>`); o pulso é aplicado numa transação."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DA_REVISAO
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def aplicar(self, pulso: Pulso, limite_s: float) -> Medida:
        referencia = self._colecao.document(f"{pulso.job_id}:{pulso.uid}")

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


class RepositorioDeAvaliacoesFirestore:
    """Um documento por vídeo e dia (`<dia>:<job>`), da avaliação por rubrica (#255)."""

    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DAS_AVALIACOES
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def gravar(self, avaliacao: Avaliacao) -> None:
        self._colecao.document(f"{avaliacao.dia.isoformat()}:{avaliacao.job_id}").set(
            avaliacao.model_dump(mode="json")
        )

    def do_dia(self, dia: date) -> list[Avaliacao]:
        return self.entre(dia, dia)

    def entre(self, de: date, ate: date) -> list[Avaliacao]:
        docs = (
            self._colecao.where(filter=FieldFilter("dia", ">=", de.isoformat()))
            .where(filter=FieldFilter("dia", "<=", ate.isoformat()))
            .stream()
        )
        return [Avaliacao(**(d.to_dict() or {})) for d in docs]


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
            credenciais, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            sessao: Any = google.auth.transport.requests.AuthorizedSession
            self._sessao = sessao(credenciais)
        return self._sessao

    def iniciar(self, job_id: str) -> None:
        corpo = {
            "overrides": {
                "containerOverrides": [{"env": [{"name": "JOB_ID", "value": job_id}]}]
            }
        }
        try:
            resposta = self._sessao_autenticada().post(
                self._url, json=corpo, timeout=30
            )
            resposta.raise_for_status()
        except requests.RequestException as e:
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

    def gravar_texto(self, objeto: str, conteudo: str) -> None:
        """Um JSON solto no bucket das decupagens (a medição do Florence-2, #329)."""
        self._cliente.bucket(self._decupagens).blob(objeto).upload_from_string(
            conteudo, content_type="application/json"
        )


class QuadrosStorage(DecupagensStorage):
    """Os JPEGs dos quadros-chave no bucket das decupagens, além da cópia limpa e da Decupagem."""

    def gravar_quadro(self, job_id: str, caminho: str, jpeg: bytes) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_do_quadro(job_id, caminho)
        ).upload_from_string(jpeg, content_type="image/jpeg")


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
        for bucket in (self._aceitos, self._decupagens):
            for blob in self._cliente.list_blobs(bucket, prefix=f"{job_id}/"):
                blob.delete()
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        if blob.exists():
            blob.delete()


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

    def url_de_download(self, job_id: str, nome: str, validade: timedelta) -> str:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_da_copia_limpa(job_id))
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
        blob = self._cliente.bucket(self._decupagens).blob(
            objeto_do_quadro(job_id, caminho)
        )
        url: str = blob.generate_signed_url(
            version="v4", expiration=validade, method="GET", **self._assinatura()
        )
        return url

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        return self._leitor.abrir_decupagem(job_id)
