import json
from typing import Any

import pytest

from api.gemini import (
    AnaliseFalhou,
    ErroHttp,
    Pedido,
    analisar,
)
from api.tests.test_decupagem import DURACAO_MS, decupagem_valida

JOB = "job-123"
VIDEO = "gs://quarentena/proxy.mp4"


class TransporteFalso:
    """Devolve, em ordem, textos ou levanta as exceções da fila."""

    def __init__(self, *respostas: str | Exception) -> None:
        self.respostas = list(respostas)
        self.pedidos: list[Pedido] = []

    def gerar(self, pedido: Pedido) -> str:
        self.pedidos.append(pedido)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Relogio:
    def __init__(self) -> None:
        self.esperas: list[float] = []

    def dormir(self, s: float) -> None:
        self.esperas.append(s)


def _rodar(transporte: TransporteFalso, relogio: Relogio | None = None) -> Any:
    relogio = relogio or Relogio()
    return analisar(
        transporte,
        video_uri=VIDEO,
        job_id=JOB,
        duracao_ms=DURACAO_MS,
        dormir=relogio.dormir,
        sortear=lambda teto: teto,  # pior caso: jitter no teto
    )


BOA = json.dumps(decupagem_valida())


def test_devolve_decupagem_valida() -> None:
    t = TransporteFalso(BOA)
    d = _rodar(t)
    assert d.programa.resumo == "Jornal da noite"
    assert len(t.pedidos) == 1


def test_pedido_leva_job_como_rotulo_e_nenhuma_ferramenta() -> None:
    t = TransporteFalso(BOA)
    _rodar(t)
    p = t.pedidos[0]
    assert p.rotulos == {"job_id": JOB}
    assert p.ferramentas == ()
    assert p.video_uri == VIDEO
    assert p.esquema["additionalProperties"] is False


def test_resposta_fora_do_esquema_e_refeita_ate_2_vezes() -> None:
    t = TransporteFalso("não é json", '{"x": 1}', BOA)
    d = _rodar(t)
    assert d.video.duracao_ms == DURACAO_MS
    assert len(t.pedidos) == 3


def test_terceira_resposta_ruim_vira_analise_falhou() -> None:
    t = TransporteFalso("lixo", "lixo", "lixo", BOA)
    with pytest.raises(AnaliseFalhou) as e:
        _rodar(t)
    assert e.value.codigo == "analise_falhou"
    assert len(t.pedidos) == 3


def test_tempo_fora_da_duracao_conta_como_resposta_invalida() -> None:
    ruim = decupagem_valida()
    ruim["planos"][0]["fim_ms"] = DURACAO_MS + 1
    t = TransporteFalso(json.dumps(ruim), BOA)
    _rodar(t)
    assert len(t.pedidos) == 2


@pytest.mark.parametrize("status", [429, 500, 503])
def test_429_e_5xx_tentam_de_novo_com_backoff_exponencial(status: int) -> None:
    relogio = Relogio()
    t = TransporteFalso(ErroHttp(status), ErroHttp(status), ErroHttp(status), BOA)
    _rodar(t, relogio)
    assert len(t.pedidos) == 4
    assert relogio.esperas == [1.0, 2.0, 4.0]


def test_jitter_total_sorteia_entre_zero_e_o_teto() -> None:
    tetos: list[float] = []

    def sortear(teto: float) -> float:
        tetos.append(teto)
        return 0.0

    t = TransporteFalso(ErroHttp(429), ErroHttp(429), BOA)
    analisar(
        t,
        video_uri=VIDEO,
        job_id=JOB,
        duracao_ms=DURACAO_MS,
        dormir=lambda s: None,
        sortear=sortear,
    )
    assert tetos == [1.0, 2.0]


def test_cinco_novas_tentativas_e_depois_analise_falhou() -> None:
    t = TransporteFalso(*[ErroHttp(503)] * 6, BOA)
    with pytest.raises(AnaliseFalhou) as e:
        _rodar(t)
    assert e.value.codigo == "analise_falhou"
    assert len(t.pedidos) == 6  # 1 chamada + 5 novas


def test_erro_4xx_diferente_de_429_nao_tenta_de_novo() -> None:
    t = TransporteFalso(ErroHttp(400), BOA)
    with pytest.raises(AnaliseFalhou):
        _rodar(t)
    assert len(t.pedidos) == 1


def test_os_dois_orcamentos_de_tentativas_sao_independentes() -> None:
    t = TransporteFalso(ErroHttp(429), "lixo", ErroHttp(500), "lixo", BOA)
    _rodar(t)
    assert len(t.pedidos) == 5
