"""Adaptadores de nuvem. Firestore e Storage rodam contra os emuladores.

Sem `FIRESTORE_EMULATOR_HOST` / `STORAGE_EMULATOR_HOST`, os testes de integração
são pulados; no CI os emuladores sobem antes do pytest.
"""

import contextlib
import os
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.api_core.exceptions import Aborted, AlreadyExists, NotFound
from google.auth import credentials as google_credentials
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from google.oauth2 import service_account

from api.auditoria import FiltroDeAuditoria, RegistroDeAuditoria
from api.catalogo import EnvioParaLixeira, FusaoDaPessoa, PessoaInexistente
from api.chaves import LimiteDeChavesAtivas, RegistroDeChave
from api.correcoes import Ancora, Correcao, CorrecaoJaExiste, Ocorrencia
from api.idempotencia import nova_reserva
from api.jobs import (
    CursorInvalido,
    FiltroDeJobs,
    Job,
    ServicoIndisponivel,
    palavras_do_nome,
)
from api.marcas import MarcaInexistente, carregar_marcas
from api.nuvem import (
    TENTATIVAS_SOB_DISPUTA,
    ArmazenamentoStorage,
    ArquivosNoStorage,
    CatalogoDeMarcasFirestore,
    CatalogoFirestore,
    ProgramasFirestore,
    ReferenciasStorage,
    RepositorioDeAprovacaoFirestore,
    RepositorioDeAuditoriaFirestore,
    RepositorioDeChavesFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioDeIdempotenciaFirestore,
    RepositorioDePapeisFirestore,
    RepositorioDeWebhooksFirestore,
    RepositorioFirestore,
    TiposDeObjetoFirestore,
    espera_sob_disputa,
)
from api.programas import NomeEmUso, Programa, RenomeacaoDoPrograma
from api.webhook import RegistroDeWebhook

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

    def test_obter_varios_le_em_lote_so_os_que_existem(
        self, repositorio: RepositorioFirestore
    ) -> None:
        for id in ("a", "b", "c"):
            repositorio.salvar(_job(id, BASE))

        achados = repositorio.obter_varios(["a", "c", "c", "nao-existe"])

        assert sorted(j.id for j in achados) == ["a", "c"]
        assert repositorio.obter_varios([]) == []

    def test_obter_varios_le_mais_de_um_lote(
        self, repositorio: RepositorioFirestore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("api.nuvem._LOTE_DE_LEITURA", 2)
        for id in ("a", "b", "c", "d", "e"):
            repositorio.salvar(_job(id, BASE))

        achados = repositorio.obter_varios(["e", "d", "c", "b", "a", "x"])

        assert sorted(j.id for j in achados) == ["a", "b", "c", "d", "e"]

    def test_remover_apaga_o_job_e_repetir_nao_da_erro(
        self, repositorio: RepositorioFirestore
    ) -> None:
        repositorio.salvar(_job("a", BASE))
        repositorio.salvar(_job("b", BASE))

        repositorio.remover("a")
        repositorio.remover("a")

        assert repositorio.obter("a") is None
        assert repositorio.obter("b") is not None

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

    def test_transitar_grava_quando_o_job_esta_na_origem(
        self, repositorio: RepositorioFirestore
    ) -> None:
        repositorio.salvar(_job("a", BASE))

        novo = repositorio.transitar("a", "aguardando_upload", {"estado": "validando"})

        assert novo is not None and novo.estado == "validando"
        assert repositorio.obter("a") == novo

    def test_transitar_de_estado_que_nao_e_mais_o_atual_nao_grava_nada(
        self, repositorio: RepositorioFirestore
    ) -> None:
        cancelado = _job("a", BASE).model_copy(update={"estado": "cancelado"})
        repositorio.salvar(cancelado)

        novo = repositorio.transitar(
            "a", "aguardando_upload", {"estado": "validando", "sha256": "ab" * 32}
        )

        assert novo is None
        assert repositorio.obter("a") == cancelado

    def test_transitar_job_inexistente_devolve_none(
        self, repositorio: RepositorioFirestore
    ) -> None:
        assert repositorio.transitar("x", "aguardando_upload", {}) is None

    def test_lista_do_mais_recente_para_o_mais_antigo(
        self, repositorio: RepositorioFirestore
    ) -> None:
        for id, minutos in [("velho", 0), ("novo", 20), ("meio", 10)]:
            repositorio.salvar(_job(id, BASE + timedelta(minutes=minutos)))

        assert [j.id for j in repositorio.listar()] == ["novo", "meio", "velho"]

    def test_consulta_combina_filtros_ordem_e_cursor(
        self, repositorio: RepositorioFirestore
    ) -> None:
        dias = [20, 20, 19, None, 18, 20]
        for i, dia in enumerate(dias):
            repositorio.salvar(
                _job(
                    f"j{i}",
                    BASE + timedelta(minutes=i),
                    programa="TV Fama" if i != 4 else "Outro",
                    data_exibicao=date(2026, 10, dia) if dia else None,
                    palavras=palavras_do_nome(
                        "FAMA_BLU.mp4" if i != 5 else "FAMA_RED.mp4"
                    ),
                ).model_copy(update={"estado": "falhou" if i == 1 else "concluido"})
            )

        def ids(**filtro: Any) -> list[str]:
            return [j.id for j in repositorio.consultar(FiltroDeJobs(**filtro)).jobs]

        assert ids() == ["j5", "j4", "j3", "j2", "j1", "j0"]
        assert ids(programa="TV Fama", estados=frozenset({"concluido"})) == [
            "j5",
            "j3",
            "j2",
            "j0",
        ]
        assert ids(palavras=("fama", "blu")) == ["j4", "j3", "j2", "j1", "j0"]
        assert ids(
            programa="TV Fama",
            estados=frozenset({"concluido"}),
            exibicao_de=date(2026, 10, 19),
            exibicao_ate=date(2026, 10, 20),
            ordem="exibicao",
        ) == ["j5", "j0", "j2"]
        assert ids(ordem="exibicao") == ["j5", "j1", "j0", "j2", "j4", "j3"]
        paginas, cursor = [], None
        while True:
            pagina = repositorio.consultar(
                FiltroDeJobs(ordem="exibicao", limite=4, cursor=cursor)
            )
            paginas.append([j.id for j in pagina.jobs])
            cursor = pagina.proximo_cursor
            if cursor is None:
                break
        assert paginas == [["j5", "j1", "j0", "j2"], ["j4", "j3"]]

    def test_consulta_com_cursor_inexistente_levanta(
        self, repositorio: RepositorioFirestore
    ) -> None:
        with pytest.raises(CursorInvalido):
            repositorio.consultar(FiltroDeJobs(limite=1, cursor="nada"))

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

        assert [
            j.id for j in repositorio.consultar(FiltroDeJobs(sistema="A")).jobs
        ] == [
            "a-novo",
            "a-velho",
        ]

    def test_lixeira_traz_so_os_da_lixeira_do_envio_mais_recente_ao_mais_antigo(
        self, repositorio: RepositorioFirestore
    ) -> None:
        def lixeira(dias: int) -> EnvioParaLixeira:
            return EnvioParaLixeira(
                em=BASE + timedelta(days=dias),
                por_uid="adm",
                por_email="ana@redetv.com",
                motivo="duplicado",
            )

        repositorio.salvar(_job("fora", BASE))
        repositorio.salvar(_job("velho", BASE, lixeira=lixeira(1)))
        repositorio.salvar(_job("novo", BASE - timedelta(days=9), lixeira=lixeira(3)))
        repositorio.salvar(_job("meio", BASE, lixeira=lixeira(2)))

        ids = [j.id for j in repositorio.consultar(FiltroDeJobs(na_lixeira=True)).jobs]

        assert ids == ["novo", "meio", "velho"]
        assert [j.id for j in repositorio.consultar(FiltroDeJobs()).jobs] == ["fora"]

    def test_lixeira_e_sha256_leem_so_os_documentos_que_devolvem(
        self, repositorio: RepositorioFirestore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        envio = EnvioParaLixeira(
            em=BASE, por_uid="adm", por_email="ana@redetv.com", motivo="duplicado"
        )
        for i in range(30):
            repositorio.salvar(_job(f"x{i}", BASE, sha256=f"{i:064x}"))
        repositorio.salvar(_job("alvo", BASE, sha256="a" * 64))
        repositorio.salvar(_job("igual", BASE, sha256="a" * 64))
        for i in range(3):
            repositorio.salvar(_job(f"l{i}", BASE, lixeira=envio))
        lidos = {"documentos": 0}
        stream = firestore.Query.stream

        def contar(consulta: firestore.Query, *args: Any, **kwargs: Any) -> Any:
            for doc in stream(consulta, *args, **kwargs):
                lidos["documentos"] += 1
                yield doc

        monkeypatch.setattr(firestore.Query, "stream", contar)

        assert len(repositorio.consultar(FiltroDeJobs(na_lixeira=True)).jobs) == 3
        assert lidos["documentos"] == 3
        filtro = FiltroDeJobs(sha256="a" * 64, na_lixeira=None)
        assert len(repositorio.consultar(filtro).jobs) == 2
        assert lidos["documentos"] == 5

    def test_pessoa_e_marca_do_catalogo_acham_so_os_jobs_certos(
        self, repositorio: RepositorioFirestore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for i in range(30):
            repositorio.salvar(_job(f"x{i}", BASE, pessoas_do_catalogo=[f"o{i}"]))
        repositorio.salvar(
            _job("a", BASE, pessoas_do_catalogo=["p1", "p2"], marcas_do_catalogo=["m1"])
        )
        repositorio.salvar(
            _job("b", BASE + timedelta(minutes=1), pessoas_do_catalogo=["p1"])
        )
        repositorio.salvar(_job("c", BASE, pessoas_do_catalogo=["p2"]))
        lidos = {"documentos": 0}
        stream = firestore.Query.stream

        def contar(consulta: firestore.Query, *args: Any, **kwargs: Any) -> Any:
            for doc in stream(consulta, *args, **kwargs):
                lidos["documentos"] += 1
                yield doc

        monkeypatch.setattr(firestore.Query, "stream", contar)

        da_pessoa = repositorio.consultar(FiltroDeJobs(pessoa_do_catalogo="p1"))
        assert [j.id for j in da_pessoa.jobs] == ["b", "a"]
        assert lidos["documentos"] == 2
        da_marca = repositorio.consultar(FiltroDeJobs(marca_do_catalogo="m1"))
        assert [j.id for j in da_marca.jobs] == ["a"]
        assert lidos["documentos"] == 3

    def test_lixeira_com_outro_filtro_confere_o_resto_em_python(
        self, repositorio: RepositorioFirestore
    ) -> None:
        envio = EnvioParaLixeira(
            em=BASE, por_uid="adm", por_email="ana@redetv.com", motivo="duplicado"
        )
        repositorio.salvar(_job("a", BASE, programa="Jornal", lixeira=envio))
        repositorio.salvar(_job("b", BASE, programa="Outro", lixeira=envio))

        filtro = FiltroDeJobs(na_lixeira=True, programa="Jornal")

        assert [j.id for j in repositorio.consultar(filtro).jobs] == ["a"]

    def test_sha256_traz_so_os_do_mesmo_arquivo_na_lixeira_ou_fora_dela(
        self, repositorio: RepositorioFirestore
    ) -> None:
        envio = EnvioParaLixeira(
            em=BASE, por_uid="adm", por_email="ana@redetv.com", motivo="duplicado"
        )
        repositorio.salvar(_job("a", BASE, sha256="a" * 64))
        repositorio.salvar(_job("b", BASE + timedelta(minutes=1), sha256="b" * 64))
        repositorio.salvar(
            _job("c", BASE + timedelta(minutes=2), sha256="a" * 64, lixeira=envio)
        )

        todos = repositorio.consultar(FiltroDeJobs(sha256="a" * 64, na_lixeira=None))
        so_acervo = repositorio.consultar(FiltroDeJobs(sha256="a" * 64))

        assert [j.id for j in todos.jobs] == ["c", "a"]
        assert [j.id for j in so_acervo.jobs] == ["a"]


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


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_cancelar_upload_apaga_o_objeto_da_quarentena(
    armazenamento: ArmazenamentoStorage,
) -> None:
    bucket = armazenamento._cliente.create_bucket(armazenamento._bucket)
    bucket.blob("job1").upload_from_string(b"parcial")

    armazenamento.cancelar_upload("job1")

    assert not bucket.blob("job1").exists()


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_cancelar_upload_sem_objeto_nao_falha(
    armazenamento: ArmazenamentoStorage,
) -> None:
    armazenamento._cliente.create_bucket(armazenamento._bucket)

    armazenamento.cancelar_upload("nunca-subiu")


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
def test_url_de_download_devolve_a_copia_limpa_como_anexo_com_o_nome(
    armazenamento: ArmazenamentoStorage,
) -> None:
    _com_buckets(armazenamento)
    armazenamento._cliente.bucket(armazenamento._aceitos).blob(
        "job1/copia_limpa.mp4"
    ).upload_from_string(b"copia-bytes", content_type="video/mp4")

    url = armazenamento.url_de_download(
        "job1", 'Jornal "Ação"; 1.mp4', timedelta(minutes=5)
    )

    consulta = parse_qs(urlparse(url).query)
    assert consulta["X-Goog-Expires"] == ["300"]
    assert "teste-aceitos" in url and "job1/copia_limpa.mp4" in url
    disposicao = (
        'attachment; filename="Jornal _Acao__ 1.mp4"; '
        "filename*=UTF-8''Jornal%20%22A%C3%A7%C3%A3o%22%3B%201.mp4"
    )
    assert consulta["response-content-disposition"] == [disposicao]
    partes = urlparse(url)
    resposta = requests.get(f"{EMULADOR_STORAGE}{partes.path}?{partes.query}")
    assert resposta.status_code == 200
    assert resposta.content == b"copia-bytes"


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


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_arquivos_no_storage_conta_o_que_o_job_tem(
    armazenamento: ArmazenamentoStorage,
) -> None:
    _com_buckets(armazenamento)
    aceitos = armazenamento._cliente.bucket(armazenamento._aceitos)
    decupagens = armazenamento._cliente.bucket(armazenamento._decupagens)
    aceitos.blob("job1/proxy.mp4").upload_from_string(b"x")
    decupagens.blob("job1.json").upload_from_string(b"{}")
    decupagens.blob("job1/quadros/plano-0.jpg").upload_from_string(b"x")
    decupagens.blob("job1/quadros/plano-1.jpg").upload_from_string(b"x")
    decupagens.blob("job2/quadros/plano-0.jpg").upload_from_string(b"x")
    arquivos = ArquivosNoStorage(
        armazenamento._cliente, armazenamento._aceitos, armazenamento._decupagens
    )

    contados = arquivos.contar("job1")

    assert (contados.decupagem, contados.proxy, contados.quadros) == (1, 1, 2)
    assert contados.copia_limpa == 0


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_arquivos_no_storage_apaga_tudo_do_job_e_nada_de_outro(
    armazenamento: ArmazenamentoStorage,
) -> None:
    _com_buckets(armazenamento)
    aceitos = armazenamento._cliente.bucket(armazenamento._aceitos)
    decupagens = armazenamento._cliente.bucket(armazenamento._decupagens)
    do_job = {
        aceitos: ["job1/proxy.mp4", "job1/copia_limpa.mp4", "job1/janelas/0000.json"],
        decupagens: ["job1.json", "job1.comparacao.json", "job1/quadros/plano-0.jpg"],
    }
    de_outro = {aceitos: ["job10/proxy.mp4"], decupagens: ["job10.json", "job2.json"]}
    for bucket, objetos in (do_job | de_outro).items():
        for objeto in objetos:
            bucket.blob(objeto).upload_from_string(b"x")
    arquivos = ArquivosNoStorage(
        armazenamento._cliente, armazenamento._aceitos, armazenamento._decupagens
    )

    arquivos.apagar("job1")
    arquivos.apagar("job1")

    assert not any(b.blob(o).exists() for b, os in do_job.items() for o in os)
    assert all(b.blob(o).exists() for b, os in de_outro.items() for o in os)


@pytest.mark.skipif(not EMULADOR_STORAGE, reason="sem emulador do Storage")
def test_referencias_apagam_a_pasta_da_pessoa_e_nada_de_outra(
    armazenamento: ArmazenamentoStorage,
) -> None:
    nome = f"teste-referencias-{uuid.uuid4().hex[:8]}"
    bucket = armazenamento._cliente.create_bucket(nome)
    da_pessoa = ["referencias/ana/0.jpg", "referencias/ana/velha.jpg"]
    de_outra = ["referencias/ana2/0.jpg", "palpites/ana/0.jpg"]
    for objeto in da_pessoa + de_outra:
        bucket.blob(objeto).upload_from_string(b"x")
    fotos = ReferenciasStorage(armazenamento._cliente, nome)

    fotos.apagar_prefixo("referencias/ana/")
    fotos.apagar_prefixo("referencias/ana/")

    assert not any(bucket.blob(o).exists() for o in da_pessoa)
    assert all(bucket.blob(o).exists() for o in de_outra)


def _registro_de_chave(id: str) -> RegistroDeChave:
    return RegistroDeChave(
        id=id,
        sistema="Legado",
        escopos=["ler"],
        hmac="ff",
        versao_mac=1,
        criada_em=BASE,
    )


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
        registro = _registro_de_chave

        chaves.salvar_nova(registro("a"), 2)
        chaves.salvar_nova(registro("b"), 2)
        with pytest.raises(LimiteDeChavesAtivas):
            chaves.salvar_nova(registro("c"), 2)
        assert chaves.obter("c") is None

        chaves.salvar(registro("a").model_copy(update={"revogada_em": BASE}))
        chaves.salvar_nova(registro("c"), 2)

        assert [r.id for r in chaves.listar_por_sistema("Legado")] == ["a", "b", "c"]

    def test_listar_traz_todos_os_sistemas_das_mais_novas_para_as_mais_antigas(
        self, chaves: RepositorioDeChavesFirestore
    ) -> None:
        chaves.salvar(_registro_de_chave("velha"))
        chaves.salvar(
            _registro_de_chave("nova").model_copy(
                update={"sistema": "Outro", "criada_em": BASE + timedelta(hours=1)}
            )
        )

        assert [r.id for r in chaves.listar()] == ["nova", "velha"]

    def test_dois_comandos_simultaneos_nao_criam_a_terceira(
        self, chaves: RepositorioDeChavesFirestore
    ) -> None:
        chaves.salvar_nova(_registro_de_chave("a"), 2)
        largada = threading.Barrier(2)
        gravadas: list[str] = []

        def emitir(id: str) -> None:
            largada.wait()
            # Perder a disputa é recusa (limite) ou transação abortada pelo
            # Firestore depois das tentativas: nos dois casos nada é gravado.
            with contextlib.suppress(ValueError):
                chaves.salvar_nova(_registro_de_chave(id), 2)
                gravadas.append(id)

        corridas = [threading.Thread(target=emitir, args=(i,)) for i in ("b", "c")]
        for corrida in corridas:
            corrida.start()
        for corrida in corridas:
            corrida.join()

        assert len(gravadas) <= 1
        ids = [r.id for r in chaves.listar_por_sistema("Legado")]
        assert sorted(ids) == sorted(["a", *gravadas])

    def test_chave_gravada_sem_o_campo_de_revogacao_conta_como_ativa(self) -> None:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        colecao = f"chaves-{uuid.uuid4().hex}"
        chaves = RepositorioDeChavesFirestore(cliente, colecao=colecao)
        for id in ("antiga-1", "antiga-2"):
            # Como as chaves emitidas antes da revogação existir: sem `revogada_em`.
            antiga = _registro_de_chave(id).model_dump(exclude={"revogada_em"})
            cliente.collection(colecao).document(id).set(antiga)

        with pytest.raises(LimiteDeChavesAtivas):
            chaves.salvar_nova(_registro_de_chave("nova"), 2)


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDeWebhooksFirestore:
    @pytest.fixture
    def webhooks(self) -> RepositorioDeWebhooksFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDeWebhooksFirestore(
            cliente, colecao=f"webhooks-{uuid.uuid4().hex}"
        )

    def test_salva_e_obtem_o_registro(
        self, webhooks: RepositorioDeWebhooksFirestore
    ) -> None:
        registro = RegistroDeWebhook(sistema="Legado", url="https://a.example/cb")

        webhooks.salvar(registro)

        assert webhooks.obter("Legado") == registro

    def test_salvar_de_novo_troca_a_url(
        self, webhooks: RepositorioDeWebhooksFirestore
    ) -> None:
        webhooks.salvar(RegistroDeWebhook(sistema="Legado", url="https://a.example/1"))
        webhooks.salvar(RegistroDeWebhook(sistema="Legado", url="https://a.example/2"))

        registro = webhooks.obter("Legado")
        assert registro is not None and registro.url == "https://a.example/2"

    def test_obter_devolve_none_se_nao_existe(
        self, webhooks: RepositorioDeWebhooksFirestore
    ) -> None:
        assert webhooks.obter("Nenhum") is None


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDePapeisFirestore:
    @pytest.fixture
    def papeis(self) -> RepositorioDePapeisFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDePapeisFirestore(
            cliente, colecao=f"papeis-{uuid.uuid4().hex}"
        )

    def test_uid_sem_documento_devolve_none(
        self, papeis: RepositorioDePapeisFirestore
    ) -> None:
        assert papeis.obter("u1") is None

    def test_grava_e_le_os_papeis_do_uid(
        self, papeis: RepositorioDePapeisFirestore
    ) -> None:
        papeis.salvar("u1", ["curador", "operador"])

        assert papeis.obter("u1") == ["operador", "curador"]
        assert papeis.obter("u2") is None

    def test_papel_desconhecido_no_documento_e_ignorado(
        self, papeis: RepositorioDePapeisFirestore
    ) -> None:
        papeis._colecao.document("u1").set({"papeis": ["chefe", "editor"]})

        assert papeis.obter("u1") == ["editor"]

    def test_salvar_de_novo_troca_os_papeis(
        self, papeis: RepositorioDePapeisFirestore
    ) -> None:
        papeis.salvar("u1", ["curador"])
        papeis.salvar("u1", ["consulta"])

        assert papeis.obter("u1") == ["consulta"]

    def test_marca_de_desativada_nao_cria_papeis_e_sobrevive_a_salvar(
        self, papeis: RepositorioDePapeisFirestore
    ) -> None:
        assert not papeis.desativada("u1")

        papeis.marcar_desativada("u1", True)

        assert papeis.desativada("u1")
        assert papeis.obter("u1") is None
        papeis.salvar("u1", ["editor"])
        assert papeis.desativada("u1")
        assert papeis.obter("u1") == ["editor"]
        papeis.marcar_desativada("u1", False)
        assert not papeis.desativada("u1")
        assert papeis.obter("u1") == ["editor"]


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDeAprovacaoFirestore:
    @pytest.fixture
    def aprovacao(self) -> RepositorioDeAprovacaoFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDeAprovacaoFirestore(
            cliente, colecao=f"configuracao-{uuid.uuid4().hex}"
        )

    def test_sem_documento_nada_exige_aprovacao(
        self, aprovacao: RepositorioDeAprovacaoFirestore
    ) -> None:
        assert aprovacao.tipos() == frozenset()

    def test_grava_e_le_os_tipos_e_a_lista_vazia_limpa(
        self, aprovacao: RepositorioDeAprovacaoFirestore
    ) -> None:
        aprovacao.definir(frozenset({"pauta.titulo", "pessoa.renomear"}))
        assert aprovacao.tipos() == {"pauta.titulo", "pessoa.renomear"}

        aprovacao.definir(frozenset())
        assert aprovacao.tipos() == frozenset()

    def test_mudar_um_tipo_nao_regrava_os_outros(
        self, aprovacao: RepositorioDeAprovacaoFirestore
    ) -> None:
        aprovacao.mudar("pauta.titulo", True)
        # A mudança de outra pessoa, em outro tipo, fica.
        aprovacao.mudar("pessoa.renomear", True)
        aprovacao.mudar("pauta.titulo", False)

        assert aprovacao.tipos() == {"pessoa.renomear"}

    def test_tipo_desconhecido_no_documento_e_ignorado(
        self, aprovacao: RepositorioDeAprovacaoFirestore
    ) -> None:
        aprovacao._documento.set({"tipos": ["pauta.foo", "pauta.titulo"]})

        assert aprovacao.tipos() == {"pauta.titulo"}


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDeCorrecoesFirestore:
    def test_guarda_a_pendente_e_a_decisao_com_a_original(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        pendente = self._correcao("c1", "j1", 1).model_copy(
            update={"exige_aprovacao": True}
        )
        aprovacao = self._correcao("c1-decidida", "j1", 2).model_copy(
            update={"tipo": "aprovar", "aprova": "c1"}
        )
        recusa = self._correcao("c2-decidida", "j1", 3).model_copy(
            update={"tipo": "recusar", "recusa": "c2"}
        )
        for c in (pendente, aprovacao, recusa):
            correcoes.acrescentar(c)

        lidos = {c.id: c for c in correcoes.listar("j1")}
        assert lidos["c1"].exige_aprovacao
        assert lidos["c1-decidida"].aprova == "c1"
        assert lidos["c2-decidida"].recusa == "c2"

    def test_purgar_apaga_so_as_correcoes_do_video(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        for id, job_id in (("c1", "j1"), ("c2", "j1"), ("c3", "j2")):
            correcoes.acrescentar(self._correcao(id, job_id, 1))

        correcoes.purgar("j1")

        assert correcoes.listar("j1") == []
        assert [c.id for c in correcoes.listar("j2")] == ["c3"]

    def test_jobs_com_correcao_respeita_os_limites_do_periodo(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        for id, job_id, minutos in (
            ("c0", "antes", 9),
            ("c1", "no_inicio", 10),
            ("c2", "no_meio", 15),
            ("c3", "no_fim", 20),
            ("c4", "depois", 21),
        ):
            correcoes.acrescentar(self._correcao(id, job_id, minutos))
        desde = BASE + timedelta(minutes=10)
        ate = BASE + timedelta(minutes=20)

        assert correcoes.jobs_com_correcao(desde, ate) == {"no_inicio", "no_meio"}
        assert correcoes.jobs_com_correcao(desde=desde) == {
            "no_inicio",
            "no_meio",
            "no_fim",
            "depois",
        }
        assert correcoes.jobs_com_correcao(ate=ate) == {
            "antes",
            "no_inicio",
            "no_meio",
        }
        assert len(correcoes.jobs_com_correcao()) == 5

    @pytest.fixture
    def correcoes(self) -> RepositorioDeCorrecoesFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDeCorrecoesFirestore(
            cliente, colecao=f"correcoes-{uuid.uuid4().hex}"
        )

    def _correcao(self, id: str, job_id: str, minutos: int) -> Correcao:
        return Correcao(
            id=id,
            job_id=job_id,
            autor_uid="u1",
            autor_email="a@b.c",
            criada_em=BASE + timedelta(minutes=minutos),
            motivo="grafia",
            tipo="pessoa.renomear",
            antes="Ana",
            depois="Anna",
            ancora=Ancora(
                versao="v" * 64,
                tipo_do_item="pessoa",
                identidade="ana",
                inicio_ms=0,
                fim_ms=10,
            ),
        )

    def test_acrescenta_e_lista_por_job_na_ordem_do_tempo(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        correcoes.acrescentar(self._correcao("c2", "j1", 5))
        correcoes.acrescentar(self._correcao("c1", "j1", 1))
        correcoes.acrescentar(self._correcao("c3", "j2", 2))

        assert [c.id for c in correcoes.listar("j1")] == ["c1", "c2"]
        assert correcoes.listar("j1")[0].ancora.identidade == "ana"

    def test_guarda_o_desfazer_com_o_item_e_a_correcao_revertida(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        desfazer = self._correcao("d1", "j1", 3).model_copy(
            update={"tipo": "desfazer", "desfaz": "c1", "item_id": "pes01"}
        )
        correcoes.acrescentar(desfazer)

        [lido] = correcoes.listar("j1")
        assert (lido.tipo, lido.desfaz, lido.item_id) == ("desfazer", "c1", "pes01")

    def test_guarda_a_reaplicacao_e_o_descarte_com_a_original(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        reaplicacao = self._correcao("r1", "j1", 3).model_copy(
            update={"reaplica": "c1"}
        )
        descarte = self._correcao("d1", "j1", 4).model_copy(
            update={"tipo": "descartar", "descarta": "c2"}
        )
        correcoes.acrescentar(reaplicacao)
        correcoes.acrescentar(descarte)

        lidos = correcoes.listar("j1")
        assert [(c.tipo, c.reaplica, c.descarta) for c in lidos] == [
            ("pessoa.renomear", "c1", None),
            ("descartar", None, "c2"),
        ]

    def test_guarda_a_correcao_de_pauta_com_a_ancora_da_pauta(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        base = self._correcao("p1", "j1", 1)
        correcoes.acrescentar(
            base.model_copy(
                update={
                    "tipo": "item.tempos",
                    "item_id": "pau01",
                    "antes": "0-20000",
                    "depois": "2000-18000",
                    "ancora": base.ancora.model_copy(update={"tipo_do_item": "pauta"}),
                }
            )
        )

        [lida] = correcoes.listar("j1")
        assert (lida.tipo, lida.depois, lida.ancora.tipo_do_item) == (
            "item.tempos",
            "2000-18000",
            "pauta",
        )

    def test_guarda_o_comercial_acrescentado_com_a_ancora_do_comercial(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        base = self._correcao("a1", "j1", 1)
        comercial = (
            '{"evidencia": "logo", "fim_ms": 22000, "inicio_ms": 20000, '
            '"marca": "Loja Sol", "tipo": "merchan_apresentador"}'
        )
        correcoes.acrescentar(
            base.model_copy(
                update={
                    "tipo": "comercial.acrescentar",
                    "item_id": "acr-a1",
                    "antes": "",
                    "depois": comercial,
                    "ancora": base.ancora.model_copy(
                        update={
                            "tipo_do_item": "comercial",
                            "identidade": "loja sol|merchan_apresentador",
                        }
                    ),
                }
            )
        )

        [lida] = correcoes.listar("j1")
        assert (lida.tipo, lida.depois, lida.ancora.tipo_do_item) == (
            "comercial.acrescentar",
            comercial,
            "comercial",
        )
        assert lida.ancora.identidade == "loja sol|merchan_apresentador"

    def test_guarda_a_ocorrencia_da_pessoa(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        correcoes.acrescentar(
            self._correcao("o1", "j1", 1).model_copy(
                update={
                    "tipo": "pessoa.nao_e",
                    "depois": "Não identificado",
                    "ocorrencia": Ocorrencia(
                        lista="na_imagem", inicio_ms=1000, fim_ms=5000
                    ),
                }
            )
        )

        [lida] = correcoes.listar("j1")
        assert lida.ocorrencia == Ocorrencia(
            lista="na_imagem", inicio_ms=1000, fim_ms=5000
        )

    def test_guarda_a_correcao_de_plano_e_de_fala(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        base = self._correcao("p1", "j1", 1)
        for cid, tipo, tipo_do_item, depois in [
            ("p1", "plano.limpo", "plano", "true"),
            ("p2", "fala.texto", "fala", '{"locutor": "Ana", "texto": "oi"}'),
        ]:
            correcoes.acrescentar(
                base.model_copy(
                    update={
                        "id": cid,
                        "tipo": tipo,
                        "depois": depois,
                        "ancora": base.ancora.model_copy(
                            update={"tipo_do_item": tipo_do_item}
                        ),
                    }
                )
            )

        lidas = correcoes.listar("j1")
        assert [(c.tipo, c.ancora.tipo_do_item, c.depois) for c in lidas] == [
            ("plano.limpo", "plano", "true"),
            ("fala.texto", "fala", '{"locutor": "Ana", "texto": "oi"}'),
        ]

    def test_nao_sobrescreve_uma_correcao_existente(
        self, correcoes: RepositorioDeCorrecoesFirestore
    ) -> None:
        correcoes.acrescentar(self._correcao("c1", "j1", 1))

        with pytest.raises(CorrecaoJaExiste):
            correcoes.acrescentar(self._correcao("c1", "j1", 2))


def _envio_para_lixeira() -> EnvioParaLixeira:
    return EnvioParaLixeira(
        em=BASE, por_uid="u1", por_email="c@redetv.com", motivo="duplicada"
    )


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestCatalogoFirestore:
    @pytest.fixture
    def catalogo(self) -> CatalogoFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return CatalogoFirestore(cliente, colecao=f"catalogo-{uuid.uuid4().hex}")

    def test_acrescenta_obtem_e_acha_por_nome_ou_apelido(
        self, catalogo: CatalogoFirestore
    ) -> None:
        leao = catalogo.acrescentar("Leão Lobo", "apresentador", ["Leãozinho"])

        assert catalogo.obter(leao.id) == leao
        assert catalogo.achar("LEAO lobo") == [leao]
        assert catalogo.achar("leaozinho") == [leao]
        assert catalogo.achar("Outro") == []
        assert catalogo.obter("inexistente") is None
        assert catalogo.todas() == [leao]

    def test_corrige_e_a_busca_acompanha(self, catalogo: CatalogoFirestore) -> None:
        p = catalogo.acrescentar("Ana", "repórter", ["Aninha"])

        nova = catalogo.corrigir(p.id, nome="Ana Souza", apelidos=[])

        assert catalogo.obter(p.id) == nova
        assert catalogo.achar("ana souza") == [nova]
        assert catalogo.achar("Aninha") == []

    def test_apaga_e_inexistente_falha(self, catalogo: CatalogoFirestore) -> None:
        p = catalogo.acrescentar("Ana", "repórter", [])

        catalogo.apagar(p.id)

        assert catalogo.obter(p.id) is None
        with pytest.raises(PessoaInexistente):
            catalogo.apagar(p.id)
        with pytest.raises(PessoaInexistente):
            catalogo.corrigir(p.id, nome="X")

    def test_lixeira_esconde_da_busca_e_restaurar_devolve(
        self, catalogo: CatalogoFirestore
    ) -> None:
        p = catalogo.acrescentar("Ana", "repórter", ["Aninha"])
        envio = _envio_para_lixeira()

        catalogo.definir_lixeira(p.id, envio)

        assert catalogo.todas() == []
        assert catalogo.achar("ana") == []
        assert [x.id for x in catalogo.na_lixeira()] == [p.id]
        assert catalogo.obter(p.id) is not None
        assert catalogo.obter(p.id).lixeira == envio  # type: ignore[union-attr]
        catalogo.definir_lixeira(p.id, None)
        assert [x.id for x in catalogo.todas()] == [p.id]
        assert catalogo.na_lixeira() == []
        with pytest.raises(PessoaInexistente):
            catalogo.definir_lixeira("inexistente", envio)

    def test_fundida_sai_da_busca_e_aponta_para_o_destino(
        self, catalogo: CatalogoFirestore
    ) -> None:
        origem = catalogo.acrescentar("Sabrina S.", "", [])
        destino = catalogo.acrescentar("Sabrina Sato", "apresentadora", [])
        fusao = FusaoDaPessoa(
            destino_id=destino.id,
            em=BASE,
            por_uid="u1",
            por_email="c@redetv.com",
            motivo="nome duplicado",
        )

        catalogo.definir_fusao(origem.id, fusao)

        assert catalogo.todas() == [destino]
        assert catalogo.achar("sabrina s") == []
        assert catalogo.na_lixeira() == []
        lida = catalogo.obter(origem.id)
        assert lida is not None and lida.fundida == fusao
        with pytest.raises(PessoaInexistente):
            catalogo.definir_fusao("inexistente", fusao)

    def test_nome_novo_fica_a_revisar_com_o_autor(
        self, catalogo: CatalogoFirestore
    ) -> None:
        nova = catalogo.acrescentar("Zeca", "cantor", [], a_revisar=True, autor="a@b")

        lida = catalogo.obter(nova.id)

        assert lida == nova
        assert lida is not None
        assert (lida.a_revisar, lida.acrescentada_por) == (True, "a@b")


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestCatalogoDeMarcasFirestore:
    @pytest.fixture
    def marcas(self) -> CatalogoDeMarcasFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return CatalogoDeMarcasFirestore(cliente, colecao=f"marcas-{uuid.uuid4().hex}")

    def test_acrescenta_obtem_e_acha_por_nome_ou_apelido(
        self, marcas: CatalogoDeMarcasFirestore
    ) -> None:
        banco = marcas.acrescentar("Banco Verde", ["BV"])

        assert marcas.obter(banco.id) == banco
        assert marcas.achar("BANCO verde") == [banco]
        assert marcas.achar("bv") == [banco]
        assert marcas.achar("Outro") == []
        assert marcas.obter("inexistente") is None
        assert marcas.todas() == [banco]

    def test_lixeira_esconde_da_busca_restaura_e_apaga(
        self, marcas: CatalogoDeMarcasFirestore
    ) -> None:
        m = marcas.acrescentar("Banco Verde", ["BV"])
        envio = _envio_para_lixeira()

        marcas.definir_lixeira(m.id, envio)

        assert marcas.todas() == []
        assert marcas.achar("bv") == []
        assert [x.id for x in marcas.na_lixeira()] == [m.id]
        marcas.definir_lixeira(m.id, None)
        assert [x.id for x in marcas.todas()] == [m.id]
        marcas.apagar(m.id)
        assert marcas.obter(m.id) is None
        with pytest.raises(MarcaInexistente):
            marcas.apagar(m.id)
        with pytest.raises(MarcaInexistente):
            marcas.definir_lixeira(m.id, envio)

    def test_nome_novo_fica_a_revisar_com_o_autor(
        self, marcas: CatalogoDeMarcasFirestore
    ) -> None:
        nova = marcas.acrescentar("Loja Sol", [], a_revisar=True, autor="a@b")

        lida = marcas.obter(nova.id)

        assert lida == nova
        assert lida is not None
        assert (lida.a_revisar, lida.acrescentada_por) == (True, "a@b")

    def test_a_carga_e_idempotente(self, marcas: CatalogoDeMarcasFirestore) -> None:
        decupagens = [{"comerciais": [{"marca": "Banco Verde"}, {"marca": "Loja Sol"}]}]

        primeira = carregar_marcas(marcas, decupagens)
        segunda = carregar_marcas(marcas, decupagens)

        assert (primeira, segunda) == (2, 0)
        assert len(marcas.todas()) == 2


def _andamento(estado: Any, pendentes: list[str]) -> RenomeacaoDoPrograma:
    return RenomeacaoDoPrograma(
        id=f"troca-{estado}",
        desde=BASE,
        nome_antigo="Antigo",
        nome_novo="Novo",
        total=2,
        pendentes=pendentes,
        estado=estado,
    )


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestProgramasFirestore:
    @pytest.fixture
    def programas(self) -> ProgramasFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return ProgramasFirestore(cliente, colecao=f"programas-{uuid.uuid4().hex}")

    def test_salvar_sem_o_andamento_deixa_o_gravado(
        self, programas: ProgramasFirestore
    ) -> None:
        concluida = _andamento("concluida", [])
        programas.salvar(
            Programa(id="p", nome="Novo", renomeacao=concluida), com_renomeacao=True
        )

        # A cópia velha do PUT não volta a troca para em andamento.
        programas.salvar(
            Programa(
                id="p",
                nome="Novo",
                perfil="Revista.",
                renomeacao=_andamento("em_andamento", ["j1"]),
            )
        )

        assert programas.obter("p") == Programa(
            id="p", nome="Novo", perfil="Revista.", renomeacao=concluida
        )
        # O desfazer de uma troca grava o andamento de antes, inclusive nenhum.
        programas.salvar(Programa(id="p", nome="Antigo"), com_renomeacao=True)
        assert programas.obter("p") == Programa(id="p", nome="Antigo")

    def test_trocar_grava_o_que_mudar_devolve_e_so_isso(
        self, programas: ProgramasFirestore
    ) -> None:
        programas.salvar(Programa(id="p", nome="Novo"))
        programas.salvar(Programa(id="q", nome="Outro"))
        andamento = _andamento("em_andamento", ["j1"])

        gravado = programas.trocar(
            "p", lambda p: p.model_copy(update={"renomeacao": andamento})
        )

        assert gravado == programas.obter("p")
        assert gravado == Programa(id="p", nome="Novo", renomeacao=andamento)
        assert programas.trocar("p", lambda p: None) is None
        assert programas.obter("p") == gravado
        with pytest.raises(NomeEmUso):
            programas.trocar("p", lambda p: p.model_copy(update={"nome": "outro"}))
        assert programas.obter("p") == gravado

    def test_levar_o_nome_ao_job_grava_o_nome_atual_do_programa(
        self, programas: ProgramasFirestore, repositorio: RepositorioFirestore
    ) -> None:
        programas.salvar(Programa(id="p", nome="Novo"))
        repositorio.salvar(_job("a", BASE, programa="Antigo"))

        levado = programas.levar_o_nome_ao_job("p", "a", repositorio)

        assert levado is not None and levado.programa == "Novo"
        assert repositorio.obter("a") == levado
        assert programas.levar_o_nome_ao_job("p", "a", repositorio) == levado
        assert programas.levar_o_nome_ao_job("p", "x", repositorio) is None
        # Programa apagado: o Job fica como está.
        programas.apagar("p")
        repositorio.salvar(_job("b", BASE, programa="Antigo"))
        assert programas.levar_o_nome_ao_job("p", "b", repositorio) is None
        assert repositorio.obter("b").programa == "Antigo"  # type: ignore[union-attr]

    def test_trocar_nao_recria_o_programa_apagado(
        self, programas: ProgramasFirestore
    ) -> None:
        programas.salvar(Programa(id="p", nome="Novo"))
        programas.apagar("p")

        assert programas.trocar("p", lambda p: p) is None
        assert programas.obter("p") is None and programas.listar() == []


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestTiposDeObjetoFirestore:
    @pytest.fixture
    def tipos(self) -> TiposDeObjetoFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        sufixo = uuid.uuid4().hex
        return TiposDeObjetoFirestore(
            cliente, colecao=f"tipos-{sufixo}", colecao_por_job=f"tipos-job-{sufixo}"
        )

    def test_registra_e_busca_por_prefixo(self, tipos: TiposDeObjetoFirestore) -> None:
        tipos.registrar("j1", {"sandália": 2, "scarpin": 1})

        assert tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 2}]
        assert tipos.buscar("SCAR") == [{"tipo": "scarpin", "ocorrencias": 1}]
        assert tipos.buscar("x") == []

    def test_trocar_a_contribuicao_do_job_nao_dobra(
        self, tipos: TiposDeObjetoFirestore
    ) -> None:
        tipos.registrar("j1", {"sandália": 2})
        tipos.registrar("j1", {"sandália": 2})
        assert tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 2}]

        tipos.registrar("j1", {"saia": 1})
        tipos.registrar("j2", {"Sandalia": 4})

        assert tipos.buscar("sa") == [
            {"tipo": "Sandalia", "ocorrencias": 4},
            {"tipo": "saia", "ocorrencias": 1},
        ]

    def test_ordena_por_ocorrencias_e_corta_no_limite(
        self, tipos: TiposDeObjetoFirestore
    ) -> None:
        tipos.registrar("j1", {"sapato": 1, "sandália": 3, "saia": 2})

        achados = tipos.buscar("sa", limite=2)

        assert [t["tipo"] for t in achados] == ["sandália", "saia"]

    def test_conhecidos_traz_todos_os_vivos_sem_o_teto_da_busca(
        self, tipos: TiposDeObjetoFirestore
    ) -> None:
        tipos.registrar("j1", {"sapato": 1, "saia": 2})
        tipos.registrar("j1", {"saia": 2})

        assert tipos.conhecidos() == ["saia"]


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDeAuditoriaFirestore:
    @pytest.fixture
    def auditoria(self) -> RepositorioDeAuditoriaFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDeAuditoriaFirestore(
            cliente, colecao=f"auditoria-{uuid.uuid4().hex}"
        )

    @staticmethod
    def _registro(id: str, minutos: int, **extra: object) -> RegistroDeAuditoria:
        campos: dict[str, object] = {
            "id": id,
            "quando": BASE + timedelta(minutes=minutos),
            "uid": "u1",
            "email": "Ana@RedeTV.com",
            "acao": "chave.emitida",
            "alvo_tipo": "sistema",
            "alvo_id": "s1",
            "alvo_nome": "Playout",
            "detalhes": {"antes": ["consulta"], "depois": ["editor"]},
        }
        campos.update(extra)
        return RegistroDeAuditoria(**campos)  # type: ignore[arg-type]

    def test_acrescenta_e_consulta_filtrando_e_paginando(
        self, auditoria: RepositorioDeAuditoriaFirestore
    ) -> None:
        auditoria.acrescentar(self._registro("a", 0))
        auditoria.acrescentar(
            self._registro("b", 10, uid="u2", email="rui@redetv.com", alvo_id="v1")
        )
        auditoria.acrescentar(
            self._registro("c", 20, acao="item.para_lixeira", alvo_id="v1")
        )

        todos = auditoria.consultar(FiltroDeAuditoria())
        assert [r.id for r in todos.registros] == ["c", "b", "a"]
        assert todos.registros[2].detalhes == {
            "antes": ["consulta"],
            "depois": ["editor"],
        }
        por_email = auditoria.consultar(FiltroDeAuditoria(pessoa="ana@redetv.com"))
        assert [r.id for r in por_email.registros] == ["c", "a"]
        por_uid = auditoria.consultar(FiltroDeAuditoria(pessoa="u2"))
        assert [r.id for r in por_uid.registros] == ["b"]
        por_alvo = auditoria.consultar(
            FiltroDeAuditoria(alvo_id="v1", acao="item.para_lixeira")
        )
        assert [r.id for r in por_alvo.registros] == ["c"]
        varias = auditoria.consultar(
            FiltroDeAuditoria(
                alvo_id="v1", acoes=("item.para_lixeira", "chave.emitida"), limite=1
            )
        )
        assert [r.id for r in varias.registros] == ["c"]
        assert varias.proximo_cursor is not None
        periodo = auditoria.consultar(
            FiltroDeAuditoria(
                de=BASE + timedelta(minutes=5), ate=BASE + timedelta(minutes=15)
            )
        )
        assert [r.id for r in periodo.registros] == ["b"]
        p1 = auditoria.consultar(FiltroDeAuditoria(limite=2))
        p2 = auditoria.consultar(FiltroDeAuditoria(limite=2, cursor=p1.proximo_cursor))
        assert [r.id for r in p1.registros] == ["c", "b"]
        assert [r.id for r in p2.registros] == ["a"]

    def test_nao_sobrescreve_um_registro_existente(
        self, auditoria: RepositorioDeAuditoriaFirestore
    ) -> None:
        auditoria.acrescentar(self._registro("a", 0))

        with pytest.raises(AlreadyExists):
            auditoria.acrescentar(self._registro("a", 5, alvo_nome="Outro"))

    def test_cursor_inexistente_levanta(
        self, auditoria: RepositorioDeAuditoriaFirestore
    ) -> None:
        with pytest.raises(CursorInvalido):
            auditoria.consultar(FiltroDeAuditoria(cursor="nada"))


class _ClienteSemRede:
    """Só o que `RepositorioFirestore` usa fora da transação; a transação é do teste."""

    def __init__(self, colecao: object = None) -> None:
        self._colecao = colecao

    def collection(self, nome: str) -> object:
        return self._colecao

    def transaction(self) -> object:
        return object()


def _esgotou_as_tentativas() -> ValueError:
    erro = ValueError("Failed to commit transaction in 5 attempts.")
    erro.__cause__ = Aborted("disputa")  # type: ignore[no-untyped-call]
    return erro


def test_sob_disputa_repete_quando_o_firestore_esgota_as_tentativas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.nuvem.time.sleep", lambda _: None)
    repositorio = RepositorioFirestore(_ClienteSemRede())  # type: ignore[arg-type]
    chamadas = 0

    def na_transacao(_: Any) -> Job | None:
        nonlocal chamadas
        chamadas += 1
        if chamadas < 3:
            raise _esgotou_as_tentativas()
        return None

    assert repositorio._sob_disputa(na_transacao) is None
    assert chamadas == 3


def test_sob_disputa_sem_fim_e_servico_indisponivel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.nuvem.time.sleep", lambda _: None)
    repositorio = RepositorioFirestore(_ClienteSemRede())  # type: ignore[arg-type]

    def na_transacao(_: Any) -> Job | None:
        raise _esgotou_as_tentativas()

    with pytest.raises(ServicoIndisponivel):
        repositorio._sob_disputa(na_transacao)


def test_espera_sob_disputa_dobra_a_cada_rodada_ate_o_teto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Com o sorteio no máximo, a espera é o limite da rodada.
    monkeypatch.setattr("api.nuvem.random.uniform", lambda _a, b: b)
    esperas = [espera_sob_disputa(r) for r in range(TENTATIVAS_SOB_DISPUTA)]
    assert esperas == [0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0, 1.0]


def test_sob_disputa_nao_repete_outro_value_error() -> None:
    repositorio = RepositorioFirestore(_ClienteSemRede())  # type: ignore[arg-type]
    chamadas = 0

    def na_transacao(_: Any) -> Job | None:
        nonlocal chamadas
        chamadas += 1
        raise ValueError("Job inválido")

    with pytest.raises(ValueError, match="Job inválido"):
        repositorio._sob_disputa(na_transacao)
    assert chamadas == 1


class _ColecaoQueAborta:
    """`create` e `update` abortam as primeiras vezes (documento travado) e depois respondem."""

    def __init__(self, abortos: int, depois: Exception | None) -> None:
        self._abortos = abortos
        self._depois = depois
        self.criacoes = 0

    def document(self, _: str) -> "_ColecaoQueAborta":
        return self

    def create(self, _: dict[str, Any]) -> None:
        self.criacoes += 1
        if self._abortos:
            self._abortos -= 1
            raise Aborted("travado")  # type: ignore[no-untyped-call]
        if self._depois is not None:
            raise self._depois

    def update(self, campos: dict[str, Any]) -> None:
        self.create(campos)


def _job_novo() -> Job:
    agora = datetime(2026, 11, 4, tzinfo=UTC)
    return Job(
        id="j1",
        nome="a.mp4",
        tamanho_bytes=10,
        estado="aguardando_upload",
        criado_por="sistema:Legado A",
        sistema="Legado A",
        criado_em=agora,
        atualizado_em=agora,
    )


@pytest.mark.parametrize(
    ("depois", "gravou"),
    [(None, True), (AlreadyExists("existe"), False)],  # type: ignore[no-untyped-call]
)
def test_criar_abortado_repete_ate_saber_se_gravou(
    monkeypatch: pytest.MonkeyPatch, depois: Exception | None, gravou: bool
) -> None:
    # `Aborted` não diz que outro gravou: devolver `False` aí faria a rota responder
    # com um Job que não existe.
    monkeypatch.setattr("api.nuvem.time.sleep", lambda _: None)
    colecao = _ColecaoQueAborta(abortos=2, depois=depois)
    repositorio = RepositorioFirestore(_ClienteSemRede(colecao))  # type: ignore[arg-type]

    assert repositorio.criar(_job_novo()) is gravou
    assert colecao.criacoes == 3


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestRepositorioDeIdempotenciaFirestore:
    @pytest.fixture
    def chaves(self) -> RepositorioDeIdempotenciaFirestore:
        cliente = firestore.Client(project="teste", credentials=_anonima())
        return RepositorioDeIdempotenciaFirestore(
            cliente, f"idempotencia-{uuid.uuid4().hex}"
        )

    def test_marca_de_job_gravado_volta_na_repeticao(
        self, chaves: RepositorioDeIdempotenciaFirestore
    ) -> None:
        chaves.reservar("sistema:Legado A", "k1", "imp", "j1", BASE)

        chaves.marcar_job_gravado("sistema:Legado A", "k1")

        reserva, nova = chaves.reservar("sistema:Legado A", "k1", "imp", "j2", BASE)
        assert (reserva.job_id, reserva.job_gravado, nova) == ("j1", True, False)

    def test_marcar_chave_sem_reserva_nao_falha_nem_cria_reserva(
        self, chaves: RepositorioDeIdempotenciaFirestore
    ) -> None:
        chaves.marcar_job_gravado("sistema:Legado A", "k1")

        reserva, nova = chaves.reservar("sistema:Legado A", "k1", "imp", "j1", BASE)
        assert (reserva.job_gravado, nova) == (False, True)


@pytest.mark.parametrize(
    "depois",
    [None, NotFound("vencida")],  # type: ignore[no-untyped-call]
)
def test_marca_de_job_gravado_abortada_repete(
    monkeypatch: pytest.MonkeyPatch, depois: Exception | None
) -> None:
    # As repetições em paralelo disputam a reserva; um 500 aqui viria depois de o Job
    # já estar gravado.
    monkeypatch.setattr("api.nuvem.time.sleep", lambda _: None)
    colecao = _ColecaoQueAborta(abortos=2, depois=depois)
    chaves = RepositorioDeIdempotenciaFirestore(_ClienteSemRede(colecao))  # type: ignore[arg-type]

    chaves.marcar_job_gravado("sistema:Legado A", "k1")

    assert colecao.criacoes == 3


class _DocumentoDaReservaVencida:
    """A reserva existe e venceu: `create` dá `AlreadyExists` e a leitura a devolve."""

    def __init__(self, reserva: dict[str, Any]) -> None:
        self._reserva = reserva

    def document(self, _: str) -> "_DocumentoDaReservaVencida":
        return self

    def create(self, _: dict[str, Any]) -> None:
        raise AlreadyExists("existe")  # type: ignore[no-untyped-call]

    def get(self, **_: Any) -> Any:
        return type("Doc", (), {"exists": True, "to_dict": lambda _: self._reserva})()


def test_troca_da_reserva_vencida_repete_quando_o_firestore_esgota_as_tentativas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Várias repetições na mesma reserva vencida disputam a transação da troca.
    monkeypatch.setattr("api.nuvem.time.sleep", lambda _: None)
    agora = datetime(2026, 11, 4, tzinfo=UTC)
    vencida = nova_reserva("imp", "velho", agora - timedelta(hours=49))
    repositorio = RepositorioDeIdempotenciaFirestore(
        _ClienteSemRede(_DocumentoDaReservaVencida(vencida.model_dump()))  # type: ignore[arg-type]
    )
    chamadas = 0

    def transacional(funcao: Any) -> Any:
        def na_transacao(transacao: Any) -> Any:
            nonlocal chamadas
            chamadas += 1
            if chamadas < 3:
                raise _esgotou_as_tentativas()
            return (nova_reserva("imp", "novo", agora), True)

        return na_transacao

    monkeypatch.setattr("api.nuvem.firestore.transactional", transacional)

    reserva, nova = repositorio.reservar("sistema:Legado A", "k1", "imp", "novo", agora)

    assert (reserva.job_id, nova) == ("novo", True)
    assert chamadas == 3
