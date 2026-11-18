"""O impacto e a prévia de uma pessoa com muitos vídeos leem as Decupagens em paralelo,
com teto, e restaurar e purgar uma pessoa não leem nenhuma (#717). Conta leituras e
sobreposição num dublê; não mede tempo."""

import logging
import time
from collections.abc import Callable, Iterable, Iterator
from threading import Barrier, Lock, Thread
from typing import Any

import pytest

from api.catalogo import CatalogoEmMemoria, PessoaDoCatalogo
from api.leitura_da_decupagem import LEITURAS_AO_MESMO_TEMPO as TETO
from api.quem_conta import QuemConta
from api.tests import test_fusao_de_pessoas as fusao
from api.tests import test_lixeira_do_catalogo as lixeira
from api.tests import test_renomeacao_de_pessoas as renomeacao
from api.tests.test_lixeira import _job

# Múltiplo do teto, `j1` e `j2` do Mundo incluídos: a barreira não deixa leitura sobrando.
VIDEOS = TETO * 3


class Leituras:
    """Troca `abrir_decupagem` do armazenamento: conta, mede a sobreposição e, com
    `barreira`, segura cada leitura até `TETO` estarem abertas ao mesmo tempo."""

    def __init__(self, armazenamento: Any, barreira: bool = False) -> None:
        self.abertas = 0
        self.maximo = 0
        self.total = 0
        self.falham: set[str] = set()
        self._trava = Lock()
        self._barreira = Barrier(TETO, timeout=5) if barreira else None
        self._original = armazenamento.abrir_decupagem
        armazenamento.abrir_decupagem = self.abrir

    def abrir(self, job_id: str) -> Iterator[bytes]:
        with self._trava:
            self.abertas += 1
            self.total += 1
            self.maximo = max(self.maximo, self.abertas)
        try:
            if self._barreira is not None:
                self._barreira.wait()
            if job_id in self.falham:
                raise OSError("leitura ruim")
            yield from self._original(job_id)
        finally:
            with self._trava:
                self.abertas -= 1


def _fusao_com_videos(n: int) -> fusao.Mundo:
    """O Mundo (`j1`, `j2`) com mais vídeos da pessoa, até `n` no total."""
    mundo = fusao.Mundo()
    for i in range(n - 2):
        id = f"v{i}"
        mundo.jobs.salvar(_job(id, pessoas_do_catalogo=[mundo.duplicada.id]))
        mundo.armazenamento.decupagens[id] = mundo.armazenamento.decupagens["j1"]
    return mundo


def _impacto_da_fusao(mundo: fusao.Mundo) -> Any:
    return mundo.cliente.get(
        f"/v1/catalogo/pessoas/{mundo.duplicada.id}/fundir/impacto",
        params={"destino_id": mundo.sabrina.id},
        headers=fusao.CURADOR,
    )


