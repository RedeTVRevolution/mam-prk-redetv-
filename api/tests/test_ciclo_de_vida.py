"""Ciclo de vida do Job: a tabela de transições e a troca condicional, em memória."""

from datetime import UTC, datetime, timedelta
from itertools import product
from typing import get_args

import pytest

from api.ciclo_de_vida import (
    JaTerminou,
    TransicaoProibida,
    cancelar,
    encerrar_etapa,
    iniciar_etapa,
    transitar,
)
from api.jobs import CodigoDeFalha, Estado, Job, JobPublico, RepositorioEmMemoria

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
DEPOIS = BASE + timedelta(minutes=5)

PERMITIDAS = {
    ("aguardando_upload", "validando"),
    ("aguardando_upload", "falhou"),
    ("aguardando_upload", "cancelado"),
    ("validando", "analisando"),
    ("validando", "falhou"),
    ("validando", "cancelado"),
    ("analisando", "concluido"),
    ("analisando", "falhou"),
    ("analisando", "cancelado"),
}


def _job(estado: Estado, job_id: str = "j1") -> Job:
    return Job(
        id=job_id,
        nome="v.mp4",
        tamanho_bytes=10,
        estado=estado,
        criado_por="u",
        criado_em=BASE,
        atualizado_em=BASE,
    )


def _repositorio(estado: Estado) -> RepositorioEmMemoria:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job(estado))
    return repositorio


@pytest.mark.parametrize(
    ("de", "para"),
    [p for p in product(get_args(Estado), repeat=2) if p not in PERMITIDAS],
)
def test_par_fora_da_tabela_e_recusado_sem_tocar_no_job(
    de: Estado, para: Estado
) -> None:
    repositorio = _repositorio(de)

    with pytest.raises(TransicaoProibida):
        transitar(repositorio, "j1", de, para, DEPOIS)

    assert repositorio.obter("j1") == _job(de)


@pytest.mark.parametrize(("de", "para"), sorted(PERMITIDAS))
def test_par_da_tabela_acontece_e_atualiza_o_horario(de: Estado, para: Estado) -> None:
    repositorio = _repositorio(de)
    codigo: CodigoDeFalha | None = "analise_falhou" if para == "falhou" else None

    novo = transitar(repositorio, "j1", de, para, DEPOIS, codigo_falha=codigo)

    assert novo is not None
    assert (novo.estado, novo.codigo_falha, novo.atualizado_em) == (
        para,
        codigo,
        DEPOIS,
    )
    assert repositorio.obter("j1") == novo


def test_transicao_leva_os_campos_que_mudam_junto() -> None:
    repositorio = _repositorio("validando")

    novo = transitar(
        repositorio,
        "j1",
        "validando",
        "analisando",
        DEPOIS,
        sha256="a" * 64,
        duracao_s=3.5,
    )

    assert novo is not None
    assert (novo.sha256, novo.duracao_s) == ("a" * 64, 3.5)


def test_job_que_ja_saiu_do_estado_de_origem_nao_e_gravado() -> None:
    repositorio = _repositorio("cancelado")

    assert transitar(repositorio, "j1", "validando", "analisando", DEPOIS) is None

    assert repositorio.obter("j1") == _job("cancelado")


def test_job_inexistente_nao_transita() -> None:
    assert (
        transitar(RepositorioEmMemoria(), "x", "validando", "analisando", DEPOIS)
        is None
    )


class _CancelaAposLer(RepositorioEmMemoria):
    """O cancelamento chega logo depois de o worker ler o Job."""

    def obter(self, job_id: str) -> Job | None:
        job = super().obter(job_id)
        self.salvar(_job("cancelado"))
        return job


def test_cancelamento_entre_a_leitura_e_a_gravacao_nao_e_sobrescrito() -> None:
    repositorio = _CancelaAposLer()
    repositorio.salvar(_job("analisando"))
    lido = repositorio.obter("j1")
    assert lido is not None

    assert transitar(repositorio, "j1", lido.estado, "concluido", DEPOIS) is None

    assert RepositorioEmMemoria.obter(repositorio, "j1") == _job("cancelado")


def test_cancelar_leva_job_em_andamento_a_cancelado() -> None:
    repositorio = _repositorio("validando")

    job = cancelar(repositorio, "j1", DEPOIS)

    assert job is not None
    assert (job.estado, job.atualizado_em) == ("cancelado", DEPOIS)


