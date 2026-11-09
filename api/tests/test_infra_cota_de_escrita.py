"""A cota de escrita da busca (#460, #472) chega a todos os que gravam pela mesma variável."""

import re
from pathlib import Path

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
MAIN = (MODULO / "main.tf").read_text()
PURGA = (MODULO / "purga.tf").read_text()


def _bloco(texto: str, cabecalho: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index("\n}\n", inicio)]


def test_a_cota_chega_ao_web_ao_purga_e_a_indexacao_pela_mesma_variavel() -> None:
    blocos = {
        "web": _bloco(MAIN, 'resource "google_cloud_run_v2_service" "web"'),
        "indexacao": _bloco(MAIN, 'resource "google_cloud_run_v2_job" "indexacao"'),
        "purga": _bloco(PURGA, 'resource "google_cloud_run_v2_job" "purga"'),
    }
    for nome, bloco in blocos.items():
        assert re.search(
            r'name\s*=\s*"BUSCA_COTA_DE_ESCRITA"\s*value\s*=\s*'
            r"tostring\(var\.cota_de_escrita_da_busca\)",
            bloco,
        ), nome


def test_colecao_de_texto_chega_aos_tres_escritores_e_aos_outputs() -> None:
    for texto, cabecalho in (
        (MAIN, 'resource "google_cloud_run_v2_service" "web"'),
        (MAIN, 'resource "google_cloud_run_v2_job" "indexacao"'),
        (PURGA, 'resource "google_cloud_run_v2_job" "purga"'),
    ):
        assert re.search(
            r'name\s*=\s*"BUSCA_COLECAO_DE_TEXTO"\s*value\s*=\s*local\.colecao_de_texto_da_busca',
            _bloco(texto, cabecalho),
        )
    assert 'output "busca_colecao_de_texto"' in MAIN
    for raiz in (
        MODULO.parents[1] / "main.tf",
        MODULO.parents[1] / "ambientes/prod/main.tf",
    ):
        assert 'output "busca_colecao_de_texto"' in raiz.read_text()
    makefile = (MODULO.parents[2] / "Makefile").read_text()
    assert "BUSCA_COLECAO_DE_TEXTO=" in makefile
    assert "output -raw busca_colecao_de_texto" in makefile
