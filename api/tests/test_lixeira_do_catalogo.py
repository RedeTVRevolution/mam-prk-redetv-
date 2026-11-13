"""Lixeira (3/3): pessoas e marcas do catálogo (#151)."""

import json
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.catalogo import CatalogoEmMemoria, FusaoDaPessoa, Rosto
from api.copia_bigquery import CopiaEmMemoria, LinhaDoMomento
from api.jobs import RepositorioEmMemoria
from api.lixeira_do_catalogo import FotosEmMemoria, purgar_catalogo_vencido
from api.lixeira_na_leitura import PurgasDeMarcaEmMemoria
from api.main import criar_app
from api.marcas import CatalogoDeMarcasEmMemoria, MarcaDoCatalogo
from api.papeis import RepositorioDePapeisEmMemoria
from api.relatorio_de_marcas import ConsultaDeInsercoes, ConsultaEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import BASE, _job

ADMIN = {"Authorization": "Bearer admin"}
CURADOR = {"Authorization": "Bearer curador"}
EDITOR = {"Authorization": "Bearer editor"}
LIXEIRA = "/v1/admin/lixeira"
AGORA = BASE + timedelta(days=40)
FOTOS = [f"referencias/ana/{i}.jpg" for i in range(3)]


def _pessoa(catalogo_id: str, fontes: list[str]) -> dict[str, Any]:
    return {
        "id": "pes01",
        "nome": "Ana Souza",
        "fontes_do_nome": fontes,
        "origem": "modelo_forte",
        "estado_do_nome": "confirmado",
        "catalogo_id": catalogo_id,
        "na_imagem": [
            {"inicio_ms": 0, "fim_ms": 1000, "evidencia": "rosto"},
            {"inicio_ms": 2000, "fim_ms": 3000, "evidencia": "rosto"},
        ],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }


class Mundo:
    def __init__(
        self,
        relatorio: ConsultaDeInsercoes | None = None,
        purgas: PurgasDeMarcaEmMemoria | None = None,
    ) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.marcas = CatalogoDeMarcasEmMemoria()
        self.ana = self.catalogo.acrescentar("Ana Souza", "apresentadora", [])
        self.catalogo.definir_rostos(
            self.ana.id,
            [Rosto(origem="acervo", referencia=objeto) for objeto in FOTOS],
        )
        self.marca = self.marcas.acrescentar("Acme", [])
        # Mais uma foto da web trocada antes, que ficou na pasta da pessoa.
        self.velha = f"referencias/{self.ana.id}/velha.jpg"
        self.fotos = FotosEmMemoria({*FOTOS, self.velha, "referencias/outra/0.jpg"})
        self.jobs = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.agora = BASE
        for id, fontes in (("j1", ["referencia"]), ("j2", ["gc"])):
            self.jobs.salvar(
                _job(
                    id,
                    pessoas_do_catalogo=[self.ana.id],
                    marcas_do_catalogo=[self.marca.id],
                )
            )
            decupagem = {
                "pessoas": [_pessoa(self.ana.id, fontes)],
                "comerciais": [
                    {
                        "id": "com000",
                        "marca": "Acme",
                        "catalogo_id": self.marca.id,
                        "inicio_ms": 0,
                        "fim_ms": 1,
                    }
                ],
            }
            self.armazenamento.decupagens[id] = [json.dumps(decupagem).encode()]
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        papeis.salvar("cur", ["curador"])
        papeis.salvar("ed", ["editor"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(
                            uid="adm", email="ana@redetv.com", login_em=AGORA
                        ),
                        "curador": Usuario(
                            uid="cur", email="cur@redetv.com", login_em=AGORA
                        ),
                        "editor": Usuario(uid="ed", email="ed@redetv.com"),
                    }
                ),
                self.jobs,
                self.armazenamento,
                papeis=papeis,
                auditoria=self.auditoria,
                catalogo=self.catalogo,
                marcas=self.marcas,
                relatorio_de_marcas=relatorio,
                purgas_de_marca=purgas,
                fotos_de_referencia=self.fotos,
                relogio=lambda: self.agora,
            )
        )

    def enviar(self, tipo: str, id: str, headers: Any = CURADOR) -> Any:
        return self.cliente.post(
            f"{LIXEIRA}/{tipo}/{id}", json={"motivo": "duplicada"}, headers=headers
        )

    def pessoa_em(self, job: str) -> dict[str, Any]:
        lida = self.cliente.get(f"/v1/jobs/{job}/decupagem", headers=ADMIN).json()
        pessoa: dict[str, Any] = lida["pessoas"][0]
        return pessoa

    def registros(self) -> list[Any]:
        return self.auditoria.consultar(FiltroDeAuditoria()).registros


