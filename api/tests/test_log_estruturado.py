"""Log estruturado (#475): texto de usuário é campo do JSON, nunca linha nova."""

import io
import json
import logging

from api.log_estruturado import FormatadorJson


def _linhas(registrar) -> list[str]:  # type: ignore[no-untyped-def]
    saida = io.StringIO()
    manejador = logging.StreamHandler(saida)
    manejador.setFormatter(FormatadorJson())
    log = logging.getLogger("teste.log_estruturado")
    log.handlers = [manejador]
    log.propagate = False
    registrar(log)
    return saida.getvalue().splitlines()


def test_texto_com_quebra_de_linha_sai_como_campo_do_json_sem_criar_linha() -> None:
    forjado = "sapato\nERROR api.main: acesso liberado"

    linhas = _linhas(lambda log: log.warning("consulta falhou (%s)", forjado))

    assert len(linhas) == 1
    registro = json.loads(linhas[0])
    assert registro["message"] == f"consulta falhou ({forjado})"
    assert registro["severity"] == "WARNING"


def test_a_excecao_tambem_fica_numa_linha_so() -> None:
    def registrar(log: logging.Logger) -> None:
        try:
            raise ValueError("a\nb")
        except ValueError:
            log.exception("falhou")

    linhas = _linhas(registrar)

    assert len(linhas) == 1
    assert "ValueError: a\nb" in json.loads(linhas[0])["exception"]
