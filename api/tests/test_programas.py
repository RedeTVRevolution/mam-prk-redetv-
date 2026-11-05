from datetime import UTC, datetime

from fastapi.testclient import TestClient

from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.carregar_programas import carregar
from api.catalogo import Catalogo, CatalogoEmMemoria
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.programas import ProgramasEmMemoria, perfis_dos_programas
from api.tests.programas_de_teste import cadastro_com_tv_fama
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

AUTORIZACAO = {"Authorization": "Bearer token"}


def _cliente(
    papeis: list[Papel],
) -> tuple[TestClient, ProgramasEmMemoria, Catalogo]:
    programas, catalogo = cadastro_com_tv_fama()
    repositorio_de_papeis = RepositorioDePapeisEmMemoria()
    repositorio_de_papeis.salvar("u1", papeis)
    cliente = TestClient(
        criar_app(
            VerificadorFalso({"token": Usuario(uid="u1", email="a@b.c")}),
            RepositorioEmMemoria(),
            ArmazenamentoFalso(),
            papeis=repositorio_de_papeis,
            programas=programas,
            catalogo=catalogo,
            auditoria=RepositorioDeAuditoriaEmMemoria(),
            relogio=lambda: datetime(2026, 11, 5, tzinfo=UTC),
        )
    )
    return cliente, programas, catalogo


def test_consulta_e_operador_recebem_403_em_cada_rota() -> None:
    for papel in ("consulta", "operador"):
        cliente, programas, _ = _cliente([papel])
        id = programas.listar()[0].id
        corpo = {"nome": "Novo"}
        chamadas = [
            cliente.get("/v1/admin/programas", headers=AUTORIZACAO),
            cliente.post("/v1/admin/programas", json=corpo, headers=AUTORIZACAO),
            cliente.put(f"/v1/admin/programas/{id}", json=corpo, headers=AUTORIZACAO),
            cliente.get(f"/v1/admin/programas/{id}/impacto", headers=AUTORIZACAO),
            cliente.delete(f"/v1/admin/programas/{id}", headers=AUTORIZACAO),
            cliente.post(
                "/v1/admin/programas/pessoas", json=corpo, headers=AUTORIZACAO
            ),
        ]
        assert [c.status_code for c in chamadas] == [403] * 6


def test_editor_cria_renomeia_e_apaga_com_auditoria() -> None:
    cliente, programas, _ = _cliente(["editor"])

    pessoa = cliente.post(
        "/v1/admin/programas/pessoas",
        json={"nome": "Fulana Nova", "apelidos": ["Fu"]},
        headers=AUTORIZACAO,
    ).json()
    criado = cliente.post(
        "/v1/admin/programas",
        json={
            "nome": "Programa Novo",
            "perfil": "Um programa.",
            "pessoas": [{"pessoa_id": pessoa["pessoa_id"], "papel": "âncora"}],
        },
        headers=AUTORIZACAO,
    )
    assert criado.status_code == 201
    id = criado.json()["id"]
    assert "Programa Novo" in cliente.get("/v1/programas", headers=AUTORIZACAO).json()

    renomeado = cliente.put(
        f"/v1/admin/programas/{id}",
        json={"nome": "Outro Nome", "perfil": "Um programa."},
        headers=AUTORIZACAO,
    )
    assert renomeado.json()["id"] == id and renomeado.json()["pessoas"] == []

    assert (
        cliente.delete(f"/v1/admin/programas/{id}", headers=AUTORIZACAO).status_code
        == 204
    )
    assert programas.obter(id) is None
    auditoria = cliente.get("/v1/admin/auditoria", headers=AUTORIZACAO)
    assert auditoria.status_code == 403  # o Editor não vê a tela da auditoria


def test_nome_repetido_da_409_e_pessoa_fora_do_catalogo_da_422() -> None:
    cliente, _, _ = _cliente(["editor"])

    repetido = cliente.post(
        "/v1/admin/programas", json={"nome": "tv fama"}, headers=AUTORIZACAO
    )
    fora = cliente.post(
        "/v1/admin/programas",
        json={"nome": "X", "pessoas": [{"pessoa_id": "nao-existe", "papel": ""}]},
        headers=AUTORIZACAO,
    )

    assert (repetido.status_code, fora.status_code) == (409, 422)


def test_perfil_enorme_e_recusado() -> None:
    cliente, _, _ = _cliente(["editor"])

    resposta = cliente.post(
        "/v1/admin/programas",
        json={"nome": "X", "perfil": "a" * 5000},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 422


def test_carga_unica_e_idempotente_e_poe_o_papel_no_vinculo() -> None:
    programas, catalogo = ProgramasEmMemoria(), CatalogoEmMemoria()
    catalogo.acrescentar("Leão Lobo", "comentarista", [])
    dados = {
        "TV Fama": {
            "perfil": "Revista.",
            "pessoas": [
                {"nome": "Leão Lobo", "papel": "apresentador", "apelidos": []},
                {"nome": "Ana", "papel": "repórter", "apelidos": ["Aninha"]},
            ],
        }
    }

    primeira = carregar(programas, catalogo, dados)
    segunda = carregar(programas, catalogo, dados)

    assert (primeira, segunda) == ((1, 1), (0, 0))
    texto = perfis_dos_programas(programas, catalogo)["TV Fama"].texto()
    assert "- Leão Lobo, apresentador." in texto
    assert '- Ana, repórter; também chamado de "Aninha".' in texto
