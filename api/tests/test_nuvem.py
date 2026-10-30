"""Adaptadores de nuvem. Firestore e Storage rodam contra os emuladores.

Sem `FIRESTORE_EMULATOR_HOST` / `STORAGE_EMULATOR_HOST`, os testes de integração
são pulados; no CI os emuladores sobem antes do pytest.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import credentials as google_credentials
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from google.oauth2 import service_account

from api.chaves import LimiteDeChavesAtivas, RegistroDeChave
from api.jobs import Job, ServicoIndisponivel
from api.nuvem import (
    ArmazenamentoStorage,
    RepositorioDeChavesFirestore,
    RepositorioFirestore,
)

EMULADOR_FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
EMULADOR_STORAGE = os.environ.get("STORAGE_EMULATOR_HOST")
BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _anonima() -> AnonymousCredentials:
    return AnonymousCredentials()  # type: ignore[no-untyped-call]


def _job(id: str, criado_em: datetime, **extra: object) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=1000,
        estado="aguardando_upload",
        criado_por="uid-1",
        criado_em=criado_em,
        atualizado_em=criado_em,
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
def repositorio() -> RepositorioFirestore:
    cliente = firestore.Client(project="teste", credentials=_anonima())
    return RepositorioFirestore(cliente, colecao=f"jobs-{uuid.uuid4().hex}")


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioFirestore:
    def test_salva_e_obtem_o_job(self, repositorio: RepositorioFirestore) -> None:
        job = _job("a", BASE, sha256="ab" * 32, duracao_s=12.5)

        repositorio.salvar(job)

        assert repositorio.obter("a") == job

    def test_obter_devolve_none_se_nao_existe(
        self, repositorio: RepositorioFirestore
    ) -> None:
        assert repositorio.obter("nao-existe") is None

    def test_salvar_de_novo_atualiza_o_job(
        self, repositorio: RepositorioFirestore
    ) -> None:
        repositorio.salvar(_job("a", BASE))
        repositorio.salvar(
            _job("a", BASE, codigo_falha="upload_expirado").model_copy(
                update={"estado": "falhou"}
            )
        )

        job = repositorio.obter("a")
        assert job is not None
        assert (job.estado, job.codigo_falha) == ("falhou", "upload_expirado")

    def test_lista_do_mais_recente_para_o_mais_antigo(
        self, repositorio: RepositorioFirestore
    ) -> None:
        for id, minutos in [("velho", 0), ("novo", 20), ("meio", 10)]:
            repositorio.salvar(_job(id, BASE + timedelta(minutes=minutos)))

        assert [j.id for j in repositorio.listar()] == ["novo", "meio", "velho"]

    def test_lista_por_sistema_so_traz_os_jobs_do_sistema(
        self, repositorio: RepositorioFirestore
    ) -> None:
        for id, minutos, sistema in [
            ("a-velho", 0, "A"),
            ("b", 5, "B"),
            ("pessoa", 7, None),
            ("a-novo", 10, "A"),
        ]:
            repositorio.salvar(
                _job(id, BASE + timedelta(minutes=minutos)).model_copy(
                    update={"sistema": sistema}
                )
            )

        assert [j.id for j in repositorio.listar_por_sistema("A")] == [
            "a-novo",
            "a-velho",
        ]


def _credencial_local() -> google_credentials.Signing:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = chave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call, no-any-return]
        {
            "type": "service_account",
            "client_email": "mam-web@teste.iam.gserviceaccount.com",
            "private_key": pem,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


@pytest.fixture
def armazenamento() -> ArmazenamentoStorage:
    endpoint = EMULADOR_STORAGE or "http://localhost:4443"
    cliente = ClienteStorage(
        project="teste",
        credentials=_anonima(),
        client_options={"api_endpoint": endpoint},
    )
    credencial = _credencial_local()
    sufixo = uuid.uuid4().hex[:8]
    return ArmazenamentoStorage(
        cliente,
        f"teste-quarentena-{sufixo}",
        f"teste-aceitos-{sufixo}",
        f"teste-decupagens-{sufixo}",
        assinatura=lambda: {"credentials": credencial},
    )


def test_url_de_upload_prende_tipo_e_tamanho_declarados(
    armazenamento: ArmazenamentoStorage,
) -> None:
    url = armazenamento.url_de_upload("job1", 123456, "video/mp4")

    consulta = parse_qs(urlparse(url).query)
    assinados = consulta["X-Goog-SignedHeaders"][0].split(";")
    assert {"content-type", "x-upload-content-length", "x-goog-resumable"} <= set(
        assinados
    )
    assert "job1" in urlparse(url).path
    assert "teste-quarentena" in url


def test_cancelar_upload_segue_indisponivel(
    armazenamento: ArmazenamentoStorage,
) -> None:
    with pytest.raises(ServicoIndisponivel):
        armazenamento.cancelar_upload("job1")


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_url_de_upload_inicia_upload_retomavel_no_emulador(
    armazenamento: ArmazenamentoStorage,
) -> None:
    # Só para criar o bucket do emulador; o nome é único a cada teste.
    armazenamento._cliente.create_bucket(armazenamento._bucket)
    url = armazenamento.url_de_upload("job1", 5, "video/mp4")

    resposta = requests.post(
        url,
        headers={
            "Content-Type": "video/mp4",
            "x-goog-resumable": "start",
            "x-upload-content-length": "5",
        },
    )

    assert resposta.status_code in (200, 201)
    assert "upload_id" in resposta.headers["Location"]


def _com_buckets(armazenamento: ArmazenamentoStorage) -> ArmazenamentoStorage:
    for nome in (armazenamento._aceitos, armazenamento._decupagens):
        armazenamento._cliente.create_bucket(nome)
    return armazenamento


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_url_de_reproducao_devolve_o_proxy_por_get(
    armazenamento: ArmazenamentoStorage,
) -> None:
    _com_buckets(armazenamento)
    armazenamento._cliente.bucket(armazenamento._aceitos).blob(
        "job1/proxy.mp4"
    ).upload_from_string(b"proxy-bytes", content_type="video/mp4")

    url = armazenamento.url_de_reproducao("job1", timedelta(minutes=10))

    consulta = parse_qs(urlparse(url).query)
    assert consulta["X-Goog-Expires"] == ["600"]
    assert "teste-aceitos" in url and "job1/proxy.mp4" in url
    # O emulador responde no próprio endereço; só o host da URL assinada muda.
    partes = urlparse(url)
    resposta = requests.get(f"{EMULADOR_STORAGE}{partes.path}?{partes.query}")
    assert resposta.status_code == 200
    assert resposta.content == b"proxy-bytes"


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_abrir_decupagem_le_o_json_em_pedacos(
    armazenamento: ArmazenamentoStorage,
) -> None:
    _com_buckets(armazenamento)
    armazenamento._cliente.bucket(armazenamento._decupagens).blob(
        "job1.json"
    ).upload_from_string(b'{"a": 1}', content_type="application/json")

    assert b"".join(armazenamento.abrir_decupagem("job1")) == b'{"a": 1}'


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_abrir_decupagem_inexistente_vira_servico_indisponivel(
    armazenamento: ArmazenamentoStorage,
) -> None:
    _com_buckets(armazenamento)

    with pytest.raises(ServicoIndisponivel):
        next(armazenamento.abrir_decupagem("nao-existe"))


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDeChavesFirestore:
    @pytest.fixture
    def chaves(self) -> RepositorioDeChavesFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDeChavesFirestore(
            cliente, colecao=f"chaves-{uuid.uuid4().hex}"
        )

    def test_salva_e_obtem_o_registro(
        self, chaves: RepositorioDeChavesFirestore
    ) -> None:
        registro = RegistroDeChave(
            id="abc",
            sistema="Legado",
            escopos=["ler"],
            hmac="ff" * 32,
            versao_mac=2,
            criada_em=BASE,
        )

        chaves.salvar(registro)

        assert chaves.obter("abc") == registro

    def test_obter_devolve_none_se_nao_existe(
        self, chaves: RepositorioDeChavesFirestore
    ) -> None:
        assert chaves.obter("nao-existe") is None

    def test_transacao_impede_a_terceira_chave_ativa(
        self, chaves: RepositorioDeChavesFirestore
    ) -> None:
        def registro(id: str) -> RegistroDeChave:
            return RegistroDeChave(
                id=id,
                sistema="Legado",
                escopos=["ler"],
                hmac="ff",
                versao_mac=1,
                criada_em=BASE,
            )

        chaves.salvar_nova(registro("a"), 2)
        chaves.salvar_nova(registro("b"), 2)
        with pytest.raises(LimiteDeChavesAtivas):
            chaves.salvar_nova(registro("c"), 2)
        assert chaves.obter("c") is None

        chaves.salvar(registro("a").model_copy(update={"revogada_em": BASE}))
        chaves.salvar_nova(registro("c"), 2)

        assert [r.id for r in chaves.listar_por_sistema("Legado")] == ["a", "b", "c"]
