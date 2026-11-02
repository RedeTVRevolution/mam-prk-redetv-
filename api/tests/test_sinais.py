"""O log estruturado dos sinais de qualidade (#286): uma linha JSON por evento."""

import json
from typing import Any

import pytest

from api.analise import executar
from api.analise_por_janelas import analisar_video
from api.ciclo_de_vida import rodar_etapa
from api.decupagem import Video
from api.gemini import AnaliseFalhou, ErroHttp
from api.jobs import Job, RepositorioEmMemoria
from api.sinais import ContagemDaAnalise
from api.tests.test_analise import BASE, DEPOIS, SHA, DecupagensEmMemoria
from api.tests.test_analise_por_janelas import (
    DURACAO_MS,
    ModeloFalso,
    resposta,
)
from api.tests.test_gemini import BOA, TransporteFalso, resposta_em_mm_ss


def _job(repositorio: RepositorioEmMemoria, estado: str = "analisando") -> None:
    repositorio.salvar(
        Job(
            id="j1",
            nome="j1.mp4",
            tamanho_bytes=10,
            sha256=SHA,
            duracao_s=60.0,
            estado=estado,  # type: ignore[arg-type]
            criado_por="uid-1",
            programa="leo-dias",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )


def _rodar(*respostas: str | Exception) -> tuple[str, list[dict[str, Any]]]:
    repositorio = RepositorioEmMemoria()
    _job(repositorio)
    linhas: list[str] = []
    resultado = executar(
        "j1",
        repositorio,
        DecupagensEmMemoria("aceitos"),
        TransporteFalso(*respostas),
        dormir=lambda _s: None,
        relogio=lambda: DEPOIS,
        registrar=linhas.append,
    )
    return resultado, [json.loads(linha) for linha in linhas]


def _com_pessoas(nomes: list[str]) -> str:
    dados = resposta_em_mm_ss()
    modelo = dados["pessoas"][0]
    dados["pessoas"] = [
        {**modelo, "id": f"pes{i:02d}", "nome": nome}
        for i, nome in enumerate(nomes, start=1)
    ]
    return json.dumps(dados)


def test_video_concluido_loga_os_sinais_e_o_programa() -> None:
    resultado, registros = _rodar(BOA)

    assert resultado == "concluido"
    (concluido,) = [r for r in registros if r["evento"] == "video_concluido"]
    assert concluido == {
        "severity": "INFO",
        "evento": "video_concluido",
        "job_id": "j1",
        "programa": "leo-dias",
        "janelas": 1,
        "janelas_escalonadas": 0,
        "pct_escalonadas": 0.0,
        "pessoas_na_imagem": 1,
        "pessoas_nao_identificadas": 0,
        "pct_nao_identificadas": 0.0,
        "respostas_fora_do_esquema": 0,
    }


def test_percentual_de_pessoas_nao_identificadas() -> None:
    _, registros = _rodar(
        _com_pessoas(
            ["Fulana", "não identificado, de cabelo curto", "Beltrano", "Ciclano"]
        )
    )

    (concluido,) = [r for r in registros if r["evento"] == "video_concluido"]
    assert concluido["pessoas_na_imagem"] == 4
    assert concluido["pessoas_nao_identificadas"] == 1
    assert concluido["pct_nao_identificadas"] == 25.0


def test_resposta_fora_do_esquema_refeita_entra_na_contagem() -> None:
    resultado, registros = _rodar("{}", "não é json", BOA)

    assert resultado == "concluido"
    (concluido,) = [r for r in registros if r["evento"] == "video_concluido"]
    assert concluido["respostas_fora_do_esquema"] == 2


def test_falha_da_analise_loga_a_etapa_e_o_motivo() -> None:
    resultado, registros = _rodar(ErroHttp(400))

    assert resultado == "falhou"
    assert [r["evento"] for r in registros] == ["falha_de_etapa"]
    assert registros[0]["severity"] == "WARNING"
    assert registros[0]["etapa"] == "analise"
    assert registros[0]["job_id"] == "j1"
    assert registros[0]["motivo"]


def test_erro_inesperado_da_analise_tambem_loga_a_falha_da_etapa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def quebra(*_a: object, **_k: object) -> None:
        raise RuntimeError("consolidação quebrou")

    monkeypatch.setattr("api.analise.analisar_video", quebra)

    resultado, registros = _rodar()

    assert resultado == "falhou"
    assert registros[0]["etapa"] == "analise"
    assert "consolidação quebrou" in registros[0]["motivo"]


def test_janelas_escalonadas_entram_na_contagem() -> None:
    contagem = ContagemDaAnalise()
    modelo = ModeloFalso(lambda _i, _f: resposta())

    analisar_video(
        modelo,
        video_uri="gs://a/p.mp4",
        job_id="j",
        video=Video(sha256="c" * 64, duracao_ms=DURACAO_MS),
        fracao_escalonada=1.0,
        contagem=contagem,
        dormir=lambda _s: None,
    )

    assert contagem.janelas > 1
    assert contagem.escalonadas == contagem.janelas


def test_sem_escalonamento_a_contagem_de_escalonadas_fica_zerada() -> None:
    contagem = ContagemDaAnalise()
    analisar_video(
        ModeloFalso(lambda _i, _f: resposta()),
        video_uri="gs://a/p.mp4",
        job_id="j",
        video=Video(sha256="c" * 64, duracao_ms=DURACAO_MS),
        contagem=contagem,
        dormir=lambda _s: None,
    )

    assert contagem.escalonadas == 0


def test_etapa_que_falha_por_resultado_loga_a_etapa_e_o_resultado() -> None:
    repositorio = RepositorioEmMemoria()
    _job(repositorio, "concluido")
    linhas: list[str] = []

    rodar_etapa(
        repositorio,
        "j1",
        "identificacao",
        lambda: "incompleto",
        bem_sucedido="identificado",
        registrar=linhas.append,
    )

    (registro,) = [json.loads(linha) for linha in linhas]
    assert registro["evento"] == "falha_de_etapa"
    assert registro["etapa"] == "identificacao"
    assert registro["job_id"] == "j1"
    assert "incompleto" in registro["motivo"]


def test_etapa_que_levanta_loga_a_falha_e_deixa_a_excecao_seguir() -> None:
    repositorio = RepositorioEmMemoria()
    _job(repositorio, "concluido")
    linhas: list[str] = []

    def quebra() -> str:
        raise AnaliseFalhou("sem resposta")

    with pytest.raises(AnaliseFalhou):
        rodar_etapa(
            repositorio,
            "j1",
            "comparacao",
            quebra,
            bem_sucedido="comparado",
            registrar=linhas.append,
        )

    (registro,) = [json.loads(linha) for linha in linhas]
    assert (registro["etapa"], registro["motivo"]) == (
        "comparacao",
        "AnaliseFalhou: sem resposta",
    )


def test_etapa_que_conclui_nao_loga_falha() -> None:
    repositorio = RepositorioEmMemoria()
    _job(repositorio, "concluido")
    linhas: list[str] = []

    rodar_etapa(
        repositorio,
        "j1",
        "identificacao",
        lambda: "identificado",
        bem_sucedido="identificado",
        registrar=linhas.append,
    )

    assert linhas == []
