import random
import threading
from typing import Any

from api.carga_dev import (
    Medidas,
    Transporte,
    Usuario,
    consultas_da_sonda,
    percentil,
    rodar,
)


def test_percentil_posto_mais_proximo() -> None:
    v = [float(n) for n in range(1, 101)]
    assert [percentil(v, p) for p in (50, 95, 99, 100)] == [50, 95, 99, 100]


def test_relatorio_conta_erros_e_buscas() -> None:
    m = Medidas()
    for s in (200, 200, 429, 504):
        m.registrar("GET /v1/busca", s, 0.1)
    m.registrar("GET /v1/jobs", 200, 0.2)
    assert m.buscas() == (4, 3)
    assert m.falhas() == 2
    texto = m.texto()
    assert "429:1 504:1" in texto and "Total de pedidos: 5 (2 com erro)" in texto
    assert "Buscas feitas: 4 enviadas, 3 executadas" in texto


def transporte_falso(chamadas: list[tuple[str, str]]) -> Transporte:
    def chamar(
        metodo: str, caminho: str, params: dict[str, Any] | None, corpo: Any
    ) -> tuple[int, Any]:
        chamadas.append((metodo, caminho))
        if caminho == "/v1/busca":
            return 200, {
                "videos": [
                    {"job_id": "j1", "momentos": [{"quadro": "quadros/plano-6.jpg"}]}
                ]
            }
        if caminho == "/v1/jobs":
            return 200, [{"id": "j2", "estado": "concluido"}]
        return 200, {}

    return chamar


def test_roteiro_so_le_e_usa_ids_vistos() -> None:
    chamadas: list[tuple[str, str]] = []
    medidas = Medidas()
    pessoa = Usuario(transporte_falso(chamadas), medidas, ["terno"], random.Random(1))
    for _ in range(30):
        pessoa.agir()
    assert {m for m, c in chamadas if c != "/v1/jobs/quadros"} == {"GET"}
    assert ("POST", "/v1/jobs/quadros") in chamadas
    assert any(c.endswith("/decupagem") for _, c in chamadas)
    assert medidas.falhas() == 0


def test_rodar_encerra_pela_duracao() -> None:
    chamadas: list[tuple[str, str]] = []
    medidas = Medidas()
    rodar(
        [transporte_falso(chamadas)],
        3,
        0.2,
        0.05,
        lambda: 0.01,
        ["x"],
        medidas,
        threading.Event(),
    )
    assert medidas.total() > 3


def test_termos_da_sonda() -> None:
    assert "terno" in consultas_da_sonda()
