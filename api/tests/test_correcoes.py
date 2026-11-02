import json
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.catalogo import CatalogoEmMemoria
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.correcoes import (
    TIPOS,
    Autoria,
    Correcao,
    CorrecaoJaExiste,
    ItemInexistente,
    NaoCandidato,
    NaoNaFila,
    NovaCorrecao,
    RepositorioDeAprovacaoEmMemoria,
    RepositorioDeCorrecoesEmMemoria,
    TipoNovo,
    aplicar,
    corrigir,
    descartar,
    fila,
    historico,
    identidade_da_pessoa,
    reaplicar,
    reconciliar,
    versao_do_modelo,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.marcas import CatalogoDeMarcasEmMemoria
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}
MAC = MacSimulado({1: b"k1"}, versao_atual=1)


def _pessoa(id: str, nome: str, inicio: int, fim: int) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "origem": "modelo",
        "na_imagem": [{"inicio_ms": inicio, "fim_ms": fim, "evidencia": "rosto"}],
        "citada_na_fala": [{"inicio_ms": fim + 5, "fim_ms": fim + 9}],
        "citada_no_texto": [],
    }


def _pauta(id: str, titulo: str, inicio: int, fim: int) -> dict[str, Any]:
    return {
        "id": id,
        "titulo": titulo,
        "resumo": f"Resumo de {titulo}",
        "inicio_ms": inicio,
        "fim_ms": fim,
        "pessoas": [],
        "locais": [],
    }


MODELO: dict[str, Any] = {
    "versao_esquema": "1.2",
    "video": {"duracao_ms": 60000},
    "pautas": [
        _pauta("pau01", "Economia", 0, 20000),
        _pauta("pau02", "Esporte", 20000, 50000),
    ],
    "pessoas": [
        _pessoa("pes01", "Ana Souza", 1000, 5000),
        _pessoa("pes02", "não identificado", 7000, 9000),
    ],
}
BYTES = json.dumps(MODELO).encode()
VERSAO = versao_do_modelo(BYTES)


def _novo(**campos: Any) -> dict[str, Any]:
    return {
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "valor": "Ana Souza Lima",
        "motivo": "sobrenome completo",
        "versao": VERSAO,
        **campos,
    }


class Mundo:
    def __init__(self, papeis: list[Papel], estado: str = "concluido") -> None:
        repo_papeis = RepositorioDePapeisEmMemoria()
        repo_papeis.salvar("u1", papeis)
        repo_papeis.salvar("u2", ["curador"])
        jobs = RepositorioEmMemoria()
        jobs.salvar(
            Job(
                id="j1",
                nome="a.mp4",
                tamanho_bytes=10,
                estado=estado,  # type: ignore[arg-type]
                criado_por="u1",
                criado_em=BASE,
                atualizado_em=BASE,
            )
        )
        self.armazenamento = ArmazenamentoFalso()
        self.armazenamento.decupagens["j1"] = [BYTES[:40], BYTES[40:]]
        self.correcoes = RepositorioDeCorrecoesEmMemoria()
        self.aprovacao = RepositorioDeAprovacaoEmMemoria()
        self.chaves = RepositorioDeChavesEmMemoria()
        self.catalogo = CatalogoEmMemoria()
        self.marcas = CatalogoDeMarcasEmMemoria()
        self.agora = BASE
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "token-bom": Usuario(uid="u1", email="ana@redetv.com.br"),
                        "token-curador": Usuario(uid="u2", email="cura@redetv.com.br"),
                    }
                ),
                jobs,
                self.armazenamento,
                papeis=repo_papeis,
                correcoes=self.correcoes,
                aprovacao=self.aprovacao,
                catalogo=self.catalogo,
                marcas=self.marcas,
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
                relogio=lambda: self.agora,
            )
        )

    def chave_com_todos_os_escopos(self) -> dict[str, str]:
        emitida = emitir_chave(
            "A", frozenset({"criar", "ler", "cancelar"}), MAC, self.chaves, BASE
        )
        return {"X-API-Key": emitida.chave}

    def corrigir(self, **campos: Any) -> Any:
        return self.cliente.post(
            "/v1/jobs/j1/correcoes", json=_novo(**campos), headers=AUTORIZACAO
        )

    def reprocessar(self, modelo: dict[str, Any]) -> None:
        """Simula o reprocessamento: um novo JSON do modelo no armazenamento."""
        self.armazenamento.decupagens["j1"] = [json.dumps(modelo).encode()]

    def avancar(self, minutos: int = 1) -> None:
        self.agora += timedelta(minutes=minutos)

    def desfazer(self, cid: str, motivo: str = "enganei-me") -> Any:
        return self.cliente.post(
            f"/v1/jobs/j1/correcoes/{cid}/desfazer",
            json={"motivo": motivo},
            headers=AUTORIZACAO,
        )

    def historico(self) -> Any:
        return self.cliente.get("/v1/jobs/j1/correcoes", headers=AUTORIZACAO)

    def nome_da_ana(self) -> str:
        return str(self.decupagem()["pessoas"][0]["nome"])

    def decupagem(self, params: str = "") -> dict[str, Any]:
        resposta = self.cliente.get(
            f"/v1/jobs/j1/decupagem{params}", headers=AUTORIZACAO
        )
        corpo: dict[str, Any] = resposta.json()
        return corpo


