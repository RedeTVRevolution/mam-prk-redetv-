import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.correcoes import (
    ItemInexistente,
    NovaCorrecao,
    RepositorioDeCorrecoesEmMemoria,
    aplicar,
    identidade_da_pessoa,
    montar_correcao,
    versao_do_modelo,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}


def _pessoa(id: str, nome: str, inicio: int, fim: int) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "origem": "modelo",
        "na_imagem": [{"inicio_ms": inicio, "fim_ms": fim, "evidencia": "rosto"}],
        "citada_na_fala": [{"inicio_ms": fim + 5, "fim_ms": fim + 9}],
        "citada_no_texto": [],
    }


MODELO: dict[str, Any] = {
    "versao_esquema": "1.1",
    "pessoas": [
        _pessoa("pes01", "Ana Souza", 1000, 5000),
        _pessoa("pes02", "não identificado", 7000, 9000),
    ],
}
BYTES = json.dumps(MODELO).encode()
VERSAO = versao_do_modelo(BYTES)


def _novo(**campos: Any) -> dict[str, Any]:
    return {
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "valor": "Ana Souza Lima",
        "motivo": "sobrenome completo",
        "versao": VERSAO,
        **campos,
    }


class Mundo:
    def __init__(self, papeis: list[Papel], estado: str = "concluido") -> None:
        repo_papeis = RepositorioDePapeisEmMemoria()
        repo_papeis.salvar("u1", papeis)
        jobs = RepositorioEmMemoria()
        jobs.salvar(
            Job(
                id="j1",
                nome="a.mp4",
                tamanho_bytes=10,
                estado=estado,  # type: ignore[arg-type]
                criado_por="u1",
                criado_em=BASE,
                atualizado_em=BASE,
            )
        )
        self.armazenamento = ArmazenamentoFalso()
        self.armazenamento.decupagens["j1"] = [BYTES[:40], BYTES[40:]]
        self.correcoes = RepositorioDeCorrecoesEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {"token-bom": Usuario(uid="u1", email="ana@redetv.com.br")}
                ),
                jobs,
                self.armazenamento,
                papeis=repo_papeis,
                correcoes=self.correcoes,
                relogio=lambda: BASE,
            )
        )

    def corrigir(self, **campos: Any) -> Any:
        return self.cliente.post(
            "/v1/jobs/j1/correcoes", json=_novo(**campos), headers=AUTORIZACAO
        )

    def decupagem(self, params: str = "") -> dict[str, Any]:
        resposta = self.cliente.get(
            f"/v1/jobs/j1/decupagem{params}", headers=AUTORIZACAO
        )
        corpo: dict[str, Any] = resposta.json()
        return corpo


def test_identidade_da_pessoa_e_o_nome_normalizado_ou_o_intervalo_se_nao_identificado() -> (
    None
):
    assert identidade_da_pessoa(_pessoa("a", "  ANA  Sôuza", 1, 2)) == "ana souza"
    assert (
        identidade_da_pessoa(_pessoa("b", "Não identificado", 7000, 9000))
        == "nao identificado@7000-9009"
    )


def test_aplicar_sem_correcoes_marca_tudo_como_modelo_e_nao_altera_o_original() -> None:
    entregue = aplicar(MODELO, VERSAO, [])

    assert [p["origem"] for p in entregue["pessoas"]] == ["modelo", "modelo"]
    assert entregue["pessoas"][0]["nome"] == "Ana Souza"
    assert MODELO["pessoas"][0]["origem"] == "modelo"


def test_montar_correcao_de_item_inexistente_levanta() -> None:
    with pytest.raises(ItemInexistente):
        montar_correcao(MODELO, VERSAO, NovaCorrecao(**_novo(item_id="pes99")), "x")


