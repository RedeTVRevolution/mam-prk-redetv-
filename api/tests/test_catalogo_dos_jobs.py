"""O Job guarda quem aparece nele, e o impacto do catálogo lê só esses vídeos (#359)."""

import json
from typing import Any

from api.catalogo import CatalogoEmMemoria
from api.catalogo_dos_jobs import ids_do_catalogo
from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.jobs import FiltroDeJobs, Job, RepositorioEmMemoria
from api.preencher_catalogo_dos_jobs import preencher
from api.tests.test_correcoes import Mundo
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import _job
from api.tests.test_lixeira_do_catalogo import CURADOR, LIXEIRA
from api.tests.test_lixeira_do_catalogo import Mundo as MundoDaLixeira

ACERVO = 5000


def _pessoa_do_job(mundo: Mundo, id: str = "j1") -> list[str]:
    job = mundo.jobs.obter(id)
    assert job
    return job.pessoas_do_catalogo


def test_o_impacto_abre_so_as_decupagens_da_pessoa() -> None:
    mundo = MundoDaLixeira()
    # `j1` e `j2` já têm a Ana; mais dois com ela e o resto do acervo sem ninguém.
    for id in ("j3", "j4"):
        mundo.jobs.salvar(
            _job(id, pessoas_do_catalogo=[mundo.ana.id], marcas_do_catalogo=[])
        )
        mundo.armazenamento.decupagens[id] = mundo.armazenamento.decupagens["j1"]
    for i in range(ACERVO - 4):
        mundo.jobs.salvar(_job(f"x{i}"))
    abertas: list[str] = []
    abrir = mundo.armazenamento.abrir_decupagem

    def contando(job_id: str) -> Any:
        abertas.append(job_id)
        return abrir(job_id)

    mundo.armazenamento.abrir_decupagem = contando  # type: ignore[method-assign]

    resposta = mundo.cliente.get(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/impacto", headers=CURADOR
    )

    assert resposta.status_code == 200
    # Só `j2` não tem o rosto como única fonte (`gc`), e cada um dos outros 3 tem 2 aparições.
    assert resposta.json()["aparicoes_que_perdem_o_nome"] == 6
    assert sorted(abertas) == ["j1", "j2", "j3", "j4"]


def test_o_impacto_da_marca_abre_so_as_decupagens_dela() -> None:
    mundo = MundoDaLixeira()
    for i in range(ACERVO):
        mundo.jobs.salvar(_job(f"x{i}"))
    abertas: list[str] = []
    abrir = mundo.armazenamento.abrir_decupagem

    def contando(job_id: str) -> Any:
        abertas.append(job_id)
        return abrir(job_id)

    mundo.armazenamento.abrir_decupagem = contando  # type: ignore[method-assign]

    resposta = mundo.cliente.get(
        f"{LIXEIRA}/marcas/{mundo.marca.id}/impacto", headers=CURADOR
    )

    assert resposta.json()["ocorrencias_que_perdem_o_vinculo"] == 2
    assert sorted(abertas) == ["j1", "j2"]


def test_correcao_que_troca_o_nome_para_pessoa_do_catalogo_poe_o_id_no_job() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
    assert _pessoa_do_job(mundo) == []

    cid = mundo.corrigir().json()["id"]

    assert _pessoa_do_job(mundo) == [ana.id]

    assert mundo.desfazer(cid).status_code == 201

    assert _pessoa_do_job(mundo) == []


def test_correcao_pendente_so_entra_no_job_quando_aprovada() -> None:
    mundo = Mundo(["editor"])
    mundo.aprovacao.definir(frozenset({"pessoa.renomear"}))
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])

    cid = mundo.corrigir().json()["id"]
    assert _pessoa_do_job(mundo) == []

    curador = {"Authorization": "Bearer token-curador"}
    mundo.cliente.post(f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=curador)

    assert _pessoa_do_job(mundo) == [ana.id]