def test_identidade_da_pessoa_e_o_nome_normalizado_ou_o_intervalo_se_nao_identificado() -> (
    None
):
    assert identidade_da_pessoa(_pessoa("a", "  ANA  Sôuza", 1, 2)) == "ana souza"
    assert (
        identidade_da_pessoa(_pessoa("b", "Não identificado", 7000, 9000))
        == "nao identificado@7000-9000"
    )


def test_aplicar_sem_correcoes_marca_tudo_como_modelo_e_nao_altera_o_original() -> None:
    entregue = aplicar(MODELO, VERSAO, [])

    assert [p["origem"] for p in entregue["pessoas"]] == ["modelo", "modelo"]
    assert entregue["pessoas"][0]["nome"] == "Ana Souza"
    assert MODELO["pessoas"][0]["origem"] == "modelo"


def test_montar_correcao_de_item_inexistente_levanta() -> None:
    with pytest.raises(ItemInexistente):
        corrigir(
            MODELO,
            VERSAO,
            [],
            NovaCorrecao(**_novo(item_id="pes99")),
            "j1",
            _AUTORIA,
        )


def test_renomear_grava_autor_data_motivo_antes_depois_e_ancora() -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.corrigir()

    assert resposta.status_code == 201
    [c] = mundo.correcoes.listar("j1")
    assert (c.autor_uid, c.autor_email, c.criada_em) == (
        "u1",
        "ana@redetv.com.br",
        BASE,
    )
    assert (c.motivo, c.tipo, c.antes, c.depois) == (
        "sobrenome completo",
        "pessoa.renomear",
        "Ana Souza",
        "Ana Souza Lima",
    )
    assert c.ancora.model_dump() == {
        "versao": VERSAO,
        "tipo_do_item": "pessoa",
        "identidade": "ana souza",
        "inicio_ms": 1000,
        "fim_ms": 5009,
    }


def test_decupagem_mostra_o_nome_novo_com_origem_revisao_e_o_modelo_continua_cru() -> (
    None
):
    mundo = Mundo(["editor"])
    mundo.corrigir()

    entregue = mundo.decupagem()
    cru = mundo.decupagem("?versao=modelo")

    assert entregue["versao_decupagem"] == VERSAO
    assert [(p["nome"], p["origem"]) for p in entregue["pessoas"]] == [
        ("Ana Souza Lima", "revisao"),
        ("não identificado", "modelo"),
    ]
    assert cru == MODELO


def test_segunda_correcao_guarda_o_nome_corrigido_como_antes() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    mundo.avancar()
    mundo.corrigir(valor="Ana S. Lima", motivo="abreviar")

    antes = [c.antes for c in mundo.correcoes.listar("j1")]
    assert antes == ["Ana Souza", "Ana Souza Lima"]
    assert mundo.decupagem()["pessoas"][0]["nome"] == "Ana S. Lima"


def test_renomear_pessoa_nao_identificada_casa_pelo_intervalo() -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(item_id="pes02", valor="Bia Reis").status_code == 201

    [c] = mundo.correcoes.listar("j1")
    assert (c.ancora.identidade, c.ancora.inicio_ms, c.ancora.fim_ms) == (
        "nao identificado@7000-9000",
        7000,
        9009,
    )
    assert [p["nome"] for p in mundo.decupagem()["pessoas"]] == [
        "Ana Souza",
        "Bia Reis",
    ]


def test_versao_desatualizada_da_409_e_nada_e_gravado() -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(versao="0" * 64).status_code == 409
    assert mundo.correcoes.listar("j1") == []


def test_job_nao_concluido_da_409() -> None:
    assert Mundo(["editor"], estado="analisando").corrigir().status_code == 409


@pytest.mark.parametrize("papeis", [["consulta"], ["operador"], []])
def test_sem_decupagem_editar_da_403(papeis: list[Papel]) -> None:
    mundo = Mundo(papeis)

    assert mundo.corrigir().status_code == 403
    assert mundo.correcoes.listar("j1") == []