def test_o_impacto_da_fusao_le_em_paralelo_com_teto_e_pessoas_em_lote_uma_vez() -> None:
    mundo = _fusao_com_videos(VIDEOS)
    leituras = Leituras(mundo.armazenamento, barreira=True)
    lotes: list[list[str]] = []
    obter_varios = mundo.catalogo.obter_varios

    def contar(ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        lotes.append(list(ids))
        return obter_varios(ids)

    mundo.catalogo.obter_varios = contar  # type: ignore[method-assign]

    resposta = _impacto_da_fusao(mundo)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["videos"] == VIDEOS
    # A barreira só abre com TETO leituras abertas: a leitura serial não passa dela.
    assert leituras.maximo == TETO
    assert len(lotes) == 1


def test_a_previa_da_renomeacao_le_em_paralelo() -> None:
    mundo = renomeacao.Mundo()
    dele = mundo.jobs.obter("j1").pessoas_do_catalogo  # type: ignore[union-attr]
    for i in range(VIDEOS - 2):
        mundo.jobs.salvar(_job(f"v{i}", pessoas_do_catalogo=dele))
        mundo.armazenamento.decupagens[f"v{i}"] = mundo.armazenamento.decupagens["j1"]
    leituras = Leituras(mundo.armazenamento, barreira=True)

    resposta = mundo.renomear(previa=True)

    assert resposta.status_code == 200, resposta.text
    assert leituras.maximo == TETO


def test_o_impacto_da_lixeira_le_em_paralelo() -> None:
    mundo = lixeira.Mundo()
    for i in range(VIDEOS - 2):
        mundo.jobs.salvar(_job(f"v{i}", pessoas_do_catalogo=[mundo.ana.id]))
        mundo.armazenamento.decupagens[f"v{i}"] = mundo.armazenamento.decupagens["j1"]
    leituras = Leituras(mundo.armazenamento, barreira=True)

    resposta = mundo.cliente.get(
        f"{lixeira.LIXEIRA}/pessoas/{mundo.ana.id}/impacto", headers=lixeira.CURADOR
    )

    assert resposta.status_code == 200, resposta.text
    assert leituras.maximo == TETO
    assert resposta.json()["aparicoes_que_perdem_o_nome"] == 2 * (
        VIDEOS - 1
    )  # menos j2, onde o GC sustenta o nome


def test_video_que_falha_ao_ler_e_pulado_com_log_e_os_outros_contam(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mundo = _fusao_com_videos(7)
    leituras = Leituras(mundo.armazenamento)
    leituras.falham = {"v0", "j2"}

    with caplog.at_level(logging.WARNING, logger="api.leitura_da_decupagem"):
        resposta = _impacto_da_fusao(mundo)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["videos"] == 5  # 7 vídeos, 2 não lidos
    assert "v0" in caplog.text and "j2" in caplog.text


def test_video_que_falha_na_lixeira_e_na_renomeacao_tambem_e_pulado() -> None:
    mundo = lixeira.Mundo()
    leituras = Leituras(mundo.armazenamento)
    leituras.falham = {"j1"}

    resposta = mundo.cliente.get(
        f"{lixeira.LIXEIRA}/pessoas/{mundo.ana.id}/impacto", headers=lixeira.CURADOR
    )

    assert resposta.json()["aparicoes_que_perdem_o_nome"] == 0  # j2 tem o nome por GC

    outra = renomeacao.Mundo()
    Leituras(outra.armazenamento).falham = {"j1"}
    assert outra.renomear(previa=True).json()["videos"] == 1


def test_o_quem_conta_compartilhado_le_cada_pessoa_uma_vez_sob_concorrencia() -> None:
    catalogo = CatalogoEmMemoria()
    pessoas = [catalogo.acrescentar(f"P{i}", "", []) for i in range(4)]
    ids = [p.id for p in pessoas]
    lidos: list[str] = []
    obter_varios = catalogo.obter_varios

    def lento(pedidos: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        pedidos = list(pedidos)
        lidos.extend(pedidos)
        time.sleep(0.05)
        return obter_varios(pedidos)

    catalogo.obter_varios = lento  # type: ignore[method-assign,assignment]
    quem = QuemConta(catalogo)
    achados: list[set[str]] = []
    chamada: Callable[[], None] = lambda: achados.append(quem.contam(ids))
    threads = [Thread(target=chamada) for _ in range(8)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert achados == [set(ids)] * 8
    assert sorted(lidos) == sorted(ids)


def _auditado(mundo: lixeira.Mundo, acao: str) -> Any:
    return next(r for r in mundo.registros() if r.acao == acao)


def test_restaurar_e_purgar_pessoa_nao_abrem_decupagem_e_gravam_sem_impacto() -> None:
    mundo = lixeira.Mundo()
    mundo.enviar("pessoas", mundo.ana.id)
    leituras = Leituras(mundo.armazenamento)

    mundo.cliente.post(
        f"{lixeira.LIXEIRA}/pessoas/{mundo.ana.id}/restaurar", headers=lixeira.ADMIN
    )
    restaurado = _auditado(mundo, "item.restaurado")
    mundo.enviar("pessoas", mundo.ana.id)
    purga = mundo.cliente.post(
        f"{lixeira.LIXEIRA}/pessoas/{mundo.ana.id}/purgar",
        json={"nome": "Ana Souza"},
        headers=lixeira.ADMIN,
    )

    assert purga.status_code == 200, purga.text
    # Só o segundo envio à lixeira calcula o impacto (j1 e j2); restaurar e purgar não.
    assert leituras.total == 2
    purgado = _auditado(mundo, "item.purgado")
    assert restaurado.detalhes == {} and purgado.detalhes == {}


def test_restaurar_e_purgar_marca_continuam_gravando_o_impacto() -> None:
    mundo = lixeira.Mundo()
    mundo.enviar("marcas", mundo.marca.id)
    mundo.cliente.post(
        f"{lixeira.LIXEIRA}/marcas/{mundo.marca.id}/restaurar", headers=lixeira.ADMIN
    )
    mundo.enviar("marcas", mundo.marca.id)
    mundo.cliente.post(
        f"{lixeira.LIXEIRA}/marcas/{mundo.marca.id}/purgar",
        json={"nome": "Acme"},
        headers=lixeira.ADMIN,
    )

    for acao in ("item.restaurado", "item.purgado"):
        assert _auditado(mundo, acao).detalhes["ocorrencias_que_perdem_o_vinculo"] == 2
