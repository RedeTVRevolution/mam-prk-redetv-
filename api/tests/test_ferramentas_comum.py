"""Utilitários que as ferramentas dividem (`api/ferramentas/comum.py`, #658)."""

import hashlib
from datetime import UTC, datetime

import pytest

from api.catalogo import EnvioParaLixeira
from api.ferramentas.comum import (
    custo_de_horas,
    custo_por_hora_do_ambiente,
    dolar,
    hash_estavel,
    jobs_concluidos,
    percentil,
)
from api.indice_da_busca import IndiceEmMemoria, Registro
from api.jobs import Job, RepositorioEmMemoria
from api.preencher_catalogo_dos_jobs import preencher as preencher_catalogo
from api.preencher_filtros_da_busca import preencher as preencher_filtros
from api.preencher_planos_recorrentes import preencher as preencher_planos
from api.reprocessar_versao import escolher
from api.tests.test_lixeira import _job
from api.tests.test_preencher_planos_recorrentes import Armazem

NA_LIXEIRA = EnvioParaLixeira(
    em=datetime(2026, 11, 2, tzinfo=UTC),
    por_uid="adm",
    por_email="adm@redetv.com",
    motivo="duplicado",
)


def _acervo() -> RepositorioEmMemoria:
    jobs = RepositorioEmMemoria()
    for i in ("a", "b", "c"):
        jobs.salvar(_job(i))
    jobs.salvar(_job("lixo", lixeira=NA_LIXEIRA))
    jobs.salvar(_job("andando", estado="analisando"))
    return jobs


def _ids(jobs: list[Job]) -> list[str]:
    return sorted(j.id for j in jobs)


def test_os_concluidos_vem_em_paginas_e_sem_os_em_andamento() -> None:
    lidos = jobs_concluidos(_acervo(), na_lixeira=None, tamanho_da_pagina=1)

    assert _ids(list(lidos)) == ["a", "b", "c", "lixo"]


def test_na_lixeira_false_deixa_o_job_da_lixeira_de_fora() -> None:
    lidos = jobs_concluidos(_acervo(), na_lixeira=False, tamanho_da_pagina=2)

    assert _ids(list(lidos)) == ["a", "b", "c"]


class _Leitura:
    def __init__(self) -> None:
        self.lidos: list[str] = []

    def corrigida(self, job_id: str) -> None:
        self.lidos.append(job_id)
        raise RuntimeError("não importa: só quem foi lido")


def test_o_job_concluido_na_lixeira_entra_nos_tres_preencher() -> None:
    jobs = _acervo()
    indice = IndiceEmMemoria()
    indice.gravar(
        "lixo",
        [
            Registro(
                id="lixo:fala:f0", tipo="fala", job_id="lixo", inicio_ms=0, fim_ms=1
            )
        ],
    )
    leitura = _Leitura()

    planos = preencher_planos(jobs, Armazem(), gravar=False, tamanho_da_pagina=1)
    filtros = preencher_filtros(jobs, indice, tamanho_da_pagina=1)
    preencher_catalogo(jobs, leitura, tamanho_da_pagina=1)  # type: ignore[arg-type]

    assert planos["falhou"] == 4  # a, b, c e `lixo` (o em andamento fica fora)
    assert filtros["videos"] == 1 and indice._por_job["lixo"][0].sistema == "Playout"
    assert sorted(leitura.lidos) == ["a", "b", "c", "lixo"]


def test_o_job_concluido_na_lixeira_fica_fora_de_reprocessar_versao() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("a", versao_pipeline="2026.10.1"))
    jobs.salvar(_job("lixo", versao_pipeline="2026.10.1", lixeira=NA_LIXEIRA))

    escolhidos = escolher(jobs, None, None, None, agora=_job("a").criado_em)  # type: ignore[arg-type]

    assert [c.job_id for c in escolhidos] == ["a"]


def test_hash_estavel_e_o_prefixo_hexadecimal_do_sha256_como_inteiro() -> None:
    cheio = hashlib.sha256(b"chave").hexdigest()

    assert hash_estavel("chave", 8) == int(cheio[:8], 16)
    assert hash_estavel("chave", 12) == int(cheio[:12], 16)
    assert hash_estavel("chave", 64) == int(cheio, 16)


@pytest.mark.parametrize("n", range(1, 101))
def test_percentil_e_o_posto_mais_proximo_sem_interpolar(n: int) -> None:
    valores = [float(i) for i in range(n, 0, -1)]  # fora de ordem de propósito

    for p in (50, 95, 99, 100):
        esperado = sorted(valores)[max(1, -(-n * p // 100)) - 1]
        assert percentil(valores, p) == esperado


def test_o_custo_por_hora_vem_do_ambiente_ou_e_nd() -> None:
    assert custo_por_hora_do_ambiente({"CUSTO_POR_HORA_USD": "1.5"}) == 1.5
    assert custo_por_hora_do_ambiente({"CUSTO_POR_HORA_USD": ""}) is None
    assert custo_por_hora_do_ambiente({}) is None


def test_o_custo_estimado_e_horas_vezes_o_custo() -> None:
    assert custo_de_horas(2.5, 4.0) == 10.0


def test_os_dois_formatos_do_dolar() -> None:
    assert dolar(1234.5) == "US$ 1.234,50"
    assert dolar(1234.5, ptbr=False, casas=4) == "US$ 1234.5000"
    assert dolar(0.12341, ptbr=False, casas=4) == "US$ 0.1234"
    assert dolar(3.14159, ptbr=False, casas=2) == "US$ 3.14"
