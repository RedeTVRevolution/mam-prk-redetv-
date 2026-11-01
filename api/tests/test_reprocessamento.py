from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

from api.auditoria import (
    FiltroDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
)
from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.ciclo_de_vida import NaoReprocessavel, etapa_de_partida, reprocessar
from api.jobs import Etapa, Job, RepositorioEmMemoria, ServicoIndisponivel
from api.main import criar_app
from api.nuvem import DisparoPeloWorkflows
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.reprocessamento import DisparoEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC

BASE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
AGORA = BASE + timedelta(hours=1)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}
ROTA = "/v1/jobs/j1/reprocessar"


def _etapa(resultado: str | None = "concluida") -> Etapa:
    return Etapa(
        inicio=BASE,
        fim=BASE if resultado else None,
        resultado=resultado,  # type: ignore[arg-type]
    )


def _job(estado: str = "falhou", **extra: Any) -> Job:
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


def _falhou_na_analise() -> Job:
    return _job(
        "falhou",
        codigo_falha="analise_falhou",
        etapas={
            "validacao": _etapa(),
            "transcricao": _etapa(),
            "leitura_da_tela": _etapa(),
            "analise": _etapa("falhou"),
        },
    )


def _concluido_sem_indexar() -> Job:
    return _job(
        "concluido",
        etapas={
            "validacao": _etapa(),
            "transcricao": _etapa(),
            "leitura_da_tela": _etapa(),
            "analise": _etapa(),
            "quadros_chave": _etapa(),
            "indexacao": _etapa("falhou"),
        },
    )


class Mundo:
    def __init__(self, job: Job | None, papeis: list[Papel] | None = None) -> None:
        self.jobs = RepositorioEmMemoria()
        if job is not None:
            self.jobs.salvar(job)
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.disparo = DisparoEmMemoria()
        repo_papeis = RepositorioDePapeisEmMemoria()
        if papeis is not None:
            repo_papeis.salvar("u1", papeis)
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
                chaves=VerificadorDeChaveDeApi(chaves, MAC),
                papeis=repo_papeis,
                auditoria=self.auditoria,
                disparo=self.disparo,
                relogio=lambda: AGORA,
            )
        )

    def reprocessar(self, **corpo: Any) -> Any:
        return self.cliente.post(ROTA, json=corpo or None, headers=AUTORIZACAO)

    def job(self) -> Job:
        job = self.jobs.obter("j1")
        assert job is not None
        return job


def test_falha_de_etapa_volta_a_analisando_na_etapa_que_falhou() -> None:
    mundo = Mundo(_falhou_na_analise())

    resposta = mundo.reprocessar(motivo="Gemini estava fora")

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["estado"] == "analisando"
    assert corpo["codigo_falha"] is None
    assert corpo["etapa_atual"] == "analise"
    assert corpo["reprocessamentos"] == 1
    job = mundo.job()
    assert job.etapas["analise"] == Etapa(inicio=AGORA)
    # As etapas já concluídas ficam como estavam.
    assert job.etapas["transcricao"] == _etapa()
    assert mundo.disparo.disparos == [("j1", "analise")]


def test_job_concluido_com_indexacao_falha_continua_concluido() -> None:
    mundo = Mundo(_concluido_sem_indexar())

    resposta = mundo.reprocessar()

    assert resposta.status_code == 202
    job = mundo.job()
    assert job.estado == "concluido"
    assert job.etapa_atual == "indexacao"
    assert job.etapas["indexacao"] == Etapa(inicio=AGORA)
    assert job.etapas["quadros_chave"] == _etapa()
    assert job.indexacao is not None and job.indexacao.estado == "pendente"
    assert mundo.disparo.disparos == [("j1", "indexacao")]


def test_a_etapa_de_partida_e_a_primeira_que_falhou() -> None:
    job = _concluido_sem_indexar()
    job.etapas["quadros_chave"] = _etapa("falhou")
    mundo = Mundo(job)

    assert mundo.reprocessar().status_code == 202
    assert mundo.disparo.disparos == [("j1", "quadros_chave")]
    # A indexação vai rodar de novo: o registro antigo dela sai.
    assert "indexacao" not in mundo.job().etapas


def test_job_falhou_sem_registro_de_etapa_parte_do_codigo_da_falha() -> None:
    mundo = Mundo(_job("falhou", codigo_falha="ocr_falhou"))

    assert mundo.reprocessar().status_code == 202
    assert mundo.disparo.disparos == [("j1", "leitura_da_tela")]


@pytest.mark.parametrize(
    "codigo",
    [
        "formato_invalido",
        "arquivo_corrompido",
        "codec_nao_suportado",
        "duracao_excedida",
        "upload_expirado",
    ],
)
def test_falha_do_arquivo_pede_novo_envio(codigo: str) -> None:
    mundo = Mundo(
        _job("falhou", codigo_falha=codigo, etapas={"validacao": _etapa("falhou")})
    )

    resposta = mundo.reprocessar()

    assert resposta.status_code == 409
    assert "enviar" in resposta.json()["detail"]
    assert mundo.job().estado == "falhou"
    assert mundo.disparo.disparos == []


@pytest.mark.parametrize(
    "job",
    [
        _job("concluido", etapas={"analise": _etapa()}),
        _job("concluido"),
        _job("analisando"),
        _job("cancelado"),
        _job("validando"),
        _job("aguardando_upload"),
    ],
)
def test_outro_estado_ou_concluido_sem_etapa_falha_da_409(job: Job) -> None:
    mundo = Mundo(job)

    assert mundo.reprocessar().status_code == 409
    assert mundo.disparo.disparos == []
    assert mundo.job() == job