def test_renomear_grava_autor_data_motivo_antes_depois_e_ancora() -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.corrigir()

    assert resposta.status_code == 201
    [c] = mundo.correcoes.listar("j1")
    assert (c.autor_uid, c.autor_email, c.criada_em) == (
        "u1",
        "ana@redetv.com.br",
        BASE,
    )
    assert (c.motivo, c.tipo, c.antes, c.depois) == (
        "sobrenome completo",
        "pessoa.renomear",
        "Ana Souza",
        "Ana Souza Lima",
    )
    assert c.ancora.model_dump() == {
        "versao": VERSAO,
        "tipo_do_item": "pessoa",
        "identidade": "ana souza",
        "inicio_ms": 1000,
        "fim_ms": 5009,
    }


def test_decupagem_mostra_o_nome_novo_com_origem_revisao_e_o_modelo_continua_cru() -> (
    None
):
    mundo = Mundo(["editor"])
    mundo.corrigir()

    entregue = mundo.decupagem()
    cru = mundo.decupagem("?versao=modelo")

    assert entregue["versao_decupagem"] == VERSAO
    assert [(p["nome"], p["origem"]) for p in entregue["pessoas"]] == [
        ("Ana Souza Lima", "revisao"),
        ("não identificado", "modelo"),
    ]
    assert cru == MODELO


def test_segunda_correcao_guarda_o_nome_corrigido_como_antes() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    mundo.corrigir(valor="Ana S. Lima", motivo="abreviar")

    antes = [c.antes for c in mundo.correcoes.listar("j1")]
    assert antes == ["Ana Souza", "Ana Souza Lima"]
    assert mundo.decupagem()["pessoas"][0]["nome"] == "Ana S. Lima"


def test_renomear_pessoa_nao_identificada_casa_pelo_intervalo() -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(item_id="pes02", valor="Bia Reis").status_code == 201

    [c] = mundo.correcoes.listar("j1")
    assert (c.ancora.identidade, c.ancora.inicio_ms, c.ancora.fim_ms) == (
        "nao identificado@7000-9009",
        7000,
        9009,
    )
    assert [p["nome"] for p in mundo.decupagem()["pessoas"]] == [
        "Ana Souza",
        "Bia Reis",
    ]


def test_versao_desatualizada_da_409_e_nada_e_gravado() -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(versao="0" * 64).status_code == 409
    assert mundo.correcoes.listar("j1") == []


def test_job_nao_concluido_da_409() -> None:
    assert Mundo(["editor"], estado="analisando").corrigir().status_code == 409


@pytest.mark.parametrize("papeis", [["consulta"], ["operador"], []])
def test_sem_decupagem_editar_da_403(papeis: list[Papel]) -> None:
    mundo = Mundo(papeis)

    assert mundo.corrigir().status_code == 403
    assert mundo.correcoes.listar("j1") == []


def test_curador_tambem_corrige() -> None:
    assert Mundo(["curador"]).corrigir().status_code == 201


def test_sem_token_da_401() -> None:
    resposta = Mundo(["editor"]).cliente.post("/v1/jobs/j1/correcoes", json=_novo())
    assert resposta.status_code == 401


def test_item_inexistente_da_422() -> None:
    assert Mundo(["editor"]).corrigir(item_id="pes99").status_code == 422


@pytest.mark.parametrize(
    "campos",
    [
        {"valor": ""},
        {"valor": "   "},
        {"valor": "x" * 201},
        {"valor": "Ana\x00"},
        {"valor": "Ana\nSouza"},
        {"motivo": ""},
        {"motivo": "x" * 501},
        {"motivo": "a\x1bb"},
        {"tipo": "pessoa.apagar"},
    ],
)
def test_entrada_hostil_da_422(campos: dict[str, Any]) -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(**campos).status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_correcao_de_outra_versao_do_modelo_nao_e_aplicada() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    nova = {**MODELO, "programa": {"resumo": "reprocessado"}}
    mundo.armazenamento.decupagens["j1"] = [json.dumps(nova).encode()]

    assert mundo.decupagem()["pessoas"][0]["nome"] == "Ana Souza"
