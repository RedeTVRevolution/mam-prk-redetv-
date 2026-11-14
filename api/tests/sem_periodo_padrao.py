"""Um `TestClient` que pede o histórico inteiro (`desde=&ate=`) quando o teste não escolhe período.

Sem isso, os testes de dados em datas fixas cairiam no período padrão (#462: os últimos 7 dias).
O período padrão em si é testado com o cliente comum."""

from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient


class ClienteSemPeriodoPadrao(TestClient):
    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        # Pares (nome, valor) ou dicionário; o nome repetido (`tipo=a&tipo=b`) se mantém.
        params = kwargs.get("params") or {}
        pares = list(params.items() if isinstance(params, dict) else params)
        na_url = parse_qs(urlsplit(str(url)).query, keep_blank_values=True)
        if not {"desde", "ate"} & ({n for n, _ in pares} | na_url.keys()):
            pares += [("desde", ""), ("ate", "")]
        kwargs["params"] = pares
        return super().request(method, url, **kwargs)
