"""A contagem de itens por tipo é feita quando a decupagem é gravada (#455)."""

import json
from typing import Any

import pytest

from api.correcoes import CORRIGIVEIS, versao_do_modelo
from api.itens_da_decupagem import ItensDaDecupagem, contar_itens, objeto_dos_itens
from api.nuvem import DecupagensStorage, ObjetosStorage


def _conteudo(pessoas: int, pautas: int, pipeline: str | None = "v1") -> bytes:
    return json.dumps(
        {
            "versao_pipeline": pipeline,
            "pessoas": [{"id": f"p{n}"} for n in range(pessoas)],
            "pautas": [{"id": f"t{n}"} for n in range(pautas)],
        }
    ).encode()


def test_conta_os_itens_de_cada_tipo_de_correcao() -> None:
    conteudo = _conteudo(3, 2)

    itens = contar_itens(conteudo)

    assert itens.versao_do_modelo == versao_do_modelo(conteudo)
    assert itens.versao_pipeline == "v1"
    assert itens.itens["pessoa.renomear"] == 3
    assert itens.itens["pauta.titulo"] == 2
    assert set(itens.itens) == set(CORRIGIVEIS)


def test_decupagem_antiga_sem_versao_do_pipeline_fica_sem_versao() -> None:
    assert contar_itens(_conteudo(1, 1, None)).versao_pipeline is None


def test_decupagem_que_nao_e_objeto_nao_se_conta() -> None:
    with pytest.raises(TypeError):
        contar_itens(b"[]")


def test_ida_e_volta_pelo_json() -> None:
    itens = contar_itens(_conteudo(3, 2))

    assert ItensDaDecupagem.do_json(itens.em_json()) == itens


class _Blob:
    def __init__(self, gravados: dict[str, bytes], nome: str) -> None:
        self._gravados = gravados
        self._nome = nome

    def upload_from_string(self, conteudo: Any, content_type: str) -> None:
        self._gravados[self._nome] = (
            conteudo if isinstance(conteudo, bytes) else conteudo.encode()
        )


class _Bucket:
    def __init__(self, gravados: dict[str, bytes], nome: str) -> None:
        self._gravados = gravados
        self._nome = nome

    def blob(self, nome: str) -> _Blob:
        return _Blob(self._gravados, f"{self._nome}/{nome}")


class _Cliente:
    def __init__(self) -> None:
        self.gravados: dict[str, bytes] = {}

    def bucket(self, nome: str) -> _Bucket:
        return _Bucket(self.gravados, nome)


@pytest.mark.parametrize(
    "fabrica",
    [
        lambda c: DecupagensStorage(c, "aceitos", "decupagens"),
        lambda c: ObjetosStorage(c, "decupagens"),
    ],
)
def test_gravar_a_decupagem_grava_a_contagem_junto_e_regravar_a_refaz(
    fabrica: Any,
) -> None:
    cliente = _Cliente()
    armazenamento = fabrica(cliente)

    armazenamento.gravar_decupagem("j1", _conteudo(3, 2).decode())
    armazenamento.gravar_decupagem("j1", _conteudo(5, 2, "v2").decode())

    gravado = ItensDaDecupagem.do_json(
        cliente.gravados[f"decupagens/{objeto_dos_itens('j1')}"].decode()
    )
    assert gravado.versao_pipeline == "v2"
    assert gravado.itens["pessoa.renomear"] == 5
    assert "decupagens/j1.json" in cliente.gravados


def test_decupagem_ilegivel_grava_a_decupagem_e_deixa_a_contagem_de_fora() -> None:
    cliente = _Cliente()

    DecupagensStorage(cliente, "aceitos", "decupagens").gravar_decupagem("j1", "[]")

    assert list(cliente.gravados) == ["decupagens/j1.json"]