def test_curador_tambem_corrige() -> None:
    assert Mundo(["curador"]).corrigir().status_code == 201


def test_sem_token_da_401() -> None:
    resposta = Mundo(["editor"]).cliente.post("/v1/jobs/j1/correcoes", json=_novo())
    assert resposta.status_code == 401


def test_item_inexistente_da_422() -> None:
    assert Mundo(["editor"]).corrigir(item_id="pes99").status_code == 422


@pytest.mark.parametrize(
    "campos",
    [
        {"valor": ""},
        {"valor": "   "},
        {"valor": "x" * 201},
        {"valor": "Ana\x00"},
        {"valor": "Ana\nSouza"},
        {"motivo": ""},
        {"motivo": "x" * 501},
        {"motivo": "a\x1bb"},
        {"valor": "A\x85na"},
        {"valor": "Ana\u202eazuoS"},
        {"valor": "A\u200bna"},
        {"motivo": "a\u2028b"},
        {"motivo": "a\rb"},
        {"tipo": "pessoa.apagar"},
    ],
)
def test_entrada_hostil_da_422(campos: dict[str, Any]) -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(**campos).status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_motivo_aceita_quebra_de_linha() -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(motivo="sobrenome\r\ncompleto").status_code == 201
    assert mundo.correcoes.listar("j1")[0].motivo == "sobrenome\ncompleto"


def test_identidade_do_nao_identificado_ignora_as_mencoes() -> None:
    pessoa = _pessoa("b", "não identificado", 7000, 9000)
    pessoa["citada_na_fala"] = [{"inicio_ms": 100, "fim_ms": 20000}]

    assert identidade_da_pessoa(pessoa) == "nao identificado@7000-9000"


def _corrigir_duas_vezes(mundo: "Mundo") -> tuple[str, str]:
    primeira = mundo.corrigir(valor="Ana S.").json()["id"]
    mundo.avancar()
    segunda = mundo.corrigir(valor="Ana Souza Lima").json()["id"]
    mundo.avancar()
    return str(primeira), str(segunda)


def test_historico_lista_da_mais_recente_para_a_mais_antiga_com_antes_depois_e_motivo() -> (
    None
):
    mundo = Mundo(["editor"])
    primeira, segunda = _corrigir_duas_vezes(mundo)

    resposta = mundo.historico()

    assert resposta.status_code == 200
    itens = resposta.json()
    assert [i["id"] for i in itens] == [segunda, primeira]
    assert (itens[0]["antes"], itens[0]["depois"]) == ("Ana S.", "Ana Souza Lima")
    assert (itens[1]["antes"], itens[1]["depois"]) == ("Ana Souza", "Ana S.")
    assert itens[0]["motivo"] == "sobrenome completo"
    assert itens[0]["autor_email"] == "ana@redetv.com.br"
    assert itens[0]["tipo"] == "pessoa.renomear"
    assert itens[0]["item_id"] == "pes01"
    assert itens[0]["estado"] == "ativa"
    assert itens[0]["criada_em"].startswith("2026-10-30T12:01")


def test_historico_sem_decupagem_editar_da_403() -> None:
    assert Mundo(["consulta"]).historico().status_code == 403


def test_desfazer_devolve_o_nome_anterior_e_as_duas_entradas_ficam_no_historico() -> (
    None
):
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.avancar()

    resposta = mundo.desfazer(cid, "erro meu")

    assert resposta.status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza"
    assert mundo.decupagem()["pessoas"][0]["origem"] == "modelo"
    itens = mundo.historico().json()
    assert [i["tipo"] for i in itens] == ["desfazer", "pessoa.renomear"]
    assert itens[0]["motivo"] == "erro meu"
    assert itens[0]["desfaz"] == cid
    assert (itens[0]["antes"], itens[0]["depois"]) == ("Ana Souza Lima", "Ana Souza")
    assert itens[1]["estado"] == "desfeita"
    assert itens[0]["estado"] == "ativa"


def test_desfazer_a_correcao_antiga_mantem_a_mais_nova() -> None:
    mundo = Mundo(["editor"])
    primeira, _ = _corrigir_duas_vezes(mundo)

    assert mundo.desfazer(primeira).status_code == 201

    assert mundo.nome_da_ana() == "Ana Souza Lima"
    [desfazer, *_] = mundo.historico().json()
    # A mais nova continua por cima: o nome entregue não muda.
    assert (desfazer["antes"], desfazer["depois"]) == (
        "Ana Souza Lima",
        "Ana Souza Lima",
    )


