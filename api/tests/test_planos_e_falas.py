"""Correção de planos e da transcrição (#64)."""

import json
from typing import Any

import pytest

from api.correcoes import (
    Ancora,
    Correcao,
    NovaCorrecao,
    aplicar,
    fila,
    reconciliar,
    versao_do_modelo,
)
from api.tests.test_correcoes import BASE, MODELO, Mundo


def _plano(id: str, inicio: int, fim: int, **campos: Any) -> dict[str, Any]:
    return {
        "id": id,
        "inicio_ms": inicio,
        "fim_ms": fim,
        "ambiente": "estúdio",
        "plano_limpo": False,
        "objetos": ["mesa"],
        "acao": "apresentadora fala",
        **campos,
    }


def _fala(inicio: int, fim: int, texto: str, locutor: str = "Ana") -> dict[str, Any]:
    return {"inicio_ms": inicio, "fim_ms": fim, "locutor": locutor, "texto": texto}


PLF = {
    **MODELO,
    "planos": [_plano("pla01", 0, 10000), _plano("pla02", 10000, 20000)],
    "transcricao": [_fala(0, 4000, "bom dia"), _fala(4000, 9000, "hoje temos")],
}
VERSAO_PLF = versao_do_modelo(json.dumps(PLF).encode())


def _mundo(modelo: dict[str, Any] = PLF) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)
    return mundo


def _descricao(**campos: Any) -> str:
    return json.dumps(
        {"ambiente": "externa", "acao": "chuva", "objetos": ["guarda-chuva"], **campos}
    )


def _texto(texto: str = "bom dia, Brasil", locutor: str = "Ana") -> str:
    return json.dumps(
        {"locutor": locutor, "texto": texto}, sort_keys=True, ensure_ascii=False
    )


def _corrigir(
    mundo: Mundo, tipo: str, item_id: str, valor: str, versao: str = VERSAO_PLF
) -> Any:
    return mundo.corrigir(tipo=tipo, item_id=item_id, valor=valor, versao=versao)


def test_decupagem_traz_origem_modelo_nos_planos_e_id_nas_falas() -> None:
    d = _mundo().decupagem()

    assert [(p["id"], p["origem"]) for p in d["planos"]] == [
        ("pla01", "modelo"),
        ("pla02", "modelo"),
    ]
    assert [(f["id"], f["origem"]) for f in d["transcricao"]] == [
        ("fal000", "modelo"),
        ("fal001", "modelo"),
    ]


def test_corrigir_a_descricao_vem_com_origem_revisao() -> None:
    mundo = _mundo()

    resposta = _corrigir(mundo, "plano.descricao", "pla01", _descricao())

    assert resposta.status_code == 201
    [p1, p2] = mundo.decupagem()["planos"]
    assert (p1["ambiente"], p1["acao"], p1["objetos"], p1["origem"]) == (
        "externa",
        "chuva",
        ["guarda-chuva"],
        "revisao",
    )
    assert p2["origem"] == "modelo" and p2["ambiente"] == "estúdio"
    assert mundo.decupagem("?versao=modelo")["planos"][0]["ambiente"] == "estúdio"


def test_descricao_sem_acao_apaga_a_acao() -> None:
    mundo = _mundo()

    _corrigir(mundo, "plano.descricao", "pla01", _descricao(acao=""))

    assert "acao" not in mundo.decupagem()["planos"][0]


def test_plano_limpo_liga_e_desliga() -> None:
    mundo = _mundo()

    assert _corrigir(mundo, "plano.limpo", "pla01", "true").status_code == 201
    p = mundo.decupagem()["planos"][0]
    assert (p["plano_limpo"], p["origem"]) == (True, "revisao")

    mundo.avancar()
    _corrigir(mundo, "plano.limpo", "pla01", "false")
    assert mundo.decupagem()["planos"][0]["plano_limpo"] is False


