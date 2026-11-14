"""Falta variável do leitor de Decupagens: todo ponto de entrada sai com 2 e "erro: X não está no ambiente" (#639)."""

from collections.abc import Callable
from typing import Any

import pytest

from api import (
    analise,
    carregar_marcas,
    copiar_para_bigquery,
    correcao_de_estado,
    gravar_versao_nos_jobs,
    identificacao_job,
    indexacao,
    preencher_catalogo_dos_jobs,
    regressao,
    reprocessar_versao,
    taxa_de_correcao,
    taxa_diaria,
)
from api.ferramentas import comparar_passadas

NOMES = ("GCP_PROJECT_ID", "BUCKET_ACEITOS", "BUCKET_DECUPAGENS")


def _codigo(chamar: Callable[[], Any]) -> int:
    try:
        resultado = chamar()
    except SystemExit as e:
        return int(e.code or 0)  # type: ignore[call-overload]
    return int(resultado)


# Os que leem `os.environ`: o teste tira a variável do ambiente do processo.
DO_PROCESSO: dict[str, Callable[[], Any]] = {
    "analise": analise.main,
    "identificacao_job": identificacao_job.main,
    "indexacao": lambda: indexacao.main([]),
    "copiar_para_bigquery": lambda: copiar_para_bigquery.main([]),
    "gravar_versao_nos_jobs": gravar_versao_nos_jobs.main,
    "preencher_catalogo_dos_jobs": preencher_catalogo_dos_jobs.main,
    "carregar_marcas": carregar_marcas.main,
    "taxa_diaria": lambda: taxa_diaria.main([]),
}

# Os que recebem o ambiente por parâmetro.
DO_PARAMETRO: dict[str, Callable[[dict[str, str]], Any]] = {
    "correcao_de_estado": lambda a: correcao_de_estado._do_ambiente([], a),
    "regressao": lambda a: regressao.main([], a),
    "reprocessar_versao": lambda a: reprocessar_versao.main([], a),
    "taxa_de_correcao": lambda a: taxa_de_correcao.main([], a),
    "comparar_passadas": lambda a: comparar_passadas.main(["j1"], a),
}


@pytest.mark.parametrize("nome", NOMES)
@pytest.mark.parametrize("ponto", DO_PROCESSO)
def test_entrada_do_processo_sai_com_2(
    ponto: str,
    nome: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for n in NOMES:
        monkeypatch.setenv(n, "x")
    monkeypatch.delenv(nome)
    # Para a cópia do BigQuery configurada: o teste é só da falta do leitor.
    monkeypatch.setattr(copiar_para_bigquery, "copia_do_ambiente", lambda _: object())
    assert _codigo(DO_PROCESSO[ponto]) == 2
    assert f"erro: {nome} não está no ambiente" in capsys.readouterr().err


@pytest.mark.parametrize("nome", NOMES)
@pytest.mark.parametrize("ponto", DO_PARAMETRO)
def test_entrada_com_ambiente_sai_com_2(
    ponto: str, nome: str, capsys: pytest.CaptureFixture[str]
) -> None:
    ambiente = {n: "x" for n in NOMES if n != nome}
    assert _codigo(lambda: DO_PARAMETRO[ponto](ambiente)) == 2
    assert f"erro: {nome} não está no ambiente" in capsys.readouterr().err
