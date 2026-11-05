"""Escala do serviço web (#357): teto de instâncias, memória e pedidos por instância."""

import re
from pathlib import Path

MAIN = (Path(__file__).parents[2] / "infra" / "modulos" / "mam" / "main.tf").read_text()


def _bloco(cabecalho: str) -> str:
    """O bloco de topo que começa em `cabecalho`, até a chave que o fecha, sem comentários."""
    inicio = MAIN.index(cabecalho)
    bloco = MAIN[inicio : MAIN.index("\n}\n", inicio)]
    return "\n".join(
        linha for linha in bloco.splitlines() if not linha.strip().startswith("#")
    )


def _web() -> str:
    return _bloco('resource "google_cloud_run_v2_service" "web"')


def test_o_web_escala_ate_10_instancias_sem_nenhuma_sempre_ligada() -> None:
    web = _web()

    assert re.search(r"max_instance_count\s*=\s*10\b", web)
    # O mínimo fica em 0: ou não é declarado, ou é declarado como 0.
    minimos = re.findall(r"min_instance_count\s*=\s*(\S+)", web)
    assert all(m == "0" for m in minimos)


def test_o_web_tem_2gi_de_memoria_1_cpu_e_40_pedidos_por_instancia() -> None:
    web = _web()
    limites = re.search(r"limits\s*=\s*\{([^}]*)\}", web)

    assert limites
    assert re.search(r'memory\s*=\s*"2Gi"', limites.group(1))
    assert re.search(r'cpu\s*=\s*"1"', limites.group(1))
    assert re.search(r"max_instance_request_concurrency\s*=\s*40\b", web)


def test_o_web_so_usa_cpu_durante_os_pedidos() -> None:
    # Com o bloco resources declarado, o provider só mantém a CPU ociosa liberada
    # se cpu_idle vier explícito; sem ele a cobrança passa a ser por instância.
    assert re.search(r"cpu_idle\s*=\s*true\b", _web())
