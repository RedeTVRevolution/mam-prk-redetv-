"""A carga dos planos recorrentes no acervo antigo (#546), em dados locais."""

import io

from PIL import Image

from api.decupagem import Decupagem
from api.jobs import RepositorioEmMemoria
from api.preencher_planos_recorrentes import preencher
from api.tests.test_lixeira import _job
from api.tests.test_planos_recorrentes import _decupagem, _plano


def _png(cor: str) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (32, 32), cor).save(saida, "PNG")
    return saida.getvalue()


class Armazem:
    def __init__(self) -> None:
        self.decupagens: dict[str, Decupagem] = {}
        self.gravadas: list[str] = []

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return self.decupagens.get(job_id)

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return _png("gray")

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self.gravadas.append(job_id)
        self.decupagens[job_id] = Decupagem.model_validate_json(conteudo)


def _acervo() -> tuple[RepositorioEmMemoria, Armazem]:
    jobs = RepositorioEmMemoria()
    for i in ("a", "b", "c"):
        jobs.salvar(_job(i))
    jobs.salvar(_job("d", estado="analisando"))
    armazem = Armazem()
    iguais = [_plano("p0", 0, "q"), _plano("p1", 1, "q")]
    armazem.decupagens["a"] = _decupagem(iguais)
    armazem.decupagens["b"] = _decupagem(iguais[:1])  # um plano só: nada a agrupar
    return jobs, armazem


def test_a_previa_conta_antes_e_depois_e_nao_grava_nada() -> None:
    jobs, armazem = _acervo()

    total = preencher(jobs, armazem, gravar=False, por_pagina=1)

    assert total == {
        "videos": 2,
        "mudam": 1,
        "planos_antes": 0,
        "grupos_antes": 0,
        "planos_depois": 2,
        "grupos_depois": 1,
        "falhou": 1,  # `c` não tem Decupagem; o Job em andamento é ignorado
    }
    assert armazem.gravadas == []


def test_gravar_regrava_so_o_que_mudou_e_repetir_nao_muda_nada() -> None:
    jobs, armazem = _acervo()

    preencher(jobs, armazem, gravar=True)
    assert armazem.gravadas == ["a"]
    assert [p.plano_recorrente for p in armazem.decupagens["a"].planos] == [
        "rec01",
        "rec01",
    ]

    de_novo = preencher(jobs, armazem, gravar=True)
    assert armazem.gravadas == ["a"]
    assert (de_novo["mudam"], de_novo["planos_antes"], de_novo["planos_depois"]) == (
        0,
        2,
        2,
    )
