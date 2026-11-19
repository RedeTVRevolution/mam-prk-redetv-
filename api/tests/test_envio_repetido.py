"""#763: o envio recusa um Job novo com o mesmo nome e a mesma data de exibição."""

from datetime import timedelta
from typing import Any

import pytest

from api import jobs as modulo_jobs
from api.catalogo import EnvioParaLixeira
from api.jobs import RepositorioEmMemoria
from api.modelo_do_job import Job
from api.tests.test_jobs import (
    INICIO,
    Ambiente,
    _criar_com_chave,
    _soltar_a_marca_de_gravado,
)
from api.tests.test_teto_de_criacao import NOVO_JOB, Mundo

REPETIDO = "Já existe um vídeo com este nome e esta data de exibição"
LIXEIRA = EnvioParaLixeira(em=INICIO, por_uid="u1", por_email="a@b.c", motivo="x")


def _guardar(ambiente: Ambiente, id_: str, **campos: Any) -> None:
    padrao: dict[str, Any] = {
        "nome": "clipe.mp4",
        "tamanho_bytes": 1000,
        "estado": "concluido",
        "criado_por": "u1",
        "data_exibicao": "2026-10-01",
        "criado_em": INICIO,
        "atualizado_em": INICIO,
    }
    ambiente.repositorio.salvar(Job(id=id_, **{**padrao, **campos}))


def test_mesmo_nome_e_mesma_data_da_409_com_o_id_do_existente() -> None:
    ambiente = Ambiente()
    primeiro = ambiente.criar().json()["id"]

    resposta = ambiente.criar()

    assert resposta.status_code == 409
    assert resposta.json() == {"detail": REPETIDO, "job_id": primeiro}
    assert len(ambiente.repositorio.listar()) == 1
    assert len(ambiente.armazenamento.pedidos) == 1


def test_outra_data_ou_outro_nome_cria_normalmente() -> None:
    ambiente = Ambiente()
    ambiente.criar()

    assert ambiente.criar(data_exibicao="2026-10-02").status_code == 202
    assert ambiente.criar(nome="outro.mp4").status_code == 202
    # O nome é comparado como veio: maiúscula é outro nome.
    assert ambiente.criar(nome="CLIPE.mp4").status_code == 202


@pytest.mark.parametrize(
    "estado,codigo",
    [("aguardando_upload", None), ("falhou", "analise_falhou"), ("cancelado", None)],
)
def test_bloqueia_em_qualquer_estado_e_o_falho_dentro_do_prazo(
    estado: str, codigo: str | None
) -> None:
    ambiente = Ambiente()
    _guardar(ambiente, "existente", estado=estado, codigo_falha=codigo)

    assert ambiente.criar().status_code == 409


def test_lixeira_upload_expirado_e_prazo_vencido_nao_bloqueiam() -> None:
    ambiente = Ambiente()
    _guardar(ambiente, "na-lixeira", lixeira=LIXEIRA)
    _guardar(ambiente, "expirado", estado="falhou", codigo_falha="upload_expirado")
    ambiente.relogio.agora = INICIO + timedelta(days=8)
    _guardar(ambiente, "vencido", estado="falhou", codigo_falha="analise_falhou")

    assert ambiente.criar().status_code == 202


def test_os_que_nao_bloqueiam_nao_escondem_o_que_bloqueia() -> None:
    ambiente = Ambiente()
    _guardar(ambiente, "a-lixeira", lixeira=LIXEIRA)
    _guardar(ambiente, "b-expirado", estado="falhou", codigo_falha="upload_expirado")
    _guardar(ambiente, "c-ativo")

    resposta = ambiente.criar()

    assert resposta.status_code == 409
    assert resposta.json()["job_id"] == "c-ativo"


def test_com_o_teto_atingido_o_repetido_da_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(modulo_jobs, "TETO_POR_HORA_DA_PESSOA", 1)
    ambiente = Ambiente()
    ambiente.criar()

    assert ambiente.criar().status_code == 409
    assert ambiente.criar(nome="outro.mp4").status_code == 429


