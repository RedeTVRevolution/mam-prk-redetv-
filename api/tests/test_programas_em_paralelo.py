"""As operações de programa leem em lote e só o que precisam (#718, spec #634)."""

from datetime import UTC, datetime
from typing import Any

from api.catalogo import CatalogoEmMemoria, EnvioParaLixeira
from api.jobs import RepositorioEmMemoria
from api.modelo_do_job import FiltroDeJobs, PaginaDeJobs
from api.programas import (
    Programa,
    ProgramasEmMemoria,
    RenomeacaoDoPrograma,
    VinculoDaPessoa,
    perfis_dos_programas,
    terminar_o_pendente,
)
from api.tests.test_lixeira import BASE, _job
from api.tests.test_programas import AUTORIZACAO, _cliente


class CatalogoQueConta(CatalogoEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.obter_chamadas: list[str] = []
        self.lotes: list[list[str]] = []

    def obter(self, id: str) -> Any:
        self.obter_chamadas.append(id)
        return super().obter(id)

    def obter_varios(self, ids: Any) -> Any:
        ids = list(ids)
        self.lotes.append(ids)
        return super().obter_varios(ids)


def _cadastro(n: int) -> tuple[ProgramasEmMemoria, CatalogoQueConta]:
    catalogo = CatalogoQueConta()
    programas = []
    for i in range(n):
        pessoa = catalogo.acrescentar(f"Pessoa {i}", "", [])
        programas.append(
            Programa(
                id=f"p{i}",
                nome=f"Programa {i}",
                pessoas=[VinculoDaPessoa(pessoa_id=pessoa.id, papel="apresentador")],
            )
        )
    return ProgramasEmMemoria(programas), catalogo


def test_perfis_le_o_catalogo_so_para_o_programa_pedido() -> None:
    programas, catalogo = _cadastro(5)
    perfis = perfis_dos_programas(programas, catalogo)
    assert catalogo.lotes == []
    assert "Programa 2" in perfis and "Inexistente" not in perfis
    assert perfis["Programa 2"].pessoas[0].nome == "Pessoa 2"
    assert perfis["Programa 2"].pessoas[0].nome == "Pessoa 2"
    assert len(catalogo.lotes) == 1
    assert len(catalogo.lotes[0]) == 1


def test_a_listagem_de_programas_le_as_pessoas_num_lote_so() -> None:
    cadastro = _cadastro(6)
    cliente, _, catalogo = _cliente(["editor"], cadastro=cadastro)
    resposta = cliente.get("/v1/admin/programas", headers=AUTORIZACAO)
    assert resposta.status_code == 200
    assert [len(p["pessoas"]) for p in resposta.json()] == [1] * 6
    assert len(catalogo.lotes) == 1  # type: ignore[attr-defined]


def test_conferir_pessoas_faz_uma_leitura_em_lote() -> None:
    programas, catalogo = _cadastro(1)
    ids = [catalogo.acrescentar(f"Outra {i}", "", []).id for i in range(8)]
    cliente, _, _ = _cliente(["editor"], cadastro=(programas, catalogo))
    corpo = {
        "nome": "Novo",
        "perfil": "",
        "pessoas": [{"pessoa_id": i, "papel": ""} for i in ids],
    }
    assert (
        cliente.post("/v1/admin/programas", json=corpo, headers=AUTORIZACAO).status_code
        == 201
    )
    assert catalogo.obter_chamadas == []
    assert sorted(catalogo.lotes[0]) == sorted(ids)  # a conferência: um lote só
    corpo["pessoas"] = [{"pessoa_id": "inexistente", "papel": ""}]
    assert (
        cliente.post(
            "/v1/admin/programas", json=corpo | {"nome": "Y"}, headers=AUTORIZACAO
        ).status_code
        == 422
    )


class JobsQueVeOFiltro(RepositorioEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.filtros: list[FiltroDeJobs] = []

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        self.filtros.append(filtro)
        return super().consultar(filtro)


def test_o_impacto_ignora_a_lixeira_e_le_so_os_campos_da_lista() -> None:
    jobs = JobsQueVeOFiltro()
    lixeira = EnvioParaLixeira(em=BASE, por_uid="u1", por_email="a@b.c", motivo="x")
    for job in (
        _job("j1", programa="TV Fama"),
        _job("j2", programa="TV Fama", lixeira=lixeira),
        _job("j3", programa="Outro"),
    ):
        jobs.salvar(job)
    cliente, _, _ = _cliente(["editor"], jobs=jobs)
    resposta = cliente.get("/v1/admin/programas/tv-fama/impacto", headers=AUTORIZACAO)
    assert resposta.json() == {"videos": 1}
    assert [f.so_os_da_lista for f in jobs.filtros] == [True]


class ProgramasQueContam(ProgramasEmMemoria):
    def __init__(self, programas: list[Programa]) -> None:
        super().__init__(programas)
        self.listagens = 0

    def listar(self) -> list[Programa]:
        self.listagens += 1
        return super().listar()


def test_terminar_o_pendente_nao_lista_os_programas() -> None:
    troca = RenomeacaoDoPrograma(
        id="t",
        nome_antigo="A",
        nome_novo="B",
        total=1,
        pendentes=["j1"],
        estado="em_andamento",
        desde=datetime(2026, 11, 5, tzinfo=UTC),
    )
    outros = [Programa(id=f"p{i}", nome=f"P{i}") for i in range(5)]
    programas = ProgramasQueContam(
        [*outros, Programa(id="x", nome="B", renomeacao=troca)]
    )
    terminar_o_pendente(programas, "j1", "B", True)
    assert programas.listagens == 0
    atual = programas.obter("x")
    assert atual and atual.renomeacao and atual.renomeacao.estado == "concluida"