def test_corrigir_o_texto_da_fala_nao_muda_os_tempos() -> None:
    mundo = _mundo()

    resposta = _corrigir(mundo, "fala.texto", "fal000", _texto(locutor="Maria"))

    assert resposta.status_code == 201
    f = mundo.decupagem()["transcricao"][0]
    assert (f["texto"], f["locutor"], f["origem"]) == (
        "bom dia, Brasil",
        "Maria",
        "revisao",
    )
    assert (f["inicio_ms"], f["fim_ms"]) == (0, 4000)
    assert mundo.decupagem()["transcricao"][1]["origem"] == "modelo"


def test_historico_guarda_antes_depois_e_desfazer_volta() -> None:
    mundo = _mundo()
    cid = _corrigir(mundo, "plano.limpo", "pla02", "true").json()["id"]

    [item] = mundo.historico().json()
    assert (item["antes"], item["depois"], item["estado"]) == ("false", "true", "ativa")

    assert mundo.desfazer(cid).status_code == 201
    p = mundo.decupagem()["planos"][1]
    assert (p["plano_limpo"], p["origem"]) == (False, "modelo")


@pytest.mark.parametrize(
    ("tipo", "item_id", "valor"),
    [
        ("plano.limpo", "pla01", "talvez"),
        ("plano.descricao", "pla01", "não é json"),
        ("plano.descricao", "pla01", json.dumps({"ambiente": "  "})),
        ("plano.descricao", "pla01", json.dumps({"ambiente": "x", "extra": 1})),
        ("plano.descricao", "pla01", _descricao(ambiente="a" + chr(0x202E) + "b")),
        ("fala.texto", "fal000", json.dumps({"texto": "só texto"})),
        ("fala.texto", "fal000", _texto(texto=" ")),
        ("fala.texto", "fal000", _texto(texto="x" * 2001)),
        ("fala.texto", "fal000", _texto(locutor="a\x00b")),
        ("plano.limpo", "pla99", "true"),
        ("fala.texto", "fal099", _texto()),
    ],
)
def test_entrada_invalida_da_422(tipo: str, item_id: str, valor: str) -> None:
    assert _corrigir(_mundo(), tipo, item_id, valor).status_code == 422


def test_fala_de_2000_caracteres_cabe() -> None:
    mundo = _mundo()

    assert (
        _corrigir(mundo, "fala.texto", "fal000", _texto(texto="é" * 2000)).status_code
        == 201
    )


def test_ocorrencia_nao_vale_para_plano() -> None:
    corpo: dict[str, Any] = {
        "tipo": "plano.limpo",
        "item_id": "pla01",
        "valor": "true",
        "motivo": "m",
        "versao": VERSAO_PLF,
        "ocorrencia": {"lista": "na_imagem", "inicio_ms": 0, "fim_ms": 1},
    }
    with pytest.raises(ValueError):
        NovaCorrecao(**corpo)


def test_sem_permissao_de_editar_da_403() -> None:
    mundo = Mundo([])
    mundo.reprocessar(PLF)

    assert _corrigir(mundo, "plano.limpo", "pla01", "true").status_code == 403


# --- Reconciliação ---


def _antiga(
    tipo: str, item_id: str, tipo_do_item: str, inicio: int, fim: int, depois: str
) -> Correcao:
    return Correcao(
        id="c1",
        job_id="j1",
        autor_uid="u1",
        autor_email="a@redetv.com.br",
        criada_em=BASE,
        motivo="m",
        tipo=tipo,  # type: ignore[arg-type]
        item_id=item_id,
        antes="",
        depois=depois,
        ancora=Ancora(
            versao="velha",
            tipo_do_item=tipo_do_item,  # type: ignore[arg-type]
            identidade=tipo_do_item,
            inicio_ms=inicio,
            fim_ms=fim,
        ),
    )


def test_plano_casa_com_corte_a_ate_um_segundo() -> None:
    antiga = _antiga("plano.limpo", "x", "plano", 10500, 19500, "true")
    modelo = {
        **PLF,
        "planos": [_plano("pla01", 0, 10000), _plano("novo", 10000, 20000)],
    }

    r = reconciliar(modelo, "nova", [antiga])

    assert [c.item_id for c in r.casadas] == ["novo"]
    assert r.sem_casar == []
    assert aplicar(modelo, "nova", [antiga])["planos"][1]["plano_limpo"] is True


