"""`GET /v1/jobs` como acervo: filtros, busca por nome, ordem, cursor e `enviado_por`."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from api.jobs import Job, palavras_do_nome
from api.tests.test_escopos import Mundo
from api.tests.test_jobs import AUTORIZACAO, Ambiente

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _semear(
    ambiente: Ambiente,
    id: str,
    minutos: int,
    nome: str | None = None,
    **extra: Any,
) -> Job:
    quando = BASE + timedelta(minutes=minutos)
    nome = nome or f"{id}.mp4"
    job = Job(
        id=id,
        nome=nome,
        tamanho_bytes=10,
        estado=extra.pop("estado", "concluido"),
        criado_por="u1",
        palavras=palavras_do_nome(nome),
        criado_em=quando,
        atualizado_em=quando,
        **extra,
    )
    ambiente.repositorio.salvar(job)
    return job


def _ids(ambiente: Ambiente, **parametros: Any) -> list[str]:
    resposta = ambiente.cliente.get("/v1/jobs", params=parametros, headers=AUTORIZACAO)
    assert resposta.status_code == 200
    return [j["id"] for j in resposta.json()]


def test_filtra_por_programa() -> None:
    a = Ambiente()
    _semear(a, "a", 0, programa="TV Fama")
    _semear(a, "b", 1, programa="Outro")
    _semear(a, "c", 2)

    assert _ids(a, programa="TV Fama") == ["a"]


def test_filtra_por_um_ou_varios_estados() -> None:
    a = Ambiente()
    _semear(a, "a", 0, estado="falhou")
    _semear(a, "b", 1, estado="concluido")
    _semear(a, "c", 2, estado="analisando")

    assert _ids(a, estado="falhou") == ["a"]
    assert _ids(a, estado=["falhou", "analisando"]) == ["c", "a"]


def test_filtra_pelo_intervalo_da_data_de_exibicao_inclusive() -> None:
    a = Ambiente()
    for id, dia in (("a", 19), ("b", 20), ("c", 21), ("d", 22)):
        _semear(a, id, int(id == "d"), data_exibicao=date(2026, 10, dia))
    _semear(a, "sem", 5)

    assert sorted(_ids(a, exibicao_de="2026-10-20", exibicao_ate="2026-10-21")) == [
        "b",
        "c",
    ]
    assert sorted(_ids(a, exibicao_de="2026-10-21")) == ["c", "d"]
    assert sorted(_ids(a, exibicao_ate="2026-10-19")) == ["a"]
    assert "sem" in _ids(a)


def test_combina_programa_estado_e_intervalo() -> None:
    a = Ambiente()
    d = date(2026, 10, 21)
    _semear(a, "ok", 0, programa="TV Fama", estado="concluido", data_exibicao=d)
    _semear(a, "outro-programa", 1, programa="X", estado="concluido", data_exibicao=d)
    _semear(a, "outro-estado", 2, programa="TV Fama", estado="falhou", data_exibicao=d)
    _semear(a, "outra-data", 3, programa="TV Fama", data_exibicao=date(2026, 9, 1))

    assert _ids(
        a,
        programa="TV Fama",
        estado="concluido",
        exibicao_de="2026-10-01",
        exibicao_ate="2026-10-31",
    ) == ["ok"]


def test_busca_por_nome_ignora_maiusculas_e_acentos_e_acha_a_palavra() -> None:
    a = Ambiente()
    _semear(a, "a", 0, nome="FAMA_20261021_720_BLU.mp4")
    _semear(a, "b", 1, nome="Café-da-manhã.mp4")
    _semear(a, "c", 2, nome="outro.mp4")

    assert _ids(a, q="FAMA") == ["a"]
    assert _ids(a, q="fama") == ["a"]
    assert _ids(a, q="blu") == ["a"]
    assert _ids(a, q="cafe MANHA") == ["b"]
    assert _ids(a, q="fama manha") == []


def test_palavras_do_nome_quebram_nos_separadores() -> None:
    assert palavras_do_nome("FAMA_20261021_720_BLU.mp4") == [
        "fama",
        "20261021",
        "720",
        "blu",
        "mp4",
    ]


def test_filtra_por_sistema() -> None:
    a = Ambiente()
    _semear(a, "a", 0, sistema="Legado")
    _semear(a, "b", 1)

    assert _ids(a, sistema="Legado") == ["a"]


def test_ordem_por_exibicao_poe_o_mais_recente_primeiro_e_sem_data_no_fim() -> None:
    a = Ambiente()
    _semear(a, "velho", 3, data_exibicao=date(2026, 10, 1))
    _semear(a, "sem", 9)
    _semear(a, "novo", 0, data_exibicao=date(2026, 10, 20))

    assert _ids(a, ordem="exibicao") == ["novo", "velho", "sem"]
    assert _ids(a) == ["sem", "velho", "novo"]
    assert _ids(a, ordem="enviado") == ["sem", "velho", "novo"]


def test_ordem_desconhecida_da_422() -> None:
    resposta = Ambiente().cliente.get("/v1/jobs?ordem=nome", headers=AUTORIZACAO)

    assert resposta.status_code == 422


def _paginar(ambiente: Ambiente, **parametros: Any) -> list[list[str]]:
    paginas: list[list[str]] = []
    cursor = None
    while True:
        resposta = ambiente.cliente.get(
            "/v1/jobs",
            params={**parametros, **({"cursor": cursor} if cursor else {})},
            headers=AUTORIZACAO,
        )
        assert resposta.status_code == 200
        paginas.append([j["id"] for j in resposta.json()])
        cursor = resposta.headers.get("X-Proximo-Cursor")
        if not cursor:
            return paginas


def test_paginas_nao_repetem_nem_pulam_jobs_na_ordem_de_envio() -> None:
    a = Ambiente()
    for i in range(7):
        _semear(a, f"j{i}", i)

    paginas = _paginar(a, limite=3)

    assert paginas == [["j6", "j5", "j4"], ["j3", "j2", "j1"], ["j0"]]


def test_paginas_na_ordem_por_exibicao_com_datas_repetidas_e_sem_data() -> None:
    a = Ambiente()
    dias = [20, 20, 20, 19, None, None, 18]
    for i, dia in enumerate(dias):
        _semear(a, f"j{i}", i, data_exibicao=date(2026, 10, dia) if dia else None)

    paginas = _paginar(a, limite=2, ordem="exibicao")

    todos = [id for pagina in paginas for id in pagina]
    assert sorted(todos) == sorted(f"j{i}" for i in range(7))
    assert len(todos) == len(set(todos)) == 7
    assert todos == _ids(a, ordem="exibicao")
    assert todos[-2:] == sorted(["j4", "j5"], reverse=True)


def test_pagina_respeita_os_filtros() -> None:
    a = Ambiente()
    for i in range(6):
        _semear(a, f"j{i}", i, programa="TV Fama" if i % 2 else None)

    assert _paginar(a, limite=2, programa="TV Fama") == [["j5", "j3"], ["j1"]]


def test_ultima_pagina_sem_cabecalho_e_pagina_cheia_exata_tambem() -> None:
    a = Ambiente()
    for i in range(4):
        _semear(a, f"j{i}", i)

    resposta = a.cliente.get("/v1/jobs?limite=4", headers=AUTORIZACAO)

    assert len(resposta.json()) == 4
    assert "X-Proximo-Cursor" not in resposta.headers


def test_sem_limite_a_lista_vem_inteira_e_sem_cursor() -> None:
    a = Ambiente()
    for i in range(60):
        _semear(a, f"j{i:02d}", i)

    resposta = a.cliente.get("/v1/jobs", headers=AUTORIZACAO)

    assert len(resposta.json()) == 60
    assert "X-Proximo-Cursor" not in resposta.headers


def test_limite_fora_de_1_a_200_e_cursor_inexistente_dao_422() -> None:
    a = Ambiente()
    for url in ("/v1/jobs?limite=0", "/v1/jobs?limite=201", "/v1/jobs?cursor=nada"):
        assert a.cliente.get(url, headers=AUTORIZACAO).status_code == 422


def test_job_criado_por_pessoa_traz_o_email_em_enviado_por() -> None:
    a = Ambiente()
    criado = a.criar()

    assert criado.json()["enviado_por"] == {
        "tipo": "pessoa",
        "nome": "ana@redetv.com.br",
    }
    lista = a.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()
    assert lista[0]["enviado_por"] == {"tipo": "pessoa", "nome": "ana@redetv.com.br"}
    job = a.repositorio.obter(criado.json()["id"])
    assert job is not None and job.palavras == ["clipe", "mp4"]


def test_job_antigo_sem_email_tem_nome_nulo() -> None:
    a = Ambiente()
    _semear(a, "a", 0)

    lista = a.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()

    assert lista[0]["enviado_por"] == {"tipo": "pessoa", "nome": None}


def test_job_criado_por_sistema_traz_o_nome_do_sistema() -> None:
    mundo = Mundo()
    chave = mundo.chave("Legado", "criar", "ler")
    corpo = {"nome": "a.mp4", "tamanho_bytes": 10, "tipo": "video/mp4"}

    criado = mundo.cliente.post("/v1/jobs", json=corpo, headers=chave).json()

    assert criado["enviado_por"] == {"tipo": "sistema", "nome": "Legado"}
    lista = mundo.cliente.get("/v1/jobs", headers=chave).json()
    assert lista[0]["enviado_por"] == {"tipo": "sistema", "nome": "Legado"}


def test_chave_de_sistema_so_ve_os_proprios_jobs_mesmo_pedindo_outro_sistema() -> None:
    mundo = Mundo()
    mundo.job("meu", "Legado")
    mundo.job("alheio", "Outro")
    mundo.job("pessoa", None)
    chave = mundo.chave("Legado", "ler")

    def ids(url: str) -> list[str]:
        resposta = mundo.cliente.get(url, headers=chave)
        assert resposta.status_code == 200
        return [j["id"] for j in resposta.json()]

    assert ids("/v1/jobs") == ["meu"]
    assert ids("/v1/jobs?sistema=Legado") == ["meu"]
    assert ids("/v1/jobs?sistema=Outro") == []
