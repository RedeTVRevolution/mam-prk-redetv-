"""Um `TestClient` que pede o histórico inteiro (`desde=&ate=`) quando o teste não escolhe período.

Sem isso, os testes de dados em datas fixas cairiam no período padrão (#462: os últimos 7 dias).
O período padrão em si é testado com o cliente comum."""

from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient


class ClienteSemPeriodoPadrao(TestClient):
    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        params = dict(kwargs.get("params") or {})
        na_url = parse_qs(urlsplit(str(url)).query, keep_blank_values=True)
        if not {"desde", "ate"} & (params.keys() | na_url.keys()):
            params.update(desde="", ate="")
        kwargs["params"] = params
        return super().request(method, url, **kwargs)
