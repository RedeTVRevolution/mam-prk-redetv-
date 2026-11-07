"""A migração que apaga as referências na web (#327), com dublês."""

import json
from typing import Any

from api.apagar_referencias_web import (
    Contagem,
    apagar,
    contar,
    tirar_a_fonte_referencia,
)
from api.catalogo import CatalogoEmMemoria, Rosto


class _Fotos:
    def __init__(self, *objetos: str) -> None:
        self.objetos = set(objetos)

    def contar_prefixo(self, prefixo: str) -> int:
        return sum(o.startswith(prefixo) for o in self.objetos)

    def apagar_prefixo(self, prefixo: str) -> None:
        self.objetos = {o for o in self.objetos if not o.startswith(prefixo)}


class _Decupagens:
    def __init__(self, decupagens: dict[str, dict[str, Any]], registros: set[str]):
        self.decupagens = {k: json.dumps(v).encode() for k, v in decupagens.items()}
        self.registros = registros

    def ler(self, job_id: str) -> bytes | None:
        return self.decupagens.get(job_id)

    def gravar(self, job_id: str, conteudo: str) -> None:
        self.decupagens[job_id] = conteudo.encode()

    def contar_registros_da_comparacao(self, job_id: str) -> int:
        return sum(r.startswith(f"{job_id}.") for r in self.registros)

    def apagar_registros_da_comparacao(self, job_id: str) -> None:
        self.registros = {r for r in self.registros if not r.startswith(f"{job_id}.")}


def _pessoa(fontes: list[str], estado: str | None) -> dict[str, Any]:
    return {"nome": "Leão Lobo", "fontes_do_nome": fontes, "estado_do_nome": estado}


def _cenario() -> dict[str, Any]:
    catalogo = CatalogoEmMemoria()
    pessoa = catalogo.acrescentar("Leão Lobo", "colunista", [])
    catalogo.definir_rostos(
        pessoa.id,
        [
            Rosto(origem="web", referencia="referencias/x/a.jpg"),
            Rosto(origem="acervo", referencia="acervo/a.jpg"),
        ],
    )
    return {
        "fotos": _Fotos(
            "referencias/x/a.jpg", "referencias/x/b.jpg", "palpites/j/1.jpg"
        ),
        "catalogo": catalogo,
        "decupagens": _Decupagens(
            {
                "j1": {"pessoas": [_pessoa(["referencia"], "confirmado")]},
                "j2": {"pessoas": [_pessoa(["gc", "referencia"], "confirmado")]},
                "j3": {"pessoas": [_pessoa(["gc"], "confirmado")]},
            },
            {"j1.comparacao.json", "j1.nomes_a_buscar.json", "j2.comparacao.json"},
        ),
        "job_ids": ["j1", "j2", "j3", "j4"],
    }


def test_conta_antes_e_depois() -> None:
    c = _cenario()

    assert contar(**c) == Contagem(2, 1, 1, 2, 3)

    apagar(**c)

    assert contar(**c) == Contagem(0, 0, 0, 0, 0)


def test_so_o_rosto_da_web_sai_do_catalogo() -> None:
    c = _cenario()

    apagar(**c)

    (pessoa,) = c["catalogo"].todas()
    assert [r.origem for r in pessoa.rostos] == ["acervo"]


def test_nome_so_com_a_referencia_volta_a_palpite_e_o_com_gc_segue_confirmado() -> None:
    c = _cenario()

    apagar(**c)

    lidas = {
        k: json.loads(v)["pessoas"][0] for k, v in c["decupagens"].decupagens.items()
    }
    assert lidas["j1"]["fontes_do_nome"] == []
    assert lidas["j1"]["estado_do_nome"] == "palpite"
    assert lidas["j1"]["nome"] == "Leão Lobo"
    assert lidas["j2"]["fontes_do_nome"] == ["gc"]
    assert lidas["j2"]["estado_do_nome"] == "confirmado"
    assert lidas["j3"] == _pessoa(["gc"], "confirmado")


def test_rodar_de_novo_nao_muda_nada() -> None:
    c = _cenario()
    apagar(**c)
    antes = dict(c["decupagens"].decupagens)

    apagar(**c)

    assert c["decupagens"].decupagens == antes


def test_decupagem_sem_pessoas_nao_muda() -> None:
    assert tirar_a_fonte_referencia({"pessoas": []}) is False
    assert tirar_a_fonte_referencia({}) is False


def test_nome_que_volta_a_palpite_perde_o_catalogo_id_e_o_da_revisora_fica() -> None:
    do_modelo = {**_pessoa(["referencia"], "confirmado"), "catalogo_id": "c1"}
    da_revisora = {**do_modelo, "origem": "revisao"}
    dados = {"pessoas": [do_modelo, da_revisora]}

    assert tirar_a_fonte_referencia(dados) is True

    assert do_modelo["estado_do_nome"] == "palpite"
    assert do_modelo["catalogo_id"] is None
    assert da_revisora["estado_do_nome"] == "confirmado"
    assert da_revisora["catalogo_id"] == "c1"
    assert da_revisora["fontes_do_nome"] == []


def test_decupagem_que_nao_abre_fica_como_esta_e_o_resto_segue() -> None:
    c = _cenario()
    c["decupagens"].decupagens["j0"] = b"{quebrado"
    c["job_ids"] = ["j0", *c["job_ids"]]

    assert contar(**c).decupagens_com_a_fonte_referencia == 2

    apagar(**c)

    assert c["decupagens"].decupagens["j0"] == b"{quebrado"
    assert contar(**c) == Contagem(0, 0, 0, 0, 0)
