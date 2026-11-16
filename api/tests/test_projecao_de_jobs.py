"""`obter_varios(..., so_a_lista=True)` e a tela de usuários lendo um documento por conta (#669)."""

from collections.abc import Iterable
from typing import Any
from unittest.mock import MagicMock

from api.eventos_do_job import RepositorioQueRegistraOFim
from api.jobs import JobResumido, RepositorioEmMemoria
from api.modelo_do_job import CAMPOS_DA_LISTA, Job
from api.nuvem import RepositorioFirestore
from api.papeis import DocumentoDePapeis
from api.tests.test_lixeira import EDITOR, Mundo, _job
from api.tests.test_usuarios import ADMIN
from api.tests.test_usuarios import ROTA as ROTA_USUARIOS
from api.tests.test_usuarios import Mundo as MundoDeUsuarios

PESADO: dict[str, Any] = {
    "cortes_ms": [10, 20, 30],
    "sha256": "b" * 64,
    "pessoas_do_catalogo": ["p1"],
}


def test_em_memoria_a_projecao_deixa_so_os_campos_da_lista() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job("a", **PESADO))

    (inteiro,) = repositorio.obter_varios(["a"])
    (projetado,) = repositorio.obter_varios(["a"], so_a_lista=True)

    assert inteiro.cortes_ms == [10, 20, 30]
    assert projetado.cortes_ms is None and projetado.pessoas_do_catalogo == []
    assert projetado.model_dump(include=set(CAMPOS_DA_LISTA)) == inteiro.model_dump(
        include=set(CAMPOS_DA_LISTA)
    )


def test_no_firestore_a_projecao_pede_so_os_campos_da_lista() -> None:
    cliente = MagicMock()
    doc = MagicMock(exists=True, id="a")
    doc.to_dict.return_value = _job("a").model_dump(include=set(CAMPOS_DA_LISTA))
    cliente.get_all.return_value = [doc]
    repositorio = RepositorioFirestore(cliente)

    (job,) = repositorio.obter_varios(["a"], so_a_lista=True)
    repositorio.obter_varios(["a"])

    assert job.id == "a"
    com, sem = cliente.get_all.call_args_list
    assert set(com.kwargs["field_paths"]) == CAMPOS_DA_LISTA
    assert "field_paths" not in sem.kwargs


def test_o_decorador_repassa_a_projecao() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job("a", **PESADO))
    decorado = RepositorioQueRegistraOFim(repositorio, MagicMock())

    (projetado,) = decorado.obter_varios(["a"], so_a_lista=True)

    assert projetado.cortes_ms is None


def _espiar(mundo: Mundo) -> list[Job]:
    lidos: list[Job] = []
    varios = mundo.jobs.obter_varios

    def espiando(job_ids: Iterable[str], **kw: Any) -> list[Job]:
        achados = varios(job_ids, **kw)
        lidos.extend(achados)
        return achados

    mundo.jobs.obter_varios = espiando  # type: ignore[method-assign,assignment]
    return lidos


def test_andamento_com_a_projecao_da_a_mesma_resposta_do_job_inteiro() -> None:
    job = _job("a", estado="analisando", **PESADO)
    mundo = Mundo(job)
    lidos = _espiar(mundo)

    corpo = mundo.cliente.get("/v1/jobs/andamento?ids=a", headers=EDITOR).json()

    esperado = JobResumido.de(job).model_dump(mode="json", exclude={"capa_url"})
    assert corpo == [esperado]
    assert [j.cortes_ms for j in lidos] == [None]


def test_quadros_em_lote_com_a_projecao_da_a_mesma_resposta_do_job_inteiro() -> None:
    mundo = Mundo(_job("a", **PESADO))
    lidos = _espiar(mundo)
    pedido = {"quadros": [{"job": "a", "arquivo": "x.jpg"}]}

    corpo = mundo.cliente.post("/v1/jobs/quadros", json=pedido, headers=EDITOR).json()

    assert corpo[0]["url"] is not None
    assert [j.cortes_ms for j in lidos] == [None]


def test_tela_de_usuarios_le_um_documento_de_papeis_por_conta() -> None:
    mundo = MundoDeUsuarios()
    chamadas: list[str] = []
    ler = mundo.papeis.ler

    def lendo(uid: str) -> DocumentoDePapeis:
        chamadas.append(uid)
        return ler(uid)

    mundo.papeis.ler = lendo  # type: ignore[method-assign]

    resposta = mundo.cliente.get(ROTA_USUARIOS, headers=ADMIN)

    assert resposta.status_code == 200
    # Uma leitura do middleware (quem pede) e uma por conta listada.
    assert sorted(chamadas) == ["adm", "adm", "u2"]
