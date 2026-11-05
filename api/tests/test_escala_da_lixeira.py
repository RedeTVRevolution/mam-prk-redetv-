"""A lixeira e a purga leem só os Jobs de que precisam, não o acervo inteiro (#358).

O repositório em memória filtra tudo em Python, então contar o que ele devolve só mede
o impacto, que antes pedia o acervo inteiro. A listagem e a purga sempre receberam só
os da lixeira: aqui se confere que pedem `FiltroDeJobs(na_lixeira=True)`, e o teste no
emulador (`test_nuvem.py`) confere que o Firestore, com esse filtro, lê só esses."""

from datetime import timedelta

from api.catalogo import EnvioParaLixeira
from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.jobs import FiltroDeJobs, PaginaDeJobs, RepositorioEmMemoria
from api.lixeira import ArquivosEmMemoria, calcular_impacto
from api.purga import purgar_vencidas
from api.tests.test_lixeira import ADMIN, LIXEIRA, Mundo, _job
from api.tests.test_purga import AGORA
from api.tests.test_purga import Mundo as MundoDaPurga

ACERVO = 5000


def _contando(
    repositorio: RepositorioEmMemoria,
) -> list[tuple[FiltroDeJobs, int]]:
    """Guarda cada filtro pedido a `consultar` com o número de Jobs devolvidos."""
    filtros: list[tuple[FiltroDeJobs, int]] = []
    consultar = repositorio.consultar

    def contar(filtro: FiltroDeJobs) -> PaginaDeJobs:
        pagina = consultar(filtro)
        filtros.append((filtro, len(pagina.jobs)))
        return pagina

    repositorio.consultar = contar  # type: ignore[method-assign]
    return filtros


def _lixeira(em_dias: int) -> EnvioParaLixeira:
    return EnvioParaLixeira(
        em=AGORA - timedelta(days=em_dias),
        por_uid="adm",
        por_email="ana@redetv.com",
        motivo="duplicado",
    )


def _acervo(repositorio: RepositorioEmMemoria) -> None:
    """`ACERVO` Jobs: 3 na lixeira e 2 fora dela com o mesmo `sha256` (`alvo` e `igual`)."""
    for i in range(ACERVO - 5):
        repositorio.salvar(_job(f"x{i}", sha256=f"{i:064x}"))
    repositorio.salvar(_job("alvo", sha256="a" * 64))
    repositorio.salvar(_job("igual", sha256="a" * 64))
    repositorio.salvar(_job("j0", sha256="d" * 64, lixeira=_lixeira(5)))
    repositorio.salvar(_job("j1", sha256="b" * 64, lixeira=_lixeira(3)))
    repositorio.salvar(_job("j2", sha256="c" * 64, lixeira=_lixeira(1)))


def test_o_impacto_le_so_os_jobs_do_mesmo_arquivo() -> None:
    repositorio = RepositorioEmMemoria()
    _acervo(repositorio)
    filtros = _contando(repositorio)
    alvo = repositorio.obter("alvo")
    assert alvo is not None

    impacto = calcular_impacto(
        alvo, repositorio, RepositorioDeCorrecoesEmMemoria(), ArquivosEmMemoria()
    )

    assert [o.id for o in impacto.outros_jobs] == ["igual"]
    assert filtros == [(FiltroDeJobs(sha256="a" * 64, na_lixeira=None), 2)]


def test_a_listagem_da_lixeira_pede_so_os_jobs_da_lixeira() -> None:
    mundo = Mundo()
    _acervo(mundo.jobs)
    filtros = _contando(mundo.jobs)

    resposta = mundo.cliente.get(LIXEIRA, headers=ADMIN)

    assert resposta.status_code == 200
    assert len(resposta.json()) == 3
    assert filtros == [(FiltroDeJobs(na_lixeira=True), 3)]


def test_a_purga_automatica_pede_so_os_jobs_da_lixeira() -> None:
    mundo = MundoDaPurga()
    _acervo(mundo.jobs)
    filtros = _contando(mundo.jobs)

    assert purgar_vencidas(mundo.jobs, mundo.purga(), AGORA) == []

    assert filtros == [(FiltroDeJobs(na_lixeira=True), 3)]
