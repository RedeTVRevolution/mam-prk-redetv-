"""Correção de pautas (#61): título, resumo e tempos."""

from typing import Any

import pytest

from api.correcoes import (
    Correcao,
    TemposInvalidos,
    aplicar,
    fila,
    montar_reaplicacao,
    reconciliar,
)
from api.tests.test_correcoes import (
    AUTORIZACAO,
    BASE,
    MODELO,
    VERSAO,
    Mundo,
    _pauta,
    _registro,
)


def _corrigir(mundo: Mundo, tipo: str, valor: str, **campos: Any) -> Any:
    return mundo.corrigir(tipo=tipo, item_id="pau01", valor=valor, **campos)


def _pauta_entregue(mundo: Mundo, id: str = "pau01") -> dict[str, Any]:
    return next(p for p in mundo.decupagem()["pautas"] if p["id"] == id)


def test_decupagem_sem_correcao_traz_as_pautas_com_origem_modelo() -> None:
    pautas = Mundo(["editor"]).decupagem()["pautas"]

    assert [p["origem"] for p in pautas] == ["modelo", "modelo"]


def test_corrigir_titulo_resumo_e_tempos_aparece_com_origem_revisao() -> None:
    mundo = Mundo(["editor"])

    assert _corrigir(mundo, "pauta.titulo", "Economia hoje").status_code == 201
    assert _corrigir(mundo, "pauta.resumo", "Novo\nresumo").status_code == 201
    assert _corrigir(mundo, "item.tempos", "2000-18000").status_code == 201

    pauta = _pauta_entregue(mundo)
    assert (pauta["titulo"], pauta["resumo"]) == ("Economia hoje", "Novo\nresumo")
    assert (pauta["inicio_ms"], pauta["fim_ms"]) == (2000, 18000)
    assert pauta["origem"] == "revisao"
    assert _pauta_entregue(mundo, "pau02")["origem"] == "modelo"


def test_correcao_de_pauta_guarda_antes_depois_e_ancora_no_modelo() -> None:
    mundo = Mundo(["editor"])

    _corrigir(mundo, "item.tempos", "2000-18000")

    c = mundo.correcoes.listar("j1")[0]
    assert (c.antes, c.depois) == ("0-20000", "2000-18000")
    assert (c.ancora.tipo_do_item, c.ancora.inicio_ms, c.ancora.fim_ms) == (
        "pauta",
        0,
        20000,
    )
    assert c.ancora.versao == VERSAO


def test_o_modelo_continua_cru_com_a_pauta_corrigida() -> None:
    mundo = Mundo(["editor"])
    _corrigir(mundo, "pauta.titulo", "Economia hoje")

    cru = mundo.decupagem("?versao=modelo")

    assert cru["pautas"][0]["titulo"] == "Economia"
    assert "origem" not in cru["pautas"][0]


@pytest.mark.parametrize(
    "valor", ["18000-2000", "0-60001", "abc", "1000", "-5-10", "1-2-3", "1.5-3"]
)
def test_tempos_invalidos_dao_422_e_nada_e_gravado(valor: str) -> None:
    mundo = Mundo(["editor"])

    assert _corrigir(mundo, "item.tempos", valor).status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_tempos_ate_a_duracao_do_video_passam() -> None:
    assert _corrigir(Mundo(["editor"]), "item.tempos", "0-60000").status_code == 201


@pytest.mark.parametrize(
    "tipo,valor",
    [
        ("pauta.titulo", "x" * 201),
        ("pauta.titulo", "Dois\nlinhas"),
        ("pauta.resumo", "x" * 2001),
        ("pauta.resumo", "a\x00b"),
        ("pauta.resumo", "a\x85b"),
    ],
)
def test_texto_de_pauta_hostil_da_422(tipo: str, valor: str) -> None:
    mundo = Mundo(["editor"])

    assert _corrigir(mundo, tipo, valor).status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_resumo_aceita_ate_2000_caracteres() -> None:
    assert _corrigir(Mundo(["editor"]), "pauta.resumo", "x" * 2000).status_code == 201


def test_resumo_guarda_a_quebra_de_linha_sem_o_retorno_de_carro() -> None:
    mundo = Mundo(["editor"])

    assert _corrigir(mundo, "pauta.resumo", "um\r\ndois").status_code == 201
    assert _pauta_entregue(mundo)["resumo"] == "um\ndois"


