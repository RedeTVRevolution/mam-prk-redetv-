from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi.testclient import TestClient

from api.auth import ESCOPOS, Escopo, Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
    main,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
NOVO_JOB = {"nome": "a.mp4", "tamanho_bytes": 10, "tipo": "video/mp4"}
PESSOA = {"Authorization": "Bearer token-bom"}


class Mundo:
    def __init__(self) -> None:
        self.chaves = RepositorioDeChavesEmMemoria()
        self.jobs = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
                self.jobs,
                self.armazenamento,
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
            )
        )

    def chave(self, sistema: str, *escopos: str) -> dict[str, str]:
        emitida = emitir_chave(
            sistema, cast(frozenset[Escopo], frozenset(escopos)), MAC, self.chaves, BASE
        )
        return {"X-API-Key": emitida.chave}

    def job(self, id: str, sistema: str | None, estado: str = "concluido") -> Job:
        job = Job(
            id=id,
            nome="a.mp4",
            tamanho_bytes=10,
            estado=estado,  # type: ignore[arg-type]
            criado_por=f"sistema:{sistema}" if sistema else "u1",
            sistema=sistema,
            criado_em=BASE,
            atualizado_em=BASE,
        )
        self.jobs.salvar(job)
        self.armazenamento.decupagens[id] = [b"{}"]
        return job


ROTAS = [
    ("criar", "POST", "/v1/jobs", {"json": NOVO_JOB}),
    ("ler", "GET", "/v1/jobs", {}),
    ("ler", "GET", "/v1/jobs/j1", {}),
    ("ler", "GET", "/v1/jobs/j1/decupagem", {}),
    ("ler", "GET", "/v1/jobs/j1/reproducao", {}),
    ("ler", "GET", "/v1/jobs/j1/quadros/plano-0.jpg", {}),
    ("cancelar", "DELETE", "/v1/jobs/j1", {}),
]


@pytest.mark.parametrize(("escopo", "metodo", "caminho", "extra"), ROTAS)
def test_rota_sem_o_escopo_recebe_403_e_com_ele_passa(
    escopo: str, metodo: str, caminho: str, extra: dict[str, object]
) -> None:
    mundo = Mundo()
    mundo.job("j1", "Legado", estado="validando" if metodo == "DELETE" else "concluido")
    outros = set(ESCOPOS) - {escopo}

    sem = mundo.cliente.request(
        metodo,
        caminho,
        headers=mundo.chave("Legado", *outros),
        **extra,  # type: ignore[arg-type]
    )
    com = mundo.cliente.request(
        metodo,
        caminho,
        headers=mundo.chave("Legado", escopo),
        **extra,  # type: ignore[arg-type]
    )

    assert sem.status_code == 403
    assert com.status_code in (200, 202)


@pytest.mark.parametrize(("escopo", "metodo", "caminho", "extra"), ROTAS)
def test_pessoa_continua_podendo_tudo(
    escopo: str, metodo: str, caminho: str, extra: dict[str, object]
) -> None:
    mundo = Mundo()
    mundo.job("j1", None, estado="validando" if metodo == "DELETE" else "concluido")

    resposta = mundo.cliente.request(metodo, caminho, headers=PESSOA, **extra)  # type: ignore[arg-type]

    assert resposta.status_code in (200, 202)


