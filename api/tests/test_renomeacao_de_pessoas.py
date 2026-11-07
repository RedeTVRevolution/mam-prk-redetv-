"""Renomear uma pessoa em todos os vídeos de uma vez (#263)."""

import json
from typing import Any

from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.catalogo import CatalogoEmMemoria, FusaoDaPessoa, RenomeacaoDaPessoa
from api.catalogo_dos_jobs import ids_do_catalogo
from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.exemplos_da_busca import EXEMPLOS
from api.indexacao import reindexar_jobs
from api.indice_da_busca import IndiceEmMemoria, Registro
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import BASE, _job

CURADOR = {"Authorization": "Bearer curador"}
EDITOR = {"Authorization": "Bearer editor"}


class IndiceQueFalhaAteConsertar(IndiceEmMemoria):
    """Também conta as gravações: renomear uma pessoa não pode gravar o índice. A falha
    é usada pelo teste de renomear programa."""

    def __init__(self) -> None:
        super().__init__()
        self.falhas_restantes = 0
        self.quebrado = False
        self.gravacoes = 0

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        self.gravacoes += 1
        if self.quebrado or self.falhas_restantes > 0:
            self.falhas_restantes = max(0, self.falhas_restantes - 1)
            raise ConnectionError("índice fora do ar")
        super().gravar(job_id, registros)

    def donos(self, job_id: str) -> set[str]:
        return {r.texto or "" for r in self._por_job.get(job_id, [])}


class Mundo:
    def __init__(self) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.sabrina = self.catalogo.acrescentar("Sabrina Sato", "apresentadora", [])
        self.outra = self.catalogo.acrescentar("Outra Pessoa", "", [])
        self.jobs = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.indice = IndiceQueFalhaAteConsertar()
        for id, exemplo in (
            ("j1", EXEMPLOS[0]),
            ("j2", EXEMPLOS[0]),
            ("j3", EXEMPLOS[1]),
        ):
            modelo = json.loads(exemplo.decupagem.model_dump_json())
            for pessoa in modelo["pessoas"]:
                pessoa["catalogo_id"] = {
                    "cat-sabrina-sato": self.sabrina.id,
                    "cat-outra": self.outra.id,
                }[pessoa["catalogo_id"]]
            self.jobs.salvar(_job(id, pessoas_do_catalogo=ids_do_catalogo(modelo)[0]))
            self.armazenamento.decupagens[id] = [json.dumps(modelo).encode()]
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("cur", ["curador"])
        papeis.salvar("ed", ["editor"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "curador": Usuario(uid="cur", email="Cur@redetv.com"),
                        "editor": Usuario(uid="ed", email="ed@redetv.com"),
                    }
                ),
                self.jobs,
                self.armazenamento,
                papeis=papeis,
                auditoria=self.auditoria,
                catalogo=self.catalogo,
                indice=self.indice,
                relogio=lambda: BASE,
            )
        )

    def renomear(
        self,
        nome: str = "Sabrina Sato Silva",
        *,
        previa: bool = False,
        headers: Any = CURADOR,
    ) -> Any:
        return self.cliente.post(
            f"/v1/catalogo/pessoas/{self.sabrina.id}/renomear",
            json={"nome": nome, "previa": previa},
            headers=headers,
        )

    def andamento(self) -> Any:
        return self.cliente.get(
            f"/v1/catalogo/pessoas/{self.sabrina.id}/renomear/andamento",
            headers=CURADOR,
        )

    def nome_na_decupagem(self, job_id: str) -> str:
        corpo = self.cliente.get(f"/v1/jobs/{job_id}/decupagem", headers=CURADOR).json()
        nome: str = next(p["nome"] for p in corpo["pessoas"] if p["id"] == "pes01")
        return nome


def test_a_previa_abre_so_as_decupagens_da_pessoa() -> None:
    mundo = Mundo()
    for i in range(50):
        mundo.jobs.salvar(_job(f"x{i}"))
    abertas: list[str] = []
    abrir = mundo.armazenamento.abrir_decupagem

    def contando(job_id: str) -> Any:
        abertas.append(job_id)
        return abrir(job_id)

    mundo.armazenamento.abrir_decupagem = contando  # type: ignore[method-assign]

    resposta = mundo.renomear(previa=True)

    assert resposta.json()["videos"] == 2
    assert sorted(abertas) == ["j1", "j2"]


def test_a_previa_conta_videos_e_momentos_sem_mudar_nada() -> None:
    mundo = Mundo()

    resposta = mundo.renomear(previa=True)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {
        "nome_antigo": "Sabrina Sato",
        "nome_novo": "Sabrina Sato Silva",
        "videos": 2,
        "momentos_afetados": 2,
        "previa": True,
    }
    assert mundo.catalogo.obter(mundo.sabrina.id).nome == "Sabrina Sato"  # type: ignore[union-attr]
    assert mundo.nome_na_decupagem("j1") == "Sabrina Sato"
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_renomear_troca_no_catalogo_e_nas_decupagens_sem_reindexar() -> None:
    mundo = Mundo()

    resposta = mundo.renomear()

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["previa"] is False
    assert mundo.catalogo.obter(mundo.sabrina.id).nome == "Sabrina Sato Silva"  # type: ignore[union-attr]
    for job in ("j1", "j2"):
        assert mundo.nome_na_decupagem(job) == "Sabrina Sato Silva"
    assert mundo.indice.gravacoes == 0
    assert mundo.andamento().json() == {
        "estado": "concluida",
        "feitos": 2,
        "total": 2,
        "nome_antigo": "Sabrina Sato",
        "nome_novo": "Sabrina Sato Silva",
    }


