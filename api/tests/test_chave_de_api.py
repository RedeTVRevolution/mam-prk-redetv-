import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.analise import executar
from api.auth import Escopo, Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
    main,
)
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.programas import PERFIS
from api.tests.test_analise import SHA, DecupagensEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_gemini import BOA, TransporteFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
MAC_V1 = MacSimulado({1: b"k1"}, versao_atual=1)
MAC_V2 = MacSimulado({1: b"k1", 2: b"k2"}, versao_atual=2)
TODOS: list[Escopo] = ["cancelar", "criar", "ler"]
NOVO_JOB = {
    "nome": "a.mp4",
    "tamanho_bytes": 10,
    "tipo": "video/mp4",
    "data_exibicao": "2026-10-01",
}


def _ambiente(mac: MacSimulado = MAC_V1) -> tuple[RepositorioDeChavesEmMemoria, str]:
    chaves = RepositorioDeChavesEmMemoria()
    return chaves, emitir_chave("Sistema Legado", TODOS, mac, chaves, BASE).chave


def _cliente(
    chaves: RepositorioDeChavesEmMemoria,
    mac: MacSimulado = MAC_V1,
    jobs: RepositorioEmMemoria | None = None,
) -> TestClient:
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            jobs or RepositorioEmMemoria(),
            ArmazenamentoFalso(),
            chaves=VerificadorDeChaveDeApi(chaves, mac),
        )
    )


def test_chave_emitida_lista_jobs() -> None:
    chaves, chave = _ambiente()

    resposta = _cliente(chaves).get("/v1/jobs", headers={"X-API-Key": chave})

    assert resposta.status_code == 200


def test_eu_responde_o_sistema() -> None:
    chaves, chave = _ambiente()

    resposta = _cliente(chaves).get("/v1/eu", headers={"X-API-Key": chave})

    assert resposta.json() == {"sistema": "Sistema Legado", "escopos": TODOS}


def test_chave_tem_prefixo_do_sistema_e_256_bits() -> None:
    _, chave = _ambiente()

    prefixo, id_publico, segredo = chave.split(".")
    assert prefixo == "sistema-legado"
    assert len(id_publico) == 16
    assert len(segredo) >= 43  # 256 bits em base64url


def _adulterar(chave: str) -> str:
    return chave[:-1] + ("A" if chave[-1] != "A" else "B")


@pytest.mark.parametrize(
    "mudar",
    [
        lambda c: "lixo",
        lambda c: "",
        _adulterar,
        lambda c: ".".join([*c.split(".")[:2], "segredo-errado"]),
        lambda c: ".".join([c.split(".")[0], "0" * 16, c.split(".")[2]]),
    ],
)
def test_chave_invalida_recebe_401(mudar) -> None:  # type: ignore[no-untyped-def]
    chaves, chave = _ambiente()

    resposta = _cliente(chaves).get("/v1/jobs", headers={"X-API-Key": mudar(chave)})

    assert resposta.status_code == 401


def test_bearer_e_chave_juntos_recebem_401() -> None:
    chaves, chave = _ambiente()

    resposta = _cliente(chaves).get(
        "/v1/jobs",
        headers={"X-API-Key": chave, "Authorization": "Bearer token-bom"},
    )

    assert resposta.status_code == 401


def test_sem_adaptador_a_api_recusa_toda_chave() -> None:
    _, chave = _ambiente()

    resposta = TestClient(criar_app()).get("/v1/jobs", headers={"X-API-Key": chave})

    assert resposta.status_code == 401


def test_repositorio_nao_guarda_a_chave_em_texto() -> None:
    chaves, chave = _ambiente()

    registro = next(iter(chaves.todas()))
    assert chave not in str(registro.model_dump())
    assert chave.split(".")[2] not in str(registro.model_dump())
    assert registro.sistema == "Sistema Legado"
    assert registro.versao_mac == 1


def test_chave_nao_aparece_em_log(caplog: pytest.LogCaptureFixture) -> None:
    chaves, chave = _ambiente()
    segredo = chave.split(".")[2]

    with caplog.at_level(logging.DEBUG):
        resposta = _cliente(chaves).get("/v1/jobs", headers={"X-API-Key": chave})
        ruim = _cliente(chaves).get(
            "/v1/jobs", headers={"X-API-Key": _adulterar(chave)}
        )

    assert segredo not in caplog.text
    assert segredo not in resposta.text + ruim.text


def test_hash_de_versao_antiga_e_aceito_e_regravado() -> None:
    chaves, chave = _ambiente(MAC_V1)
    id_publico = chave.split(".")[1]

    resposta = _cliente(chaves, MAC_V2).get("/v1/jobs", headers={"X-API-Key": chave})

    assert resposta.status_code == 200
    registro = chaves.obter(id_publico)
    assert registro is not None
    assert registro.versao_mac == 2
    # Já regravado, continua valendo.
    assert (
        _cliente(chaves, MAC_V2)
        .get("/v1/jobs", headers={"X-API-Key": chave})
        .status_code
        == 200
    )


def test_post_com_chave_grava_o_sistema_no_job() -> None:
    chaves, chave = _ambiente()
    jobs = RepositorioEmMemoria()

    resposta = _cliente(chaves, jobs=jobs).post(
        "/v1/jobs", json=NOVO_JOB, headers={"X-API-Key": chave}
    )

    assert resposta.status_code == 202
    (job,) = jobs.listar()
    assert job.sistema == "Sistema Legado"


