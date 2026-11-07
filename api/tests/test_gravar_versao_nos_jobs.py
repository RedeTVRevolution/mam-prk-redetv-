"""A carga dos Jobs antigos (#494): `make gravar-versao-nos-jobs` grava `versao_pipeline`."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from api.gravar_versao_nos_jobs import gravar
from api.jobs import Job, ServicoIndisponivel

AGORA = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


class _Doc:
    def __init__(self, dados: dict[str, Any]) -> None:
        self.dados, self.reference = dados, dados["id"]

    def to_dict(self) -> dict[str, Any]:
        return self.dados


class _Lote:
    def __init__(self, gravados: dict[str, Any], lotes: list[int]) -> None:
        self.gravados, self.lotes, self.n = gravados, lotes, 0

    def update(self, referencia: str, campos: dict[str, Any]) -> None:
        self.gravados[referencia] = campos
        self.n += 1

    def commit(self) -> None:
        self.lotes.append(self.n)


class _Colecao:
    def __init__(self, docs: list[_Doc]) -> None:
        self.docs = docs

    def stream(self) -> list[_Doc]:
        return self.docs


class _Cliente:
    def __init__(self) -> None:
        self.gravados: dict[str, Any] = {}
        self.lotes: list[int] = []

    def batch(self) -> _Lote:
        return _Lote(self.gravados, self.lotes)


class _Decupagens:
    def __init__(self, versoes: dict[str, str | None]) -> None:
        self._versoes = versoes
        self.abertas: list[str] = []

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        self.abertas.append(job_id)
        if job_id not in self._versoes:
            raise ServicoIndisponivel
        versao = self._versoes[job_id]
        yield json.dumps({"versao_pipeline": versao} if versao else {}).encode()


def _doc(id: str, estado: str = "concluido", **extra: Any) -> _Doc:
    job = Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=1,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        criado_em=AGORA,
        atualizado_em=AGORA,
        **extra,
    )
    dados = job.model_dump()
    if extra.get("versao_pipeline") is None:
        dados.pop("versao_pipeline")
    return _Doc(dados)


def _docs() -> list[_Doc]:
    return [
        _doc("antigo"),
        _doc("outro"),
        _doc("pronto", versao_pipeline="2026.11.7"),
        _doc("andando", estado="analisando"),
        _doc("sem-campo"),
        _doc("ilegivel"),
    ]


_VERSOES = {
    "antigo": "2026.10.1",
    "outro": "2026.10.2",
    "andando": "2026.10.1",
    "sem-campo": None,
}


def test_grava_a_versao_da_decupagem_so_nos_concluidos_que_nao_a_tem() -> None:
    cliente, decupagens = _Cliente(), _Decupagens(_VERSOES)

    contagem = gravar(_Colecao(_docs()), cliente, decupagens)

    assert cliente.gravados == {
        "antigo": {"versao_pipeline": "2026.10.1"},
        "outro": {"versao_pipeline": "2026.10.2"},
    }
    assert contagem == {"gravados": 2, "iguais": 1, "sem_versao": 1, "nao_lidos": 1}
    # O Job que já tem a versão e o que ainda anda não abrem a decupagem.
    assert sorted(decupagens.abertas) == ["antigo", "ilegivel", "outro", "sem-campo"]


def test_repetir_nao_grava_nem_baixa_de_novo() -> None:
    docs = _docs()
    cliente = _Cliente()
    gravar(_Colecao(docs), cliente, _Decupagens(_VERSOES))
    for doc in docs:
        doc.dados.update(cliente.gravados.get(doc.dados["id"], {}))
    decupagens = _Decupagens(_VERSOES)

    segunda = gravar(_Colecao(docs), _Cliente(), decupagens)

    assert segunda["gravados"] == 0 and segunda["iguais"] == 3
    assert sorted(decupagens.abertas) == ["ilegivel", "sem-campo"]


def test_grava_em_lotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.gravar_versao_nos_jobs.LOTE", 2)
    docs = [_doc(f"j{i}") for i in range(5)]
    cliente = _Cliente()

    contagem = gravar(
        _Colecao(docs), cliente, _Decupagens({d.dados["id"]: "2026.10.1" for d in docs})
    )

    assert contagem["gravados"] == 5
    assert cliente.lotes == [2, 2, 1]