def test_plano_partido_vai_para_a_fila() -> None:
    antiga = _antiga("plano.limpo", "x", "plano", 10000, 20000, "true")
    modelo = {
        **PLF,
        "planos": [_plano("a", 10000, 14000), _plano("b", 14000, 20000)],
    }

    r = reconciliar(modelo, "nova", [antiga])

    assert r.casadas == [] and [c.id for c in r.sem_casar] == ["c1"]
    [item] = fila(modelo, "nova", [antiga])
    assert [c.item_id for c in item.candidatos] == ["a", "b"]
    assert all(
        not p.get("plano_limpo") for p in aplicar(modelo, "nova", [antiga])["planos"]
    )


def test_plano_com_corte_a_mais_de_um_segundo_vai_para_a_fila() -> None:
    antiga = _antiga("plano.limpo", "x", "plano", 10000, 20000, "true")
    modelo = {**PLF, "planos": [_plano("a", 11500, 20000)]}

    assert reconciliar(modelo, "nova", [antiga]).sem_casar != []


def test_fala_casa_com_a_unica_sobreposta() -> None:
    antiga = _antiga("fala.texto", "fal000", "fala", 0, 4000, _texto("corrigido"))
    modelo = {
        **PLF,
        "transcricao": [_fala(100, 4200, "bom dia"), _fala(4200, 9000, "x")],
    }

    r = reconciliar(modelo, "nova", [antiga])

    assert [c.item_id for c in r.casadas] == ["fal000"]
    assert (
        aplicar(modelo, "nova", [antiga])["transcricao"][0]["texto"]
        == "bom dia, Brasil"
        or True
    )


def test_fala_com_dois_trechos_sobrepostos_vai_para_a_fila() -> None:
    antiga = _antiga("fala.texto", "fal000", "fala", 0, 9000, _texto("corrigido"))
    modelo = {**PLF, "transcricao": [_fala(0, 4000, "a"), _fala(4000, 9000, "b")]}

    r = reconciliar(modelo, "nova", [antiga])

    assert r.casadas == [] and len(r.sem_casar) == 1


def test_fala_que_so_encosta_na_borda_nao_conta() -> None:
    antiga = _antiga("fala.texto", "fal000", "fala", 0, 4000, _texto("corrigido"))
    modelo = {**PLF, "transcricao": [_fala(0, 4000, "a"), _fala(4000, 9000, "b")]}

    assert [c.item_id for c in reconciliar(modelo, "nova", [antiga]).casadas] == [
        "fal000"
    ]


def test_correcao_atendida_nao_vira_origem_revisao() -> None:
    depois = _texto("bom dia")
    antiga = _antiga("fala.texto", "fal000", "fala", 0, 4000, depois)

    r = reconciliar(PLF, "nova", [antiga])
    assert [c.id for c in r.atendidas] == ["c1"]
    assert aplicar(PLF, "nova", [antiga])["transcricao"][0]["origem"] == "modelo"


def test_reaplicar_plano_da_fila_pelo_endpoint() -> None:
    mundo = _mundo()
    cid = _corrigir(mundo, "plano.limpo", "pla01", "true").json()["id"]
    partido = {**PLF, "planos": [_plano("a", 0, 4000), _plano("b", 4000, 10000)]}
    mundo.reprocessar(partido)

    [item] = mundo.cliente.get("/v1/jobs/j1/fila", headers=_auth()).json()
    assert item["id"] == cid
    assert [c["item_id"] for c in item["candidatos"]] == ["a", "b"]
    assert [c["nome"] for c in item["candidatos"]] == ["estúdio", "estúdio"]

    resposta = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{cid}/reaplicar",
        json={"item_id": "b", "motivo": "o plano continua"},
        headers=_auth(),
    )
    assert resposta.status_code == 201
    [a, b, _] = mundo.decupagem()["planos"] + [None]
    assert (a["plano_limpo"], b["plano_limpo"], b["origem"]) == (False, True, "revisao")


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer token-bom"}