def test_post_com_token_nao_tem_sistema() -> None:
    chaves, _ = _ambiente()
    jobs = RepositorioEmMemoria()

    _cliente(chaves, jobs=jobs).post(
        "/v1/jobs", json=NOVO_JOB, headers={"Authorization": "Bearer token-bom"}
    )

    (job,) = jobs.listar()
    assert (job.sistema, job.criado_por) == (None, "u1")


def test_comando_imprime_a_chave_uma_unica_vez_e_grava_so_o_hash() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    saida: list[str] = []

    codigo = main(["Sistema Legado", "ler"], MAC_V1, chaves, saida.append, lambda: BASE)

    assert codigo == 0
    (registro,) = chaves.todas()
    chave = next(linha for linha in saida if linha.startswith("sistema-legado."))
    assert sum(chave in linha for linha in saida) == 1
    assert chave not in str(registro.model_dump())
    assert registro.criada_em == BASE


def test_comando_sem_nome_do_sistema_nao_emite() -> None:
    chaves = RepositorioDeChavesEmMemoria()

    assert main([], MAC_V1, chaves, lambda _: None) == 2
    assert main(["", "ler"], MAC_V1, chaves, lambda _: None) == 2
    assert chaves.todas() == []


def test_sistema_consulta_status_com_etag_e_recebe_304() -> None:
    chaves, chave = _ambiente()
    cliente = _cliente(chaves)
    job_id = cliente.post(
        "/v1/jobs", json=NOVO_JOB, headers={"X-API-Key": chave}
    ).json()["id"]
    etag = cliente.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": chave}).headers[
        "ETag"
    ]

    resposta = cliente.get(
        f"/v1/jobs/{job_id}", headers={"X-API-Key": chave, "If-None-Match": etag}
    )

    assert resposta.status_code == 304


def _criar_com_chave(
    chaves: RepositorioDeChavesEmMemoria,
    chave: str,
    jobs: RepositorioEmMemoria | None = None,
    **corpo: object,
) -> Any:
    return _cliente(chaves, jobs=jobs).post(
        "/v1/jobs", json={**NOVO_JOB, **corpo}, headers={"X-API-Key": chave}
    )


def test_chave_cria_job_com_programa_e_data_e_o_perfil_chega_na_analise() -> None:
    chaves, chave = _ambiente()
    jobs = RepositorioEmMemoria()

    resposta = _criar_com_chave(
        chaves, chave, jobs, programa="TV Fama", data_exibicao="2026-10-01"
    )

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert (corpo["programa"], corpo["data_exibicao"]) == ("TV Fama", "2026-10-01")
    job = jobs.obter(corpo["id"])
    assert job is not None and job.sistema == "Sistema Legado"
    assert (job.programa, job.data_exibicao) == ("TV Fama", date(2026, 10, 1))
    # O programa guardado é o que a análise usa para escolher o perfil.
    job = job.model_copy(
        update={"estado": "analisando", "sha256": SHA, "duracao_s": 60.0}
    )
    jobs.salvar(job)
    transporte = TransporteFalso(BOA)
    executar(
        job.id,
        jobs,
        DecupagensEmMemoria("teste-aceitos"),
        transporte,
        dormir=lambda _s: None,
        relogio=lambda: BASE,
    )
    assert PERFIS["TV Fama"] in transporte.chamadas[0].instrucao


def test_chave_com_programa_fora_do_catalogo_da_422_com_os_validos() -> None:
    chaves, chave = _ambiente()

    resposta = _criar_com_chave(chaves, chave, programa="Programa Inventado")

    assert resposta.status_code == 422
    assert "TV Fama" in str(resposta.json()["detail"])


@pytest.mark.parametrize("data", ["2999-01-01", "31/12/1999", "ontem", 20261029])
def test_chave_com_data_futura_ou_mal_formada_da_422(data: object) -> None:
    chaves, chave = _ambiente()

    assert _criar_com_chave(chaves, chave, data_exibicao=data).status_code == 422


@pytest.mark.parametrize("escopo", ["criar", "ler"])
def test_chave_com_escopo_de_criar_ou_ler_lista_os_programas(escopo: Escopo) -> None:
    chaves = RepositorioDeChavesEmMemoria()
    chave = emitir_chave("Legado", [escopo], MAC_V1, chaves, BASE).chave

    resposta = _cliente(chaves).get("/v1/programas", headers={"X-API-Key": chave})

    assert resposta.status_code == 200
    assert resposta.json() == ["TV Fama"]


def test_chave_so_com_cancelar_nao_lista_os_programas() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    chave = emitir_chave("Legado", ["cancelar"], MAC_V1, chaves, BASE).chave

    resposta = _cliente(chaves).get("/v1/programas", headers={"X-API-Key": chave})

    assert resposta.status_code == 403


def test_envio_sem_programa_fica_sem_programa_para_a_chave() -> None:
    chaves, chave = _ambiente()

    resposta = _criar_com_chave(chaves, chave)

    assert resposta.status_code == 202 and resposta.json()["programa"] is None
