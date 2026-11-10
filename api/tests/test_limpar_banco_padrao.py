"""A limpeza das coleções de segurança antigas do banco padrão (#530), com bancos em memória."""

from typing import Any

import pytest

from api.limpar_banco_padrao import limpar, main


class _Documento:
    def __init__(self, colecao: str, id: str) -> None:
        self.id = id
        self.reference = (colecao, id)


class _Colecao:
    def __init__(self, banco: "_Banco", nome: str) -> None:
        self._banco, self._nome = banco, nome

    def select(self, _campos: list[str]) -> "_Colecao":
        return self

    def stream(self) -> list[_Documento]:
        ids = sorted(self._banco.docs.get(self._nome, []))
        return [_Documento(self._nome, i) for i in ids]


class _Lote:
    def __init__(self, banco: "_Banco") -> None:
        self._banco = banco
        self._apagar: list[tuple[str, str]] = []

    def delete(self, ref: tuple[str, str]) -> None:
        self._apagar.append(ref)

    def commit(self) -> None:
        assert len(self._apagar) <= 400
        self._banco.commits += 1
        for nome, id in self._apagar:
            self._banco.docs[nome].discard(id)


class _Banco:
    def __init__(self, docs: dict[str, set[str]]) -> None:
        self.docs = docs
        self.commits = 0

    def collection(self, nome: str) -> _Colecao:
        return _Colecao(self, nome)

    def batch(self) -> _Lote:
        return _Lote(self)


def _fabrica(banco: _Banco, abertos: list[str]) -> Any:
    def fabrica(project: str, database: str) -> _Banco:
        abertos.append(database)
        return banco

    return fabrica


def test_recusa_banco_que_nao_e_o_padrao() -> None:
    abertos: list[str] = []
    banco = _Banco({"auditoria": {"a"}})
    with pytest.raises(ValueError, match="banco"):
        limpar("p", "mam-seguranca", ["auditoria"], False, _fabrica(banco, abertos))
    assert abertos == []
    assert banco.docs["auditoria"] == {"a"}


def test_listar_conta_e_nao_apaga() -> None:
    abertos: list[str] = []
    banco = _Banco({"auditoria": {"a", "b"}, "chaves_de_api": {"c"}})
    contagens = limpar(
        "p",
        "(default)",
        ["auditoria", "chaves_de_api", "papeis_de_usuarios"],
        False,
        _fabrica(banco, abertos),
    )
    assert contagens == {"auditoria": 2, "chaves_de_api": 1, "papeis_de_usuarios": 0}
    assert abertos == ["(default)"]
    assert banco.docs == {"auditoria": {"a", "b"}, "chaves_de_api": {"c"}}


def test_apagar_esvazia_as_colecoes_em_lotes() -> None:
    abertos: list[str] = []
    banco = _Banco(
        {
            "auditoria": {f"a{i}" for i in range(401)},
            "chaves_de_api": {"c"},
            "papeis_de_usuarios": set(),
        }
    )
    contagens = limpar(
        "p",
        "(default)",
        ["auditoria", "chaves_de_api", "papeis_de_usuarios"],
        True,
        _fabrica(banco, abertos),
    )
    assert contagens == {"auditoria": 401, "chaves_de_api": 1, "papeis_de_usuarios": 0}
    assert all(not ids for ids in banco.docs.values())
    assert banco.commits == 3  # 400 + 1 da auditoria, 1 das chaves


def test_main_sem_argumento_so_lista_o_banco_padrao(
    capsys: pytest.CaptureFixture[str],
) -> None:
    abertos: list[str] = []
    banco = _Banco({"auditoria": {"a"}})
    assert main([], {"GCP_PROJECT_ID": "p"}, _fabrica(banco, abertos)) == 0
    assert abertos == ["(default)"]
    assert banco.docs == {"auditoria": {"a"}}
    assert "auditoria: 1" in capsys.readouterr().out


def test_main_com_apagar_apaga() -> None:
    banco = _Banco({"auditoria": {"a"}})
    assert main(["--apagar"], {"GCP_PROJECT_ID": "p"}, _fabrica(banco, [])) == 0
    assert banco.docs == {"auditoria": set()}


def test_recusa_colecao_fora_das_tres() -> None:
    abertos: list[str] = []
    banco = _Banco({"auditoria": {"a"}, "videos": {"v"}})
    with pytest.raises(ValueError, match="videos"):
        limpar(
            "p", "(default)", ["auditoria", "videos"], True, _fabrica(banco, abertos)
        )
    assert abertos == []
    assert banco.docs == {"auditoria": {"a"}, "videos": {"v"}}