def test_pauta_inexistente_da_422() -> None:
    resposta = Mundo(["editor"]).corrigir(
        tipo="pauta.titulo", item_id="pes01", valor="X"
    )

    assert resposta.status_code == 422


def test_pessoa_nao_se_corrige_como_pauta_nem_o_contrario() -> None:
    mundo = Mundo(["editor"])

    assert mundo.corrigir(tipo="pessoa.renomear", item_id="pau01").status_code == 422
    assert (
        mundo.corrigir(tipo="item.tempos", item_id="pes01", valor="0-1").status_code
        == 422
    )


def test_sem_decupagem_editar_da_403_para_pauta() -> None:
    assert _corrigir(Mundo(["consulta"]), "pauta.titulo", "X").status_code == 403


def test_segunda_correcao_da_pauta_guarda_o_valor_corrigido_como_antes() -> None:
    mundo = Mundo(["editor"])
    _corrigir(mundo, "pauta.titulo", "Um")
    mundo.avancar()

    _corrigir(mundo, "pauta.titulo", "Dois")

    assert mundo.correcoes.listar("j1")[1].antes == "Um"


def test_desfazer_correcao_de_pauta_volta_ao_valor_do_modelo() -> None:
    mundo = Mundo(["editor"])
    cid = _corrigir(mundo, "pauta.titulo", "Um").json()["id"]
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    pauta = _pauta_entregue(mundo)
    assert (pauta["titulo"], pauta["origem"]) == ("Economia", "modelo")
    item = mundo.historico().json()[0]
    assert (item["tipo"], item["antes"], item["depois"]) == (
        "desfazer",
        "Um",
        "Economia",
    )


def test_desfazer_uma_correcao_de_titulo_nao_mexe_no_resumo() -> None:
    mundo = Mundo(["editor"])
    titulo = _corrigir(mundo, "pauta.titulo", "Um").json()["id"]
    mundo.avancar()
    _corrigir(mundo, "pauta.resumo", "R")
    mundo.avancar()

    mundo.desfazer(titulo)

    pauta = _pauta_entregue(mundo)
    assert (pauta["titulo"], pauta["resumo"], pauta["origem"]) == (
        "Economia",
        "R",
        "revisao",
    )


# --- Reconciliação ---


def _antiga(
    tipo: str = "pauta.titulo", depois: str = "Economia hoje", **campos: Any
) -> Correcao:
    base: dict[str, Any] = {
        "id": "c1",
        "job_id": "j1",
        "autor_uid": "u1",
        "autor_email": "ana@redetv.com.br",
        "criada_em": BASE,
        "motivo": "m",
        "tipo": tipo,
        "item_id": "pau01",
        "antes": "Economia",
        "depois": depois,
        "ancora": {
            "versao": "velha",
            "tipo_do_item": "pauta",
            "identidade": "economia",
            "inicio_ms": 0,
            "fim_ms": 20000,
        },
    }
    return Correcao(**{**base, **campos})


def _modelo(*pautas: dict[str, Any]) -> dict[str, Any]:
    return {
        "versao_esquema": "1.1",
        "video": {"duracao_ms": 60000},
        "pautas": list(pautas),
        "pessoas": [],
    }


def test_reconciliar_casa_com_a_mesma_pauta_deslocada_alguns_segundos() -> None:
    novo = _modelo(_pauta("n9", "Economia e mercado", 3000, 24000))

    r = reconciliar(novo, "nova", [_antiga()])

    assert [(c.id, c.item_id, c.ancora.versao) for c in r.casadas] == [
        ("c1", "n9", "nova")
    ]
    assert aplicar(novo, "nova", [_antiga()])["pautas"][0]["titulo"] == "Economia hoje"
    assert aplicar(novo, "nova", [_antiga()])["pautas"][0]["origem"] == "revisao"


def test_reconciliar_tempos_aplica_os_tempos_corrigidos_na_pauta_nova() -> None:
    novo = _modelo(_pauta("n9", "Economia", 3000, 24000))

    entregue = aplicar(novo, "nova", [_antiga("item.tempos", "2000-18000")])

    assert (entregue["pautas"][0]["inicio_ms"], entregue["pautas"][0]["fim_ms"]) == (
        2000,
        18000,
    )


