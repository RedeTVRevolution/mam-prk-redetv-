import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.ciclo_de_vida import EstadoNaoCorrigivel, corrigir_estado
from api.correcao_de_estado import main as comando
from api.jobs import Etapa, Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_decupagem import decupagem_valida
from api.tests.test_escopos import MAC
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
AGORA = BASE + timedelta(hours=1)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}
ROTA = "/v1/admin/jobs/j1/estado"


def _job(estado: str, **extra: Any) -> Job:
    campos: dict[str, Any] = {
        "id": "j1",
        "nome": "a.mp4",
        "tamanho_bytes": 10,
        "estado": estado,
        "criado_por": "u1",
        "criado_em": BASE,
        "atualizado_em": BASE,
    }
    campos.update(extra)
    return Job(**campos)


class Mundo:
    def __init__(
        self,
        job: Job,
        papeis: list[Papel] | None = None,
        decupagem: bool = False,
    ) -> None:
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(job)
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        if decupagem:
            self.armazenamento.decupagens["j1"] = [
                json.dumps(decupagem_valida()).encode()
            ]
        repo_papeis = RepositorioDePapeisEmMemoria()
        repo_papeis.salvar("u1", papeis if papeis is not None else ["administrador"])
        chaves = RepositorioDeChavesEmMemoria()
        self.chave = emitir_chave(
            "Playout", frozenset({"criar", "ler", "cancelar"}), MAC, chaves, BASE
        ).chave
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {"token-bom": Usuario(uid="u1", email="Ana@redetv.com")}
                ),
                self.jobs,
                self.armazenamento,
                chaves=VerificadorDeChaveDeApi(chaves, MAC),
                papeis=repo_papeis,
                auditoria=self.auditoria,
                relogio=lambda: AGORA,
            )
        )

    def corrigir(self, estado: str = "falhou", motivo: str | None = "teste") -> Any:
        corpo = {"estado": estado} | ({"motivo": motivo} if motivo is not None else {})
        return self.cliente.post(ROTA, json=corpo, headers=AUTORIZACAO)

    def job(self) -> Job:
        job = self.jobs.obter("j1")
        assert job is not None
        return job


def test_marca_falha_um_job_que_esta_andando_e_audita() -> None:
    mundo = Mundo(_job("analisando"))

    resposta = mundo.corrigir("falhou", "o Workflows morreu sem avisar")

    assert resposta.status_code == 200
    assert resposta.json()["estado"] == "falhou"
    assert mundo.job().estado == "falhou"
    assert mundo.job().atualizado_em == AGORA
    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.acao == "job.estado_corrigido"
    assert (registro.alvo_tipo, registro.alvo_id) == ("job", "j1")
    assert registro.email == "ana@redetv.com" and registro.uid == "u1"
    assert registro.motivo == "o Workflows morreu sem avisar"
    assert registro.detalhes == {"de": "analisando", "para": "falhou"}


@pytest.mark.parametrize("estado", ["aguardando_upload", "validando", "analisando"])
def test_falha_vale_de_qualquer_estado_que_nao_e_final(estado: str) -> None:
    mundo = Mundo(_job(estado))

    assert mundo.corrigir("falhou").status_code == 200


@pytest.mark.parametrize("estado", ["concluido", "falhou", "cancelado"])
def test_falha_de_estado_final_e_recusada(estado: str) -> None:
    mundo = Mundo(_job(estado))

    resposta = mundo.corrigir("falhou")

    assert resposta.status_code == 409
    assert mundo.job().estado == estado
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_devolve_a_concluido_com_decupagem_completa() -> None:
    mundo = Mundo(
        _job(
            "falhou",
            codigo_falha="analise_falhou",
            etapas={"analise": Etapa(inicio=BASE, fim=BASE, resultado="falhou")},
        ),
        decupagem=True,
    )

    resposta = mundo.corrigir("concluido")

    assert resposta.status_code == 200
    job = mundo.job()
    assert job.estado == "concluido" and job.codigo_falha is None
    assert job.indexacao is not None and job.indexacao.estado == "pendente"
    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.detalhes == {"de": "falhou", "para": "concluido"}


def test_concluido_sem_decupagem_e_recusado() -> None:
    mundo = Mundo(_job("falhou", codigo_falha="analise_falhou"))
    mundo.armazenamento.decupagens_indisponiveis = True  # o objeto não existe

    resposta = mundo.corrigir("concluido")

    assert resposta.status_code == 409
    assert "decupagem" in resposta.json()["detail"]
    assert mundo.job().estado == "falhou"
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_concluido_com_decupagem_incompleta_e_recusado() -> None:
    mundo = Mundo(_job("falhou"))
    mundo.armazenamento.decupagens["j1"] = [b'{"versao_esquema": "1.2"}']

    assert mundo.corrigir("concluido").status_code == 409


