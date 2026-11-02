"""`make reprocessar-versao` (#250): lista os Jobs de versão anterior, limita e confirma."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.jobs import Job, RepositorioEmMemoria, ServicoIndisponivel
from api.progresso_das_janelas import JanelasEmMemoria
from api.reprocessamento import DisparoEmMemoria
from api.reprocessar_versao import escolher, main, reprocessar_versao
from api.versao_pipeline import VERSAO_PIPELINE

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class Decupagens:
    def __init__(self, versoes: dict[str, str | None]) -> None:
        self._versoes = versoes

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        if job_id not in self._versoes:
            raise ServicoIndisponivel
        versao = self._versoes[job_id]
        yield json.dumps({"versao_pipeline": versao} if versao else {}).encode()


def _job(id: str, estado: str = "concluido", horas: float = 1.0, dia: int = 0) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        duracao_s=horas * 3600,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        criado_em=BASE + timedelta(days=dia),
        atualizado_em=BASE,
        etapas={},
    )


class Mundo:
    def __init__(self, jobs: list[Job], versoes: dict[str, str | None]) -> None:
        self.jobs = RepositorioEmMemoria()
        for j in jobs:
            self.jobs.salvar(j)
        self.decupagens = Decupagens(versoes)
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.disparo = DisparoEmMemoria()
        self.janelas = JanelasEmMemoria()
        self.pausas: list[float] = []

    def rodar(self, **extra: Any) -> list[str]:
        saida: list[str] = []
        reprocessar_versao(
            self.jobs,
            self.decupagens,
            self.auditoria,
            self.disparo,
            self.janelas,
            relogio=lambda: BASE,
            dormir=self.pausas.append,
            escrever=saida.append,
            **extra,
        )
        return saida


def _mundo() -> Mundo:
    return Mundo(
        [
            _job("antigo", dia=0),
            _job("outra", dia=1),
            _job("vigente", dia=2),
            _job("sem-campo", dia=3),
            _job("andando", estado="analisando", dia=4),
        ],
        {
            "antigo": "2026.10.1",
            "outra": "2026.10.2",
            "vigente": VERSAO_PIPELINE,
            "sem-campo": None,
            "andando": "2026.10.1",
        },
    )


def test_sem_confirmar_so_lista_com_o_custo_estimado_e_nao_dispara() -> None:
    mundo = _mundo()

    saida = mundo.rodar(custo_por_hora=2.5)

    texto = "\n".join(saida)
    assert "antigo" in texto and "outra" in texto and "sem-campo" in texto
    assert "vigente" not in texto  # o Job da versão atual fica fora
    assert "andando" not in texto  # só concluídos
    assert "3 Jobs" in texto and "US$ 7,50" in texto  # 3 h × 2,50
    assert mundo.disparo.disparos == []
    assert mundo.jobs.obter("antigo").estado == "concluido"  # type: ignore[union-attr]


def test_sem_custo_por_hora_o_custo_e_nd() -> None:
    assert "n/d" in "\n".join(_mundo().rodar())


def test_o_limite_vale_e_pega_os_mais_antigos() -> None:
    mundo = _mundo()

    mundo.rodar(limite=2, confirmar=True)

    assert [d[0] for d in mundo.disparo.disparos] == ["antigo", "outra"]


def test_de_so_pega_a_versao_pedida_e_anterior_pega_a_sem_campo() -> None:
    mundo = _mundo()
    mundo.rodar(de="2026.10.2", confirmar=True)
    assert [d[0] for d in mundo.disparo.disparos] == ["outra"]

    outro = _mundo()
    outro.rodar(de="anterior", confirmar=True)
    assert [d[0] for d in outro.disparo.disparos] == ["sem-campo"]


def test_confirmar_reprocessa_pela_analise_com_rastro_e_em_lotes() -> None:
    mundo = _mundo()

    mundo.rodar(confirmar=True, tamanho_do_lote=2, pausa_s=30)

    assert mundo.disparo.disparos == [
        ("antigo", "analise"),
        ("outra", "analise"),
        ("sem-campo", "analise"),
    ]
    assert mundo.pausas == [30]  # entre o lote de 2 e o de 1, nunca depois do último
    antigo = mundo.jobs.obter("antigo")
    assert antigo is not None and antigo.estado == "analisando"
    assert mundo.jobs.obter("vigente").estado == "concluido"  # type: ignore[union-attr]


def test_um_job_que_falha_no_disparo_volta_ao_que_era_e_nao_derruba_os_outros() -> None:
    mundo = _mundo()
    iniciar = mundo.disparo.iniciar

    def disparo_que_falha(job_id: str, etapa: Any) -> None:
        if job_id == "outra":
            raise ServicoIndisponivel
        iniciar(job_id, etapa)

    mundo.disparo.iniciar = disparo_que_falha  # type: ignore[method-assign]

    saida = mundo.rodar(confirmar=True)

    assert [d[0] for d in mundo.disparo.disparos] == ["antigo", "sem-campo"]
    assert mundo.jobs.obter("outra").estado == "concluido"  # type: ignore[union-attr]
    assert any(l.startswith("outra") and "falhou" in l for l in saida)


def test_decupagem_ilegivel_fica_de_fora() -> None:
    mundo = _mundo()
    del mundo.decupagens._versoes["antigo"]

    mundo.rodar(confirmar=True)

    assert [d[0] for d in mundo.disparo.disparos] == ["outra", "sem-campo"]


def test_escolher_nao_muda_a_ordem_nem_passa_do_limite() -> None:
    mundo = _mundo()
    assert [c.job_id for c in escolher(mundo.jobs, mundo.decupagens, None, 1)] == [
        "antigo"
    ]


def test_o_comando_pede_o_ambiente(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], ambiente={}) == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err


def test_limite_que_nao_e_numero_e_erro_de_uso(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ambiente = {
        nome: "x"
        for nome in (
            "GCP_PROJECT_ID",
            "BUCKET_ACEITOS",
            "BUCKET_DECUPAGENS",
            "WORKFLOW_REGIAO",
            "WORKFLOW_VALIDACAO",
        )
    }

    assert main(["", "dez"], ambiente=ambiente) == 2
    assert "dez" in capsys.readouterr().err


def test_job_sem_duracao_fica_fora_do_custo_e_e_avisado() -> None:
    mundo = Mundo([_job("a"), _job("b")], {"a": None, "b": None})
    sem = mundo.jobs.obter("b")
    assert sem is not None
    mundo.jobs.salvar(sem.model_copy(update={"duracao_s": None}))

    texto = "\n".join(mundo.rodar(custo_por_hora=2.0))

    assert "duração n/d" in texto
    assert "2 Jobs, 1.00 h" in texto and "US$ 2,00" in texto
    assert "1 Jobs sem duração" in texto
