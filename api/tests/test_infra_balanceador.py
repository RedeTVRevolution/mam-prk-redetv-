"""O balanceador HTTPS na frente do Cloud Run, ligado só com `dominio` (#294)."""

import re
from pathlib import Path

import pytest

INFRA = Path(__file__).parents[2] / "infra"
MODULO = INFRA / "modulos" / "mam"
BALANCEADOR = (MODULO / "balanceador.tf").read_text()
MAIN = (MODULO / "main.tf").read_text()

RECURSOS = [
    "google_compute_global_address",
    "google_compute_region_network_endpoint_group",
    "google_compute_backend_service",
    "google_compute_url_map",
    "google_compute_managed_ssl_certificate",
    "google_compute_target_https_proxy",
    "google_compute_global_forwarding_rule",
    "google_compute_target_http_proxy",
]


def _bloco(texto: str, cabecalho: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index("\n}\n", inicio)]


def test_o_dominio_vem_por_variavel_e_vazio_por_padrao() -> None:
    corpo = _bloco(MAIN, 'variable "dominio"')

    assert 'default     = ""' in corpo


def test_com_dominio_vazio_nenhum_recurso_do_balanceador_nasce() -> None:
    blocos = re.findall(
        r'^resource "(\w+)" "\w+" \{\n(.*?)^\}', BALANCEADOR, re.DOTALL | re.MULTILINE
    )

    assert {tipo for tipo, _ in blocos} >= set(RECURSOS)
    for tipo, corpo in blocos:
        assert re.search(
            r"^  count\s*= local\.balanceador \? 1 : 0$", corpo, re.MULTILINE
        ), tipo
    assert re.search(r'balanceador\s*= var\.dominio != ""', BALANCEADOR)


def test_o_certificado_e_gerenciado_para_o_dominio() -> None:
    certificado = _bloco(
        BALANCEADOR, 'resource "google_compute_managed_ssl_certificate"'
    )

    assert "domains = [var.dominio]" in certificado
    assert "create_before_destroy = true" in certificado


def test_o_http_redireciona_para_https() -> None:
    http = _bloco(
        BALANCEADOR, 'resource "google_compute_global_forwarding_rule" "http"'
    )
    https = _bloco(
        BALANCEADOR, 'resource "google_compute_global_forwarding_rule" "https"'
    )
    redireciona = _bloco(
        BALANCEADOR, 'resource "google_compute_url_map" "redireciona_para_https"'
    )
    proxy_http = _bloco(
        BALANCEADOR,
        'resource "google_compute_target_http_proxy" "redireciona_para_https"',
    )

    assert re.search(r'port_range\s*= "80"', http)
    assert "google_compute_target_http_proxy.redireciona_para_https[0].id" in http
    assert re.search(r'port_range\s*= "443"', https)
    assert "google_compute_target_https_proxy.web[0].id" in https
    assert "google_compute_url_map.redireciona_para_https[0].id" in proxy_http
    assert re.search(r"https_redirect\s*= true", redireciona)


def test_o_back_end_e_o_servico_web_por_neg_serverless() -> None:
    neg = _bloco(BALANCEADOR, 'resource "google_compute_region_network_endpoint_group"')

    assert 'network_endpoint_type = "SERVERLESS"' in neg
    assert "service = google_cloud_run_v2_service.web.name" in neg


def test_com_balanceador_o_cloud_run_so_aceita_o_balanceador() -> None:
    web = _bloco(MAIN, 'resource "google_cloud_run_v2_service" "web"')

    assert re.search(
        r'ingress\s*=\s*local\.balanceador \? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_ALL"',
        web,
    )


def test_o_cors_e_o_login_incluem_o_dominio() -> None:
    cors = _bloco(MAIN, 'resource "google_storage_bucket" "mam"')
    login = _bloco(MAIN, 'resource "google_identity_platform_config" "mam"')
    origens = re.search(r"^  origens_da_aplicacao\s*=(.*)$", MAIN, re.MULTILINE)
    dominios = re.search(r"^  authorized_domains\s*=(.*)$", login, re.MULTILINE)

    assert "origin          = local.origens_da_aplicacao" in cors
    assert origens and 'local.balanceador ? ["https://${var.dominio}"]' in origens[1]
    assert dominios and re.search(
        r"local\.balanceador \? \[.*var\.dominio\] : null", dominios[1]
    )


def test_o_endereco_e_o_dominio_com_o_balanceador_e_o_run_app_sem_ele() -> None:
    url = _bloco(MAIN, 'output "url"')
    ip = _bloco(BALANCEADOR, 'output "ip_do_balanceador"')

    assert (
        'local.balanceador ? "https://${var.dominio}" : google_cloud_run_v2_service.web.uri'
        in url
    )
    assert re.search(r"local\.balanceador \? .* : null", ip)


def test_o_deploy_so_testa_o_dominio_com_o_certificado_ativo() -> None:
    deploy = (INFRA.parent / "scripts" / "deploy-dev.sh").read_text()
    certificado = deploy.index("tf output -json certificado_do_balanceador")
    ativo = deploy.index("!= ACTIVE ]]", certificado)
    teste = deploy.index('curl -sSf "$URL/v1/health"', ativo)

    assert certificado < ativo < teste


def test_o_endereco_sai_como_output_e_o_dominio_chega_aos_tres_ambientes() -> None:
    assert 'output "ip_do_balanceador"' in BALANCEADOR
    assert 'output "ip_do_balanceador"' in (INFRA / "main.tf").read_text()
    for main in (
        INFRA / "main.tf",
        INFRA / "ambientes" / "staging" / "main.tf",
        INFRA / "ambientes" / "prod" / "main.tf",
    ):
        texto = main.read_text()
        assert re.search(r"^\s*dominio\s*= var\.dominio$", texto, re.MULTILINE), main
        assert 'variable "dominio"' in texto, main


@pytest.mark.parametrize("assunto", ["registro A", "certificado", "US$"])
def test_o_readme_diz_o_registro_de_dns_a_espera_do_certificado_e_o_custo(
    assunto: str,
) -> None:
    assert assunto in (INFRA / "README.md").read_text()
