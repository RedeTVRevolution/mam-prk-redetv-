"""Restaurar ou mandar para a lixeira durante a indexação deixa o índice certo no fim (#806)."""

import json
import threading
from datetime import timedelta
from typing import Any

import pytest

from api.catalogo import EnvioParaLixeira
from api.ciclo_de_vida import PRAZO_DA_RODADA, tomar_a_rodada
from api.copia_bigquery import CopiaEmMemoria
from api.copiar_para_bigquery import copiar
from api.indexacao import reindexar
from api.indice_da_busca import Consulta, Filtros, IndiceEmMemoria, Registro
from api.tests.test_indexacao import MODELO
from api.tests.test_lixeira import ADMIN, BASE, ROTA_DO_VIDEO, Mundo, _job

ESPERA_S = 10


def _mundo(**job: Any) -> Mundo:
    mundo = Mundo(_job(data_exibicao=None, **job))
    mundo.armazenamento.decupagens["j1"] = [json.dumps(MODELO).encode()]
    return mundo


def _reindexar(mundo: Mundo) -> None:
    job = mundo.jobs.obter("j1")
    assert job
    reindexar(
        job,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.indice,
        relogio=lambda: mundo.agora,
    )


def _na_lixeira(mundo: Mundo) -> set[bool]:
    achados = mundo.indice.buscar(Consulta(filtros=Filtros(na_lixeira=None)))
    assert achados
    return {r.na_lixeira for r in achados}


class IndiceQueAgeNaPrimeiraGravacao(IndiceEmMemoria):
    """Na primeira gravação, com os registros já preparados, roda `antes` e só então grava."""

    def __init__(self, antes: Any) -> None:
        super().__init__()
        self._antes = antes
        self._gravacoes = 0

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        self._gravacoes += 1
        if self._gravacoes == 1:
            self._antes()
        super().gravar(job_id, registros)


RESTAURAR = f"{ROTA_DO_VIDEO}/restaurar"


def test_restaurar_durante_a_indexacao_deixa_o_indice_fora_da_lixeira() -> None:
    mundo: Mundo
    mundo = Mundo(
        _job(data_exibicao=None),
        indice=IndiceQueAgeNaPrimeiraGravacao(
            lambda: mundo.cliente.post(RESTAURAR, headers=ADMIN)
        ),
    )
    mundo.armazenamento.decupagens["j1"] = [json.dumps(MODELO).encode()]
    assert mundo.enviar().status_code == 201

    _reindexar(mundo)

    assert _na_lixeira(mundo) == {False}


def test_mandar_para_a_lixeira_durante_a_indexacao_deixa_o_indice_na_lixeira() -> None:
    mundo: Mundo
    mundo = Mundo(
        _job(data_exibicao=None),
        indice=IndiceQueAgeNaPrimeiraGravacao(lambda: mundo.enviar()),
    )
    mundo.armazenamento.decupagens["j1"] = [json.dumps(MODELO).encode()]

    _reindexar(mundo)

    assert _na_lixeira(mundo) == {True}


@pytest.mark.parametrize("vencida", [False, True])
def test_sem_rodada_em_andamento_a_versao_nao_muda(vencida: bool) -> None:
    mundo = _mundo()
    if vencida:
        assert tomar_a_rodada(mundo.jobs, "j1", BASE - PRAZO_DA_RODADA, "velha")
    antes = mundo.jobs.obter("j1")
    assert antes

    assert mundo.enviar().status_code == 201
    assert mundo.cliente.post(RESTAURAR, headers=ADMIN).status_code == 200

    job = mundo.jobs.obter("j1")
    assert job
    assert (job.versao_pedida, job.versao_indexada) == (
        antes.versao_pedida,
        antes.versao_indexada,
    )
    assert job.indexacao is None


class _Pausa:
    """Uma rota de admin rodando em outra thread, parada num ponto até a rodada deixar."""

    def __init__(self) -> None:
        self.dentro = threading.Event()
        self.liberar = threading.Event()

    def parar(self) -> None:
        self.dentro.set()
        assert self.liberar.wait(ESPERA_S)


def _rota_em_thread(mundo: Mundo, rota: Any) -> threading.Thread:
    # A resposta de erro não importa aqui; só o que a rota deixa no Job e no índice.
    def correr() -> None:
        try:
            rota()
        except Exception:
            pass

    t = threading.Thread(target=correr)
    t.start()
    return t


