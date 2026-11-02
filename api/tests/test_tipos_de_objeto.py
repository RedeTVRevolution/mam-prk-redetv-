"""O índice dos tipos de objeto (#308): a lista que o autocompletar consulta."""

from api.tests.test_correcoes import AUTORIZACAO, Mundo
from api.tipos_de_objeto import TiposDeObjetoEmMemoria


def test_busca_por_prefixo_sem_acento_nem_maiuscula() -> None:
    tipos = TiposDeObjetoEmMemoria()
    tipos.registrar("j1", {"sandália": 2, "scarpin": 1})

    assert tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 2}]
    assert tipos.buscar("SCAR") == [{"tipo": "scarpin", "ocorrencias": 1}]
    assert tipos.buscar("x") == []


def test_ordena_por_ocorrencias_e_corta_no_limite() -> None:
    tipos = TiposDeObjetoEmMemoria()
    tipos.registrar("j1", {"sapato": 1, "sandália": 3, "saia": 2})

    assert [t["tipo"] for t in tipos.buscar("sa")] == ["sandália", "saia", "sapato"]
    assert [t["tipo"] for t in tipos.buscar("sa", limite=2)] == ["sandália", "saia"]


def test_registrar_de_novo_o_mesmo_job_troca_a_contribuicao() -> None:
    tipos = TiposDeObjetoEmMemoria()
    tipos.registrar("j1", {"sandália": 2})
    tipos.registrar("j1", {"sandália": 2})
    assert tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 2}]

    tipos.registrar("j1", {"saia": 1})

    assert tipos.buscar("sa") == [{"tipo": "saia", "ocorrencias": 1}]


def test_jobs_diferentes_somam() -> None:
    tipos = TiposDeObjetoEmMemoria()
    tipos.registrar("j1", {"sandália": 2})
    tipos.registrar("j2", {"Sandalia": 1})

    [achado] = tipos.buscar("sand")
    assert achado["ocorrencias"] == 3


def test_sem_decupagem_ver_a_rota_da_403() -> None:
    resposta = Mundo([]).cliente.get(
        "/v1/objetos/tipos", params={"q": "a"}, headers=AUTORIZACAO
    )

    assert resposta.status_code == 403


def test_sem_login_a_rota_da_401() -> None:
    resposta = Mundo(["editor"]).cliente.get("/v1/objetos/tipos", params={"q": "a"})

    assert resposta.status_code == 401
