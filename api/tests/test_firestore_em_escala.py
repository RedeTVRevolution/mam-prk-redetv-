"""A lógica pura do teste em escala: Jobs falsos com prefixo, intervalo do apagar, contas."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from api import firestore_em_escala
from api.firestore_em_escala import (
    FIM_DO_INTERVALO,
    PREFIXO,
    PROGRAMAS,
    apagar,
    casos,
    entradas_automaticas,
    entradas_compostas,
    job_falso,
    limites_do_apagar,
    main,
)

AGORA = datetime(2026, 11, 11, tzinfo=UTC)


class Colecao:
    def document(self, id: str) -> str:
        return id


def test_todo_job_falso_tem_o_prefixo_e_e_o_mesmo_para_o_mesmo_indice() -> None:
    jobs = [job_falso(i, AGORA) for i in range(300)]
    assert all(j.id.startswith(PREFIXO) for j in jobs)
    assert len({j.id for j in jobs}) == 300
    assert job_falso(7, AGORA) == jobs[7]
    assert {j.programa for j in jobs} <= set(PROGRAMAS)


def test_os_limites_do_apagar_cercam_so_os_ids_teste() -> None:
    ini, fim = limites_do_apagar(Colecao())
    assert (ini, fim) == ("teste_", "teste`")
    assert FIM_DO_INTERVALO == "teste" + chr(ord("_") + 1)
    assert ini <= "teste_0000001" < fim
    assert not ini <= "teste" < fim and not ini <= "testf" < fim
    assert not ini <= "teste`" < fim


def test_cancelado_nunca_cai_no_programa_grande_e_falhou_acontece() -> None:
    jobs = [job_falso(i, AGORA) for i in range(20_000)]
    assert not [
        j for j in jobs if j.estado == "cancelado" and j.programa == PROGRAMAS[0]
    ]
    assert any(j.estado == "cancelado" for j in jobs)
    assert any(j.estado == "falhou" and j.codigo_falha for j in jobs)


def test_contas_de_entradas_do_indice() -> None:
    doc: dict[str, Any] = {
        "a": 1,
        "b": None,
        "p": ["x", "y", "z"],
        "m": {"k": 1},
        "cortes_ms": [1, 2],
    }
    assert entradas_automaticas(doc) == 2 + 2 + 3 + 2
    assert entradas_compostas({"palavras": ["a", "b"]}) == 2 + 2 + 2 + 4 + 1 + 1


def test_os_casos_incluem_o_pior_caso_com_pagina_de_50() -> None:
    todos = casos(AGORA.date())
    assert [c for c in todos if "RUIM" in c.nome]
    assert all(c.filtro.limite == 50 for c in todos)


class ConsultaFalsa:
    def __init__(
        self,
        cliente: "ClienteFalso",
        ini: str = "",
        fim: str = "\U0010ffff",
        n: int | None = None,
    ):
        self.cliente, self.ini, self.fim, self.n = cliente, ini, fim, n

    def where(self, filter: Any) -> "ConsultaFalsa":
        if filter.op_string == ">=":
            return ConsultaFalsa(self.cliente, filter.value, self.fim, self.n)
        return ConsultaFalsa(self.cliente, self.ini, filter.value, self.n)

    def select(self, _: Any) -> "ConsultaFalsa":
        return self

    def order_by(self, _: Any) -> "ConsultaFalsa":
        return self

    def limit(self, n: int) -> "ConsultaFalsa":
        return ConsultaFalsa(self.cliente, self.ini, self.fim, n)

    def _ids(self) -> list[str]:
        ids = sorted(i for i in self.cliente.docs if self.ini <= i < self.fim)
        return ids[: self.n]

    def stream(self) -> list[Any]:
        return [SimpleNamespace(reference=i) for i in self._ids()]

    def count(self) -> "ConsultaFalsa":
        return self

    def get(self) -> list[list[Any]]:
        return [[SimpleNamespace(value=len(self._ids()))]]


class EscritorFalso:
    """Imita o BulkWriter: `flush` entrega cada exclusão aos callbacks, com as tentativas."""

    def __init__(self, cliente: "ClienteFalso"):
        self.cliente = cliente
        self.fila: list[str] = []
        self.ok: Any = None
        self.erro: Any = None

    def on_write_result(self, cb: Any) -> None:
        self.ok = cb

    def on_write_error(self, cb: Any) -> None:
        self.erro = cb

    def delete(self, ref: str) -> None:
        self.fila.append(ref)

    def flush(self) -> None:
        fila, self.fila = self.fila, []
        if self.cliente.sem_callback:
            return  # o envio do lote falhou: nenhum callback é chamado
        for ref in fila:
            tentativas = 0
            while True:
                falha = self.cliente.falhas.get(ref, [])
                if not falha:
                    self.cliente.docs.discard(ref)
                    self.ok(ref, None, self)
                    break
                motivo = falha.pop(0)
                if not self.erro(
                    SimpleNamespace(attempts=tentativas, message=motivo), self
                ):
                    break
                tentativas += 1

    def close(self) -> None:
        pass


class ClienteFalso:
    def __init__(
        self,
        docs: list[str],
        falhas: dict[str, list[str]] | None = None,
        sem_callback: bool = False,
    ):
        self.docs = set(docs)
        self.falhas = falhas or {}
        self.sem_callback = sem_callback

    def collection(self, _: str) -> "ClienteFalso":
        return self

    def document(self, id: str) -> str:
        return id

    def where(self, filter: Any) -> ConsultaFalsa:
        return ConsultaFalsa(self).where(filter)

    def bulk_writer(self, _: Any = None) -> EscritorFalso:
        return EscritorFalso(self)


def ids(n: int) -> list[str]:
    return [f"teste_{i:07d}" for i in range(n)]


def test_apagar_colecao_vazia(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    r = apagar(ClienteFalso([]))
    assert (r.confirmados, r.motivo, r.faltou) == (0, None, False)
    assert _roda(monkeypatch, ClienteFalso([])) == 0
    assert "0 apagados nesta rodada" in capsys.readouterr().out


def test_apagar_tudo_confirmado_em_varios_lotes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(firestore_em_escala, "LOTE_DO_APAGAR", 2)
    c = ClienteFalso(ids(5))
    r = apagar(c)
    assert (r.confirmados, r.faltou) == (5, False)
    assert not c.docs


def test_apagar_falha_transitoria_que_se_recupera_nao_e_falha(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def falhas() -> dict[
        str, list[str]
    ]:  # nova a cada uso: o escritor falso consome a lista
        return {"teste_0000000": ["indisponivel"]}

    r = apagar(ClienteFalso(ids(2), falhas()))
    assert (r.confirmados, r.motivo, r.faltou) == (2, None, False)
    c = ClienteFalso(ids(2), falhas())
    assert _roda(monkeypatch, c) == 0
    assert not c.falhas.get("teste_0000000"), "o comando passou pela falha transitória"
    saida = capsys.readouterr().out
    assert "2 apagados nesta rodada" in saida and "Faltou" not in saida


def test_apagar_falha_definitiva_para_com_o_primeiro_motivo() -> None:
    c = ClienteFalso(ids(3), {"teste_0000001": ["sem permissao"] * 100})
    r = apagar(c)
    assert (r.confirmados, r.faltou, r.motivo) == (2, True, "sem permissao")
    assert c.docs == {"teste_0000001"}


def test_apagar_lote_sem_callback_termina_e_nao_inventa_motivo() -> None:
    c = ClienteFalso(ids(3), sem_callback=True)
    r = apagar(c)
    assert (r.confirmados, r.faltou, r.motivo) == (0, True, None)


def test_apagar_retoma_na_nova_rodada(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = ClienteFalso(ids(3), {"teste_0000001": ["x"] * 4})
    assert apagar(c).faltou
    c = ClienteFalso(ids(3), {"teste_0000001": ["x"] * 4})
    assert _roda(monkeypatch, c) != 0
    assert "Faltou confirmação" in capsys.readouterr().out
    assert _roda(monkeypatch, c) == 0
    assert "apagados nesta rodada" in capsys.readouterr().out
    assert not c.docs


def test_apagar_nunca_toca_documento_fora_do_prefixo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = ClienteFalso([*ids(2), "job_real", "teste", "testf_1"])
    assert _roda(monkeypatch, c) == 0
    assert "2 apagados nesta rodada" in capsys.readouterr().out
    assert c.docs == {"job_real", "teste", "testf_1"}


def _roda(monkeypatch: pytest.MonkeyPatch, cliente: ClienteFalso) -> int:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setattr(firestore_em_escala, "cliente_do_firestore", lambda _: cliente)
    return main(["apagar"])


def test_comando_apagar_informa_e_sai_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _roda(monkeypatch, ClienteFalso(ids(3))) == 0
    assert "3 apagados nesta rodada" in capsys.readouterr().out


def test_comando_apagar_com_falha_sai_diferente_de_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    c = ClienteFalso(ids(3), {"teste_0000001": ["sem permissao"] * 100})
    assert _roda(monkeypatch, c) != 0
    saida = capsys.readouterr().out
    assert "2 apagados nesta rodada" in saida
    assert "restam 1" in saida and "sem permissao" in saida


def test_comando_apagar_sem_callback_diz_que_faltou_confirmacao(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _roda(monkeypatch, ClienteFalso(ids(2), sem_callback=True)) != 0
    saida = capsys.readouterr().out
    assert (
        "Faltou confirmação" in saida
        and "sem motivo conhecido" in saida
        and "restam 2" in saida
    )
