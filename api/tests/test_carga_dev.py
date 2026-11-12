import os
import random
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest

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
    # Pares dos termos, para a busca não cair quase sempre no cache de 60 s.
    assert len(set(consultas_da_sonda())) > 400


def test_interrupcao_para_todos_os_usuarios_logo() -> None:
    def interrompe(
        metodo: str, caminho: str, params: dict[str, Any] | None, corpo: Any
    ) -> tuple[int, Any]:
        raise KeyboardInterrupt

    parar = threading.Event()
    inicio = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        rodar(
            [interrompe, transporte_falso([])],
            4,
            60,
            0,
            lambda: 0.01,
            ["x"],
            Medidas(),
            parar,
        )
    assert parar.is_set() and time.monotonic() - inicio < 5


def test_pedido_nao_iniciado_nao_sai_depois_da_parada() -> None:
    chamadas: list[tuple[str, str]] = []
    parar = threading.Event()

    def para_na_primeira(
        metodo: str, caminho: str, params: dict[str, Any] | None, corpo: Any
    ) -> tuple[int, Any]:
        chamadas.append((metodo, caminho))
        parar.set()  # a parada chega com o primeiro pedido no ar
        return 200, {
            "id": "j1",
            "videos": [{"job_id": "j1", "momentos": [{"quadro": "q/a.jpg"}]}],
        }

    pessoa = Usuario(para_na_primeira, Medidas(), ["x"], random.Random(1), parar)
    pessoa._ids = ["j1"]
    pessoa.abrir()  # dois pedidos
    pessoa.buscar()  # busca + quadros
    assert len(chamadas) == 1


def test_relatorio_mostra_concluidos_e_no_ar() -> None:
    m = Medidas()
    m.iniciar()
    m.registrar("GET /v1/jobs", 200, 0.1)
    m.iniciar()  # fica no ar
    texto = m.copia().texto()
    assert "Total de pedidos: 1 (0 com erro)" in texto
    assert "No ar na parada: 1" in texto
    assert "No ar na parada" not in Medidas().texto()


def test_copia_nao_muda_quando_pedido_termina_depois() -> None:
    m = Medidas()
    m.iniciar()
    c = m.copia()
    m.registrar("GET /v1/jobs", 500, 0.1)
    assert (c.total(), c.falhas(), c.no_ar) == (0, 0, 1)
    assert (m.total(), m.falhas(), m.no_ar) == (1, 1, 0)


def test_fim_normal_espera_pedido_que_demora() -> None:
    def lento(
        metodo: str, caminho: str, params: dict[str, Any] | None, corpo: Any
    ) -> tuple[int, Any]:
        time.sleep(0.5)  # passa da duração
        return 200, {}

    medidas = Medidas()
    rodar([lento], 1, 0.1, 0, lambda: 0.01, ["x"], medidas, threading.Event())
    assert medidas.total() >= 1 and medidas.no_ar == 0


def test_sigint_termina_o_processo_sem_esperar_o_pedido_bloqueado(
    tmp_path: Path,
) -> None:
    marca = tmp_path / "bloqueado"
    codigo = textwrap.dedent(
        f"""
        import signal, sys, threading
        signal.signal(signal.SIGINT, signal.default_int_handler)
        import api.carga_dev as c
        def transporte(url, token):
            def chamar(*a):
                open({str(marca)!r}, "w").close()
                threading.Event().wait(120)  # o pedido preso
                return 200, {{}}
            return chamar
        c.transporte_http = transporte
        sys.exit(c.main())
        """
    )
    env = {
        **os.environ,
        "URL": "http://x",
        "TOKEN": "t",
        "USUARIOS": "2",
        "RAMPA_S": "0",
        "DURACAO_S": "300",
        "PAUSA_S": "1",
    }
    raiz = Path(__file__).parents[2]
    proc = subprocess.Popen(
        [sys.executable, "-c", codigo],
        cwd=raiz,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        fim = time.monotonic() + 60
        while not marca.exists():
            assert time.monotonic() < fim and proc.poll() is None
            time.sleep(0.05)
        proc.send_signal(signal.SIGINT)
        inicio = time.monotonic()
        proc.wait(timeout=20)
        assert time.monotonic() - inicio < 15
        assert proc.returncode == 1  # nenhum pedido concluído
    finally:
        proc.kill()
        proc.communicate()