def test_ids_do_catalogo_sem_repetir_e_sem_vazios() -> None:
    entregue = {
        "pessoas": [{"catalogo_id": "b"}, {"catalogo_id": "a"}, {"catalogo_id": "b"}],
        "comerciais": [{"catalogo_id": None}, {"catalogo_id": "m"}, {}],
    }

    assert ids_do_catalogo(entregue) == (["a", "b"], ["m"])


def _decupagem(pessoa: str | None, marca: str | None) -> bytes:
    return json.dumps(
        {
            "pessoas": [{"id": "pes01", "nome": "Ana", "catalogo_id": pessoa}],
            "comerciais": [
                {
                    "id": "com000",
                    "marca": "Acme",
                    "catalogo_id": marca,
                    "inicio_ms": 0,
                    "fim_ms": 1,
                }
            ],
        }
    ).encode()


def test_a_carga_preenche_os_jobs_antigos_e_repetir_nao_muda_nada() -> None:
    catalogo = CatalogoEmMemoria()
    repositorio = RepositorioEmMemoria()
    armazenamento = ArmazenamentoFalso()
    repositorio.salvar(_job("com"))
    armazenamento.decupagens["com"] = [_decupagem("p1", "m1")]
    repositorio.salvar(_job("sem"))
    armazenamento.decupagens["sem"] = [_decupagem(None, None)]
    repositorio.salvar(_job("andando", estado="analisando"))

    def rodar() -> dict[str, int]:
        return preencher(
            repositorio,
            armazenamento,
            RepositorioDeCorrecoesEmMemoria(),
            catalogo.obter,
        )

    assert rodar() == {"gravados": 1, "iguais": 1, "falhou": 0}
    depois = {j.id: j for j in repositorio.listar()}
    assert depois["com"].pessoas_do_catalogo == ["p1"]
    assert depois["com"].marcas_do_catalogo == ["m1"]
    assert depois["sem"].pessoas_do_catalogo == []

    assert rodar() == {"gravados": 0, "iguais": 2, "falhou": 0}
    assert {j.id: j for j in repositorio.listar()} == depois


def test_a_reconciliacao_le_em_paginas_e_acha_o_job_sem_o_campo() -> None:
    catalogo = CatalogoEmMemoria()
    repositorio = RepositorioEmMemoria()
    armazenamento = ArmazenamentoFalso()
    for i in range(5):
        repositorio.salvar(_job(f"j{i}"))  # nenhum tem o campo: a gravação falhou
        armazenamento.decupagens[f"j{i}"] = [_decupagem("p1", None)]
    consultas: list[int | None] = []
    consultar = repositorio.consultar

    def contando(filtro: FiltroDeJobs) -> Any:
        consultas.append(filtro.limite)
        return consultar(filtro)

    repositorio.consultar = contando  # type: ignore[method-assign]

    def rodar() -> dict[str, int]:
        return preencher(
            repositorio,
            armazenamento,
            RepositorioDeCorrecoesEmMemoria(),
            catalogo.obter,
            por_lote=2,
        )

    assert rodar() == {"gravados": 5, "iguais": 0, "falhou": 0}
    assert consultas == [2, 2, 2]
    achados = repositorio.consultar(FiltroDeJobs(pessoa_do_catalogo="p1")).jobs
    assert sorted(j.id for j in achados) == [f"j{i}" for i in range(5)]
    assert rodar() == {"gravados": 0, "iguais": 5, "falhou": 0}


def test_a_consulta_por_pessoa_e_marca_acha_so_os_jobs_certos() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job("a", pessoas_do_catalogo=["p1"], marcas_do_catalogo=["m1"]))
    repositorio.salvar(_job("b", pessoas_do_catalogo=["p1", "p2"]))
    repositorio.salvar(_job("c", pessoas_do_catalogo=["p2"]))

    def ids(**filtro: Any) -> list[str]:
        return sorted(j.id for j in repositorio.consultar(FiltroDeJobs(**filtro)).jobs)

    assert ids(pessoa_do_catalogo="p1") == ["a", "b"]
    assert ids(marca_do_catalogo="m1") == ["a"]
    assert ids(pessoa_do_catalogo="p3") == []
    assert isinstance(repositorio.obter("a"), Job)
