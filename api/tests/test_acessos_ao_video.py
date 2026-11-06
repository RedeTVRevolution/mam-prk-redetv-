from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.auditoria import (
    FiltroDeAuditoria,
    RegistroDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
)
from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.tests.test_jobs import ArmazenamentoFalso, Relogio

INICIO = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
ANA = {"Authorization": "Bearer ana"}
BETO = {"Authorization": "Bearer beto"}


class AuditoriaQueFalha(RepositorioDeAuditoriaEmMemoria):
    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        raise RuntimeError("Firestore fora")


class Mundo:
    def __init__(
        self,
        auditoria: RepositorioDeAuditoriaEmMemoria | None = None,
        estado: str = "concluido",
        papeis_da_ana: list[Papel] | None = None,
    ) -> None:
        self.auditoria = auditoria or RepositorioDeAuditoriaEmMemoria()
        self.relogio = Relogio()
        self.relogio.agora = INICIO
        self.chaves = RepositorioDeChavesEmMemoria()
        self.chave = emitir_chave("Playout", ["ler"], MAC, self.chaves, INICIO).chave
        jobs = RepositorioEmMemoria()
        jobs.salvar(
            Job(
                id="j1",
                nome="Programa Ação.mp4",
                tamanho_bytes=10,
                estado=estado,  # type: ignore[arg-type]
                criado_por="sistema:Playout",
                sistema="Playout",
                criado_em=INICIO,
                atualizado_em=INICIO,
            )
        )
        armazenamento = ArmazenamentoFalso()
        armazenamento.decupagens["j1"] = [b'{"versao_esquema": "1.2"}']
        papeis = RepositorioDePapeisEmMemoria()
        if papeis_da_ana is not None:
            papeis.salvar("ana", papeis_da_ana)
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "ana": Usuario(uid="ana", email="ana@redetv.com.br"),
                        "beto": Usuario(uid="beto", email="beto@redetv.com.br"),
                        "carla": Usuario(uid="carla", email="Carla@RedeTV.com.br"),
                    }
                ),
                jobs,
                armazenamento,
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
                papeis=papeis,
                auditoria=self.auditoria,
                relogio=self.relogio,
            )
        )

    def registros(self, acao: str) -> list[RegistroDeAuditoria]:
        pagina = self.auditoria.consultar(FiltroDeAuditoria(alvo_id="j1"))
        return [r for r in pagina.registros if r.acao == acao]


def test_baixar_o_video_devolve_a_copia_limpa_com_o_nome_e_grava_video_baixado() -> (
    None
):
    mundo = Mundo()

    resposta = mundo.cliente.get("/v1/jobs/j1/download", headers=ANA)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["url"].startswith(
        "https://storage.exemplo/copia-limpa/j1?nome=Programa"
    )
    assert "nome=Programa Ação.mp4&" in corpo["url"]
    # A validade do vídeo não muda com a das imagens (#408): 5 min.
    assert corpo["url"].endswith("&validade=300")
    assert corpo["expira_em"] == "2026-11-01T12:05:00Z"
    [registro] = mundo.registros("video.baixado")
    assert (registro.uid, registro.email) == ("ana", "ana@redetv.com.br")
    assert (registro.alvo_id, registro.alvo_nome) == ("j1", "Programa Ação.mp4")
    assert registro.quando == INICIO


def test_cada_pedido_de_download_grava_um_registro() -> None:
    mundo = Mundo()

    mundo.cliente.get("/v1/jobs/j1/download", headers=ANA)
    mundo.cliente.get("/v1/jobs/j1/download", headers=ANA)

    assert len(mundo.registros("video.baixado")) == 2


def test_baixar_o_json_entrega_a_decupagem_com_o_nome_e_grava_decupagem_baixada() -> (
    None
):
    mundo = Mundo()

    resposta = mundo.cliente.get("/v1/jobs/j1/decupagem/download", headers=ANA)

    assert resposta.status_code == 200
    assert resposta.json()["versao_esquema"] == "1.2"
    assert resposta.text.startswith('{\n  "versao_esquema": "1.2",\n')
    disposicao = resposta.headers["content-disposition"]
    assert disposicao.startswith("attachment;")
    assert "filename*=UTF-8''Programa%20A%C3%A7%C3%A3o.decupagem.json" in disposicao
    [registro] = mundo.registros("decupagem.baixada")
    assert registro.email == "ana@redetv.com.br"


