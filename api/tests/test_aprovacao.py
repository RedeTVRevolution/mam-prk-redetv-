from typing import Any

from api.correcoes import (
    aplicar,
    historico,
)
from api.tests.test_correcoes import AUTORIZACAO, MODELO, VERSAO, Mundo

CURADOR = {"Authorization": "Bearer token-curador"}


def _mundo_com_aprovacao(*tipos: str) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.aprovacao.definir(frozenset(tipos))
    return mundo


def _aprovar(mundo: Mundo, cid: str, headers: dict[str, str] = CURADOR) -> Any:
    return mundo.cliente.post(f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=headers)


def _recusar(
    mundo: Mundo,
    cid: str,
    motivo: str = "não confere",
    headers: dict[str, str] = CURADOR,
) -> Any:
    return mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{cid}/recusar", json={"motivo": motivo}, headers=headers
    )


def _estados(mundo: Mundo) -> dict[str, str]:
    return {i["id"]: i["estado"] for i in mundo.historico().json()}


def test_lista_vazia_nada_muda_e_a_correcao_entra_direto() -> None:
    mundo = Mundo(["editor"])

    mundo.corrigir()

    assert mundo.nome_da_ana() == "Ana Souza Lima"
    [item] = mundo.historico().json()
    assert item["estado"] == "ativa"


def test_editor_com_o_tipo_na_lista_fica_pendente_e_fora_da_decupagem() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")

    cid = mundo.corrigir().json()["id"]

    assert mundo.nome_da_ana() == "Ana Souza"
    assert _estados(mundo) == {cid: "pendente"}


def test_tipo_fora_da_lista_entra_direto() -> None:
    mundo = _mundo_com_aprovacao("pauta.titulo")

    mundo.corrigir()

    assert mundo.nome_da_ana() == "Ana Souza Lima"


def test_correcao_do_curador_entra_direto() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")

    resposta = mundo.cliente.post(
        "/v1/jobs/j1/correcoes",
        json={
            "tipo": "pessoa.renomear",
            "item_id": "pes01",
            "valor": "Ana Souza Lima",
            "motivo": "sobrenome",
            "versao": VERSAO,
        },
        headers=CURADOR,
    )

    assert resposta.status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza Lima"
    assert list(_estados(mundo).values()) == ["ativa"]


def test_aprovar_poe_na_decupagem_e_registra_quem_e_quando() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]
    mundo.avancar()

    resposta = _aprovar(mundo, cid)

    assert resposta.status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza Lima"
    assert _estados(mundo)[cid] == "aprovada"
    decisao = next(c for c in mundo.correcoes.listar("j1") if c.aprova == cid)
    assert (decisao.tipo, decisao.autor_uid, decisao.autor_email) == (
        "aprovar",
        "u2",
        "cura@redetv.com.br",
    )
    assert decisao.criada_em == mundo.agora


def test_recusar_mantem_fora_com_o_motivo_no_historico() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]

    resposta = _recusar(mundo, cid, "não confere")

    assert resposta.status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza"
    historico_ = {i["id"]: i for i in mundo.historico().json()}
    assert historico_[cid]["estado"] == "recusada"
    [recusa] = [i for i in historico_.values() if i["tipo"] == "recusar"]
    assert recusa["motivo"] == "não confere"
    assert recusa["recusa"] == cid


def test_editor_tentando_aprovar_ou_recusar_recebe_403() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]

    assert _aprovar(mundo, cid, AUTORIZACAO).status_code == 403
    assert _recusar(mundo, cid, headers=AUTORIZACAO).status_code == 403
    assert mundo.nome_da_ana() == "Ana Souza"


def test_chave_de_sistema_nao_aprova() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]

    resposta = _aprovar(mundo, cid, mundo.chave_com_todos_os_escopos())

    assert resposta.status_code == 403


def test_correcao_inexistente_dá_404() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")

    assert _aprovar(mundo, "nao-existe").status_code == 404


def test_decidir_duas_vezes_ou_o_que_nao_e_pendente_dá_409() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    pendente = mundo.corrigir().json()["id"]
    _aprovar(mundo, pendente)
    mundo.aprovacao.definir(frozenset())
    direta = mundo.corrigir(valor="Ana S. Lima").json()["id"]

    assert _aprovar(mundo, pendente).status_code == 409
    assert _recusar(mundo, pendente).status_code == 409
    assert _aprovar(mundo, direta).status_code == 409


def test_recusa_sem_motivo_dá_422() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]

    resposta = _recusar(mundo, cid, motivo="  ")

    assert resposta.status_code == 422


def test_pendente_nao_se_desfaz() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]

    assert mundo.desfazer(cid).status_code == 409


def test_aprovada_se_desfaz_como_qualquer_outra() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]
    _aprovar(mundo, cid)

    assert mundo.desfazer(cid).status_code == 201
    assert mundo.nome_da_ana() == "Ana Souza"


