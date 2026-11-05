"""A lixeira e a purga leem só os Jobs de que precisam, não o acervo inteiro (#358)."""

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


def _contando(repositorio: RepositorioEmMemoria) -> dict[str, int]:
    """Conta os Jobs devolvidos por `consultar` (o que o Firestore cobraria como leitura)."""
    contagem = {"lidos": 0}
    consultar = repositorio.consultar

    def contar(filtro: FiltroDeJobs) -> PaginaDeJobs:
        pagina = consultar(filtro)
        contagem["lidos"] += len(pagina.jobs)
        return pagina

    repositorio.consultar = contar  # type: ignore[method-assign]
    return contagem


def _lixeira(em_dias: int) -> EnvioParaLixeira:
    return EnvioParaLixeira(
        em=AGORA - timedelta(days=em_dias),
        por_uid="adm",
        por_email="ana@redetv.com",
        motivo="duplicado",
    )


def _acervo(repositorio: RepositorioEmMemoria) -> None:
    """5.000 Jobs: 3 na lixeira (j0 com o `sha256` "a") e 2 fora dela com o `sha256` "a"
    (o `alvo` e `igual`)."""
    for i in range(ACERVO - 5):
        repositorio.salvar(_job(f"x{i}", sha256=f"{i:064x}"))
    repositorio.salvar(_job("alvo", sha256="a" * 64))
    repositorio.salvar(_job("igual", sha256="a" * 64))
    repositorio.salvar(_job("j0", sha256="a" * 64, lixeira=_lixeira(5)))
    repositorio.salvar(_job("j1", sha256="b" * 64, lixeira=_lixeira(3)))
    repositorio.salvar(_job("j2", sha256="c" * 64, lixeira=_lixeira(1)))


def test_o_impacto_le_so_os_jobs_do_mesmo_arquivo() -> None:
    repositorio = RepositorioEmMemoria()
    _acervo(repositorio)
    contagem = _contando(repositorio)
    alvo = repositorio.obter("alvo")
    assert alvo is not None

    impacto = calcular_impacto(
        alvo, repositorio, RepositorioDeCorrecoesEmMemoria(), ArquivosEmMemoria()
    )

    assert sorted(o.id for o in impacto.outros_jobs) == ["igual", "j0"]
    assert contagem["lidos"] == 3  # os dois outros e o próprio alvo


def test_a_listagem_da_lixeira_le_so_os_jobs_da_lixeira() -> None:
    mundo = Mundo()
    _acervo(mundo.jobs)
    contagem = _contando(mundo.jobs)

    resposta = mundo.cliente.get(LIXEIRA, headers=ADMIN)

    assert resposta.status_code == 200
    assert len(resposta.json()) == 3
    assert contagem["lidos"] == 3


def test_a_purga_automatica_le_so_os_jobs_da_lixeira() -> None:
    mundo = MundoDaPurga()
    _acervo(mundo.jobs)
    contagem = _contando(mundo.jobs)

    assert purgar_vencidas(mundo.jobs, mundo.purga(), AGORA) == []

    assert contagem["lidos"] == 3