def test_dois_sistemas_com_arquivo_igual_nao_enxergam_o_job_um_do_outro() -> None:
    mundo = Mundo()
    a, b = mundo.chave("A", *ESCOPOS), mundo.chave("B", *ESCOPOS)
    id_a = mundo.cliente.post("/v1/jobs", json=NOVO_JOB, headers=a).json()["id"]
    id_b = mundo.cliente.post("/v1/jobs", json=NOVO_JOB, headers=b).json()["id"]
    for job_id in (id_a, id_b):
        mundo.jobs.salvar(
            mundo.jobs.obter(job_id).model_copy(update={"estado": "concluido"})  # type: ignore[union-attr]
        )
        mundo.armazenamento.decupagens[job_id] = [b"{}"]

    for cabecalho, alheio in ((a, id_b), (b, id_a)):
        for sufixo in ("", "/decupagem", "/reproducao", "/quadros/plano-0.jpg"):
            resposta = mundo.cliente.get(
                f"/v1/jobs/{alheio}{sufixo}", headers=cabecalho
            )
            assert resposta.status_code == 404
        # Nem um If-None-Match com o ETag certo revela o job alheio com um 304.
        etag = mundo.cliente.get(f"/v1/jobs/{alheio}", headers=PESSOA).headers["ETag"]
        resposta = mundo.cliente.get(
            f"/v1/jobs/{alheio}", headers={**cabecalho, "If-None-Match": etag}
        )
        assert resposta.status_code == 404
        assert (
            mundo.cliente.delete(f"/v1/jobs/{alheio}", headers=cabecalho).status_code
            == 404
        )
    assert [j["id"] for j in mundo.cliente.get("/v1/jobs", headers=a).json()] == [id_a]
    assert [j["id"] for j in mundo.cliente.get("/v1/jobs", headers=b).json()] == [id_b]
    # O 404 não mexeu no job alheio.
    assert mundo.jobs.obter(id_b).estado == "concluido"  # type: ignore[union-attr]


def test_job_de_pessoa_responde_404_para_sistema() -> None:
    mundo = Mundo()
    mundo.job("j1", None)

    resposta = mundo.cliente.get("/v1/jobs/j1", headers=mundo.chave("A", "ler"))

    assert resposta.status_code == 404
    assert mundo.cliente.get("/v1/jobs", headers=mundo.chave("A", "ler")).json() == []


def test_404_do_alheio_e_igual_ao_do_inexistente() -> None:
    mundo = Mundo()
    mundo.job("j1", "B")
    a = mundo.chave("A", "ler")

    alheio = mundo.cliente.get("/v1/jobs/j1", headers=a)
    inexistente = mundo.cliente.get("/v1/jobs/nao-existe", headers=a)

    assert (alheio.status_code, alheio.json()) == (
        inexistente.status_code,
        inexistente.json(),
    )


def test_pessoa_ve_os_jobs_dos_dois_sistemas() -> None:
    mundo = Mundo()
    mundo.job("ja", "A")
    mundo.job("jb", "B")

    ids = {j["id"] for j in mundo.cliente.get("/v1/jobs", headers=PESSOA).json()}

    assert ids == {"ja", "jb"}
    assert mundo.cliente.get("/v1/jobs/ja", headers=PESSOA).status_code == 200
    assert mundo.cliente.get("/v1/jobs/jb", headers=PESSOA).status_code == 200


def test_eu_mostra_os_escopos() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get("/v1/eu", headers=mundo.chave("A", "ler", "criar"))

    assert resposta.json() == {"sistema": "A", "escopos": ["criar", "ler"]}


def test_chave_sem_escopo_no_registro_antigo_nao_pode_nada() -> None:
    mundo = Mundo()
    emitida = emitir_chave("A", frozenset({"ler"}), MAC, mundo.chaves, BASE)
    antigo = emitida.registro.model_dump(exclude={"escopos"})
    mundo.chaves.salvar(type(emitida.registro)(**antigo))

    resposta = mundo.cliente.get("/v1/jobs", headers={"X-API-Key": emitida.chave})

    assert resposta.status_code == 403


def _emitir(*argv: str) -> tuple[int, RepositorioDeChavesEmMemoria, list[str]]:
    chaves = RepositorioDeChavesEmMemoria()
    saida: list[str] = []
    codigo = main(list(argv), MAC, chaves, saida.append, lambda: BASE)
    return codigo, chaves, saida


def test_comando_recusa_emitir_chave_sem_escopos() -> None:
    for argv in (["Legado"], ["Legado", ""], ["Legado", " , "]):
        codigo, chaves, _ = _emitir(*argv)
        assert codigo == 2
        assert chaves.todas() == []


def test_comando_recusa_escopo_desconhecido() -> None:
    codigo, chaves, _ = _emitir("Legado", "ler,apagar")

    assert codigo == 2
    assert chaves.todas() == []


def test_comando_grava_os_escopos_pedidos() -> None:
    codigo, chaves, _ = _emitir("Legado", "ler, criar")

    assert codigo == 0
    (registro,) = chaves.todas()
    assert registro.escopos == ["criar", "ler"]
