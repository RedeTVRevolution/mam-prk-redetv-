from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import (
    FiltroDeAuditoria,
    RegistroDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
)
from api.auth import Usuario
from api.carregar_programas import carregar
from api.catalogo import Catalogo, CatalogoEmMemoria, EnvioParaLixeira
from api.copia_bigquery import CopiaEmMemoria
from api.exemplos_da_busca import EXEMPLOS
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.programas import (
    ProgramaInexistente,
    ProgramasEmMemoria,
    RenomeacaoDoPrograma,
    perfis_dos_programas,
)
from api.tests.programas_de_teste import cadastro_com_tv_fama
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import BASE, _job
from api.tests.test_renomeacao_de_pessoas import IndiceQueFalhaAteConsertar

AUTORIZACAO = {"Authorization": "Bearer token"}


def _cliente(
    papeis: list[Papel],
    jobs: RepositorioEmMemoria | None = None,
    auditoria: RepositorioDeAuditoriaEmMemoria | None = None,
    armazenamento: ArmazenamentoFalso | None = None,
    indice: IndiceQueFalhaAteConsertar | None = None,
    copia: CopiaEmMemoria | None = None,
) -> tuple[TestClient, ProgramasEmMemoria, Catalogo]:
    programas, catalogo = cadastro_com_tv_fama()
    repositorio_de_papeis = RepositorioDePapeisEmMemoria()
    repositorio_de_papeis.salvar("u1", papeis)
    cliente = TestClient(
        criar_app(
            VerificadorFalso({"token": Usuario(uid="u1", email="a@b.c")}),
            jobs or RepositorioEmMemoria(),
            armazenamento or ArmazenamentoFalso(),
            papeis=repositorio_de_papeis,
            indice=indice,
            copia=copia,
            programas=programas,
            catalogo=catalogo,
            auditoria=auditoria or RepositorioDeAuditoriaEmMemoria(),
            relogio=lambda: datetime(2026, 11, 5, tzinfo=UTC),
        )
    )
    return cliente, programas, catalogo


def test_consulta_e_operador_recebem_403_em_cada_rota() -> None:
    for papel in ("consulta", "operador"):
        cliente, programas, _ = _cliente([papel])
        id = programas.listar()[0].id
        corpo = {"nome": "Novo"}
        chamadas = [
            cliente.get("/v1/admin/programas", headers=AUTORIZACAO),
            cliente.post("/v1/admin/programas", json=corpo, headers=AUTORIZACAO),
            cliente.put(f"/v1/admin/programas/{id}", json=corpo, headers=AUTORIZACAO),
            cliente.get(f"/v1/admin/programas/{id}/impacto", headers=AUTORIZACAO),
            cliente.delete(f"/v1/admin/programas/{id}", headers=AUTORIZACAO),
            cliente.post(
                "/v1/admin/programas/pessoas", json=corpo, headers=AUTORIZACAO
            ),
            cliente.post(
                f"/v1/admin/programas/{id}/renomear/retomar", headers=AUTORIZACAO
            ),
        ]
        assert [c.status_code for c in chamadas] == [403] * 7


def test_editor_cria_renomeia_e_apaga_com_auditoria() -> None:
    cliente, programas, _ = _cliente(["editor"])

    pessoa = cliente.post(
        "/v1/admin/programas/pessoas",
        json={"nome": "Fulana Nova", "apelidos": ["Fu"]},
        headers=AUTORIZACAO,
    ).json()
    criado = cliente.post(
        "/v1/admin/programas",
        json={
            "nome": "Programa Novo",
            "perfil": "Um programa.",
            "pessoas": [{"pessoa_id": pessoa["pessoa_id"], "papel": "âncora"}],
        },
        headers=AUTORIZACAO,
    )
    assert criado.status_code == 201
    id = criado.json()["id"]
    assert "Programa Novo" in cliente.get("/v1/programas", headers=AUTORIZACAO).json()

    renomeado = cliente.put(
        f"/v1/admin/programas/{id}",
        json={"nome": "Outro Nome", "perfil": "Um programa."},
        headers=AUTORIZACAO,
    )
    assert renomeado.json()["id"] == id and renomeado.json()["pessoas"] == []

    assert (
        cliente.delete(f"/v1/admin/programas/{id}", headers=AUTORIZACAO).status_code
        == 204
    )
    assert programas.obter(id) is None
    auditoria = cliente.get("/v1/admin/auditoria", headers=AUTORIZACAO)
    assert auditoria.status_code == 403  # o Editor não vê a tela da auditoria