def test_pendente_mais_nova_nao_derruba_a_direta_anterior() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir(valor="Ana A")
    mundo.avancar()
    mundo.aprovacao.definir(frozenset({"pessoa.renomear"}))

    mundo.corrigir(valor="Ana B")

    assert mundo.nome_da_ana() == "Ana A"


def test_pendente_aprovada_depois_de_reprocessar_passa_pela_reconciliacao() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    cid = mundo.corrigir().json()["id"]
    mundo.reprocessar({**MODELO, "pautas": MODELO["pautas"][:1]})
    mundo.avancar()
    assert mundo.nome_da_ana() == "Ana Souza"

    _aprovar(mundo, cid)

    assert mundo.nome_da_ana() == "Ana Souza Lima"
    assert mundo.decupagem()["pessoas"][0]["origem"] == "revisao"


def test_pendente_de_versao_antiga_nao_entra_na_fila() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    mundo.corrigir()
    sem_ana = {**MODELO, "pessoas": MODELO["pessoas"][1:]}
    mundo.reprocessar(sem_ana)

    fila = mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json()

    assert fila == []


def _aprovada_que_foi_para_a_fila() -> tuple[Mundo, str]:
    """Correção do Editor aprovada e, depois de um reprocessamento, sem casar."""
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    original = mundo.corrigir().json()["id"]
    mundo.avancar()
    assert _aprovar(mundo, original).status_code == 201
    mundo.reprocessar(
        {
            **MODELO,
            "pessoas": [
                {**MODELO["pessoas"][0], "nome": "Anna S.", "id": "pes07"},
                *MODELO["pessoas"][1:],
            ],
        }
    )
    mundo.avancar()
    return mundo, original


def test_reaplicar_a_aprovada_nao_pede_nova_aprovacao() -> None:
    mundo, original = _aprovada_que_foi_para_a_fila()

    resposta = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{original}/reaplicar",
        json={"item_id": "pes07", "motivo": "é a mesma"},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 201
    estados = _estados(mundo)
    assert estados[resposta.json()["id"]] == "ativa"
    assert mundo.decupagem()["pessoas"][0]["nome"] == "Ana Souza Lima"
    # A aprovada que saiu da fila não mostra mais "aprovada" nem oferece desfazer.
    assert estados[original] == "reaplicada"


def test_descartar_a_aprovada_mostra_descartada() -> None:
    mundo, original = _aprovada_que_foi_para_a_fila()

    assert (
        mundo.cliente.post(
            f"/v1/jobs/j1/fila/{original}/descartar",
            json={"motivo": "não vale mais"},
            headers=AUTORIZACAO,
        ).status_code
        == 201
    )
    assert _estados(mundo)[original] == "descartada"


def test_reaplicacao_do_editor_nao_espera_aprovacao() -> None:
    mundo = Mundo(["editor"])
    original = mundo.corrigir().json()["id"]
    sem_ana = {
        **MODELO,
        "pessoas": [
            {**MODELO["pessoas"][0], "nome": "Anna S.", "id": "pes07"},
            *MODELO["pessoas"][1:],
        ],
    }
    mundo.reprocessar(sem_ana)
    mundo.aprovacao.definir(frozenset({"pessoa.renomear"}))
    mundo.avancar()

    resposta = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{original}/reaplicar",
        json={"item_id": "pes07", "motivo": "é a mesma"},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 201
    assert mundo.decupagem()["pessoas"][0]["nome"] == "Ana Souza Lima"
    assert _estados(mundo)[resposta.json()["id"]] == "ativa"


def test_aplicar_puro_ignora_pendente_e_recusada() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    mundo.corrigir()
    [c] = mundo.correcoes.listar("j1")

    assert c.exige_aprovacao
    assert aplicar(MODELO, VERSAO, [c])["pessoas"][0]["nome"] == "Ana Souza"
    assert [i.estado for i in historico([c])] == ["pendente"]


def test_aprovada_vale_a_partir_da_aprovacao_sobre_a_feita_enquanto_esperava() -> None:
    mundo = _mundo_com_aprovacao("pessoa.renomear")
    pendente = mundo.corrigir().json()["id"]
    mundo.avancar()
    assert (
        mundo.cliente.post(
            "/v1/jobs/j1/correcoes",
            json={
                "tipo": "pessoa.renomear",
                "item_id": "pes01",
                "valor": "Ana S.",
                "motivo": "abreviar",
                "versao": VERSAO,
            },
            headers=CURADOR,
        ).status_code
        == 201
    )
    assert mundo.nome_da_ana() == "Ana S."
    mundo.avancar()

    assert _aprovar(mundo, pendente).status_code == 201

    assert mundo.nome_da_ana() == "Ana Souza Lima"