def test_pessoa_na_lixeira_perde_o_nome_so_onde_so_o_rosto_o_sustentava() -> None:
    mundo = Mundo()

    assert mundo.enviar("pessoas", mundo.ana.id).status_code == 201

    pelo_rosto = mundo.pessoa_em("j1")
    assert pelo_rosto["nome"].startswith("não identificado")
    assert pelo_rosto["fontes_do_nome"] == []
    assert pelo_rosto.get("catalogo_id") is None
    assert len(pelo_rosto["na_imagem"]) == 2
    assert mundo.pessoa_em("j2")["nome"] == "Ana Souza"
    assert mundo.fotos.objetos == {"referencias/outra/0.jpg"}
    assert mundo.catalogo.obter(mundo.ana.id).rostos == []  # type: ignore[union-attr]


def test_restaurar_devolve_a_pessoa_mas_nao_as_fotos() -> None:
    mundo = Mundo()
    mundo.enviar("pessoas", mundo.ana.id)

    resposta = mundo.cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/restaurar", headers=ADMIN
    )

    assert resposta.status_code == 200
    assert mundo.catalogo.achar("ana souza")[0].rostos == []
    assert mundo.pessoa_em("j1")["nome"] == "Ana Souza"


def test_o_impacto_conta_as_aparicoes_que_perdem_o_nome_e_as_fotos() -> None:
    mundo = Mundo()

    impacto = mundo.cliente.get(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/impacto", headers=CURADOR
    ).json()

    assert impacto["aparicoes_que_perdem_o_nome"] == 2
    assert impacto["fotos_apagadas"] == 3
    assert impacto["restaurar_devolve_as_fotos"] is False


def test_o_impacto_de_b_conta_as_aparicoes_de_a_fundida_nela() -> None:
    mundo = Mundo()
    b = mundo.catalogo.acrescentar("Ana Souza Lima", "apresentadora", [])
    # A (ana) foi fundida em B: o Catálogo do Job de j1 já lista B, a Decupagem ainda diz A.
    mundo.catalogo.definir_fusao(
        mundo.ana.id,
        FusaoDaPessoa(
            destino_id=b.id, em=BASE, por_uid="u1", por_email="a@r.com", motivo="x"
        ),
    )
    mundo.jobs.salvar(_job("j1", pessoas_do_catalogo=[b.id]))

    impacto = mundo.cliente.get(f"{LIXEIRA}/pessoas/{b.id}/impacto", headers=CURADOR)

    # j1 só tem o rosto como fonte (2 aparições); j2 não lista B.
    assert impacto.json()["aparicoes_que_perdem_o_nome"] == 2


def test_curador_manda_para_a_lixeira_mas_nao_restaura_nem_purga() -> None:
    mundo = Mundo()
    assert mundo.enviar("pessoas", mundo.ana.id).status_code == 201

    restaurar = mundo.cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/restaurar", headers=CURADOR
    )
    purgar = mundo.cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/purgar",
        json={"nome": "Ana Souza"},
        headers=CURADOR,
    )

    assert (restaurar.status_code, purgar.status_code) == (403, 403)
    assert mundo.enviar("marcas", mundo.marca.id, EDITOR).status_code == 403


