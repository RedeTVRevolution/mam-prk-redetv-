"""Vídeo na lixeira sai do Tempo de tela e de Marcas (#619), na hora, com o cache quente."""

from typing import Any

from api.jobs import RepositorioEmMemoria
from api.tests.test_busca import job as _job
from api.tests.test_lixeira_na_leitura import (
    ADMIN,
    ENVIO,
    ROTA,
    ROTA_DAS_MARCAS,
    Mundo,
    MundoDasMarcas,
    _marcas,
    _nomes,
    _nomes_das_marcas,
    _ranking,
)


def _jobs() -> RepositorioEmMemoria:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("j1"))
    jobs.salvar(_job("j2"))
    return jobs


def _lixeira(jobs: RepositorioEmMemoria, id: str, envio: Any) -> None:
    jobs.trocar(id, lambda _: {"lixeira": envio})


def test_video_na_lixeira_sai_do_tempo_de_tela_e_volta_ao_restaurar_com_o_cache_quente() -> (
    None
):
    jobs = _jobs()
    cliente = Mundo().instancia(repositorio=jobs)
    assert _nomes(_ranking(cliente)) == ["Ana", "Bia", "Cris"]  # esquenta o cache

    _lixeira(jobs, "j1", ENVIO)
    depois = _ranking(cliente)

    assert _nomes(depois) == ["Ana", "Cris"]  # Bia só estava em j1
    assert depois["total"] == {
        "pessoas": 2,
        "tempo_de_tela_ms": 2_000,
        "videos": 1,
        "aparicoes": 2,
        "mencoes_na_fala": 0,
        "mencoes_no_texto": 0,
    }
    csv_ = cliente.get(ROTA, params={"formato": "csv"}, headers=ADMIN).text
    assert "Bia" not in csv_
    completo = cliente.get(ROTA, headers=ADMIN).json()
    assert [p["nome"] for p in completo["pessoas"]] == ["Ana", "Cris"]
    assert completo["pessoas"][0]["tempo_de_tela_ms"] == 1_000
    assert [v["job_id"] for v in completo["pessoas"][0]["por_video"]] == ["j2"]

    _lixeira(jobs, "j1", None)
    de_volta = _ranking(cliente)
    assert _nomes(de_volta) == ["Ana", "Bia", "Cris"]
    assert de_volta["pessoas"][0]["tempo_de_tela_ms"] == 5_000


def test_o_detalhe_da_pessoa_nao_traz_o_video_na_lixeira() -> None:
    jobs = _jobs()
    mundo = Mundo()
    cliente = mundo.instancia(repositorio=jobs)

    def videos() -> list[str]:
        resposta = cliente.get(
            f"{ROTA}/videos", params={"pessoa_id": mundo.ana.id}, headers=ADMIN
        )
        return [v["job_id"] for v in resposta.json()]

    assert videos() == ["j1", "j2"]  # esquenta o cache
    _lixeira(jobs, "j1", ENVIO)
    assert videos() == ["j2"]
    _lixeira(jobs, "j1", None)
    assert videos() == ["j1", "j2"]


def test_video_na_lixeira_sai_de_marcas_e_volta_ao_restaurar_com_o_cache_quente() -> (
    None
):
    jobs = _jobs()
    cliente = MundoDasMarcas().instancia(repositorio=jobs)
    assert _nomes_das_marcas(_marcas(cliente)) == [
        "AB INBEV",
        "Ambev",
        "NESTLE",
        "Natura",
    ]  # esquenta o cache

    _lixeira(jobs, "j2", ENVIO)  # j2 só tem a Ambev
    depois = _marcas(cliente)

    assert _nomes_das_marcas(depois) == ["AB INBEV", "NESTLE", "Natura"]
    assert depois["total"] == {
        "marcas": 3,
        "insercoes": 3,
        "tempo_ms": 3_000,
        "videos": 1,
    }
    csv_ = cliente.get(ROTA_DAS_MARCAS, params={"formato": "csv"}, headers=ADMIN).text
    assert "Ambev" not in csv_
    completo = cliente.get(ROTA_DAS_MARCAS, headers=ADMIN).json()
    assert [x["marca"] for x in completo["marcas"]] == ["AB INBEV", "NESTLE", "Natura"]
    lista = cliente.get(
        f"{ROTA_DAS_MARCAS}/insercoes", params={"marca": "Ambev"}, headers=ADMIN
    )
    assert lista.json() == []

    _lixeira(jobs, "j2", None)
    assert _marcas(cliente)["total"]["insercoes"] == 4
    lista = cliente.get(
        f"{ROTA_DAS_MARCAS}/insercoes", params={"marca": "Ambev"}, headers=ADMIN
    )
    assert [i["job_id"] for i in lista.json()] == ["j2"]