def test_envio_que_falha_no_registro_durante_a_indexacao_termina_com_o_indice_igual_ao_job() -> (
    None
):
    pausa = _Pausa()
    threads: list[threading.Thread] = []
    gravacoes: list[int] = []

    def iniciar_o_envio() -> None:
        def falha_ao_registrar(_: Any) -> None:
            pausa.parar()
            raise RuntimeError("auditoria fora do ar")

        mundo.auditoria.acrescentar = falha_ao_registrar  # type: ignore[method-assign]
        threads.append(_rota_em_thread(mundo, mundo.enviar))
        assert pausa.dentro.wait(ESPERA_S)  # o Job já está na lixeira, temporariamente

    class Indice(IndiceEmMemoria):
        def gravar(self, job_id: str, registros: list[Registro]) -> None:
            gravacoes.append(1)
            if len(gravacoes) == 1:
                iniciar_o_envio()
            if len(gravacoes) == 2:
                # a rodada repetida já leu o Job na lixeira: agora o envio é desfeito
                pausa.liberar.set()
                threads[0].join(ESPERA_S)
            super().gravar(job_id, registros)

    mundo = Mundo(_job(data_exibicao=None), indice=Indice())
    mundo.armazenamento.decupagens["j1"] = [json.dumps(MODELO).encode()]

    _reindexar(mundo)

    job = mundo.jobs.obter("j1")
    assert job and job.lixeira is None
    assert _na_lixeira(mundo) == {False}


class _IndiceDoEnvioQueFalha(IndiceEmMemoria):
    """O `marcar_lixeira` do envio espera a rodada fechar e falha; o desfazer pode falhar."""

    def __init__(self, pausa: _Pausa, desfazer_falha: bool) -> None:
        super().__init__()
        self.pausa = pausa
        self.desfazer_falha = desfazer_falha
        self.marcacoes = 0

    def marcar_lixeira(self, job_id: str, na_lixeira: bool) -> None:
        self.marcacoes += 1
        if self.marcacoes == 1:
            self.pausa.parar()
            raise ConnectionError("índice fora do ar")
        if self.desfazer_falha:
            raise ConnectionError("índice ainda fora do ar")
        super().marcar_lixeira(job_id, na_lixeira)


@pytest.mark.parametrize("desfazer_falha", [False, True])
def test_desfazer_depois_da_rodada_fechada_remarca_o_indice_ou_deixa_o_limite_1(
    desfazer_falha: bool,
) -> None:
    pausa = _Pausa()
    indice = _IndiceDoEnvioQueFalha(pausa, desfazer_falha)
    mundo = Mundo(_job(data_exibicao=None), indice=indice)
    mundo.armazenamento.decupagens["j1"] = [json.dumps(MODELO).encode()]
    threads: list[threading.Thread] = []
    gravacoes: list[int] = []
    gravar = IndiceEmMemoria.gravar

    def gravar_e_iniciar_o_envio(
        self: IndiceEmMemoria, job_id: str, registros: list[Registro]
    ) -> None:
        gravacoes.append(1)
        if len(gravacoes) == 1:
            threads.append(_rota_em_thread(mundo, mundo.enviar))
            assert pausa.dentro.wait(ESPERA_S)
        gravar(self, job_id, registros)

    indice.gravar = gravar_e_iniciar_o_envio.__get__(indice)  # type: ignore[method-assign]

    _reindexar(mundo)  # a rodada repetida gravou o Job na lixeira e fechou
    assert _na_lixeira(mundo) == {True}
    pausa.liberar.set()  # o índice do envio falha: o Job volta, depois da rodada
    threads[0].join(ESPERA_S)

    job = mundo.jobs.obter("j1")
    assert job and job.lixeira is None
    assert _na_lixeira(mundo) == ({True} if desfazer_falha else {False})


def test_restaurar_enquanto_a_copia_do_bigquery_tem_a_vez_indexa_de_novo_ao_fechar() -> (
    None
):
    mundo = _mundo()
    assert mundo.enviar().status_code == 201
    _reindexar(mundo)  # indexado, na lixeira, versões iguais
    antes = mundo.jobs.obter("j1")
    assert antes and antes.versao_pedida == antes.versao_indexada
    assert _na_lixeira(mundo) == {True}

    class Copia(CopiaEmMemoria):
        def gravar(self, job_id: str, linhas: Any, **kw: Any) -> None:
            assert mundo.cliente.post(RESTAURAR, headers=ADMIN).status_code == 200
            super().gravar(job_id, linhas, **kw)

    copiar(
        antes,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        Copia(),
        relogio=lambda: mundo.agora,
        indice=mundo.indice,
    )

    job = mundo.jobs.obter("j1")
    assert job and job.rodada_da_indexacao is None
    assert job.versao_indexada == job.versao_pedida == antes.versao_pedida + 1
    assert _na_lixeira(mundo) == {False}