def test_marca_na_lixeira_perde_o_vinculo_e_mantem_o_texto() -> None:
    mundo = Mundo()

    assert mundo.enviar("marcas", mundo.marca.id).status_code == 201

    lida = mundo.cliente.get("/v1/jobs/j1/decupagem", headers=ADMIN).json()
    comercial = lida["comerciais"][0]
    assert comercial["marca"] == "Acme"
    assert comercial.get("catalogo_id") is None
    assert mundo.marcas.achar("acme") == []


def _relatorio(textos: dict[str, list[str]]) -> ConsultaEmMemoria:
    """Uma inserção comercial por texto, em cada vídeo: o que o relatório de marcas lê."""
    copia = CopiaEmMemoria()
    for job, marcas in textos.items():
        copia.gravar(
            job,
            [
                LinhaDoMomento(
                    job_id=job,
                    programa="Jornal",
                    data_de_exibicao=None,
                    tipo="comercial",
                    inicio_ms=i * 10,
                    fim_ms=i * 10 + 5,
                    marca=m,
                    tipo_de_insercao="intervalo",
                )
                for i, m in enumerate(marcas)
            ],
        )
    return ConsultaEmMemoria(copia)


def _impacto_da_marca(mundo: Mundo) -> dict[str, Any]:
    resposta = mundo.cliente.get(
        f"{LIXEIRA}/marcas/{mundo.marca.id}/impacto", headers=CURADOR
    )
    assert resposta.status_code == 200
    impacto: dict[str, Any] = resposta.json()
    return impacto


def test_o_impacto_da_marca_conta_as_insercoes_do_relatorio_pelo_nome_e_pelo_apelido() -> (
    None
):
    mundo = Mundo(
        _relatorio(
            {
                "j1": ["Acme", "Outra"],  # j1 tem o vínculo e o nome: conta uma vez
                "j2": ["ACME  Ltda", "Acme"],  # o apelido e o nome, sem o vínculo
                "j3": ["Acmé"],  # só o texto, em vídeo sem vínculo nenhum
            }
        )
    )
    mundo.marca.apelidos.append("Acme Ltda")

    impacto = _impacto_da_marca(mundo)

    assert impacto["insercoes_que_saem_do_relatorio"] == 4
    assert impacto["ocorrencias_que_perdem_o_vinculo"] == 2  # o sentido de antes


def test_a_contagem_nova_vale_na_lixeira_e_sem_relatorio_configurado() -> None:
    mundo = Mundo(_relatorio({"j1": ["Acme"]}))
    mundo.enviar("marcas", mundo.marca.id)

    # O relatório já não conta a marca; a contagem do que saiu, sim.
    assert _impacto_da_marca(mundo)["insercoes_que_saem_do_relatorio"] == 1
    assert _impacto_da_marca(Mundo())["insercoes_que_saem_do_relatorio"] == 0


def test_a_contagem_nova_respeita_o_corte_da_purga_da_homonima() -> None:
    purgas = PurgasDeMarcaEmMemoria()
    purgas.gravar(MarcaDoCatalogo(id="antiga", nome="Acme"), BASE + timedelta(days=5))
    mundo = Mundo(_relatorio({"j1": ["Acme"], "j2": ["Acme"], "j3": ["Acme"]}), purgas)
    # j1 e j2 são anteriores à purga e já não contam; j3, criado depois, conta.
    mundo.jobs.salvar(_job("j3", criado_em=BASE + timedelta(days=6)))

    assert _impacto_da_marca(mundo)["insercoes_que_saem_do_relatorio"] == 1


def test_a_auditoria_grava_a_contagem_nova_no_envio_e_na_restauracao() -> None:
    mundo = Mundo(_relatorio({"j1": ["Acme"], "j2": ["Acme"]}))

    mundo.enviar("marcas", mundo.marca.id)
    mundo.cliente.post(f"{LIXEIRA}/marcas/{mundo.marca.id}/restaurar", headers=ADMIN)

    marcas = [r.detalhes for r in mundo.registros() if r.alvo_tipo == "marca"]
    assert [d["insercoes_que_saem_do_relatorio"] for d in marcas] == [2, 2]


