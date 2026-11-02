"""A rota da tela lado a lado (#249): a comparação do Job com uma passada, com cada item marcado."""

from typing import Any

from fastapi.testclient import TestClient

from api.auth import Usuario
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.passadas import Custo, Etapa, Passada, PassadasEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_comparar_passadas import BASE, _par
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_passadas import AUTORIZACAO, _job

ROTA = "/v1/jobs/j1/passadas/p1/comparacao"


def _cliente(papeis: list[Papel] | None = None, estado: str = "concluido") -> Any:
    a, b = _par()
    armazem = PassadasEmMemoria()
    armazem.gravar_passada(
        Passada(
            id="p1",
            job_id="j1",
            modelo="gemini-3.8-flash",
            criada_em=BASE,
            custo=Custo(
                tokens_de_entrada=1_000_000,
                tokens_de_saida=0,
                preco_por_milhao_de_entrada=3.0,
                preco_por_milhao_de_saida=9.0,
                usd=3.0,
            ),
            etapas=[
                Etapa(nome="janelas", segundos=30),
                Etapa(nome="consolidacao", segundos=5),
            ],
            decupagem=b,
        )
    )
    armazenamento = ArmazenamentoFalso()
    armazenamento.decupagens["j1"] = [a.model_dump_json().encode()]
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job(estado).model_copy(update={"duracao_s": 3600.0}))
    repo_papeis = RepositorioDePapeisEmMemoria()
    if papeis is not None:
        repo_papeis.salvar("u1", papeis)
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            jobs,
            armazenamento,
            papeis=repo_papeis,
            passadas=armazem,
        )
    )


def _requisito(corpo: dict[str, Any], nome: str) -> dict[str, Any]:
    return next(r for r in corpo["requisitos"] if r["nome"] == nome)


def test_cada_lado_traz_os_itens_com_a_marca_de_diferenca() -> None:
    resposta = _cliente().get(ROTA, headers=AUTORIZACAO)

    assert resposta.status_code == 200
    pautas = _requisito(resposta.json(), "pautas")
    marcas_a = {i["identidade"]: (i["marca"], i["motivos"]) for i in pautas["a"]}
    marcas_b = {i["identidade"]: (i["marca"], i["motivos"]) for i in pautas["b"]}
    assert marcas_a == {
        "Chuva": ("igual", []),
        "Trânsito": ("difere", ["tempo"]),
        "Esporte": ("difere", ["nome"]),
        "Clima": ("so_aqui", []),
    }
    assert marcas_b == {
        "Chuva": ("igual", []),
        "Trânsito": ("difere", ["tempo"]),
        "Futebol": ("difere", ["nome"]),
        "Política": ("so_aqui", []),
    }
    chuva = next(i for i in pautas["a"] if i["identidade"] == "Chuva")
    assert (chuva["inicio_ms"], chuva["fim_ms"]) == (0, 10_000)


def test_o_topo_traz_custo_por_hora_e_tempo_de_cada_lado() -> None:
    corpo = _cliente().get(ROTA, headers=AUTORIZACAO).json()

    assert corpo["modelo"] == "gemini-3.8-flash"
    assert corpo["b"]["custo_por_hora_usd"] == 3.0
    assert corpo["b"]["tempo_total_s"] == 35
    assert [e["nome"] for e in corpo["b"]["etapas"]] == ["janelas", "consolidacao"]
    # O Job não guarda os tokens: sem custo, e a tela diz "n/d".
    assert corpo["a"]["custo_por_hora_usd"] is None


def test_os_comerciais_mostram_o_tipo_como_detalhe() -> None:
    comerciais = _requisito(
        _cliente().get(ROTA, headers=AUTORIZACAO).json(), "comerciais"
    )

    marca_e = next(i for i in comerciais["b"] if i["identidade"] == "Marca E")
    assert marca_e["detalhe"] == "produto_em_cena" and marca_e["motivos"] == ["tipo"]


def test_passada_que_nao_existe_e_404_e_sem_decupagem_ver_e_403() -> None:
    assert (
        _cliente()
        .get("/v1/jobs/j1/passadas/x/comparacao", headers=AUTORIZACAO)
        .status_code
        == 404
    )
    assert _cliente([]).get(ROTA, headers=AUTORIZACAO).status_code == 403


def test_job_que_nao_concluiu_e_409() -> None:
    assert (
        _cliente(estado="analisando").get(ROTA, headers=AUTORIZACAO).status_code == 409
    )