def test_concluido_de_job_que_ja_esta_concluido_e_recusado() -> None:
    mundo = Mundo(_job("concluido"), decupagem=True)

    assert mundo.corrigir("concluido").status_code == 409


def test_concluido_de_job_cancelado_ou_que_nem_comecou_e_recusado() -> None:
    for estado in ("cancelado", "aguardando_upload", "validando"):
        mundo = Mundo(_job(estado), decupagem=True)
        assert mundo.corrigir("concluido").status_code == 409


@pytest.mark.parametrize("motivo", [None, "", "   "])
def test_motivo_e_obrigatorio(motivo: str | None) -> None:
    mundo = Mundo(_job("analisando"))

    assert mundo.corrigir("falhou", motivo).status_code == 422
    assert mundo.job().estado == "analisando"


def test_estado_de_destino_fora_dos_dois_e_422() -> None:
    mundo = Mundo(_job("analisando"))

    assert mundo.corrigir("cancelado").status_code == 422


def test_job_inexistente_e_404() -> None:
    mundo = Mundo(_job("analisando"))

    resposta = mundo.cliente.post(
        "/v1/admin/jobs/outro/estado",
        json={"estado": "falhou", "motivo": "x"},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 404


@pytest.mark.parametrize("papeis", [["consulta", "operador"], ["editor"], ["curador"]])
def test_quem_nao_e_administrador_recebe_403(papeis: list[Papel]) -> None:
    mundo = Mundo(_job("analisando"), papeis=papeis)

    assert mundo.corrigir().status_code == 403
    assert mundo.job().estado == "analisando"
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_chave_de_sistema_recebe_403() -> None:
    mundo = Mundo(_job("analisando"))

    resposta = mundo.cliente.post(
        ROTA,
        json={"estado": "falhou", "motivo": "x"},
        headers={"X-API-Key": mundo.chave},
    )

    assert resposta.status_code == 403


def test_sem_token_e_401() -> None:
    mundo = Mundo(_job("analisando"))

    resposta = mundo.cliente.post(ROTA, json={"estado": "falhou", "motivo": "x"})

    assert resposta.status_code == 401


def test_corrigir_estado_do_ciclo_de_vida_recusa_o_estado_que_nao_existe_na_tabela() -> (
    None
):
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("validando"))

    with pytest.raises(EstadoNaoCorrigivel):
        corrigir_estado(jobs, "j1", "cancelado", AGORA, decupagem_completa=lambda: True)


# O comando `make corrigir-estado`, pela mesma função da rota.


def _comando(mundo: Mundo, argumentos: list[str], saida: list[str]) -> int:
    return comando(
        argumentos,
        mundo.jobs,
        mundo.auditoria,
        mundo.armazenamento,
        relogio=lambda: AGORA,
        quem="ana",
        escrever=saida.append,
    )


def test_comando_corrige_o_estado_e_audita_quem_rodou() -> None:
    mundo = Mundo(_job("analisando"))
    saida: list[str] = []

    codigo = _comando(mundo, ["j1", "falhou", "travou na fila"], saida)

    assert codigo == 0
    assert mundo.job().estado == "falhou"
    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.sistema == "corrigir-estado:ana" and registro.uid is None
    assert registro.motivo == "travou na fila"
    assert registro.detalhes == {"de": "analisando", "para": "falhou"}
    assert any("falhou" in linha for linha in saida)


@pytest.mark.parametrize(
    "argumentos",
    [
        ["j1", "falhou", ""],
        ["j1", "falhou", "   "],
        ["j1", "", "motivo"],
        ["", "falhou", "motivo"],
        ["j1", "cancelado", "motivo"],
    ],
)
def test_comando_recusa_argumento_vazio_ou_estado_invalido(
    argumentos: list[str],
) -> None:
    mundo = Mundo(_job("analisando"))
    saida: list[str] = []

    assert _comando(mundo, argumentos, saida) == 2
    assert mundo.job().estado == "analisando"
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_comando_com_transicao_recusada_sai_com_erro_e_nao_audita() -> None:
    mundo = Mundo(_job("concluido"))
    saida: list[str] = []

    assert _comando(mundo, ["j1", "falhou", "motivo"], saida) == 1
    assert mundo.job().estado == "concluido"
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_comando_com_job_inexistente_sai_com_erro() -> None:
    mundo = Mundo(_job("analisando"))

    assert _comando(mundo, ["zz", "falhou", "motivo"], []) == 1
