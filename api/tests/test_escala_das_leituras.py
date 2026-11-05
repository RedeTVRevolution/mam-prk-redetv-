"""Leituras que se repetiam a cada pedido, agora uma só (#362): os papéis, a credencial
da assinatura e o catálogo na leitura da Decupagem."""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from threading import Barrier, Thread
from typing import Any

from fastapi.testclient import TestClient

from api.auth import Usuario
from api.catalogo import CatalogoEmMemoria, PessoaDoCatalogo
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.marcas import CatalogoDeMarcasEmMemoria, MarcaDoCatalogo
from api.nuvem import AssinaturaPeloIam
from api.papeis import DocumentoDePapeis, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ADMIN = {"Authorization": "Bearer admin"}


class PapeisContados(RepositorioDePapeisEmMemoria):
    """Conta as leituras do documento de papéis (as três portas de leitura)."""

    def __init__(self) -> None:
        super().__init__()
        self.leituras = 0

    def ler(self, uid: str) -> DocumentoDePapeis:
        self.leituras += 1
        return DocumentoDePapeis(uid, uid in self._desativadas, self._papeis.get(uid))

    def obter(self, uid: str) -> list[Any] | None:
        self.leituras += 1
        return super().obter(uid)

    def desativada(self, uid: str) -> bool:
        self.leituras += 1
        return super().desativada(uid)


def _job(id: str = "j1") -> Job:
    return Job(
        id=id,
        nome="tv-fama.mp4",
        tamanho_bytes=10,
        sha256="a" * 64,
        estado="concluido",
        criado_por="sistema:Playout",
        sistema="Playout",
        criado_em=BASE,
        atualizado_em=BASE,
    )


def _cliente(
    papeis: PapeisContados,
    catalogo: CatalogoEmMemoria | None = None,
    marcas: CatalogoDeMarcasEmMemoria | None = None,
    armazenamento: ArmazenamentoFalso | None = None,
) -> TestClient:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job())
    return TestClient(
        criar_app(
            VerificadorFalso({"admin": Usuario(uid="adm", email="adm@redetv.com")}),
            jobs,
            armazenamento or ArmazenamentoFalso(),
            papeis=papeis,
            catalogo=catalogo,
            marcas=marcas,
        )
    )


def test_papeis_sao_lidos_uma_vez_por_pedido_mesmo_com_varias_permissoes() -> None:
    papeis = PapeisContados()
    papeis.salvar("adm", ["administrador"])
    cliente = _cliente(papeis)

    # A rota confere `ler` na dependência e a lixeira do Job: mais de uma permissão.
    resposta = cliente.get("/v1/jobs/j1", headers=ADMIN)

    assert resposta.status_code == 200
    assert papeis.leituras == 1


def test_conta_desativada_continua_recusada() -> None:
    papeis = PapeisContados()
    papeis.salvar("adm", ["administrador"])
    papeis.marcar_desativada("adm", True)
    cliente = _cliente(papeis)

    assert cliente.get("/v1/jobs/j1", headers=ADMIN).status_code == 401
    assert papeis.leituras == 1


class CredencialFalsa:
    def __init__(self) -> None:
        self.valid = False
        self.renovacoes = 0
        self.token = "token-0"
        self.service_account_email = "svc@projeto.iam.gserviceaccount.com"

    def refresh(self, requisicao: object) -> None:
        self.renovacoes += 1
        self.valid = True
        self.token = f"token-{self.renovacoes}"


def test_cinquenta_assinaturas_seguidas_renovam_a_credencial_uma_vez() -> None:
    credencial = CredencialFalsa()
    obtidas: list[int] = []

    def obter() -> CredencialFalsa:
        obtidas.append(1)
        return credencial

    assinatura = AssinaturaPeloIam(obter, lambda: object())

    respostas = [assinatura() for _ in range(50)]

    assert credencial.renovacoes == 1
    assert len(obtidas) == 1
    assert {r["access_token"] for r in respostas} == {"token-1"}


def test_credencial_expirada_e_renovada_de_novo() -> None:
    credencial = CredencialFalsa()
    assinatura = AssinaturaPeloIam(lambda: credencial, lambda: object())
    assinatura()
    credencial.valid = False

    assert assinatura()["access_token"] == "token-2"


def test_threads_juntas_renovam_a_credencial_uma_vez() -> None:
    credencial = CredencialFalsa()
    assinatura = AssinaturaPeloIam(lambda: credencial, lambda: object())
    largada = Barrier(8)
    respostas: list[dict[str, Any]] = []

    def assinar() -> None:
        largada.wait()
        respostas.append(assinatura())

    threads = [Thread(target=assinar) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert credencial.renovacoes == 1
    assert len(respostas) == 8
    assert {r["access_token"] for r in respostas} == {"token-1"}


class CatalogoContado(CatalogoEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lotes: list[list[str]] = []
        self.individuais = 0

    def obter(self, id: str) -> PessoaDoCatalogo | None:
        self.individuais += 1
        return super().obter(id)

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        self.lotes.append(list(ids))
        return super().obter_varios(ids)


class MarcasContadas(CatalogoDeMarcasEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lotes: list[list[str]] = []
        self.individuais = 0

    def obter(self, id: str) -> MarcaDoCatalogo | None:
        self.individuais += 1
        return super().obter(id)

    def obter_varios(self, ids: Iterable[str]) -> dict[str, MarcaDoCatalogo]:
        self.lotes.append(list(ids))
        return super().obter_varios(ids)


def test_decupagem_com_30_pessoas_de_10_ids_faz_uma_leitura_em_lote() -> None:
    catalogo = CatalogoContado()
    marcas = MarcasContadas()
    for i in range(10):
        catalogo._pessoas[f"p{i}"] = PessoaDoCatalogo(
            id=f"p{i}", nome=f"Pessoa {i}", papel="x"
        )
    marcas._marcas["m0"] = MarcaDoCatalogo(id="m0", nome="Marca")
    modelo = {
        "pessoas": [
            {
                "nome": f"Pessoa {i % 10}",
                "catalogo_id": f"p{i % 10}",
                "inicio_ms": i,
                "fim_ms": i + 1,
            }
            for i in range(30)
        ],
        "comerciais": [
            {"marca": "Marca", "catalogo_id": "m0", "inicio_ms": i, "fim_ms": i + 1}
            for i in range(5)
        ],
    }
    armazenamento = ArmazenamentoFalso()
    armazenamento.decupagens["j1"] = [json.dumps(modelo).encode()]
    papeis = PapeisContados()
    papeis.salvar("adm", ["administrador"])
    cliente = _cliente(papeis, catalogo, marcas, armazenamento)

    resposta = cliente.get("/v1/jobs/j1/decupagem", headers=ADMIN)

    assert resposta.status_code == 200
    assert len(catalogo.lotes) == 1
    assert sorted(catalogo.lotes[0]) == sorted(f"p{i}" for i in range(10))
    assert marcas.lotes == [["m0"]]
    assert catalogo.individuais == 0
    assert marcas.individuais == 0
    assert all(p["catalogo_id"].startswith("p") for p in resposta.json()["pessoas"])
