"""A busca lê vídeos e nomes em lote e usa uma cópia do catálogo, com trava (#364)."""

import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Thread

from api.busca import Busca, RankingEmOrdem
from api.catalogo import (
    VALIDADE_DA_COPIA,
    CatalogoEmMemoria,
    CopiaCurta,
    PessoaDoCatalogo,
    nomes_de_busca,
)
from api.comparador import normalizar
from api.entendimento_da_consulta import ModelArmorEmMemoria
from api.jobs import Job, RepositorioEmMemoria
from api.tests.test_busca import (
    PROGRAMAS,
    VESTIDO,
    Mundo,
    job,
    objeto,
    pedido,
)

AGORA = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class JobsContados(RepositorioEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.um_a_um = 0
        self.lotes: list[list[str]] = []

    def obter(self, job_id: str) -> Job | None:
        self.um_a_um += 1
        return super().obter(job_id)

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        ids = list(job_ids)
        self.lotes.append(ids)
        return super().obter_varios(ids)


class CatalogoContado(CatalogoEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.um_a_um = 0
        self.lotes = 0
        self.leituras_de_todas = 0

    def obter(self, id: str) -> PessoaDoCatalogo | None:
        self.um_a_um += 1
        return super().obter(id)

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        self.lotes += 1
        return super().obter_varios(ids)

    def achar(self, nome: str) -> list[PessoaDoCatalogo]:
        # No Firestore é uma consulta por nome, não a leitura da coleção.
        chave = normalizar(nome)
        return [p for p in super().todas() if chave in nomes_de_busca(p)]

    def todas(self) -> list[PessoaDoCatalogo]:
        self.leituras_de_todas += 1
        return super().todas()


def _mundo(*respostas: str) -> tuple[Mundo, JobsContados, CatalogoContado]:
    m = Mundo(*respostas)
    jobs, catalogo = JobsContados(), CatalogoContado()
    m.jobs, m.catalogo = jobs, catalogo
    m.sabrina = catalogo.acrescentar("Sabrina Sato", "apresentadora", ["Sabrina"]).id
    return m, jobs, catalogo


def test_cem_registros_de_quarenta_videos_leem_os_jobs_numa_leitura_em_lote() -> None:
    m, jobs, catalogo = _mundo(pedido(pessoas=["Sabrina Sato"], objetos=[VESTIDO]))
    for v in range(40):
        m.com(
            job(f"j{v}"),
            *(
                objeto(
                    f"j{v}:objeto:{i}",
                    f"j{v}",
                    i * 10_000,
                    i * 10_000 + 2_000,
                    dono=m.sabrina,
                )
                for i in range(3 if v < 20 else 2)
            ),
        )
    jobs.um_a_um = 0
    jobs.lotes.clear()

    resultado = m.busca().buscar("vestido vermelho da Sabrina Sato", limite=100)

    assert len(resultado.videos) == 40
    assert jobs.um_a_um == 0
    assert len(jobs.lotes) == 1
    assert len(set(jobs.lotes[0])) == 40
    # E os nomes: em lote (as pessoas entendidas, depois as dos registros), nenhuma
    # pessoa lida sozinha.
    assert catalogo.um_a_um == 0
    assert catalogo.lotes <= 2


def test_video_que_nao_e_visivel_continua_fora_do_resultado_em_lote() -> None:
    m, _, _ = _mundo(pedido(pessoas=["Sabrina Sato"], objetos=[VESTIDO]))
    m.com(job("bom"), objeto("bom:objeto:0", "bom", 1_000, 2_000, dono=m.sabrina))
    m.com(
        job("falhou", estado="falhou"),
        objeto("falhou:objeto:0", "falhou", 1_000, 2_000, dono=m.sabrina),
    )
    m.indice.gravar(
        "sumido", [objeto("sumido:objeto:0", "sumido", 1_000, 2_000, dono=m.sabrina)]
    )

    resultado = m.busca().buscar("vestido vermelho da Sabrina Sato")

    assert [v.job_id for v in resultado.videos] == ["bom"]


def test_duas_consultas_com_nome_errado_nao_leem_o_catalogo_inteiro_duas_vezes() -> (
    None
):
    errado = pedido(pessoas=["Sabrnia Sato"])
    m, _, catalogo = _mundo(errado, errado)
    busca = m.busca()

    busca.buscar("Sabrnia Sato")
    busca.buscar("Sabrnia Sato")

    assert catalogo.leituras_de_todas == 1


def test_a_busca_e_o_autocompletar_podem_dividir_a_mesma_copia() -> None:
    errado = pedido(pessoas=["Sabrnia Sato"])
    m, _, catalogo = _mundo(errado)
    copia = CopiaCurta(catalogo.todas, lambda: AGORA)
    copia.itens()  # o autocompletar leu antes

    busca = Busca(
        transporte=m.transporte,
        catalogo=catalogo,
        armor=ModelArmorEmMemoria(),
        programas=PROGRAMAS,
        indice=m.indice,
        ranking=RankingEmOrdem(),
        repositorio=m.jobs,
        armazenamento=m.armazenamento,
        relogio=lambda: AGORA,
        copia_do_catalogo=copia,
    )
    busca.buscar("Sabrnia Sato")

    assert catalogo.leituras_de_todas == 1


def _copia_lenta(
    quantas: list[int], relogio: list[datetime], solta: Event
) -> CopiaCurta[int]:
    def ler() -> list[int]:
        quantas.append(1)
        solta.wait(5)
        return [len(quantas)]

    return CopiaCurta(ler, lambda: relogio[0])


def _dez_threads(
    copia: CopiaCurta[int], solta: Event, antes_de_soltar: int = 0
) -> list[list[int]]:
    """Dez threads pedem a cópia ao mesmo tempo; a leitura só termina depois que
    `antes_de_soltar` delas já voltaram."""
    vistas: list[list[int]] = []
    largada = Barrier(10)

    def pedir() -> None:
        largada.wait()
        vistas.append(copia.itens())

    threads = [Thread(target=pedir) for _ in range(10)]
    for t in threads:
        t.start()
    prazo = time.monotonic() + 5
    while len(vistas) < antes_de_soltar and time.monotonic() < prazo:
        time.sleep(0.001)
    solta.set()
    for t in threads:
        t.join(10)
    return vistas


def test_dez_threads_com_a_copia_expirada_causam_uma_recarga_so() -> None:
    quantas: list[int] = []
    relogio = [AGORA]
    solta = Event()
    solta.set()
    copia = _copia_lenta(quantas, relogio, solta)
    assert copia.itens() == [1]
    relogio[0] = AGORA + VALIDADE_DA_COPIA + timedelta(seconds=1)
    solta.clear()

    # A leitura segura a que recarrega até as outras nove voltarem.
    vistas = _dez_threads(copia, solta, antes_de_soltar=9)

    assert len(quantas) == 2
    # Quem não recarregou usou a cópia anterior, sem esperar.
    assert sorted(vistas) == [[1]] * 9 + [[2]]


def test_dez_threads_na_primeira_leitura_esperam_uma_so_leitura() -> None:
    quantas: list[int] = []
    solta = Event()
    copia = _copia_lenta(quantas, [AGORA], solta)

    vistas = _dez_threads(copia, solta)

    assert len(quantas) == 1
    assert vistas == [[1]] * 10


def test_descartar_faz_a_proxima_leitura_esperar_a_copia_nova() -> None:
    lidas: list[list[str]] = [["a"], ["a", "b"]]
    copia = CopiaCurta(lambda: lidas.pop(0), lambda: AGORA)
    assert copia.itens() == ["a"]

    copia.descartar()

    assert copia.itens() == ["a", "b"]


def test_descartar_durante_a_leitura_nao_deixa_a_copia_velha_valer() -> None:
    copia: CopiaCurta[str]
    leituras = iter([["velha"], ["nova"]])

    def ler() -> list[str]:
        itens = next(leituras)
        if itens == ["velha"]:
            copia.descartar()  # um nome entrou enquanto a leitura corria
        return itens

    copia = CopiaCurta(ler, lambda: AGORA)

    copia.itens()

    assert copia.itens() == ["nova"]