def test_a_correcao_de_outro_nome_no_video_nao_e_trocada() -> None:
    mundo = Mundo()
    modelo = json.loads(mundo.armazenamento.decupagens["j2"][0])
    modelo["pessoas"][0]["nome"] = "Sabrina Sato Sa"
    mundo.armazenamento.decupagens["j2"] = [json.dumps(modelo).encode()]

    previa = mundo.renomear(previa=True).json()
    mundo.renomear()

    assert mundo.nome_na_decupagem("j2") == "Sabrina Sato Sa"
    assert mundo.nome_na_decupagem("j1") == "Sabrina Sato Silva"
    # A prévia só conta o vídeo em que o nome muda.
    assert previa["videos"] == 1
    assert mundo.andamento().json()["total"] == 1


def test_o_nome_antigo_fica_como_apelido_para_a_busca() -> None:
    mundo = Mundo()

    mundo.renomear()

    [achada] = mundo.catalogo.achar("Sabrina Sato")
    assert achada.id == mundo.sabrina.id
    assert achada.nome == "Sabrina Sato Silva"


def test_reindexar_depois_da_renomeacao_nao_poe_o_nome_no_indice() -> None:
    mundo = Mundo()
    mundo.renomear()

    reindexar_jobs(
        None,
        mundo.jobs,
        mundo.armazenamento,
        RepositorioDeCorrecoesEmMemoria(),
        mundo.indice,
        pessoas=mundo.catalogo.obter,
    )

    assert not any("Sabrina" in t for t in mundo.indice.donos("j1"))


def test_pessoa_inexistente_e_404_e_fundida_e_422() -> None:
    mundo = Mundo()
    mundo.catalogo.definir_fusao(
        mundo.outra.id,
        FusaoDaPessoa(
            destino_id=mundo.sabrina.id,
            em=BASE,
            por_uid="cur",
            por_email="cur@redetv.com",
            motivo="duplicada",
        ),
    )

    inexistente = mundo.cliente.post(
        "/v1/catalogo/pessoas/nao-existe/renomear",
        json={"nome": "X"},
        headers=CURADOR,
    )
    fundida = mundo.cliente.post(
        f"/v1/catalogo/pessoas/{mundo.outra.id}/renomear",
        json={"nome": "X"},
        headers=CURADOR,
    )

    assert inexistente.status_code == 404
    assert fundida.status_code == 422


def test_renomeacao_presa_sem_pendentes_termina_ao_retomar() -> None:
    mundo = Mundo()
    mundo.catalogo.definir_renomeacao(
        mundo.sabrina.id,
        RenomeacaoDaPessoa(
            nome_antigo="Sabrina",
            nome_novo="Sabrina Sato",
            nomes_anteriores=["Sabrina"],
            em=BASE,
            por_uid="cur",
            por_email="cur@redetv.com",
            total=2,
            pendentes=[],
            estado="em_andamento",
        ),
    )
    assert mundo.renomear().status_code == 409

    mundo.cliente.post(
        f"/v1/catalogo/pessoas/{mundo.sabrina.id}/renomear/retomar", headers=CURADOR
    )

    assert mundo.andamento().json()["estado"] == "concluida"
    assert mundo.renomear().status_code == 200


def test_sem_correcao_aprovar_e_403_e_nada_muda() -> None:
    mundo = Mundo()

    assert mundo.renomear(headers=EDITOR).status_code == 403
    assert mundo.renomear(previa=True, headers=EDITOR).status_code == 403
    assert mundo.catalogo.obter(mundo.sabrina.id).nome == "Sabrina Sato"  # type: ignore[union-attr]


def test_a_renomeacao_grava_o_nome_antigo_o_novo_quem_fez_e_a_quantidade() -> None:
    mundo = Mundo()

    mundo.renomear()

    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.acao == "pessoa.renomeada"
    assert registro.uid == "cur" and registro.email == "cur@redetv.com"
    assert registro.alvo_id == mundo.sabrina.id
    assert registro.detalhes == {
        "nome_antigo": "Sabrina Sato",
        "nome_novo": "Sabrina Sato Silva",
        "videos": 2,
        "momentos_afetados": 2,
    }


def test_nome_de_outra_pessoa_ou_igual_ao_atual_e_422() -> None:
    mundo = Mundo()

    assert mundo.renomear("outra pessoa").status_code == 422
    assert mundo.renomear("Sabrina Sato").status_code == 422
    assert mundo.renomear("  ").status_code == 422
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_andamento_de_pessoa_que_nunca_foi_renomeada_e_404() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get(
        f"/v1/catalogo/pessoas/{mundo.outra.id}/renomear/andamento", headers=CURADOR
    )

    assert resposta.status_code == 404
