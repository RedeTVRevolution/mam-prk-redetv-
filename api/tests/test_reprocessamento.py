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
from api.nuvem import DisparoDaIndexacaoNoCloudRun, DisparoPeloWorkflows
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.progresso_das_janelas import JanelaGravada, JanelasEmMemoria
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
        self.janelas = JanelasEmMemoria()
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
                janelas=self.janelas,
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


@pytest.mark.parametrize("etapa", ["identificacao", "referencias", "comparacao"])
def test_etapa_nova_do_112_e_etapa_de_partida(etapa: str) -> None:
    job = _concluido_sem_indexar()
    job.etapas["indexacao"] = _etapa()
    job.etapas[etapa] = _etapa("falhou")  # type: ignore[index]
    mundo = Mundo(job)

    assert mundo.reprocessar().status_code == 202
    assert mundo.disparo.disparos == [("j1", etapa)]
    assert mundo.job().estado == "concluido"
    # As etapas dali em diante vão rodar de novo.
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


def test_interrompido_com_etapa_fechada_recomeca_dela() -> None:
    job = _job(
        "falhou",
        codigo_falha="processamento_interrompido",
        etapas={"validacao": _etapa(), "analise": _etapa("falhou")},
    )
    assert etapa_de_partida(job) == "analise"


def test_interrompido_entre_etapas_recomeca_da_primeira_que_nao_concluiu() -> None:
    job = _job(
        "falhou",
        codigo_falha="processamento_interrompido",
        etapas={
            "validacao": _etapa(),
            "transcricao": _etapa(),
            "leitura_da_tela": _etapa(),
        },
    )
    assert etapa_de_partida(job) == "analise"


def test_interrompido_na_validacao_pede_o_envio_sem_culpar_o_arquivo() -> None:
    job = _job("falhou", codigo_falha="processamento_interrompido", etapas={})
    with pytest.raises(NaoReprocessavel, match="na validação do arquivo"):
        etapa_de_partida(job)


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


def test_o_disparo_da_indexacao_roda_o_job_com_o_job_id_sem_esperar() -> None:
    sessao = SessaoFalsa()

    DisparoDaIndexacaoNoCloudRun("proj", "regiao-1", "indexador", sessao).iniciar("j1")

    [(url, kwargs)] = sessao.chamadas
    assert url == (
        "https://run.googleapis.com/v2/projects/proj/locations/regiao-1"
        "/jobs/indexador:run"
    )
    assert kwargs["json"] == {
        "overrides": {
            "containerOverrides": [{"env": [{"name": "JOB_ID", "value": "j1"}]}]
        }
    }


def test_o_disparo_da_indexacao_que_falha_vira_servico_indisponivel() -> None:
    with pytest.raises(ServicoIndisponivel):
        DisparoDaIndexacaoNoCloudRun(
            "proj", "regiao-1", "indexador", SessaoQueFalha()
        ).iniciar("j1")


def _concluido_completo() -> Job:
    return _job(
        "concluido",
        etapas={
            nome: _etapa()
            for nome in (
                "validacao",
                "transcricao",
                "leitura_da_tela",
                "analise",
                "identificacao",
                "referencias",
                "comparacao",
                "quadros_chave",
                "inventario_de_objetos",
                "indexacao",
            )
        },
    )


ETAPAS_ESCOLHIDAS = [
    "analise",
    "quadros_chave",
    "identificacao",
    "inventario_de_objetos",
    "indexacao",
]
SEGUINTES = {
    "analise": {
        "identificacao",
        "referencias",
        "comparacao",
        "quadros_chave",
        "inventario_de_objetos",
        "indexacao",
    },
    "identificacao": {
        "referencias",
        "comparacao",
        "quadros_chave",
        "inventario_de_objetos",
        "indexacao",
    },
    "quadros_chave": {"inventario_de_objetos", "indexacao"},
    "inventario_de_objetos": {"indexacao"},
    "indexacao": set(),
}


@pytest.mark.parametrize("papeis", [["curador"], ["administrador"]])
@pytest.mark.parametrize("etapa", ETAPAS_ESCOLHIDAS)
def test_curador_e_administrador_reprocessam_um_concluido_a_partir_da_etapa_escolhida(
    papeis: list[Papel], etapa: str
) -> None:
    mundo = Mundo(_concluido_completo(), papeis)

    resposta = mundo.reprocessar(etapa=etapa, motivo="instrução nova")

    assert resposta.status_code == 202
    job = mundo.job()
    assert job.etapa_atual == etapa
    assert job.etapas[etapa] == Etapa(inicio=AGORA)
    # As posteriores perdem o registro antigo; as anteriores ficam.
    assert not SEGUINTES[etapa] & set(job.etapas)
    assert job.etapas["transcricao"] == _etapa()
    assert mundo.disparo.disparos == [("j1", etapa)]
    assert job.reprocessamentos == 1


def test_com_a_analise_escolhida_o_job_volta_a_analisando() -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])

    corpo = mundo.reprocessar(etapa="analise", motivo="x").json()

    assert corpo["estado"] == "analisando"
    assert mundo.job().estado == "analisando"