def test_desfazer_a_antiga_e_depois_a_nova_volta_ao_modelo_e_o_historico_conta_isso() -> (
    None
):
    mundo = Mundo(["editor"])
    primeira, segunda = _corrigir_duas_vezes(mundo)
    mundo.desfazer(primeira)
    mundo.avancar()

    mundo.desfazer(segunda)

    assert mundo.nome_da_ana() == "Ana Souza"
    ultimo = mundo.historico().json()[0]
    assert (ultimo["antes"], ultimo["depois"]) == ("Ana Souza Lima", "Ana Souza")


def test_desfazer_a_mais_nova_volta_para_a_antiga() -> None:
    mundo = Mundo(["editor"])
    _, segunda = _corrigir_duas_vezes(mundo)

    mundo.desfazer(segunda)

    assert mundo.nome_da_ana() == "Ana S."


def test_nova_correcao_depois_do_desfazer_guarda_o_nome_visivel_como_antes() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.avancar()
    mundo.desfazer(cid)
    mundo.avancar()

    mundo.corrigir(valor="Ana Maria")

    assert mundo.historico().json()[0]["antes"] == "Ana Souza"


def test_desfazer_um_desfazer_da_409() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.desfazer(cid)
    [desfazer] = [c for c in mundo.correcoes.listar("j1") if c.tipo == "desfazer"]

    assert mundo.desfazer(desfazer.id).status_code == 409


def test_desfazer_duas_vezes_a_mesma_correcao_da_409() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.desfazer(cid)

    assert mundo.desfazer(cid).status_code == 409
    assert len(mundo.correcoes.listar("j1")) == 2


def test_dois_desfazer_simultaneos_gravam_um_so() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    antes_do_primeiro = mundo.correcoes.listar("j1")
    # O segundo pedido leu a lista antes de o primeiro gravar.
    mundo.correcoes.listar = lambda job_id: antes_do_primeiro  # type: ignore[method-assign]
    mundo.desfazer(cid)

    assert mundo.desfazer(cid).status_code == 409
    assert len(mundo.correcoes._correcoes) == 2


def test_repositorio_em_memoria_nao_sobrescreve() -> None:
    repo = RepositorioDeCorrecoesEmMemoria()
    mundo = Mundo(["editor"])
    mundo.corrigir()
    [correcao] = mundo.correcoes.listar("j1")
    repo.acrescentar(correcao)

    with pytest.raises(CorrecaoJaExiste):
        repo.acrescentar(correcao.model_copy(update={"depois": "Outro"}))


def test_desfazer_correcao_de_outra_versao_que_nao_casa_da_409() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.reprocessar(
        {**MODELO, "pessoas": [_pessoa("pes01", "Carla Dias", 1000, 5000)]}
    )

    assert mundo.desfazer(cid).status_code == 409
    assert [c.tipo for c in mundo.correcoes.listar("j1")] == ["pessoa.renomear"]


def test_correcoes_com_a_mesma_data_seguem_a_ordem_do_id() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    [base] = mundo.correcoes.listar("j1")
    repo = RepositorioDeCorrecoesEmMemoria()
    empatadas: list[Correcao] = [
        base.model_copy(update={"id": "b", "depois": "Ana B"}),
        base.model_copy(update={"id": "a", "depois": "Ana A"}),
    ]
    for c in empatadas:
        repo.acrescentar(c)

    assert [c.id for c in repo.listar("j1")] == ["a", "b"]
    entregue = aplicar(MODELO, VERSAO, list(reversed(repo.listar("j1"))))
    assert entregue["pessoas"][0]["nome"] == "Ana B"


def test_chave_de_sistema_nao_ve_o_historico_nem_desfaz() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    chave = mundo.chave_com_todos_os_escopos()

    historico = mundo.cliente.get("/v1/jobs/j1/correcoes", headers=chave)
    desfazer = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{cid}/desfazer", json={"motivo": "x"}, headers=chave
    )

    assert (historico.status_code, desfazer.status_code) == (403, 403)


def test_desfazer_correcao_inexistente_da_404() -> None:
    assert Mundo(["editor"]).desfazer("nao-existe").status_code == 404


def test_desfazer_sem_decupagem_editar_da_403() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    sem_permissao = Mundo(["consulta"])
    sem_permissao.correcoes.acrescentar(mundo.correcoes.listar("j1")[0])

    assert sem_permissao.desfazer(cid).status_code == 403


@pytest.mark.parametrize("motivo", ["", "   ", "a" * 501, "x\u202ey"])
def test_desfazer_com_motivo_invalido_da_422(motivo: str) -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]

    assert mundo.desfazer(cid, motivo).status_code == 422