def test_pauta_que_virou_duas_vai_para_a_fila_e_nao_se_aplica() -> None:
    novo = _modelo(
        _pauta("n1", "Economia A", 0, 10000), _pauta("n2", "Economia B", 10000, 20000)
    )
    antiga = _antiga()

    assert reconciliar(novo, "nova", [antiga]).sem_casar == [antiga]
    assert aplicar(novo, "nova", [antiga])["pautas"][0]["titulo"] == "Economia A"
    itens = fila(novo, "nova", [antiga])
    assert [(c.item_id, c.nome) for c in itens[0].candidatos] == [
        ("n1", "Economia A"),
        ("n2", "Economia B"),
    ]


def test_sobreposicao_menor_que_metade_do_menor_nao_casa() -> None:
    # sobrepõe 2s de 20s: bem menos que a metade do menor.
    novo = _modelo(_pauta("n1", "Outra", 18000, 40000))

    assert reconciliar(novo, "nova", [_antiga()]).sem_casar != []


def test_pauta_curta_dentro_da_ancorada_casa_pela_metade_do_menor() -> None:
    novo = _modelo(_pauta("n1", "Curta", 2000, 8000))  # 6s dentro: 100% do menor

    assert [c.item_id for c in reconciliar(novo, "nova", [_antiga()]).casadas] == ["n1"]


def test_pauta_de_um_instante_casa_com_a_que_a_contem() -> None:
    antiga = _antiga("item.tempos", "5000-5000")
    antiga = antiga.model_copy(
        update={
            "ancora": antiga.ancora.model_copy(
                update={"inicio_ms": 5000, "fim_ms": 5000}
            )
        }
    )
    novo = _modelo(_pauta("n1", "Economia", 3000, 9000))

    assert [c.item_id for c in reconciliar(novo, "nova", [antiga]).casadas] == ["n1"]


def test_reaplicar_tempos_alem_da_duracao_do_video_novo_e_recusado() -> None:
    novo = {
        **_modelo(_pauta("n1", "A", 0, 10000), _pauta("n2", "B", 10000, 20000)),
        "video": {"duracao_ms": 20000},
    }
    original = _antiga("item.tempos", "0-30000")

    with pytest.raises(TemposInvalidos):
        montar_reaplicacao(
            novo, "nova", original, [original], "n2", "é B", **_registro()
        )


def test_reaplicar_pauta_na_fila_escolhe_um_candidato() -> None:
    novo = _modelo(
        _pauta("n1", "Economia A", 0, 10000), _pauta("n2", "Economia B", 10000, 20000)
    )
    original = _antiga()

    nova = montar_reaplicacao(
        novo, "nova", original, [original], "n2", "é B", **_registro()
    )

    assert (nova.tipo, nova.reaplica, nova.item_id) == ("pauta.titulo", "c1", "n2")
    assert (nova.antes, nova.depois) == ("Economia B", "Economia hoje")
    entregue = aplicar(novo, "nova", [original, nova])
    assert [p["titulo"] for p in entregue["pautas"]] == ["Economia A", "Economia hoje"]
    assert fila(novo, "nova", [original, nova]) == []


def test_api_correcao_de_pauta_sobrevive_ao_reprocessamento() -> None:
    mundo = Mundo(["editor"])
    _corrigir(mundo, "pauta.titulo", "Economia hoje")
    mundo.reprocessar({**MODELO, "pautas": [_pauta("n9", "Econ.", 2000, 21000)]})

    pauta = _pauta_entregue(mundo, "n9")

    assert (pauta["titulo"], pauta["origem"]) == ("Economia hoje", "revisao")


def test_api_pauta_que_virou_duas_aparece_na_fila_e_pode_ser_reaplicada() -> None:
    mundo = Mundo(["editor"])
    _corrigir(mundo, "pauta.titulo", "Economia hoje")
    mundo.reprocessar(
        {
            **MODELO,
            "pautas": [_pauta("n1", "A", 0, 9000), _pauta("n2", "B", 9000, 20000)],
        }
    )

    itens = mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json()
    assert [c["item_id"] for c in itens[0]["candidatos"]] == ["n1", "n2"]

    mundo.avancar()
    resposta = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{itens[0]['id']}/reaplicar",
        json={"item_id": "n2", "motivo": "é a B"},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 201
    assert [p["titulo"] for p in mundo.decupagem()["pautas"]] == ["A", "Economia hoje"]
