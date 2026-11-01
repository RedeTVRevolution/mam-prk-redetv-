"""Pauta que cita uma pessoa que não está na Decupagem (#236): o esquema recusa, a
consolidação não cai e a análise marca a própria falha."""

import logging
from typing import Any

import pytest
from pydantic import ValidationError

from api.analise_por_janelas import analisar_video
from api.consolidacao import consolidar
from api.decupagem import Decupagem
from api.gemini import Chamada, gerar_validado
from api.progresso_das_janelas import JanelaGravada, JanelasEmMemoria
from api.tests.test_analise import _ambiente
from api.tests.test_analise_por_janelas import URI, ModeloFalso, resposta
from api.tests.test_analise_por_janelas import VIDEO as VIDEO_LONGO
from api.tests.test_consolidacao import J0, J1, VIDEO, decupagem, pauta, pessoa


def _com_pessoa_fora() -> dict[str, Any]:
    return {
        "pessoas": [pessoa("p1", "Ana", [(1_000, 5_000)])],
        "pautas": [pauta("t1", 0, 10_000, "Golaço", ["p1", "silhueta"])],
    }


def test_o_esquema_recusa_pauta_com_pessoa_fora_da_decupagem() -> None:
    with pytest.raises(ValidationError, match="pauta"):
        decupagem(**_com_pessoa_fora())


def test_pauta_com_pessoa_da_decupagem_passa() -> None:
    d = decupagem(
        pessoas=[pessoa("p1", "Ana", [(1_000, 5_000)])],
        pautas=[pauta("t1", 0, 10_000, "Golaço", ["p1"])],
    )

    assert d.pautas[0].pessoas == ["p1"]


def test_gerar_validado_pede_outra_resposta_quando_a_pauta_cita_pessoa_fora() -> None:
    boa = decupagem(
        pessoas=[pessoa("p1", "Ana", [(1_000, 5_000)])],
        pautas=[pauta("t1", 0, 10_000, "Golaço", ["p1"])],
    )
    ruim = boa.model_copy(deep=True)
    ruim.pautas[0].pessoas.append("silhueta")  # o modelo respondeu isto
    respostas = [ruim.model_dump_json(), boa.model_dump_json()]
    chamadas: list[Chamada] = []

    class Transporte:
        def gerar(self, chamada: Chamada) -> str:
            chamadas.append(chamada)
            return respostas.pop(0)

    chamada = Chamada("m", "i", "gs://x", {}, {})

    d = gerar_validado(Transporte(), chamada, Decupagem.model_validate_json)

    assert d == boa
    assert len(chamadas) == 2


def test_consolidacao_ignora_pessoa_desconhecida_da_pauta(
    caplog: pytest.LogCaptureFixture,
) -> None:
    r0 = decupagem(
        pessoas=[pessoa("p1", "Ana", [(1_000, 5_000)])],
        pautas=[pauta("t1", 0, 10_000, "Golaço", ["p1"])],
    )
    r0.pautas[0].pessoas.append("silhueta")
    r1 = decupagem()

    with caplog.at_level(logging.WARNING):
        r = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [p.nome for p in r.pessoas] == ["Ana"]
    assert r.pautas[0].pessoas == [r.pessoas[0].id]
    assert "silhueta" in caplog.text


def _janela_gravada_invalida() -> str:
    boa = decupagem(
        pessoas=[pessoa("p1", "Ana", [(1_000, 5_000)])],
        pautas=[pauta("t1", 0, 10_000, "Golaço", ["p1"])],
    )
    boa.pautas[0].pessoas.append("silhueta")  # gravada antes do esquema novo
    return (
        '{"indice": 0, "situacao": "concluida", "tentativas": 1, "erro": null,'
        f' "refeita": false, "decupagem": {boa.model_dump_json()}}}'
    )


def test_janela_gravada_que_nao_passa_no_esquema_conta_como_nao_gravada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    janelas = JanelasEmMemoria()
    janelas._guardadas["j"] = {0: _janela_gravada_invalida()}
    modelo = ModeloFalso(lambda _i, _f: resposta())

    with caplog.at_level(logging.WARNING):
        analisar_video(
            modelo,
            video_uri=URI,
            job_id="j",
            video=VIDEO_LONGO,
            dormir=lambda _s: None,
            janelas_do_job=janelas,
        )

    assert (0, 310_000) in modelo.trechos()
    assert "j" in caplog.text
    gravada = janelas.ler("j")[0]
    assert isinstance(gravada, JanelaGravada)


def test_erro_inesperado_na_analise_leva_o_job_a_falhou() -> None:
    ambiente = _ambiente(RuntimeError("boom"))
    ambiente.registrar("j1")

    resultado = ambiente.executar("j1")

    assert resultado == "falhou"
    job = ambiente.job("j1")
    assert job.estado == "falhou"
    assert job.codigo_falha == "analise_falhou"
