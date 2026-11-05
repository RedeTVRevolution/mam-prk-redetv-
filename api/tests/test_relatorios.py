"""A leitura da resposta do BigQuery nos relatórios: todas as páginas (#363)."""

from typing import Any

import pytest

from api.relatorios import linhas_da_consulta


class Paginas:
    """Dublê do transporte: devolve as respostas na ordem e guarda os pedidos."""

    def __init__(self, *respostas: dict[str, Any]) -> None:
        self.respostas = list(respostas)
        self.corpos: list[dict[str, Any]] = []

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return self.respostas.pop(0)


def _linha(*valores: str) -> dict[str, Any]:
    return {"f": [{"v": v} for v in valores]}


def _duas_paginas() -> Paginas:
    return Paginas(
        {
            "jobComplete": True,
            "jobReference": {"projectId": "p", "jobId": "job-1", "location": "US"},
            "rows": [_linha("a", "1")],
            "pageToken": "t1",
        },
        {"jobComplete": True, "rows": [_linha("b", "2"), _linha("c", "3")]},
    )


def test_resultado_em_duas_paginas_junta_as_duas() -> None:
    transporte = _duas_paginas()

    linhas = linhas_da_consulta(transporte, "regiao", "SELECT 1")

    assert linhas == [["a", "1"], ["b", "2"], ["c", "3"]]
    assert transporte.respostas == []


def test_a_pagina_seguinte_pede_o_job_a_regiao_e_o_token_da_primeira() -> None:
    transporte = _duas_paginas()

    linhas_da_consulta(transporte, "regiao", "SELECT 1")

    primeira, segunda = transporte.corpos
    assert primeira["query"] == "SELECT 1"
    assert segunda == {
        "jobId": "job-1",
        "location": "US",
        "pageToken": "t1",
        "maxResults": 100_000,
    }


def test_transporte_http_pede_a_pagina_seguinte_com_get_no_job(
    monkeypatch: Any,
) -> None:
    import google.auth
    import google.auth.transport.requests

    import api.copia_bigquery as copia

    chamadas: list[tuple[str, str, dict[str, Any]]] = []

    class Sessao:
        def __init__(self, credenciais: object) -> None: ...

        def _responde(self, metodo: str, url: str, **kw: Any) -> Any:
            chamadas.append((metodo, url, kw))
            return type(
                "R", (), {"ok": True, "json": lambda _: {"jobComplete": True}}
            )()

        def get(self, url: str, **kw: Any) -> Any:
            return self._responde("GET", url, **kw)

        def post(self, url: str, **kw: Any) -> Any:
            return self._responde("POST", url, **kw)

    monkeypatch.setattr(google.auth, "default", lambda scopes: (None, "p"))
    monkeypatch.setattr(google.auth.transport.requests, "AuthorizedSession", Sessao)
    chamar = copia.transporte_http("proj")

    chamar({"query": "SELECT 1"})
    chamar({"jobId": "job-1", "location": "US", "pageToken": "t1"})

    (m1, url1, kw1), (m2, url2, kw2) = chamadas
    assert (m1, url1, kw1["json"]) == (
        "POST",
        f"{copia.URL_BASE}/projects/proj/queries",
        {"query": "SELECT 1"},
    )
    assert (m2, url2) == ("GET", f"{copia.URL_BASE}/projects/proj/queries/job-1")
    assert kw2["params"] == {"location": "US", "pageToken": "t1"}


def test_pagina_sem_o_job_vira_erro_de_consulta_e_nao_key_error() -> None:
    transporte = Paginas({"jobComplete": True, "rows": [], "pageToken": "t1"})

    with pytest.raises(RuntimeError, match="paginada sem o job"):
        linhas_da_consulta(transporte, "regiao", "SELECT 1")
