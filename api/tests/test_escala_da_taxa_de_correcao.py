"""A taxa de correção parte das Correções do período, não do acervo inteiro (#360).

Os repositórios abaixo contam o que a taxa lê: com 5.000 Jobs, só os 3 com Correção no
período são lidos (e só as decupagens deles). O resultado é o mesmo do cálculo que
percorria o acervo, que aqui é refeito como referência."""

import json
from collections.abc import Iterable, Iterator
from datetime import timedelta
from typing import Any

from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.jobs import Job, RepositorioEmMemoria
from api.revisao import RepositorioDeRevisaoEmMemoria
from api.taxa_de_correcao import _em_vigor_no_periodo, calcular
from api.tests.test_taxa_de_correcao import (
    BASE,
    Decupagens,
    _c,
    _job,
    _modelo,
    _pulsar,
)

ACERVO = 5000
DESDE = BASE
ATE = BASE + timedelta(days=5)


class JobsQueConta(RepositorioEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lidos: list[str] = []
        self.listagens = 0

    def listar(self) -> list[Job]:
        self.listagens += 1
        return super().listar()

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        achados = super().obter_varios(job_ids)
        self.lidos += [j.id for j in achados]
        return achados


class DecupagensQueConta(Decupagens):
    def __init__(self, dados: dict[str, dict[str, Any]]) -> None:
        super().__init__(dados)
        self.abertas: list[str] = []

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        self.abertas.append(job_id)
        return super().abrir_decupagem(job_id)


def _acervo() -> tuple[
    JobsQueConta,
    DecupagensQueConta,
    RepositorioDeCorrecoesEmMemoria,
    RepositorioDeRevisaoEmMemoria,
]:
    """5.000 Jobs; `a`, `b` e `c` com Correção no período (`c` por pulso), `fora1` e
    `fora2` com Correção fora dele."""
    jobs = JobsQueConta()
    modelos: dict[str, dict[str, Any]] = {}
    correcoes = RepositorioDeCorrecoesEmMemoria()
    revisao = RepositorioDeRevisaoEmMemoria()
    for i in range(ACERVO):
        jobs.salvar(_job(f"x{i}", "Jornal"))
    for id in ("a", "b", "c", "fora1", "fora2"):
        jobs.salvar(_job(id, "Jornal"))
        modelos[id] = _modelo(10, 5)
    for id, dias in (("a", 1), ("b", 4), ("fora1", -3), ("fora2", 9)):
        correcoes.acrescentar(_c(f"c-{id}", id, modelos[id], dias=dias))
    _pulsar(revisao, "c", dias=2)
    return jobs, DecupagensQueConta(modelos), correcoes, revisao


def _como_antes(
    jobs: RepositorioEmMemoria,
    decupagens: Decupagens,
    correcoes: RepositorioDeCorrecoesEmMemoria,
    revisao: RepositorioDeRevisaoEmMemoria,
) -> list[Any]:
    """O cálculo de antes do #360, só para comparar: o acervo inteiro, Job a Job."""
    from api.correcoes import CORRIGIVEIS, versao_do_modelo
    from api.itens_da_decupagem import itens_do_tipo as _itens_do_tipo
    from api.taxa_de_correcao import LinhaDaTaxa, _no_periodo

    pulsados = {
        m.job_id
        for m in revisao.todas(DESDE)
        if _no_periodo(m.ultimo_pulso, DESDE, ATE)
    }
    somas: dict[tuple[str | None, str | None, str], tuple[int, int]] = {}
    for job in jobs.listar():
        feitas = correcoes.listar(job.id)
        if job.id not in pulsados and not any(
            (c.tipo in CORRIGIVEIS or c.aprova) and _no_periodo(c.criada_em, DESDE, ATE)
            for c in feitas
        ):
            continue
        conteudo = b"".join(decupagens.abrir_decupagem(job.id))
        modelo = json.loads(conteudo)
        vigor = _em_vigor_no_periodo(feitas, versao_do_modelo(conteudo), DESDE, ATE)
        for tipo in CORRIGIVEIS:
            chave = (job.programa, modelo.get("versao_pipeline"), tipo)
            n, itens = somas.get(chave, (0, 0))
            somas[chave] = (
                n + sum(c.tipo == tipo for c in vigor),
                itens + _itens_do_tipo(modelo, tipo),
            )
    return [
        LinhaDaTaxa(
            programa=p,
            versao_pipeline=v,
            tipo=t,
            correcoes=n,
            itens=itens,
            taxa_de_correcao=round(n / itens, 4) if itens else None,
        )
        for (p, v, t), (n, itens) in sorted(
            somas.items(), key=lambda kv: tuple(x or "" for x in kv[0])
        )
    ]


def test_le_so_os_jobs_e_as_decupagens_com_correcao_no_periodo() -> None:
    jobs, decupagens, correcoes, revisao = _acervo()

    linhas = calcular(jobs, decupagens, correcoes, revisao, DESDE, ATE)

    assert sorted(jobs.lidos) == ["a", "b", "c"]
    assert sorted(decupagens.abertas) == ["a", "b", "c"]
    assert jobs.listagens == 0
    assert linhas == _como_antes(jobs, decupagens, correcoes, revisao)
    assert sum(linha.correcoes for linha in linhas) == 2


def test_o_filtro_de_programa_nao_abre_a_decupagem_de_outro() -> None:
    jobs, decupagens, correcoes, revisao = _acervo()
    jobs.salvar(_job("outro", "Fama"))
    correcoes.acrescentar(_c("c-outro", "outro", _modelo(10, 5), dias=1))

    calcular(jobs, decupagens, correcoes, revisao, DESDE, ATE, "Jornal")

    assert "outro" not in decupagens.abertas


def test_sem_periodo_limita_se_aos_videos_revisados() -> None:
    jobs, decupagens, correcoes, revisao = _acervo()

    calcular(jobs, decupagens, correcoes, revisao)

    assert sorted(jobs.lidos) == ["a", "b", "c", "fora1", "fora2"]
    assert jobs.listagens == 0