def test_cancelar_job_cancelado_devolve_o_job_sem_mudar() -> None:
    repositorio = _repositorio("cancelado")

    assert cancelar(repositorio, "j1", DEPOIS) == _job("cancelado")


def test_cancelar_job_inexistente_devolve_none() -> None:
    assert cancelar(RepositorioEmMemoria(), "x", DEPOIS) is None


@pytest.mark.parametrize("estado", ["concluido", "falhou"])
def test_cancelar_job_final_avisa_o_estado(estado: Estado) -> None:
    repositorio = _repositorio(estado)

    with pytest.raises(JaTerminou, match=estado):
        cancelar(repositorio, "j1", DEPOIS)

    assert repositorio.obter("j1") == _job(estado)


def test_concluir_deixa_a_indexacao_pendente() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job("analisando"))

    job = transitar(repositorio, "j1", "analisando", "concluido", DEPOIS)

    assert job and job.indexacao
    assert (job.indexacao.estado, job.indexacao.em) == ("pendente", DEPOIS)


def test_falhar_nao_mexe_na_indexacao() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job("analisando"))

    job = transitar(repositorio, "j1", "analisando", "falhou", DEPOIS)

    assert job and job.indexacao is None


def test_etapas_de_um_job_que_falha_na_leitura_da_tela() -> None:
    repositorio = _repositorio("analisando")
    for etapa in ("transcricao", "leitura_da_tela"):
        iniciar_etapa(repositorio, "j1", etapa, BASE)
        if etapa == "transcricao":
            encerrar_etapa(repositorio, "j1", etapa, "concluida", DEPOIS)
    encerrar_etapa(repositorio, "j1", "leitura_da_tela", "falhou", DEPOIS)
    transitar(
        repositorio, "j1", "analisando", "falhou", DEPOIS, codigo_falha="ocr_falhou"
    )

    job = repositorio.obter("j1")
    assert job is not None
    assert job.estado == "falhou"
    assert job.etapa_atual is None
    assert job.etapas["transcricao"].resultado == "concluida"
    assert job.etapas["transcricao"].fim == DEPOIS
    assert job.etapas["leitura_da_tela"].resultado == "falhou"
    assert "analise" not in job.etapas


def test_etapa_atual_e_o_inicio_e_o_fim_ficam_na_etapa() -> None:
    repositorio = _repositorio("analisando")

    iniciada = iniciar_etapa(repositorio, "j1", "analise", BASE)
    assert iniciada is not None
    assert iniciada.etapa_atual == "analise"
    assert iniciada.etapas["analise"].inicio == BASE
    assert iniciada.etapas["analise"].fim is None

    encerrada = encerrar_etapa(repositorio, "j1", "analise", "concluida", DEPOIS)
    assert encerrada is not None
    assert encerrada.etapa_atual is None
    assert encerrada.etapas["analise"].fim == DEPOIS


def test_indexacao_que_falha_em_job_concluido_nao_muda_o_estado() -> None:
    repositorio = _repositorio("concluido")

    iniciar_etapa(repositorio, "j1", "indexacao", BASE)
    encerrar_etapa(repositorio, "j1", "indexacao", "falhou", DEPOIS)

    job = repositorio.obter("j1")
    assert job is not None
    assert job.estado == "concluido"
    assert job.etapas["indexacao"].resultado == "falhou"


def test_encerrar_etapa_que_nao_comecou_nao_grava() -> None:
    repositorio = _repositorio("analisando")

    assert encerrar_etapa(repositorio, "j1", "analise", "concluida", DEPOIS) is None
    assert encerrar_etapa(repositorio, "outro", "analise", "falhou", DEPOIS) is None


def test_job_anterior_ao_campo_e_lido_com_etapas_vazias() -> None:
    job = Job.model_validate(
        {
            k: v
            for k, v in _job("concluido").model_dump().items()
            if k not in {"etapa_atual", "etapas"}
        }
    )
    publico = JobPublico.de(job)

    assert job.etapas == {} and job.etapa_atual is None
    assert publico.etapas == [] and publico.etapa_atual is None


def test_job_publico_lista_as_etapas_na_ordem_do_inicio() -> None:
    repositorio = _repositorio("analisando")
    iniciar_etapa(repositorio, "j1", "transcricao", BASE)
    iniciar_etapa(repositorio, "j1", "validacao", BASE - timedelta(minutes=1))
    job = repositorio.obter("j1")
    assert job is not None

    publico = JobPublico.de(job)

    assert [e.nome for e in publico.etapas] == ["validacao", "transcricao"]