def test_job_inexistente_da_404() -> None:
    assert Mundo(None).reprocessar().status_code == 404


@pytest.mark.parametrize("papeis", [["consulta"], ["editor"], ["curador"], []])
def test_sem_video_reprocessar_da_403(papeis: list[Papel]) -> None:
    mundo = Mundo(_falhou_na_analise(), papeis)

    assert mundo.reprocessar().status_code == 403
    assert mundo.job().estado == "falhou"


@pytest.mark.parametrize("papeis", [None, ["operador"], ["administrador"]])
def test_operador_e_administrador_reprocessam(papeis: list[Papel] | None) -> None:
    assert Mundo(_falhou_na_analise(), papeis).reprocessar().status_code == 202


def test_chave_de_sistema_nao_reprocessa() -> None:
    mundo = Mundo(_falhou_na_analise())

    resposta = mundo.cliente.post(ROTA, headers={"X-API-Key": mundo.chave})

    assert resposta.status_code == 403
    assert mundo.job().estado == "falhou"


def test_dois_pedidos_para_o_mesmo_job_falho_so_um_passa() -> None:
    mundo = Mundo(_falhou_na_analise())

    primeiro, segundo = mundo.reprocessar(), mundo.reprocessar()

    assert (primeiro.status_code, segundo.status_code) == (202, 409)
    assert mundo.disparo.disparos == [("j1", "analise")]
    assert mundo.job().reprocessamentos == 1


def test_dois_pedidos_para_o_mesmo_job_concluido_so_um_passa() -> None:
    mundo = Mundo(_concluido_sem_indexar())

    primeiro, segundo = mundo.reprocessar(), mundo.reprocessar()

    assert (primeiro.status_code, segundo.status_code) == (202, 409)
    assert mundo.disparo.disparos == [("j1", "indexacao")]


def test_o_pedido_que_chega_com_o_job_ja_mudado_nao_passa() -> None:
    # A leitura do segundo pedido é a do repositório, na hora da troca: o que o
    # primeiro gravou já vale.
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_concluido_sem_indexar())

    assert reprocessar(repositorio, "j1", AGORA) is not None
    with pytest.raises(NaoReprocessavel):
        reprocessar(repositorio, "j1", AGORA)


def test_grava_o_registro_na_auditoria_com_etapa_e_motivo() -> None:
    mundo = Mundo(_falhou_na_analise())

    mundo.reprocessar(motivo="  Gemini estava fora  ")

    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.acao == "video.reprocessado"
    assert (registro.uid, registro.email) == ("u1", "ana@redetv.com")
    assert (registro.alvo_tipo, registro.alvo_id, registro.alvo_nome) == (
        "job",
        "j1",
        "a.mp4",
    )
    assert registro.motivo == "Gemini estava fora"
    assert registro.detalhes == {"etapa": "analise"}
    assert registro.quando == AGORA


def test_pedido_recusado_nao_deixa_registro() -> None:
    mundo = Mundo(_job("concluido"))

    mundo.reprocessar()

    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_motivo_longo_demais_ou_campo_estranho_da_422() -> None:
    mundo = Mundo(_falhou_na_analise())

    assert mundo.reprocessar(motivo="x" * 501).status_code == 422
    assert mundo.reprocessar(outro=1).status_code == 422
    assert mundo.job().estado == "falhou"


def test_se_o_workflow_nao_dispara_o_job_volta_ao_que_era() -> None:
    mundo = Mundo(_falhou_na_analise())
    antes = mundo.job()

    def falha(job_id: str, etapa: str) -> None:
        raise ConnectionError("Workflows fora do ar")

    mundo.disparo.iniciar = falha  # type: ignore[method-assign]
    mundo.cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)

    resposta = mundo.reprocessar()

    assert resposta.status_code == 500
    depois = mundo.job()
    assert depois.model_copy(update={"atualizado_em": BASE}) == antes


def test_sem_disparo_configurado_a_api_responde_503_e_nao_muda_o_job() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_falhou_na_analise())
    cliente = TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            jobs,
            relogio=lambda: AGORA,
        )
    )

    assert cliente.post(ROTA, headers=AUTORIZACAO).status_code == 503
    job = jobs.obter("j1")
    assert job is not None and job.estado == "falhou"


def test_etapa_de_partida_de_job_em_andamento_nao_existe() -> None:
    with pytest.raises(NaoReprocessavel):
        etapa_de_partida(_job("analisando", etapas={"analise": _etapa("falhou")}))


class SessaoFalsa:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> "SessaoFalsa":
        self.chamadas.append((url, kwargs))
        return self

    def raise_for_status(self) -> None:
        pass


def test_o_disparo_cria_uma_execucao_com_o_job_e_a_etapa_inicial() -> None:
    sessao = SessaoFalsa()

    DisparoPeloWorkflows("proj", "regiao-1", "fluxo", sessao).iniciar("j1", "analise")

    [(url, kwargs)] = sessao.chamadas
    assert url == (
        "https://workflowexecutions.googleapis.com/v1/projects/proj/locations/"
        "regiao-1/workflows/fluxo/executions"
    )
    assert kwargs["json"] == {
        "argument": '{"job_id": "j1", "etapa_inicial": "analise"}'
    }


class SessaoQueFalha(SessaoFalsa):
    def raise_for_status(self) -> None:
        raise requests.HTTPError("403")


def test_o_disparo_que_falha_vira_servico_indisponivel() -> None:
    with pytest.raises(ServicoIndisponivel):
        DisparoPeloWorkflows("proj", "regiao-1", "fluxo", SessaoQueFalha()).iniciar(
            "j1", "analise"
        )