class Acervo:
    """Vídeos com Decupagem do "TV Fama" (um na lixeira) e um de outro programa."""

    def __init__(self) -> None:
        self.jobs = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.indice = IndiceQueFalhaAteConsertar()
        self.copia = CopiaEmMemoria()
        lixeira = EnvioParaLixeira(
            em=BASE, por_uid="u1", por_email="a@b.c", motivo="duplicado"
        )
        for job in (
            _job("j1", programa="TV Fama"),
            _job("j2", programa="TV Fama", lixeira=lixeira),
            _job("j3", programa="Outro"),
        ):
            self.jobs.salvar(job)
            self.armazenamento.decupagens[job.id] = [
                EXEMPLOS[0].decupagem.model_dump_json().encode()
            ]
        self.cliente, self.programas, _ = _cliente(
            ["editor"],
            self.jobs,
            armazenamento=self.armazenamento,
            indice=self.indice,
            copia=self.copia,
        )
        self.id = next(p.id for p in self.programas.listar() if p.nome == "TV Fama")

    def renomear(self, nome: str = "Fama Hoje", perfil: str = "") -> Any:
        return self.cliente.put(
            f"/v1/admin/programas/{self.id}",
            json={"nome": nome, "perfil": perfil},
            headers=AUTORIZACAO,
        )

    def programa(self, job_id: str) -> str | None:
        return self.jobs.obter(job_id).programa  # type: ignore[union-attr]

    def no_indice(self, job_id: str) -> set[str | None]:
        return {r.programa for r in self.indice._por_job.get(job_id, [])}

    def na_copia(self, job_id: str) -> set[str | None]:
        return {linha.programa for linha in self.copia.por_job.get(job_id, [])}


def test_renomear_troca_o_nome_nos_videos_e_reindexa() -> None:
    acervo = Acervo()

    renomeado = acervo.renomear()

    assert renomeado.status_code == 200, renomeado.text
    assert [acervo.programa(j) for j in ("j1", "j2", "j3")] == [
        "Fama Hoje",
        "Fama Hoje",
        "Outro",
    ]
    assert acervo.no_indice("j1") == {"Fama Hoje"}
    assert acervo.na_copia("j1") == {"Fama Hoje"}
    # Na lixeira também: restaurar não reindexa, e ele voltaria com o nome antigo.
    assert acervo.no_indice("j2") == {"Fama Hoje"}
    assert acervo.na_copia("j2") == {"Fama Hoje"}
    assert acervo.no_indice("j3") == set()
    lido = acervo.cliente.get("/v1/admin/programas", headers=AUTORIZACAO).json()
    assert next(p for p in lido if p["id"] == acervo.id)["renomeacao"] == {
        "estado": "concluida",
        "feitos": 2,
        "total": 2,
        "nome_antigo": "TV Fama",
        "nome_novo": "Fama Hoje",
    }
    impacto = acervo.cliente.get(
        f"/v1/admin/programas/{acervo.id}/impacto", headers=AUTORIZACAO
    )
    assert impacto.json() == {"videos": 1}


def test_indice_fora_do_ar_deixa_pendente_e_retomar_termina() -> None:
    acervo = Acervo()
    acervo.indice.quebrado = True

    acervo.renomear()

    assert acervo.programa("j1") == "Fama Hoje"
    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert renomeacao is not None
    assert (renomeacao.estado, set(renomeacao.pendentes)) == ("falhou", {"j1", "j2"})
    assert acervo.renomear(perfil="Revista.").status_code == 200
    assert acervo.programas.obter(acervo.id).renomeacao == renomeacao  # type: ignore[union-attr]

    acervo.indice.quebrado = False
    retomado = acervo.cliente.post(
        f"/v1/admin/programas/{acervo.id}/renomear/retomar", headers=AUTORIZACAO
    )

    assert retomado.status_code == 200
    assert acervo.no_indice("j1") == {"Fama Hoje"}
    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert renomeacao is not None
    assert (renomeacao.estado, renomeacao.pendentes) == ("concluida", [])
    assert acervo.renomear("Outro Nome").status_code == 200


def test_criar_alterar_e_apagar_vao_para_a_auditoria() -> None:
    auditoria = RepositorioDeAuditoriaEmMemoria()
    cliente, _, _ = _cliente(["editor"], auditoria=auditoria)

    id = cliente.post(
        "/v1/admin/programas", json={"nome": "Novo"}, headers=AUTORIZACAO
    ).json()["id"]
    cliente.put(
        f"/v1/admin/programas/{id}", json={"nome": "Novo 2"}, headers=AUTORIZACAO
    )
    cliente.delete(f"/v1/admin/programas/{id}", headers=AUTORIZACAO)

    registros = auditoria.consultar(FiltroDeAuditoria(alvo_id=id)).registros
    assert sorted(r.acao for r in registros) == [
        "programa.alterado",
        "programa.apagado",
        "programa.criado",
    ]