# --- Reconciliação (#59) ---


def _correcao_antiga(
    identidade: str = "ana souza", inicio: int = 1000, fim: int = 5000, **campos: Any
) -> Correcao:
    base: dict[str, Any] = {
        "id": "c1",
        "job_id": "j1",
        "autor_uid": "u1",
        "autor_email": "ana@redetv.com.br",
        "criada_em": BASE,
        "motivo": "sobrenome",
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "antes": "Ana Souza",
        "depois": "Ana Souza Lima",
        "ancora": {
            "versao": "velha",
            "tipo_do_item": "pessoa",
            "identidade": identidade,
            "inicio_ms": inicio,
            "fim_ms": fim,
        },
    }
    return Correcao(**{**base, **campos})


def _modelo_com(*pessoas: dict[str, Any]) -> dict[str, Any]:
    return {"versao_esquema": "1.2", "pessoas": list(pessoas)}


def test_reconciliar_casa_com_um_candidato_e_aponta_para_o_item_novo() -> None:
    novo = _modelo_com(_pessoa("p9", "Ana Souza", 1200, 4800))

    resultado = reconciliar(novo, "nova", [_correcao_antiga()])

    assert [c.item_id for c in resultado.casadas] == ["p9"]
    assert resultado.casadas[0].ancora.versao == "nova"
    assert resultado.sem_casar == []
    assert resultado.atendidas == []


def test_reconciliar_nao_casa_com_zero_candidatos() -> None:
    novo = _modelo_com(_pessoa("p9", "Beto Lima", 1200, 4800))

    resultado = reconciliar(novo, "nova", [_correcao_antiga()])

    assert resultado.casadas == []
    assert [c.id for c in resultado.sem_casar] == ["c1"]


def test_reconciliar_nao_casa_se_o_intervalo_nao_sobrepoe() -> None:
    novo = _modelo_com(_pessoa("p9", "Ana Souza", 20000, 30000))

    assert reconciliar(novo, "nova", [_correcao_antiga()]).casadas == []


def test_reconciliar_nao_casa_com_dois_candidatos() -> None:
    novo = _modelo_com(
        _pessoa("p1", "Ana Souza", 1000, 2000), _pessoa("p2", "Ana Souza", 3000, 4000)
    )

    resultado = reconciliar(novo, "nova", [_correcao_antiga()])

    assert resultado.casadas == []
    assert [c.id for c in resultado.sem_casar] == ["c1"]


def test_reconciliar_correcao_ja_atendida_pela_versao_nova() -> None:
    novo = _modelo_com(_pessoa("p9", "Ana Souza Lima", 1200, 4800))
    antiga = _correcao_antiga()  # o modelo agora já diz o "depois"

    resultado = reconciliar(novo, "nova", [antiga])

    assert resultado.sem_casar == []
    assert [c.id for c in resultado.atendidas] == ["c1"]


def test_reconciliar_nao_identificado_casa_pela_unica_aparicao_sobreposta() -> None:
    antiga = _correcao_antiga(
        identidade="nao identificado@7000-9000",
        inicio=7000,
        fim=9000,
        antes="não identificado",
        depois="Beto Lima",
    )
    novo = _modelo_com(
        _pessoa("p1", "Ana Souza", 1000, 5000),
        _pessoa("p2", "não identificado", 7500, 9500),
    )

    resultado = reconciliar(novo, "nova", [antiga])

    assert [c.item_id for c in resultado.casadas] == ["p2"]


def test_reconciliar_nao_identificado_com_dois_candidatos_nao_casa() -> None:
    antiga = _correcao_antiga(
        identidade="nao identificado@7000-9000", inicio=7000, fim=9000
    )
    novo = _modelo_com(
        _pessoa("p1", "não identificado", 6000, 8000),
        _pessoa("p2", "não identificado", 8500, 9500),
    )

    assert reconciliar(novo, "nova", [antiga]).casadas == []


def test_reconciliar_ignora_correcao_desfeita_e_a_da_versao_atual() -> None:
    novo = _modelo_com(_pessoa("p9", "Ana Souza", 1200, 4800))
    desfeita = _correcao_antiga(id="c1")
    desfazer = _correcao_antiga(id="c1-desfeita", tipo="desfazer", desfaz="c1")
    atual = _correcao_antiga(id="c2")
    atual.ancora.versao = "nova"

    resultado = reconciliar(novo, "nova", [desfeita, desfazer, atual])

    assert resultado.casadas == [] and resultado.sem_casar == []