def test_a_mesma_chave_devolve_o_mesmo_job_e_outro_corpo_segue_no_409_da_chave() -> (
    None
):
    ambiente = Ambiente()
    primeira = _criar_com_chave(ambiente, "k1")
    repeticao = _criar_com_chave(ambiente, "k1")
    outro = _criar_com_chave(ambiente, "k1", tamanho_bytes=2000)

    assert (primeira.status_code, repeticao.status_code) == (202, 200)
    assert repeticao.json()["id"] == primeira.json()["id"]
    assert outro.json()["detail"] == "Idempotency-Key já usada com outro corpo"


class _GravadoDuranteARepeticao(RepositorioEmMemoria):
    """A outra repetição grava o Job entre o `obter` desta e a consulta da trava."""

    def __init__(self) -> None:
        super().__init__()
        self.atrasar: Job | None = None

    def obter(self, job_id: str) -> Job | None:
        if self.atrasar is not None and self.atrasar.id == job_id:
            self.salvar(self.atrasar)
            self.atrasar = None
            return None
        return super().obter(job_id)


def test_repeticao_concorrente_da_mesma_chave_nao_e_barrada_pelo_proprio_job() -> None:
    repositorio = _GravadoDuranteARepeticao()
    ambiente = Ambiente(repositorio=repositorio)
    primeira = _criar_com_chave(ambiente, "k1")
    assert primeira.status_code == 202, primeira.text
    gravado = repositorio.obter(primeira.json()["id"])
    assert gravado is not None
    # A outra repetição ainda não gravou nem marcou a reserva.
    repositorio.remover(gravado.id)
    _soltar_a_marca_de_gravado(ambiente)
    repositorio.atrasar = gravado

    repeticao = _criar_com_chave(ambiente, "k1")

    assert repeticao.status_code == 200
    assert repeticao.json()["id"] == gravado.id


def test_chave_de_sistema_so_recebe_o_id_do_job_que_enxerga() -> None:
    mundo = Mundo()
    a, b = mundo.chave("a"), mundo.chave("b")
    pessoa = mundo.cliente.post(
        "/v1/jobs", json=NOVO_JOB, headers={"Authorization": "Bearer token-bom"}
    )
    outra_data = {**NOVO_JOB, "data_exibicao": "2026-10-02"}
    do_sistema = mundo.cliente.post("/v1/jobs", json=outra_data, headers=a)
    assert (pessoa.status_code, do_sistema.status_code) == (202, 202)

    de_pessoa = mundo.cliente.post("/v1/jobs", json=NOVO_JOB, headers=a)
    de_outro = mundo.cliente.post("/v1/jobs", json=outra_data, headers=b)
    proprio = mundo.cliente.post("/v1/jobs", json=outra_data, headers=a)

    assert de_pessoa.status_code == de_outro.status_code == proprio.status_code == 409
    assert de_pessoa.json() == {"detail": REPETIDO}
    assert de_outro.json() == {"detail": REPETIDO}
    assert proprio.json() == {"detail": REPETIDO, "job_id": do_sistema.json()["id"]}


def test_pessoa_recebe_o_id_do_job_de_um_sistema() -> None:
    mundo = Mundo()
    do_sistema = mundo.cliente.post("/v1/jobs", json=NOVO_JOB, headers=mundo.chave("a"))

    resposta = mundo.cliente.post(
        "/v1/jobs", json=NOVO_JOB, headers={"Authorization": "Bearer token-bom"}
    )

    assert resposta.json() == {"detail": REPETIDO, "job_id": do_sistema.json()["id"]}


def test_repeticao_concorrente_ganha_do_outro_job_que_tambem_bloqueia() -> None:
    # Outro envio com chave diferente passou junto pela trava de melhor esforço: a
    # repetição desta chave segue devolvendo o seu Job (200), não o 409.
    repositorio = _GravadoDuranteARepeticao()
    ambiente = Ambiente(repositorio=repositorio)
    primeira = _criar_com_chave(ambiente, "k1")
    gravado = repositorio.obter(primeira.json()["id"])
    assert gravado is not None
    repositorio.remover(gravado.id)
    _soltar_a_marca_de_gravado(ambiente)
    _guardar(ambiente, "outro", estado="aguardando_upload")
    repositorio.atrasar = gravado

    repeticao = _criar_com_chave(ambiente, "k1")

    assert repeticao.status_code == 200
    assert repeticao.json()["id"] == gravado.id
