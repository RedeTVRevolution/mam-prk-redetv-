"""Fundir duas pessoas do catálogo (#209)."""

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.catalogo import CatalogoEmMemoria, Rosto
from api.correcoes import LIMITE_DO_MOTIVO, versao_do_modelo
from api.jobs import RepositorioEmMemoria
from api.lixeira_do_catalogo import FotosEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import BASE, _job

CURADOR = {"Authorization": "Bearer curador"}
EDITOR = {"Authorization": "Bearer editor"}


def _pessoa(catalogo_id: str, nome: str) -> dict[str, Any]:
    return {
        "id": "pes01",
        "nome": nome,
        "fontes_do_nome": ["gc"],
        "origem": "modelo_forte",
        "estado_do_nome": "confirmado",
        "catalogo_id": catalogo_id,
        "na_imagem": [
            {"inicio_ms": 0, "fim_ms": 1000, "evidencia": "gc"},
            {"inicio_ms": 2000, "fim_ms": 3000, "evidencia": "gc"},
        ],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }


class Mundo:
    def __init__(self) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.sabrina = self.catalogo.acrescentar(
            "Sabrina Sato", "apresentadora", ["Sá"]
        )
        self.duplicada = self.catalogo.acrescentar("Sabrina S.", "", [], a_revisar=True)
        self.catalogo.definir_rostos(
            self.sabrina.id,
            [Rosto(origem="acervo", referencia=f"referencias/{self.sabrina.id}/a.jpg")],
        )
        self.catalogo.definir_rostos(
            self.duplicada.id,
            [
                Rosto(
                    origem="acervo", referencia=f"referencias/{self.duplicada.id}/b.jpg"
                )
            ],
        )
        self.fotos = FotosEmMemoria(
            {
                f"referencias/{self.sabrina.id}/a.jpg",
                f"referencias/{self.duplicada.id}/b.jpg",
                f"referencias/{self.duplicada.id}/velha.jpg",
            }
        )
        self.jobs = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        for id in ("j1", "j2"):
            self.jobs.salvar(_job(id, pessoas_do_catalogo=[self.duplicada.id]))
            self.armazenamento.decupagens[id] = [
                json.dumps(
                    {"pessoas": [_pessoa(self.duplicada.id, "Sabrina S.")]}
                ).encode()
            ]
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("cur", ["curador"])
        papeis.salvar("ed", ["editor"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "curador": Usuario(uid="cur", email="Cur@redetv.com"),
                        "editor": Usuario(uid="ed", email="ed@redetv.com"),
                    }
                ),
                self.jobs,
                self.armazenamento,
                papeis=papeis,
                auditoria=self.auditoria,
                catalogo=self.catalogo,
                fotos_de_referencia=self.fotos,
                relogio=lambda: BASE,
            )
        )

    def fundir(
        self,
        origem: str | None = None,
        destino: str | None = None,
        headers: Any = CURADOR,
    ) -> Any:
        return self.cliente.post(
            f"/v1/catalogo/pessoas/{origem or self.duplicada.id}/fundir",
            json={"destino_id": destino or self.sabrina.id, "motivo": "nome duplicado"},
            headers=headers,
        )

    def achar(self, q: str) -> list[str]:
        resposta = self.cliente.get(
            "/v1/catalogo/pessoas", params={"q": q}, headers=CURADOR
        )
        return [p["id"] for p in resposta.json()]


def test_depois_de_fundir_buscar_pela_origem_acha_o_destino() -> None:
    mundo = Mundo()
    assert set(mundo.achar("sabrina")) == {mundo.sabrina.id, mundo.duplicada.id}

    resposta = mundo.fundir()

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "origem_id": mundo.duplicada.id,
        "destino_id": mundo.sabrina.id,
        "destino_nome": "Sabrina Sato",
        "videos": 2,
        "aparicoes": 4,
    }
    assert mundo.achar("sabrina s") == [mundo.sabrina.id]
    destino = mundo.catalogo.obter(mundo.sabrina.id)
    assert destino and destino.apelidos == ["Sá", "Sabrina S."]
    origem = mundo.catalogo.obter(mundo.duplicada.id)
    assert origem and origem.fundida and origem.fundida.destino_id == destino.id
    assert mundo.catalogo.achar("Sabrina S.")[0].id == destino.id