def test_chave_de_sistema_tambem_fica_registrada_com_o_nome_do_sistema() -> None:
    mundo = Mundo()
    chave = {"X-API-Key": mundo.chave}

    assert mundo.cliente.get("/v1/jobs/j1/download", headers=chave).status_code == 200
    assert mundo.cliente.get("/v1/jobs/j1/reproducao", headers=chave).status_code == 200

    [baixado] = mundo.registros("video.baixado")
    [aberto] = mundo.registros("video.aberto")
    assert (baixado.sistema, baixado.uid) == ("Playout", None)
    assert (aberto.sistema, aberto.uid) == ("Playout", None)


def test_reproducao_grava_no_maximo_uma_abertura_por_pessoa_a_cada_30_minutos() -> None:
    mundo = Mundo()

    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=ANA)
    mundo.relogio.agora = INICIO + timedelta(minutes=10)
    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=ANA)
    assert len(mundo.registros("video.aberto")) == 1

    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=BETO)
    assert sorted(str(r.uid) for r in mundo.registros("video.aberto")) == [
        "ana",
        "beto",
    ]

    mundo.relogio.agora = INICIO + timedelta(minutes=31)
    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=ANA)
    abertas = [r for r in mundo.registros("video.aberto") if r.uid == "ana"]
    assert [r.quando for r in abertas] == [
        INICIO + timedelta(minutes=31),
        INICIO,
    ]


def test_e_mail_com_maiusculas_no_token_nao_conta_nova_abertura() -> None:
    # O registro guarda o e-mail sem maiúsculas; a renovação ainda é da mesma pessoa.
    mundo = Mundo()
    carla = {"Authorization": "Bearer carla"}

    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=carla)
    mundo.relogio.agora = INICIO + timedelta(minutes=10)
    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=carla)

    [aberto] = mundo.registros("video.aberto")
    assert (aberto.uid, aberto.email) == ("carla", "carla@redetv.com.br")


def test_sem_decupagem_ver_responde_403_e_nada_e_gravado() -> None:
    mundo = Mundo(papeis_da_ana=[])

    for rota in ("/download", "/decupagem/download", "/reproducao"):
        assert mundo.cliente.get(f"/v1/jobs/j1{rota}", headers=ANA).status_code == 403
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_job_nao_concluido_responde_409() -> None:
    mundo = Mundo(estado="analisando")

    for rota in ("/download", "/decupagem/download"):
        assert mundo.cliente.get(f"/v1/jobs/j1{rota}", headers=ANA).status_code == 409
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_com_a_auditoria_falhando_o_download_responde_503_sem_a_url() -> None:
    mundo = Mundo(auditoria=AuditoriaQueFalha())

    for rota in ("/download", "/decupagem/download"):
        resposta = mundo.cliente.get(f"/v1/jobs/j1{rota}", headers=ANA)
        assert resposta.status_code == 503
        assert "storage.exemplo" not in resposta.text
        assert "versao_esquema" not in resposta.text


def test_com_a_auditoria_falhando_a_reproducao_continua() -> None:
    mundo = Mundo(auditoria=AuditoriaQueFalha())

    assert mundo.cliente.get("/v1/jobs/j1/reproducao", headers=ANA).status_code == 200


def test_a_consulta_da_auditoria_filtra_pelo_id_do_video() -> None:
    mundo = Mundo(papeis_da_ana=["administrador"])
    mundo.cliente.get("/v1/jobs/j1/reproducao", headers=ANA)
    mundo.cliente.get("/v1/jobs/j1/download", headers=ANA)
    mundo.cliente.get("/v1/jobs/j1/decupagem/download", headers=ANA)

    resposta = mundo.cliente.get("/v1/admin/auditoria?alvo=j1", headers=ANA)
    outro = mundo.cliente.get("/v1/admin/auditoria?alvo=outro", headers=ANA)

    assert sorted(r["acao"] for r in resposta.json()) == [
        "decupagem.baixada",
        "video.aberto",
        "video.baixado",
    ]
    assert outro.json() == []
