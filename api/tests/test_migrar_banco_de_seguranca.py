"""A migração das coleções de segurança (#465), com bancos em memória."""

from typing import Any

import pytest

from api.migrar_banco_de_seguranca import LOTE, migrar

AMBIENTE = {"FIRESTORE_BANCO_DE_SEGURANCA": "mam-seguranca"}


class _Documento:
    def __init__(self, id: str, dados: dict[str, Any]) -> None:
        self.id = id
        self._dados = dados

    def to_dict(self) -> dict[str, Any]:
        return dict(self._dados)


class _Colecao:
    def __init__(self, banco: "_Banco", nome: str) -> None:
        self._banco, self._nome = banco, nome

    def document(self, id: str) -> tuple[str, str]:
        return (self._nome, id)

    def select(self, _campos: list[str]) -> "_Colecao":
        return self

    def stream(self) -> list[_Documento]:
        return [
            _Documento(id, dados)
            for (nome, id), dados in sorted(self._banco.docs.items())
            if nome == self._nome
        ]


class _Lote:
    def __init__(self, banco: "_Banco") -> None:
        self._banco = banco
        self._escritas: list[tuple[tuple[str, str], dict[str, Any]]] = []
        banco.commits += 1

    def set(self, ref: tuple[str, str], dados: dict[str, Any]) -> None:
        self._escritas.append((ref, dados))

    def commit(self) -> None:
        for ref, dados in self._escritas:
            self._banco.docs[ref] = dict(dados)


class _Banco:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.commits = 0

    def collection(self, nome: str) -> _Colecao:
        return _Colecao(self, nome)

    def batch(self) -> _Lote:
        return _Lote(self)


def _bancos() -> tuple[dict[str, _Banco], Any]:
    bancos: dict[str, _Banco] = {}

    def fabrica(project: str, database: str) -> _Banco:
        return bancos.setdefault(database, _Banco())

    return bancos, fabrica


def _semear(origem: _Banco) -> None:
    origem.docs[("papeis_de_usuarios", "ana@redetv.com.br")] = {"papeis": ["editor"]}
    origem.docs[("chaves_de_api", "k1")] = {
        "sistema": "Nome",
        "escopos": ["ler"],
        "ativa": True,
    }
    origem.docs[("auditoria", "a1")] = {"acao": "x", "quando": "2026-01-01", "n": 3}
    origem.docs[("jobs", "j1")] = {"estado": "concluido"}


def test_copia_preserva_ids_e_campos_so_das_tres_colecoes() -> None:
    bancos, fabrica = _bancos()
    origem = fabrica("p", "(default)")
    _semear(origem)

    resultado = migrar("p", AMBIENTE, fabrica)

    destino = bancos["mam-seguranca"]
    assert destino.docs == {k: v for k, v in origem.docs.items() if k[0] != "jobs"}
    assert resultado["auditoria"] == {"origem": 1, "destino": 1}
    assert ("jobs", "j1") in origem.docs


def test_rodar_duas_vezes_nao_duplica() -> None:
    bancos, fabrica = _bancos()
    _semear(fabrica("p", "(default)"))

    migrar("p", AMBIENTE, fabrica)
    primeira = dict(bancos["mam-seguranca"].docs)
    resultado = migrar("p", AMBIENTE, fabrica)

    assert bancos["mam-seguranca"].docs == primeira
    assert all(c["origem"] == c["destino"] for c in resultado.values())


def test_colecao_grande_vai_em_lotes() -> None:
    _, fabrica = _bancos()
    origem = fabrica("p", "(default)")
    for i in range(LOTE + 5):
        origem.docs[("auditoria", f"a{i:04}")] = {"i": i}

    resultado = migrar("p", AMBIENTE, fabrica)

    assert resultado["auditoria"] == {"origem": LOTE + 5, "destino": LOTE + 5}


def test_sem_banco_de_seguranca_recusa() -> None:
    _, fabrica = _bancos()
    with pytest.raises(ValueError):
        migrar("p", {}, fabrica)