def test_a_lista_traz_os_tres_tipos_e_cada_acao_grava_auditoria() -> None:
    mundo = Mundo()
    mundo.enviar("pessoas", mundo.ana.id)
    mundo.enviar("marcas", mundo.marca.id)
    mundo.cliente.post(f"{LIXEIRA}/videos/j1", json={"motivo": "x"}, headers=ADMIN)

    itens = mundo.cliente.get(LIXEIRA, headers=ADMIN).json()

    assert sorted(i["tipo"] for i in itens) == ["marca", "pessoa", "video"]
    assert sorted(r.alvo_tipo for r in mundo.registros()) == [
        "marca",
        "pessoa",
        "video",
    ]


def test_purga_manual_apaga_a_pessoa_e_deixa_o_registro() -> None:
    mundo = Mundo()
    mundo.enviar("pessoas", mundo.ana.id)
    rota = f"{LIXEIRA}/pessoas/{mundo.ana.id}/purgar"

    errada = mundo.cliente.post(rota, json={"nome": "Outra"}, headers=ADMIN)
    certa = mundo.cliente.post(rota, json={"nome": "Ana Souza"}, headers=ADMIN)

    assert (errada.status_code, certa.status_code) == (422, 200)
    assert mundo.catalogo.obter(mundo.ana.id) is None
    assert mundo.pessoa_em("j2")["nome"] == "Ana Souza"
    # O relógio é fixo: os registros empatam na data, então a ordem não vale.
    assert sorted(r.acao for r in mundo.registros()) == [
        "item.para_lixeira",
        "item.purgado",
    ]
    purgado = next(r for r in mundo.registros() if r.acao == "item.purgado")
    assert purgado.detalhes["aparicoes_que_perdem_o_nome"] == 2


def test_restaurar_grava_os_numeros_do_impacto() -> None:
    mundo = Mundo()
    mundo.enviar("pessoas", mundo.ana.id)
    mundo.enviar("marcas", mundo.marca.id)

    mundo.cliente.post(f"{LIXEIRA}/pessoas/{mundo.ana.id}/restaurar", headers=ADMIN)
    mundo.cliente.post(f"{LIXEIRA}/marcas/{mundo.marca.id}/restaurar", headers=ADMIN)

    detalhes = {
        r.alvo_tipo: r.detalhes
        for r in mundo.registros()
        if r.acao == "item.restaurado"
    }
    assert detalhes["pessoa"]["aparicoes_que_perdem_o_nome"] == 2
    assert detalhes["pessoa"]["fotos_apagadas"] == 0
    assert detalhes["marca"]["ocorrencias_que_perdem_o_vinculo"] == 2


def test_purga_automatica_aos_30_dias() -> None:
    mundo = Mundo()
    mundo.enviar("pessoas", mundo.ana.id)
    mundo.enviar("marcas", mundo.marca.id)

    antes = purgar_catalogo_vencido(
        mundo.catalogo,
        mundo.marcas,
        mundo.auditoria,
        BASE + timedelta(days=29),
        PurgasDeMarcaEmMemoria(),
    )
    depois = purgar_catalogo_vencido(
        mundo.catalogo,
        mundo.marcas,
        mundo.auditoria,
        BASE + timedelta(days=30),
        PurgasDeMarcaEmMemoria(),
    )

    assert (antes, depois) == (0, 2)
    assert mundo.catalogo.obter(mundo.ana.id) is None
    assert mundo.marcas.obter(mundo.marca.id) is None


def test_pessoa_na_lixeira_sai_da_copia_do_catalogo_na_hora() -> None:
    mundo = Mundo()

    def autocompletar() -> list[str]:
        achadas = mundo.cliente.get(
            "/v1/catalogo/pessoas", params={"q": "ana"}, headers=CURADOR
        ).json()
        return [p["id"] for p in achadas]

    assert autocompletar() == [mundo.ana.id]  # a cópia é lida aqui

    mundo.enviar("pessoas", mundo.ana.id)
    assert autocompletar() == []

    mundo.cliente.post(f"{LIXEIRA}/pessoas/{mundo.ana.id}/restaurar", headers=ADMIN)
    assert autocompletar() == [mundo.ana.id]