def test_a_decupagem_mostra_o_destino_sem_reescrever_o_gravado() -> None:
    mundo = Mundo()
    mundo.fundir()

    lida = mundo.cliente.get("/v1/jobs/j1/decupagem", headers=CURADOR).json()

    assert lida["pessoas"][0]["nome"] == "Sabrina Sato"
    assert lida["pessoas"][0]["catalogo_id"] == mundo.sabrina.id
    gravada = json.loads(mundo.armazenamento.decupagens["j1"][0])
    assert gravada["pessoas"][0]["catalogo_id"] == mundo.duplicada.id


def test_as_fotos_da_origem_somem_e_as_do_destino_ficam() -> None:
    mundo = Mundo()

    mundo.fundir()

    assert mundo.fotos.objetos == {f"referencias/{mundo.sabrina.id}/a.jpg"}
    origem = mundo.catalogo.obter(mundo.duplicada.id)
    assert origem and origem.rostos == []
    destino = mundo.catalogo.obter(mundo.sabrina.id)
    assert destino and len(destino.rostos) == 1


def test_fundir_em_si_mesma_ou_em_quem_ja_aponta_ou_inexistente_da_422() -> None:
    mundo = Mundo()
    terceira = mundo.catalogo.acrescentar("Outra", "", [])

    assert mundo.fundir(destino=mundo.duplicada.id).status_code == 422
    assert mundo.fundir(destino="nao-existe").status_code == 422
    assert mundo.fundir().status_code == 200
    # O destino já aponta para outra pessoa; a origem já foi fundida.
    em_quem_ja_aponta = mundo.fundir(origem=terceira.id, destino=mundo.duplicada.id)
    assert em_quem_ja_aponta.status_code == 422
    assert "já foi fundida" in em_quem_ja_aponta.json()["detail"]
    assert mundo.fundir().status_code == 422


def test_sem_a_permissao_e_403_e_nada_muda() -> None:
    mundo = Mundo()

    assert mundo.fundir(headers=EDITOR).status_code == 403
    assert mundo.cliente.post(
        f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir", json={}
    ).status_code in (401, 403)
    origem = mundo.catalogo.obter(mundo.duplicada.id)
    assert origem and origem.fundida is None
    assert len(mundo.fotos.objetos) == 3


def test_o_motivo_e_obrigatorio() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.post(
        f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir",
        json={"destino_id": mundo.sabrina.id, "motivo": "  "},
        headers=CURADOR,
    )

    assert resposta.status_code == 422


def test_a_fusao_grava_pessoa_fundida_na_auditoria() -> None:
    mundo = Mundo()

    mundo.fundir()

    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.acao == "pessoa.fundida"
    assert registro.uid == "cur" and registro.email == "cur@redetv.com"
    assert registro.alvo_id == mundo.duplicada.id
    assert registro.motivo == "nome duplicado"
    assert registro.detalhes == {
        "origem_id": mundo.duplicada.id,
        "origem_nome": "Sabrina S.",
        "destino_id": mundo.sabrina.id,
        "destino_nome": "Sabrina Sato",
        "videos": 2,
        "aparicoes": 4,
        "fotos_apagadas": 1,
    }


def test_o_impacto_conta_videos_aparicoes_e_fotos_sem_mudar_nada() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get(
        f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir/impacto",
        params={"destino_id": mundo.sabrina.id},
        headers=CURADOR,
    )

    assert resposta.json() == {
        "origem_nome": "Sabrina S.",
        "destino_nome": "Sabrina Sato",
        "videos": 2,
        "aparicoes": 4,
        "fotos_apagadas": 1,
    }
    origem = mundo.catalogo.obter(mundo.duplicada.id)
    assert origem and origem.fundida is None


