"""Escala do serviço web (#357): teto de instâncias, memória e pedidos por instância."""

import re
from pathlib import Path

MAIN = (Path(__file__).parents[2] / "infra" / "modulos" / "mam" / "main.tf").read_text()


def _web() -> str:
    inicio = MAIN.index('resource "google_cloud_run_v2_service" "web"')
    return MAIN[inicio:].split("\nresource ")[0]


def _sem_comentarios(texto: str) -> str:
    return "\n".join(l for l in texto.splitlines() if not l.strip().startswith("#"))


def test_o_web_escala_ate_10_instancias_sem_nenhuma_sempre_ligada() -> None:
    web = _sem_comentarios(_web())

    assert re.search(r"max_instance_count\s*=\s*10\b", web)
    # O mínimo fica em 0: ou não é declarado, ou é declarado como 0.
    minimos = re.findall(r"min_instance_count\s*=\s*(\S+)", web)
    assert all(m == "0" for m in minimos)


def test_o_web_tem_2gi_de_memoria_1_cpu_e_40_pedidos_por_instancia() -> None:
    web = _sem_comentarios(_web())

    assert re.search(r'memory\s*=\s*"2Gi"', web)
    assert re.search(r'cpu\s*=\s*"1"', web)
    assert re.search(r"max_instance_request_concurrency\s*=\s*40\b", web)