def test_renomear_troca_o_json_do_modelo_e_o_nome_corrigido_continua() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    nova = {**MODELO, "programa": {"resumo": "reprocessado"}}
    mundo.reprocessar(nova)

    decupagem = mundo.decupagem()

    assert decupagem["pessoas"][0]["nome"] == "Ana Souza Lima"
    assert decupagem["pessoas"][0]["origem"] == "revisao"
    assert decupagem["versao_decupagem"] == versao_do_modelo(json.dumps(nova).encode())


def test_correcao_que_nao_casa_nao_aparece_e_continua_ativa_no_historico() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    nova = {**MODELO, "pessoas": [_pessoa("pes01", "Carla Dias", 1000, 5000)]}
    mundo.reprocessar(nova)

    assert mundo.nome_da_ana() == "Carla Dias"
    itens = mundo.historico().json()
    assert [i["estado"] for i in itens] == ["ativa"]


def test_versao_modelo_entrega_o_json_novo_cru() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    nova = {**MODELO, "programa": {"resumo": "reprocessado"}}
    mundo.reprocessar(nova)

    assert mundo.decupagem("?versao=modelo") == nova


def test_correcao_atendida_entrega_o_nome_como_o_modelo_escreveu() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()
    mundo.reprocessar(
        {**MODELO, "pessoas": [_pessoa("p9", "ANA SOUZA LIMA", 1200, 4800)]}
    )

    pessoa = mundo.decupagem()["pessoas"][0]

    assert (pessoa["nome"], pessoa["origem"]) == ("ANA SOUZA LIMA", "modelo")


def test_desfazer_correcao_reconciliada_volta_ao_nome_do_modelo_novo() -> None:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.reprocessar({**MODELO, "pessoas": [_pessoa("p9", "Ana Souza", 1200, 4800)]})

    assert mundo.desfazer(cid).status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza"
    desfazer = mundo.correcoes.listar("j1")[-1]
    assert (desfazer.item_id, desfazer.antes, desfazer.depois) == (
        "p9",
        "Ana Souza Lima",
        "Ana Souza",
    )


# --- Fila de revisão (#60) ---


_AUTORIA = Autoria("u2", "bia@redetv.com.br", BASE + timedelta(hours=1))


def test_fila_lista_a_que_nao_casou_com_os_candidatos_que_sobrepoem_o_intervalo() -> (
    None
):
    novo = _modelo_com(
        _pessoa("p1", "Carla Dias", 1000, 5000),
        _pessoa("p2", "Davi Lima", 9000, 9500),
    )

    itens = fila(novo, "nova", [_correcao_antiga()])

    assert [i.id for i in itens] == ["c1"]
    assert [(c.item_id, c.nome) for c in itens[0].candidatos] == [("p1", "Carla Dias")]


def test_fila_nao_traz_a_que_casou_nem_a_da_versao_atual() -> None:
    novo = _modelo_com(_pessoa("p9", "Ana Souza", 1200, 4800))
    atual = _correcao_antiga(
        id="c2", ancora=_correcao_antiga().ancora.model_copy(update={"versao": "nova"})
    )

    assert fila(novo, "nova", [_correcao_antiga(), atual]) == []


def test_reaplicar_cria_correcao_na_versao_atual_ligada_a_original() -> None:
    novo = _modelo_com(_pessoa("p1", "Carla Dias", 1000, 5000))
    original = _correcao_antiga()

    nova = reaplicar(
        novo, "nova", [original], original.id, "p1", "é a mesma", "j1", _AUTORIA
    )

    assert (nova.tipo, nova.reaplica, nova.item_id) == ("pessoa.renomear", "c1", "p1")
    assert (nova.antes, nova.depois) == ("Carla Dias", "Ana Souza Lima")
    assert nova.ancora.versao == "nova"
    assert nova.ancora.identidade == "carla dias"
    assert (
        aplicar(novo, "nova", [original, nova])["pessoas"][0]["nome"]
        == "Ana Souza Lima"
    )
    assert fila(novo, "nova", [original, nova]) == []


@pytest.mark.parametrize("item_id", ["zzz", "p2"])
def test_reaplicar_em_quem_nao_e_candidato_levanta(item_id: str) -> None:
    novo = _modelo_com(
        _pessoa("p1", "Carla Dias", 1000, 5000),
        _pessoa("p2", "Davi Lima", 9000, 9500),  # existe, mas fora do intervalo
    )
    original = _correcao_antiga()

    with pytest.raises(NaoCandidato):
        reaplicar(novo, "nova", [original], original.id, item_id, "x", "j1", _AUTORIA)