def test_o_impacto_da_fusao_abre_so_as_decupagens_da_pessoa() -> None:
    mundo = Mundo()
    for i in range(50):
        mundo.jobs.salvar(_job(f"x{i}"))
    abertas: list[str] = []
    abrir = mundo.armazenamento.abrir_decupagem

    def contando(job_id: str) -> Any:
        abertas.append(job_id)
        return abrir(job_id)

    mundo.armazenamento.abrir_decupagem = contando  # type: ignore[method-assign]

    mundo.cliente.get(
        f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir/impacto",
        params={"destino_id": mundo.sabrina.id},
        headers=CURADOR,
    )

    assert sorted(abertas) == ["j1", "j2"]


def test_o_motivo_vai_ate_o_limite_das_correcoes() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.post(
        f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir",
        json={"destino_id": mundo.sabrina.id, "motivo": "a" * LIMITE_DO_MOTIVO},
        headers=CURADOR,
    )

    assert resposta.status_code == 200, resposta.text


def test_fundir_de_novo_conta_tambem_quem_ja_foi_fundido_na_origem() -> None:
    mundo = Mundo()
    terceira = mundo.catalogo.acrescentar("Sabrina Sato Oficial", "", [])
    mundo.fundir()

    resposta = mundo.fundir(origem=mundo.sabrina.id, destino=terceira.id)

    assert resposta.status_code == 200, resposta.text
    assert (resposta.json()["videos"], resposta.json()["aparicoes"]) == (2, 4)
    lida = mundo.cliente.get("/v1/jobs/j1/decupagem", headers=CURADOR).json()
    assert lida["pessoas"][0]["catalogo_id"] == terceira.id


def test_a_previa_deixa_a_fusao_para_a_leitura_e_pula_a_que_nao_abre(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mundo = Mundo()
    mundo.jobs.salvar(
        _job("j3", pessoas_do_catalogo=[mundo.duplicada.id])
    )  # sem arquivo
    lidas: list[str] = []
    obter = mundo.catalogo.obter

    def obter_contado(id: str) -> Any:
        lidas.append(id)
        return obter(id)

    mundo.catalogo.obter = obter_contado  # type: ignore[method-assign]
    logger = logging.getLogger("api.leitura_da_decupagem")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING"):
            resposta = mundo.cliente.get(
                f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir/impacto",
                params={"destino_id": mundo.sabrina.id},
                headers=CURADOR,
            )
    finally:
        logger.removeHandler(caplog.handler)

    assert resposta.status_code == 200, resposta.text
    assert (resposta.json()["videos"], resposta.json()["aparicoes"]) == (2, 4)
    assert "j3" in caplog.text
    # só a validação da rota lê a origem e o destino: a prévia não resolve fusão por conta própria
    assert sorted(lidas) == sorted([mundo.duplicada.id, mundo.sabrina.id])


def test_pessoa_fundida_nao_vai_para_a_lixeira() -> None:
    mundo = Mundo()
    mundo.fundir()

    resposta = mundo.cliente.post(
        f"/v1/admin/lixeira/pessoas/{mundo.duplicada.id}",
        json={"motivo": "duplicada"},
        headers=CURADOR,
    )

    assert resposta.status_code == 422
    origem = mundo.catalogo.obter(mundo.duplicada.id)
    assert origem and origem.lixeira is None and origem.fundida is not None


def test_a_correcao_nao_aponta_para_pessoa_fundida() -> None:
    mundo = Mundo()
    mundo.fundir()

    resposta = mundo.cliente.post(
        "/v1/jobs/j1/correcoes",
        json={
            "tipo": "pessoa.renomear",
            "item_id": "pes01",
            "valor": "Sabrina S.",
            "catalogo_id": mundo.duplicada.id,
            "motivo": "nome do catálogo",
            "versao": versao_do_modelo(mundo.armazenamento.decupagens["j1"][0]),
        },
        headers=CURADOR,
    )

    assert resposta.status_code == 422, resposta.text


def test_a_fusao_passa_a_origem_para_o_destino_nos_jobs() -> None:
    mundo = Mundo()

    assert mundo.fundir().status_code == 200

    for id in ("j1", "j2"):
        job = mundo.jobs.obter(id)
        assert job and job.pessoas_do_catalogo == [mundo.sabrina.id]