def test_pessoa_criada_no_programa_fica_a_revisar() -> None:
    cliente, _, catalogo = _cliente(["editor"])
    busca = "/v1/catalogo/pessoas?q=Fulana"
    assert cliente.get(busca, headers=AUTORIZACAO).json() == []  # a cópia já existe

    criada = cliente.post(
        "/v1/admin/programas/pessoas",
        json={"nome": "Fulana Nova"},
        headers=AUTORIZACAO,
    ).json()

    assert catalogo.obter(criada["pessoa_id"]).a_revisar is True  # type: ignore[union-attr]
    # A cópia das pessoas foi descartada: o autocompletar já acha a nova.
    achadas = cliente.get(busca, headers=AUTORIZACAO).json()
    assert [p["id"] for p in achadas] == [criada["pessoa_id"]]


class _AuditoriaQueFalha(RepositorioDeAuditoriaEmMemoria):
    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        raise RuntimeError("auditoria fora do ar")


def test_renomear_sem_auditoria_desfaz_e_nao_toca_nos_videos() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("j1", programa="TV Fama"))
    cliente, programas, _ = _cliente(["editor"], jobs, _AuditoriaQueFalha())
    id = next(p.id for p in programas.listar() if p.nome == "TV Fama")

    with pytest.raises(RuntimeError):
        cliente.put(
            f"/v1/admin/programas/{id}", json={"nome": "Fama Hoje"}, headers=AUTORIZACAO
        )

    assert programas.obter(id).nome == "TV Fama"  # type: ignore[union-attr]
    assert programas.obter(id).renomeacao is None  # type: ignore[union-attr]
    assert jobs.obter("j1").programa == "TV Fama"  # type: ignore[union-attr]


def test_renomear_sem_ler_os_videos_nao_grava_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("j1", programa="TV Fama"))
    auditoria = RepositorioDeAuditoriaEmMemoria()
    cliente, programas, _ = _cliente(["editor"], jobs, auditoria)

    def fora(*_: Any, **__: Any) -> Any:
        raise ConnectionError("Firestore fora")

    monkeypatch.setattr(jobs, "consultar", fora)
    with pytest.raises(ConnectionError):
        cliente.put(
            "/v1/admin/programas/tv-fama",
            json={"nome": "Fama Hoje"},
            headers=AUTORIZACAO,
        )

    # Nada renomeado sem andamento: `retomar` e o 409 dependem dele.
    programa = programas.obter("tv-fama")
    assert programa is not None
    assert (programa.nome, programa.renomeacao) == ("TV Fama", None)
    assert auditoria.consultar(FiltroDeAuditoria(alvo_id="tv-fama")).registros == []


def _andamento(estado: Any, pendentes: list[str]) -> RenomeacaoDoPrograma:
    return RenomeacaoDoPrograma(
        nome_antigo="Antigo",
        nome_novo="TV Fama",
        total=2,
        pendentes=pendentes,
        estado=estado,
    )


def test_salvar_nao_toca_no_andamento_e_o_andamento_nao_recria_o_programa() -> None:
    programas, _ = cadastro_com_tv_fama()
    concluida = _andamento("concluida", [])
    programas.gravar_renomeacao("tv-fama", concluida)

    # A cópia velha do PUT (andamento em andamento) não volta a troca atrás.
    velho = programas.obter("tv-fama")
    assert velho is not None
    programas.salvar(
        velho.model_copy(
            update={"perfil": "Novo.", "renomeacao": _andamento("em_andamento", ["j1"])}
        )
    )
    lido = programas.obter("tv-fama")
    assert lido is not None
    assert (lido.perfil, lido.renomeacao) == ("Novo.", concluida)

    programas.apagar("tv-fama")
    with pytest.raises(ProgramaInexistente):
        programas.gravar_renomeacao("tv-fama", concluida)
    assert programas.obter("tv-fama") is None


def test_com_a_troca_em_andamento_renomear_e_apagar_dao_409() -> None:
    cliente, programas, _ = _cliente(["editor"])
    programas.gravar_renomeacao("tv-fama", _andamento("em_andamento", ["j1"]))

    renomear = cliente.put(
        "/v1/admin/programas/tv-fama", json={"nome": "Outro"}, headers=AUTORIZACAO
    )
    apagar = cliente.delete("/v1/admin/programas/tv-fama", headers=AUTORIZACAO)

    assert (renomear.status_code, apagar.status_code) == (409, 409)
    assert programas.obter("tv-fama") is not None


def test_falha_passageira_ao_gravar_o_andamento_nao_mata_a_troca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acervo = Acervo()
    gravar = acervo.programas.gravar_renomeacao
    falhas: list[str] = []

    def falha_uma_vez(id: str, r: RenomeacaoDoPrograma) -> None:
        if len(r.pendentes) < r.total and not falhas:
            falhas.append(id)
            raise ConnectionError("Firestore fora")
        gravar(id, r)

    monkeypatch.setattr(acervo.programas, "gravar_renomeacao", falha_uma_vez)
    acervo.renomear()

    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert falhas and renomeacao is not None
    # O Job da falha ficou pendente e a rodada seguinte o terminou.
    assert (renomeacao.estado, renomeacao.pendentes) == ("concluida", [])


