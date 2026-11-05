"""O gRPC não pode registrar handler de `fork` (#385): o ffmpeg sobe por `subprocess` num
processo com o cliente do Firestore aberto, e sob carga o handler aborta o filho."""

import os
import subprocess
import sys


def _python(codigo: str, env: dict[str, str]) -> str:
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=60,
    )
    return resultado.stdout.strip()


def _ambiente(**extra: str) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k != "GRPC_ENABLE_FORK_SUPPORT"}
    return {**base, **extra}


def test_importar_a_api_desliga_o_fork_do_grpc_antes_do_grpc() -> None:
    codigo = (
        "import os, sys, api; "
        "assert 'grpc' not in sys.modules; "
        "print(os.environ['GRPC_ENABLE_FORK_SUPPORT'])"
    )
    assert _python(codigo, _ambiente()) == "false"


def test_o_gRPC_de_fato_le_a_variavel() -> None:
    codigo = "import api, grpc; from grpc._cython import cygrpc; print(cygrpc._GRPC_ENABLE_FORK_SUPPORT)"
    assert _python(codigo, _ambiente()) == "False"


def test_valor_posto_de_fora_vence() -> None:
    codigo = "import os, api; print(os.environ['GRPC_ENABLE_FORK_SUPPORT'])"
    assert _python(codigo, _ambiente(GRPC_ENABLE_FORK_SUPPORT="true")) == "true"
