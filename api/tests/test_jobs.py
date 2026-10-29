from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from api.auth import TokenInvalido, Usuario
from api.jobs import Job, RepositorioEmMemoria, expirar_uploads
from api.main import criar_app

AUTORIZACAO = {"Authorization": "Bearer token-bom"}
INICIO = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class VerificadorFalso:
    def verificar(self, token: str) -> Usuario:
        if token != "token-bom":
            raise TokenInvalido
        return Usuario(uid="u1", email="ana@redetv.com.br")


class ArmazenamentoFalso:
    """Storage simulado: devolve uma URL assinada fixa por Job e anota o que pediram."""

    def __init__(self) -> None:
        self.pedidos: list[dict[str, Any]] = []
        self.cancelados: list[str] = []

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        self.pedidos.append(
            {"job_id": job_id, "tamanho_bytes": tamanho_bytes, "tipo": tipo}
        )
        return f"https://storage.exemplo/quarentena/{job_id}?assinatura=x"

    def cancelar_upload(self, job_id: str) -> None:
        self.cancelados.append(job_id)


class Relogio:
    def __init__(self) -> None:
        self.agora = INICIO

    def __call__(self) -> datetime:
        return self.agora


class Ambiente:
    def __init__(self, tamanho_maximo: int = 4 * 1024**3) -> None:
        self.repositorio = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.relogio = Relogio()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(),
                repositorio=self.repositorio,
                armazenamento=self.armazenamento,
                tamanho_maximo_bytes=tamanho_maximo,
                relogio=self.relogio,
            )
        )

    def criar(self, **corpo: Any) -> Any:
        padrao = {"nome": "clipe.mp4", "tamanho_bytes": 1000, "tipo": "video/mp4"}
        return self.cliente.post(
            "/v1/jobs", json={**padrao, **corpo}, headers=AUTORIZACAO
        )


def test_criar_job_devolve_202_com_url_assinada_e_job_aguardando_upload() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar()

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["estado"] == "aguardando_upload"
    assert (
        corpo["url_de_upload"]
        == f"https://storage.exemplo/quarentena/{corpo['id']}?assinatura=x"
    )
    assert ambiente.armazenamento.pedidos == [
        {"job_id": corpo["id"], "tamanho_bytes": 1000, "tipo": "video/mp4"}
    ]
    guardado = ambiente.cliente.get(
        f"/v1/jobs/{corpo['id']}", headers=AUTORIZACAO
    ).json()
    assert guardado["nome"] == "clipe.mp4"
    assert guardado["estado"] == "aguardando_upload"


def test_tipo_diferente_de_mp4_recebe_415_e_nada_e_criado() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar(tipo="video/quicktime")

    assert resposta.status_code == 415
    assert ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json() == []
    assert ambiente.armazenamento.pedidos == []


def test_tipo_errado_recebe_415_mesmo_com_nome_ou_tamanho_invalidos() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar(nome="clipe.mov", tipo="video/quicktime", tamanho_bytes=0)

    assert resposta.status_code == 415
    assert ambiente.armazenamento.pedidos == []


def test_tamanho_acima_do_maximo_configurado_recebe_422() -> None:
    ambiente = Ambiente(tamanho_maximo=5000)

    assert ambiente.criar(tamanho_bytes=5000).status_code == 202
    assert ambiente.criar(tamanho_bytes=5001).status_code == 422


def test_tamanho_zero_negativo_ou_nao_inteiro_recebe_422() -> None:
    ambiente = Ambiente()

    for tamanho in (0, -1, "1000", 10.5, None):
        assert ambiente.criar(tamanho_bytes=tamanho).status_code == 422


def test_nome_vazio_ou_longo_recebe_422() -> None:
    ambiente = Ambiente()

    assert ambiente.criar(nome="").status_code == 422
    assert ambiente.criar(nome="a" * 252 + ".mp4").status_code == 422


def test_nome_com_caminho_ou_sem_extensao_mp4_recebe_422() -> None:
    ambiente = Ambiente()

    for nome in (
        "../clipe.mp4",
        "a/b.mp4",
        "a\\b.mp4",
        "clipe.mov",
        "clipe",
        "a\x00b.mp4",
    ):
        assert ambiente.criar(nome=nome).status_code == 422, nome


def test_campo_desconhecido_recebe_422() -> None:
    assert Ambiente().criar(estado="concluido").status_code == 422


def test_get_jobs_lista_do_mais_recente_para_o_mais_antigo() -> None:
    ambiente = Ambiente()
    for nome in ("a.mp4", "b.mp4", "c.mp4"):
        ambiente.criar(nome=nome)
        ambiente.relogio.agora += timedelta(minutes=1)

    lista = ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()

    assert [j["nome"] for j in lista] == ["c.mp4", "b.mp4", "a.mp4"]
    assert set(lista[0]) == {
        "id",
        "nome",
        "estado",
        "codigo_falha",
        "duracao_s",
        "criado_em",
        "atualizado_em",
    }


def test_get_job_inexistente_recebe_404() -> None:
    resposta = Ambiente().cliente.get("/v1/jobs/nao-existe", headers=AUTORIZACAO)

    assert resposta.status_code == 404


def test_jobs_sem_token_recebe_401() -> None:
    assert Ambiente().cliente.get("/v1/jobs").status_code == 401


def test_sem_adaptadores_reais_a_api_responde_503() -> None:
    cliente = TestClient(criar_app(VerificadorFalso()))

    assert cliente.get("/v1/jobs", headers=AUTORIZACAO).status_code == 503


def test_job_sem_upload_em_24h_vira_falhou_com_upload_expirado() -> None:
    ambiente = Ambiente()
    antigo = ambiente.criar(nome="antigo.mp4").json()["id"]
    ambiente.relogio.agora += timedelta(hours=23, minutes=59)
    recente = ambiente.criar(nome="recente.mp4").json()["id"]
    ambiente.relogio.agora = INICIO + timedelta(hours=24)

    expirados = expirar_uploads(
        ambiente.repositorio, ambiente.armazenamento, ambiente.relogio()
    )

    assert expirados == [antigo]
    assert ambiente.armazenamento.cancelados == [antigo]
    job = ambiente.cliente.get(f"/v1/jobs/{antigo}", headers=AUTORIZACAO).json()
    assert (job["estado"], job["codigo_falha"]) == ("falhou", "upload_expirado")
    assert ambiente.cliente.get(f"/v1/jobs/{recente}", headers=AUTORIZACAO).json()[
        "estado"
    ] == ("aguardando_upload")


def test_expiracao_nao_mexe_em_job_que_ja_passou_do_upload() -> None:
    ambiente = Ambiente()
    job_id = ambiente.criar().json()["id"]
    job = ambiente.repositorio.obter(job_id)
    assert isinstance(job, Job)
    ambiente.repositorio.salvar(job.model_copy(update={"estado": "validando"}))
    ambiente.relogio.agora += timedelta(days=3)

    assert (
        expirar_uploads(
            ambiente.repositorio, ambiente.armazenamento, ambiente.relogio()
        )
        == []
    )