def test_troca_que_falhou_aceita_outro_nome_e_leva_os_pendentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acervo = Acervo()
    trocar = acervo.jobs.trocar

    def trocar_menos_j1(job_id: str, mudar: Any) -> Any:
        if job_id == "j1":
            raise ConnectionError("Firestore fora")
        return trocar(job_id, mudar)

    monkeypatch.setattr(acervo.jobs, "trocar", trocar_menos_j1)
    acervo.renomear()
    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert renomeacao is not None
    assert (renomeacao.estado, renomeacao.pendentes) == ("falhou", ["j1"])
    assert acervo.programa("j1") == "TV Fama"

    monkeypatch.setattr(acervo.jobs, "trocar", trocar)
    assert acervo.renomear("Fama Já").status_code == 200

    # O pendente herdado ainda tinha o nome mais antigo e também foi para o novo.
    assert [acervo.programa(j) for j in ("j1", "j2")] == ["Fama Já", "Fama Já"]
    assert acervo.no_indice("j1") == {"Fama Já"}
    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert renomeacao is not None
    assert (renomeacao.estado, renomeacao.total, renomeacao.pendentes) == (
        "concluida",
        2,
        [],
    )


def test_copia_que_falha_deixa_pendente_ate_retomar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acervo = Acervo()
    gravar = acervo.copia.gravar

    def fora(*_: Any) -> None:
        raise ConnectionError("BigQuery fora")

    monkeypatch.setattr(acervo.copia, "gravar", fora)
    acervo.renomear()

    assert acervo.no_indice("j1") == {"Fama Hoje"} and acervo.na_copia("j1") == set()
    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert renomeacao is not None
    assert (renomeacao.estado, set(renomeacao.pendentes)) == ("falhou", {"j1", "j2"})

    monkeypatch.setattr(acervo.copia, "gravar", gravar)
    acervo.cliente.post(
        f"/v1/admin/programas/{acervo.id}/renomear/retomar", headers=AUTORIZACAO
    )

    assert acervo.na_copia("j1") == {"Fama Hoje"}
    renomeacao = acervo.programas.obter(acervo.id).renomeacao  # type: ignore[union-attr]
    assert renomeacao is not None and renomeacao.estado == "concluida"


def test_apagar_deixa_o_nome_nos_videos_antigos() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("j1", programa="TV Fama"))
    cliente, programas, _ = _cliente(["editor"], jobs)
    id = next(p.id for p in programas.listar() if p.nome == "TV Fama")

    cliente.delete(f"/v1/admin/programas/{id}", headers=AUTORIZACAO)

    assert jobs.obter("j1").programa == "TV Fama"  # type: ignore[union-attr]
    assert "TV Fama" not in cliente.get("/v1/programas", headers=AUTORIZACAO).json()


def test_nome_repetido_da_409_e_pessoa_fora_do_catalogo_da_422() -> None:
    cliente, _, _ = _cliente(["editor"])

    repetido = cliente.post(
        "/v1/admin/programas", json={"nome": "tv fama"}, headers=AUTORIZACAO
    )
    fora = cliente.post(
        "/v1/admin/programas",
        json={"nome": "X", "pessoas": [{"pessoa_id": "nao-existe", "papel": ""}]},
        headers=AUTORIZACAO,
    )

    assert (repetido.status_code, fora.status_code) == (409, 422)


def test_perfil_enorme_e_recusado() -> None:
    cliente, _, _ = _cliente(["editor"])

    resposta = cliente.post(
        "/v1/admin/programas",
        json={"nome": "X", "perfil": "a" * 5000},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 422


def test_carga_unica_e_idempotente_e_poe_o_papel_no_vinculo() -> None:
    programas, catalogo = ProgramasEmMemoria(), CatalogoEmMemoria()
    catalogo.acrescentar("Leão Lobo", "comentarista", [])
    dados = {
        "TV Fama": {
            "perfil": "Revista.",
            "pessoas": [
                {"nome": "Leão Lobo", "papel": "apresentador", "apelidos": []},
                {"nome": "Ana", "papel": "repórter", "apelidos": ["Aninha"]},
            ],
        }
    }

    primeira = carregar(programas, catalogo, dados)
    segunda = carregar(programas, catalogo, dados)

    assert (primeira, segunda) == ((1, 1), (0, 0))
    texto = perfis_dos_programas(programas, catalogo)["TV Fama"].texto()
    assert "- Leão Lobo, apresentador." in texto
    assert '- Ana, repórter; também chamado de "Aninha".' in texto
