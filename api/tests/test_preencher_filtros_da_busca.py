"""A carga dos filtros da busca nos objetos antigos (#483)."""

from datetime import UTC, datetime

from api.catalogo import EnvioParaLixeira
from api.indice_da_busca import IndiceEmMemoria, Registro
from api.jobs import RepositorioEmMemoria
from api.preencher_filtros_da_busca import preencher
from api.tests.test_lixeira import _job


def _registro(job_id: str) -> Registro:
    return Registro(
        id=f"{job_id}:fala:f0", tipo="fala", job_id=job_id, inicio_ms=0, fim_ms=1
    )


def test_a_carga_da_a_cada_video_o_valor_do_job_e_repetir_nao_muda_nada() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("a", sistema="Playout"))
    jobs.salvar(_job("b", sistema=None))
    indice = IndiceEmMemoria()
    for i in ("a", "b"):
        indice.gravar(i, [_registro(i)])

    assert preencher(jobs, indice, por_lote=1) == {
        "videos": 1,  # `b` não tem sistema e a lixeira falsa já é o padrão do registro
        "objetos": 1,
        "falhou": 0,
    }
    assert preencher(jobs, indice) == {"videos": 0, "objetos": 0, "falhou": 0}
    (a,) = indice._por_job["a"]
    assert a.sistema == "Playout" and a.na_lixeira is False


def test_um_video_que_falha_nao_para_a_carga_e_fica_para_a_proxima() -> None:
    jobs = RepositorioEmMemoria()
    for i in ("a", "b"):
        jobs.salvar(_job(i))
    indice = IndiceEmMemoria()
    for i in ("a", "b"):
        indice.gravar(i, [_registro(i)])
    original = indice.preencher_filtros
    falhar = {"a"}

    def instavel(job_id: str, sistema: str | None, na_lixeira: bool) -> int:
        if job_id in falhar:
            raise RuntimeError("429")
        return original(job_id, sistema, na_lixeira)

    indice.preencher_filtros = instavel  # type: ignore[method-assign]
    assert preencher(jobs, indice)["falhou"] == 1
    falhar.clear()
    assert preencher(jobs, indice)["falhou"] == 0


def test_a_restauracao_no_meio_da_carga_nao_esconde_o_video() -> None:
    envio = EnvioParaLixeira(
        em=datetime(2026, 11, 2, tzinfo=UTC),
        por_uid="adm",
        por_email="adm@redetv.com",
        motivo="duplicado",
    )
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("a", lixeira=envio))
    indice = IndiceEmMemoria()
    indice.gravar("a", [_registro("a")])
    original = indice.preencher_filtros

    def com_restauracao_no_meio(
        job_id: str, sistema: str | None, na_lixeira: bool
    ) -> int:
        # A carga leu o Job na lixeira; a restauração troca o Job e marca o índice, e só
        # então chega o `batchUpdate` da carga, com a cópia que ela leu.
        jobs.salvar(_job(job_id))
        indice.marcar_lixeira(job_id, False)
        original(job_id, sistema, na_lixeira)
        indice.marcar_lixeira(job_id, na_lixeira)
        return 1

    indice.preencher_filtros = com_restauracao_no_meio  # type: ignore[method-assign]
    preencher(jobs, indice)
    (a,) = indice._por_job["a"]
    assert a.na_lixeira is False