@pytest.mark.parametrize(
    "etapa", ["quadros_chave", "identificacao", "inventario_de_objetos", "indexacao"]
)
def test_com_as_outras_etapas_o_job_continua_concluido(etapa: str) -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])

    mundo.reprocessar(etapa=etapa, motivo="x")

    assert mundo.job().estado == "concluido"


@pytest.mark.parametrize("papeis", [None, ["operador"], ["editor"], ["consulta"]])
def test_sem_a_permissao_da_etapa_escolhida_da_403(papeis: list[Papel] | None) -> None:
    mundo = Mundo(_concluido_completo(), papeis)

    assert mundo.reprocessar(etapa="analise", motivo="x").status_code == 403
    assert mundo.job() == _concluido_completo()
    assert mundo.disparo.disparos == []


def test_curador_sem_etapa_escolhida_nao_reprocessa_o_que_falhou() -> None:
    mundo = Mundo(_falhou_na_analise(), ["curador"])

    assert mundo.reprocessar().status_code == 403


def test_chave_de_sistema_nao_reprocessa_a_partir_de_etapa_escolhida() -> None:
    mundo = Mundo(_concluido_completo())

    resposta = mundo.cliente.post(
        ROTA,
        json={"etapa": "analise", "motivo": "x"},
        headers={"X-API-Key": mundo.chave},
    )

    assert resposta.status_code == 403


@pytest.mark.parametrize("motivo", [None, "", "   "])
def test_etapa_escolhida_sem_motivo_da_422(motivo: str | None) -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])
    corpo: dict[str, Any] = {"etapa": "analise"}
    if motivo is not None:
        corpo["motivo"] = motivo

    assert mundo.reprocessar(**corpo).status_code == 422
    assert mundo.job() == _concluido_completo()


@pytest.mark.parametrize("etapa", ["transcricao", "referencias", "validacao", "xis"])
def test_etapa_fora_da_lista_da_409(etapa: str) -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])

    assert mundo.reprocessar(etapa=etapa, motivo="x").status_code == 409
    assert mundo.job() == _concluido_completo()


@pytest.mark.parametrize("estado", ["analisando", "falhou", "cancelado"])
def test_etapa_escolhida_em_job_que_nao_esta_concluido_da_409(estado: str) -> None:
    mundo = Mundo(_job(estado), ["curador"])

    assert mundo.reprocessar(etapa="analise", motivo="x").status_code == 409


def test_a_auditoria_guarda_motivo_etapa_e_que_foi_escolhida() -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])

    mundo.reprocessar(etapa="identificacao", motivo="  objetos novos  ")

    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.acao == "video.reprocessado"
    assert registro.motivo == "objetos novos"
    assert registro.detalhes == {"etapa": "identificacao", "etapa_escolhida": True}


def test_o_registro_do_que_falhou_nao_diz_etapa_escolhida() -> None:
    mundo = Mundo(_falhou_na_analise())

    mundo.reprocessar()

    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.detalhes == {"etapa": "analise"}


def _janela() -> JanelaGravada:
    return JanelaGravada.model_validate_json(
        '{"indice": 0, "situacao": "concluida", "tentativas": 1, "erro": null,'
        ' "decupagem": null, "refeita": false}'
    )


def test_com_a_analise_escolhida_o_progresso_das_janelas_e_apagado_antes_do_disparo() -> (
    None
):
    mundo = Mundo(_concluido_completo(), ["curador"])
    mundo.janelas.gravar("j1", _janela())
    mundo.janelas.gravar("outro", _janela())
    visto: list[bool] = []
    original = mundo.disparo.iniciar

    def iniciar(job_id: str, etapa: Any) -> None:
        visto.append(bool(mundo.janelas.ler("j1")))
        original(job_id, etapa)

    mundo.disparo.iniciar = iniciar  # type: ignore[method-assign]

    mundo.reprocessar(etapa="analise", motivo="x")

    assert visto == [False]
    assert mundo.janelas.ler("outro") != {}


def test_com_as_outras_etapas_as_janelas_ficam() -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])
    mundo.janelas.gravar("j1", _janela())

    mundo.reprocessar(etapa="quadros_chave", motivo="x")

    assert mundo.janelas.ler("j1") != {}


def test_reprocessar_o_que_falhou_na_analise_mantem_as_janelas() -> None:
    mundo = Mundo(_falhou_na_analise())
    mundo.janelas.gravar("j1", _janela())

    mundo.reprocessar()

    assert mundo.janelas.ler("j1") != {}


def test_falha_no_disparo_da_etapa_escolhida_desfaz_a_mudanca_no_job() -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])
    antes = mundo.job()

    def falha(job_id: str, etapa: str) -> None:
        raise ConnectionError("Workflows fora do ar")

    mundo.disparo.iniciar = falha  # type: ignore[method-assign]
    mundo.cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)

    assert mundo.reprocessar(etapa="analise", motivo="x").status_code == 500
    assert mundo.job().model_copy(update={"atualizado_em": BASE}) == antes


def test_dois_pedidos_de_etapa_escolhida_so_um_passa() -> None:
    mundo = Mundo(_concluido_completo(), ["curador"])

    primeiro = mundo.reprocessar(etapa="analise", motivo="x")
    segundo = mundo.reprocessar(etapa="analise", motivo="x")

    assert (primeiro.status_code, segundo.status_code) == (202, 409)
