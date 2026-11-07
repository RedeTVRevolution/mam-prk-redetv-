"""Um `TestClient` que pede o histórico inteiro (`desde=&ate=`) quando o teste não escolhe período.

Sem isso, os testes de dados em datas fixas cairiam no período padrão (#462: os últimos 7 dias).
O período padrão em si é testado com o cliente comum."""

from typing import Any

from fastapi.testclient import TestClient


class ClienteSemPeriodoPadrao(TestClient):
    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        params = dict(kwargs.get("params") or {})
        if "desde" not in params and "ate" not in params and "desde=" not in str(url):
            params.update(desde="", ate="")
        kwargs["params"] = params
        return super().request(method, url, **kwargs)
