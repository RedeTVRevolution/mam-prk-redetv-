"""Jobs da identificação (modelo forte) e da comparação (#112), com dublês em memória.

O ffmpeg é trocado por `quadros_falsos` e o Gemini, pelo `TransporteFalso`.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api import comparacao_job, identificacao_job
from api.catalogo import CatalogoEmMemoria
from api.decupagem import Decupagem
from api.gemini import ErroHttp
from api.jobs import Job, RepositorioEmMemoria
from api.referencias import SugestoesEmMemoria
from api.tests.test_comparacao import Cenario, confianca, escolha
from api.tests.test_gemini import TransporteFalso
from api.tests.test_identificacao import decupagem, gc, pessoa, whisper

BASE = datetime(2026, 10, 31, tzinfo=UTC)
BARBA = "não identificado, homem de barba"


class DecupagensEmMemoria:
    def __init__(self, atual: Decupagem | None, com_copia: bool = True) -> None:
        self.atual = atual
        self.com_copia = com_copia
        self.gravada: Decupagem | None = None
        self.comparacao: str | None = None

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return self.atual

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool:
        return self.com_copia

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self.gravada = Decupagem.model_validate_json(conteudo)

    def gravar_comparacao(self, job_id: str, conteudo: str) -> None:
        self.comparacao = conteudo


class TranscricoesEmMemoria:
    def ler_transcricao(self, job_id: str) -> Any:
        return whisper(("oi", 1.0))


def repositorio(estado: str = "concluido") -> RepositorioEmMemoria:
    r = RepositorioEmMemoria()
    r.salvar(
        Job(
            id="job-1",
            nome="a.mp4",
            tamanho_bytes=10,
            sha256="a" * 64,
            duracao_s=60.0,
            estado=estado,  # type: ignore[arg-type]
            criado_por="uid-1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    return r


@pytest.fixture(autouse=True)
def quadros_falsos(monkeypatch: pytest.MonkeyPatch) -> None:
    def falsos(video: Path, instantes: Sequence[int]) -> list[bytes]:
        return [f"quadro-{i}".encode() for i in instantes]

    monkeypatch.setattr(identificacao_job, "extrair_quadros", falsos)
    monkeypatch.setattr(comparacao_job, "extrair_quadros", falsos)


def com_gc() -> Decupagem:
    return decupagem(
        [pessoa("pes01", BARBA, [(100_000, 110_000)], fontes_do_nome=[])],
        [gc("Leão Lobo", 101_000, 108_000)],
    )


def identificar(
    d: Decupagem | None,
    *respostas: str | Exception,
    estado: str = "concluido",
    com_copia: bool = True,
    tmp_path: Path,
) -> tuple[str, DecupagensEmMemoria]:
    decupagens = DecupagensEmMemoria(d, com_copia)
    resultado = identificacao_job.executar(
        "job-1",
        repositorio(estado),
        decupagens,
        TransporteFalso(*respostas),
        TranscricoesEmMemoria(),
        CatalogoEmMemoria(),
        tmp_path,
    )
    return resultado, decupagens


def nome_do_modelo_forte() -> str:
    return json.dumps(
        {
            "resultado": "nome_com_prova",
            "nome": "Leão Lobo",
            "prova": "gc",
            "tempo_da_prova": "01:41",
        }
    )


def test_identificacao_regrava_a_decupagem_com_o_nome_confirmado(
    tmp_path: Path,
) -> None:
    resultado, decupagens = identificar(
        com_gc(), nome_do_modelo_forte(), tmp_path=tmp_path
    )

    assert resultado == "identificado"
    assert decupagens.gravada is not None
    assert decupagens.gravada.pessoas[0].nome == "Leão Lobo"


def test_identificacao_ignora_job_que_nao_esta_concluido(tmp_path: Path) -> None:
    resultado, decupagens = identificar(
        com_gc(), estado="analisando", tmp_path=tmp_path
    )

    assert resultado == "ignorado"
    assert decupagens.gravada is None


@pytest.mark.parametrize("sem", ["decupagem", "copia"])
def test_identificacao_sem_decupagem_ou_sem_copia_limpa_nao_muda_nada(
    sem: str, tmp_path: Path
) -> None:
    resultado, decupagens = identificar(
        None if sem == "decupagem" else com_gc(),
        com_copia=sem != "copia",
        tmp_path=tmp_path,
    )

    assert resultado == "sem_alteracao"
    assert decupagens.gravada is None


def test_falha_do_modelo_forte_nao_derruba_a_execucao_e_mantem_a_decupagem(
    tmp_path: Path,
) -> None:
    resultado, decupagens = identificar(com_gc(), ErroHttp(400), tmp_path=tmp_path)

    assert resultado == "identificado"
    assert decupagens.gravada is not None
    assert decupagens.gravada.pessoas[0].nome == BARBA


def comparar_em(
    c: Cenario, d: Decupagem | None, *respostas: str | Exception, tmp_path: Path
) -> tuple[str, DecupagensEmMemoria]:
    decupagens = DecupagensEmMemoria(d)
    resultado = comparacao_job.executar(
        "job-1",
        repositorio(),
        decupagens,
        TransporteFalso(*respostas),
        c.fotos,
        c.catalogo,
        SugestoesEmMemoria(),
        tmp_path,
        validade=timedelta(days=180),
        limiar=0.8,
    )
    return resultado, decupagens


def test_comparacao_regrava_a_decupagem_e_guarda_os_vereditos(tmp_path: Path) -> None:
    c = Cenario()
    d = decupagem([pessoa("pes01", BARBA, [(10_000, 40_000)], fontes_do_nome=[])])

    resultado, decupagens = comparar_em(
        c,
        d,
        escolha("A"),
        confianca(0.9),
        confianca(0.9),
        confianca(0.9),
        tmp_path=tmp_path,
    )

    assert resultado == "comparado"
    assert decupagens.gravada is not None
    # a ordem dos rótulos é sorteada: A é um dos dois candidatos
    assert decupagens.gravada.pessoas[0].nome in {"Leão Lobo", "Nelson Rubens"}
    assert decupagens.comparacao is not None
    [veredito] = json.loads(decupagens.comparacao)
    assert veredito["estado"] == "confirmado"
