"""Purga em lote (#668): o cliente real do Storage, com a rede trocada por um dublê que
responde no formato multipart do endpoint de lote. O fake-gcs-server não atende lote,
então estes testes não dependem do emulador."""

import re
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest
import requests
from google.api_core.exceptions import InternalServerError
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

from api.nuvem import (
    ArquivosNoStorage,
    JanelasStorage,
    ReferenciasStorage,
    RepositorioDeCorrecoesFirestore,
    apagar_objetos,
)


class _Nuvem:
    """O Storage em memória: `objetos` por bucket e o que cada POST de lote trouxe."""

    def __init__(self, objetos: dict[str, set[str]], falham: dict[str, int]) -> None:
        self.objetos = objetos
        self.falham = falham  # objeto -> status que o lote devolve para ele
        self.lotes: list[list[str]] = []

    def listar(self, bucket: str, prefix: str = "") -> list[Any]:
        return [
            _Blob(f"{bucket}/{o}")
            for o in sorted(self.objetos[bucket])
            if o.startswith(prefix)
        ]

    def responder(self, **kwargs: Any) -> requests.Response:
        alvos = re.findall(r"DELETE \S+/b/([^/]+)/o/([^?\s]+)", kwargs["data"])
        nomes = [(b, unquote(o)) for b, o in alvos]
        self.lotes.append([o for _, o in nomes])
        partes = []
        for i, (bucket, objeto) in enumerate(nomes, 1):
            status = self.falham.get(objeto) or (
                204 if objeto in self.objetos[bucket] else 404
            )
            if status == 204:
                self.objetos[bucket].discard(objeto)
            partes.append(
                f"--b\nContent-Type: application/http\nContent-ID: <response-{i}>\n\n"
                f"HTTP/1.1 {status} X\nContent-Type: application/json\n\n{{}}\n"
            )
        resposta = requests.Response()
        resposta.status_code = 200
        resposta.headers["content-type"] = 'multipart/mixed; boundary="b"'
        resposta._content = ("".join(partes) + "--b--\n").encode()
        return resposta


class _Blob:
    def __init__(self, nome: str) -> None:
        self.nome = nome


def _cliente(nuvem: _Nuvem) -> Any:
    cliente = storage.Client(project="p", credentials=AnonymousCredentials())  # type: ignore[no-untyped-call]
    cliente._base_connection._make_request = lambda method, url, **kw: nuvem.responder(
        method=method, url=url, **kw
    )

    def listar(bucket: str, prefix: str = "") -> list[storage.Blob]:
        return [
            storage.Blob(b.nome.split("/", 1)[1], cliente.bucket(bucket))
            for b in nuvem.listar(bucket, prefix)
        ]

    cliente.list_blobs = listar
    return cliente


def _nuvem(
    objetos: dict[str, set[str]], falham: dict[str, int] | None = None
) -> _Nuvem:
    return _Nuvem(objetos, falham or {})


def test_apaga_em_lotes_de_100_e_so_o_prefixo() -> None:
    nuvem = _nuvem({"ref": {f"r/ana/{i}.jpg" for i in range(250)} | {"r/ana2/0.jpg"}})

    ReferenciasStorage(_cliente(nuvem), "ref").apagar_prefixo("r/ana/")

    assert [len(lote) for lote in nuvem.lotes] == [100, 100, 50]
    assert nuvem.objetos["ref"] == {"r/ana2/0.jpg"}


def test_objeto_que_sumiu_entre_a_listagem_e_o_apagar_e_aceito() -> None:
    nuvem = _nuvem({"ref": {"r/a/0", "r/a/1"}}, {"r/a/0": 404})

    ReferenciasStorage(_cliente(nuvem), "ref").apagar_prefixo("r/a/")

    assert nuvem.objetos["ref"] == {"r/a/0"}  # o dublê só finge o 404 dele


def test_outro_erro_sobe_mesmo_com_um_404_depois_dele() -> None:
    # O cliente só levanta o último erro do lote: o 404 final esconderia o 500.
    nuvem = _nuvem({"ref": {"r/a/0", "r/a/1", "r/a/2"}}, {"r/a/0": 500, "r/a/2": 404})

    with pytest.raises(InternalServerError):
        ReferenciasStorage(_cliente(nuvem), "ref").apagar_prefixo("r/a/")

    # O lote correu inteiro: o r/a/1 saiu mesmo com o erro no r/a/0.
    assert "r/a/1" not in nuvem.objetos["ref"]


def test_sem_objetos_nao_chama_o_storage() -> None:
    nuvem = _nuvem({"ref": set()})

    apagar_objetos(_cliente(nuvem), [])

    assert nuvem.lotes == []


def test_arquivos_no_storage_apaga_tudo_do_job_e_nada_de_outro() -> None:
    nuvem = _nuvem(
        {
            "aceitos": {"j1/proxy.mp4", "j1/janelas/0000.json", "j10/proxy.mp4"},
            "decupagens": {
                "j1.json",
                "j1.comparacao.json",
                "j1/quadros/p-0.jpg",
                "j10.json",
                "j2.json",
            },
        }
    )

    ArquivosNoStorage(_cliente(nuvem), "aceitos", "decupagens").apagar("j1")

    assert nuvem.objetos == {
        "aceitos": {"j10/proxy.mp4"},
        "decupagens": {"j10.json", "j2.json"},
    }


def test_janelas_apagam_so_as_do_job() -> None:
    nuvem = _nuvem({"aceitos": {"j1/janelas/0000.json", "j1/proxy.mp4"}})

    JanelasStorage(_cliente(nuvem), "aceitos").apagar("j1")

    assert nuvem.objetos["aceitos"] == {"j1/proxy.mp4"}


def test_purgar_correcoes_apaga_em_lotes_de_500() -> None:
    docs = [MagicMock() for _ in range(1200)]
    cliente = MagicMock()
    cliente.collection.return_value.where.return_value.stream.return_value = iter(docs)
    lotes = [MagicMock() for _ in range(3)]
    cliente.batch.side_effect = lotes

    RepositorioDeCorrecoesFirestore(cliente).purgar("j1")

    assert [l.delete.call_count for l in lotes] == [500, 500, 200]
    assert all(l.commit.call_count == 1 for l in lotes)