def test_reaplicar_quem_nao_esta_na_fila_levanta() -> None:
    novo = _modelo_com(_pessoa("p9", "Ana Souza", 1200, 4800))
    original = _correcao_antiga()  # casa, logo não está na fila

    with pytest.raises(NaoNaFila):
        reaplicar(novo, "nova", [original], original.id, "p9", "x", "j1", _AUTORIA)


def test_descartar_tira_da_fila_e_o_historico_marca_descartada() -> None:
    novo = _modelo_com(_pessoa("p1", "Carla Dias", 1000, 5000))
    original = _correcao_antiga()

    descarte = descartar(
        novo, "nova", [original], original.id, "não vale", "j1", _AUTORIA
    )

    assert (descarte.tipo, descarte.descarta) == ("descartar", "c1")
    assert fila(novo, "nova", [original, descarte]) == []
    assert [(i.id, i.estado) for i in historico([original, descarte])] == [
        ("c1-resolvida", "ativa"),
        ("c1", "descartada"),
    ]
    assert (
        aplicar(novo, "nova", [original, descarte])["pessoas"][0]["nome"]
        == "Carla Dias"
    )


def test_descartar_duas_vezes_levanta() -> None:
    novo = _modelo_com(_pessoa("p1", "Carla Dias", 1000, 5000))
    original = _correcao_antiga()
    descarte = descartar(novo, "nova", [original], original.id, "x", "j1", _AUTORIA)

    with pytest.raises(NaoNaFila):
        descartar(novo, "nova", [original, descarte], original.id, "x", "j1", _AUTORIA)


def test_historico_marca_a_original_reaplicada() -> None:
    novo = _modelo_com(_pessoa("p1", "Carla Dias", 1000, 5000))
    original = _correcao_antiga()
    nova = reaplicar(novo, "nova", [original], original.id, "p1", "x", "j1", _AUTORIA)

    estados = {i.id: i.estado for i in historico([original, nova])}

    assert estados == {"c1": "reaplicada", "c1-resolvida": "ativa"}


def _mundo_com_fila() -> tuple["Mundo", str]:
    mundo = Mundo(["editor"])
    cid = mundo.corrigir().json()["id"]
    mundo.avancar()
    mundo.reprocessar({**MODELO, "pessoas": [_pessoa("p1", "Carla Dias", 1000, 5000)]})
    return mundo, cid


def _fila(mundo: "Mundo", headers: dict[str, str] = AUTORIZACAO) -> Any:
    return mundo.cliente.get("/v1/jobs/j1/fila", headers=headers)


def _resolver(mundo: "Mundo", cid: str, acao: str, **corpo: Any) -> Any:
    return mundo.cliente.post(
        f"/v1/jobs/j1/fila/{cid}/{acao}",
        json={"motivo": "revisei", **corpo},
        headers=AUTORIZACAO,
    )


def test_fila_da_api_traz_a_que_nao_casou_com_candidatos() -> None:
    mundo, cid = _mundo_com_fila()

    itens = _fila(mundo).json()

    assert [i["id"] for i in itens] == [cid]
    item = itens[0]
    assert (item["autor_email"], item["motivo"]) == (
        "ana@redetv.com.br",
        "sobrenome completo",
    )
    assert (item["antes"], item["depois"]) == ("Ana Souza", "Ana Souza Lima")
    assert item["ancora"]["identidade"] == "ana souza"
    assert [c["nome"] for c in item["candidatos"]] == ["Carla Dias"]


def test_fila_vazia_sem_reprocessamento() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()

    assert _fila(mundo).json() == []


def test_reaplicar_aplica_na_decupagem_tira_da_fila_e_liga_a_original() -> None:
    mundo, cid = _mundo_com_fila()

    resposta = _resolver(mundo, cid, "reaplicar", item_id="p1")

    assert resposta.status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza Lima"
    assert _fila(mundo).json() == []
    itens = mundo.historico().json()
    assert {i["id"]: i["estado"] for i in itens}[cid] == "reaplicada"
    nova = next(i for i in itens if i["id"] == resposta.json()["id"])
    assert (nova["reaplica"], nova["estado"]) == (cid, "ativa")


def test_reaplicar_pode_ser_desfeita() -> None:
    mundo, cid = _mundo_com_fila()
    nova = _resolver(mundo, cid, "reaplicar", item_id="p1").json()["id"]

    assert mundo.desfazer(nova).status_code == 201
    assert mundo.nome_da_ana() == "Carla Dias"


def test_descartar_tira_da_fila_e_mantem_no_historico_como_descartada() -> None:
    mundo, cid = _mundo_com_fila()

    assert _resolver(mundo, cid, "descartar").status_code == 201

    assert _fila(mundo).json() == []
    assert mundo.nome_da_ana() == "Carla Dias"
    estados = {i["id"]: i["estado"] for i in mundo.historico().json()}
    assert estados[cid] == "descartada"


