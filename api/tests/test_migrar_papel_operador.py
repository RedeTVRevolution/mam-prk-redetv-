"""A migração do papel Operador (#664): `make migrar-papel-operador`."""

from typing import Any

from api.migrar_papel_operador import LOTE, migrar


class _Doc:
    def __init__(self, uid: str, dados: dict[str, Any]) -> None:
        self.dados, self.reference = dados, uid

    def to_dict(self) -> dict[str, Any]:
        return self.dados


class _Lote:
    def __init__(self, banco: "_Banco") -> None:
        self.banco, self.n = banco, 0

    def update(self, uid: str, campos: dict[str, Any]) -> None:
        self.banco.docs[uid].update(campos)
        self.n += 1

    def commit(self) -> None:
        self.banco.lotes.append(self.n)


class _Banco:
    """Faz de coleção e de cliente: `stream` lê, `batch` grava."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self.docs = docs
        self.lotes: list[int] = []

    def stream(self) -> list[_Doc]:
        return [_Doc(uid, d) for uid, d in self.docs.items()]

    def batch(self) -> _Lote:
        return _Lote(self)


def test_troca_operador_por_consulta_na_ordem_e_sem_repetir() -> None:
    banco = _Banco(
        {
            "a": {"papeis": ["operador"]},
            "b": {"papeis": ["editor", "operador"], "desativada": True},
            "c": {"papeis": ["consulta", "operador"]},
        }
    )

    assert migrar(banco, banco) == 3
    assert banco.docs == {
        "a": {"papeis": ["consulta"]},
        "b": {"papeis": ["consulta", "editor"], "desativada": True},
        "c": {"papeis": ["consulta"]},
    }


def test_documento_sem_operador_nao_e_gravado_e_repetir_nao_grava_nada() -> None:
    banco = _Banco(
        {
            "a": {"papeis": ["editor", "consulta"]},  # fora da ordem: não é da migração
            "b": {"desativada": True},
            "c": {"papeis": ["operador"]},
        }
    )

    assert migrar(banco, banco) == 1
    assert banco.docs["a"] == {"papeis": ["editor", "consulta"]}
    assert banco.docs["b"] == {"desativada": True}

    banco.lotes.clear()
    assert migrar(banco, banco) == 0
    assert banco.lotes == []


def test_grava_em_lotes_de_400() -> None:
    banco = _Banco({f"u{i}": {"papeis": ["operador"]} for i in range(LOTE + 1)})

    assert migrar(banco, banco) == LOTE + 1
    assert banco.lotes == [LOTE, 1]