def test_resolver_duas_vezes_da_409() -> None:
    mundo, cid = _mundo_com_fila()
    _resolver(mundo, cid, "descartar")

    assert _resolver(mundo, cid, "descartar").status_code == 409
    assert _resolver(mundo, cid, "reaplicar", item_id="p1").status_code == 409


def test_reaplicar_item_inexistente_da_422_e_correcao_inexistente_da_404() -> None:
    mundo, cid = _mundo_com_fila()

    assert _resolver(mundo, cid, "reaplicar", item_id="zzz").status_code == 422
    assert _resolver(mundo, "nao-existe", "descartar").status_code == 404
    assert _resolver(mundo, cid, "reaplicar").status_code == 422


def test_descartada_nao_se_desfaz() -> None:
    mundo, cid = _mundo_com_fila()
    descarte = _resolver(mundo, cid, "descartar").json()["id"]

    assert mundo.desfazer(descarte).status_code == 409
    assert mundo.desfazer(cid).status_code == 409


def test_fila_sem_decupagem_editar_da_403_e_chave_de_sistema_tambem() -> None:
    mundo = Mundo(["consulta"])

    assert _fila(mundo).status_code == 403
    assert _resolver(mundo, "c", "descartar").status_code == 403
    assert _fila(mundo, mundo.chave_com_todos_os_escopos()).status_code == 403


# --- Uma entrada por tipo e formato gravado (#132) ---


def test_todo_tipo_novo_tem_entrada_na_tabela() -> None:
    assert [t for t in get_args(TipoNovo) if t not in TIPOS] == []


def test_registros_no_formato_gravado_continuam_sendo_aplicados() -> None:
    # Como o Firestore guarda hoje: `valor` e `depois` em texto, a âncora em dict.
    gravados = [
        {
            "id": "c1",
            "job_id": "j1",
            "autor_uid": "u1",
            "autor_email": "ana@redetv.com.br",
            "criada_em": BASE.isoformat(),
            "motivo": "sobrenome",
            "tipo": "pessoa.renomear",
            "item_id": "pes01",
            "antes": "Ana Souza",
            "depois": "Ana Souza Lima",
            "ancora": {
                "versao": VERSAO,
                "tipo_do_item": "pessoa",
                "identidade": "ana souza",
                "inicio_ms": 1000,
                "fim_ms": 5000,
            },
        },
        {
            "id": "c2",
            "job_id": "j1",
            "autor_uid": "u1",
            "autor_email": "ana@redetv.com.br",
            "criada_em": (BASE + timedelta(minutes=1)).isoformat(),
            "motivo": "tempos",
            "tipo": "item.tempos",
            "item_id": "pau01",
            "antes": "0-20000",
            "depois": "0-18000",
            "ancora": {
                "versao": VERSAO,
                "tipo_do_item": "pauta",
                "identidade": "economia",
                "inicio_ms": 0,
                "fim_ms": 20000,
            },
        },
        {
            "id": "c3",
            "job_id": "j1",
            "autor_uid": "u1",
            "autor_email": "ana@redetv.com.br",
            "criada_em": (BASE + timedelta(minutes=2)).isoformat(),
            "motivo": "faltou o merchan",
            "tipo": "comercial.acrescentar",
            "item_id": "acr-c3",
            "antes": "",
            # O valor em JSON fica em texto, com as chaves em ordem.
            "depois": '{"evidencia": "logo", "fim_ms": 22000, "inicio_ms": 20000, '
            '"marca": "Loja Sol", "tipo": "merchan_apresentador"}',
            "ancora": {
                "versao": VERSAO,
                "tipo_do_item": "comercial",
                "identidade": "loja sol|merchan_apresentador",
                "inicio_ms": 20000,
                "fim_ms": 22000,
            },
        },
    ]

    correcoes = [Correcao.model_validate(g) for g in gravados]
    entregue = aplicar(MODELO, VERSAO, correcoes)

    assert entregue["pessoas"][0]["nome"] == "Ana Souza Lima"
    assert entregue["pessoas"][0]["origem"] == "revisao"
    assert entregue["pautas"][0]["fim_ms"] == 18000
    assert entregue["comerciais"] == [
        {
            "evidencia": "logo",
            "fim_ms": 22000,
            "inicio_ms": 20000,
            "marca": "Loja Sol",
            "tipo": "merchan_apresentador",
            "id": "acr-c3",
            "origem": "revisao",
            "acrescentado": True,
        }
    ]
