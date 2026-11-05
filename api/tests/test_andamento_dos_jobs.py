"""`GET /v1/jobs/andamento` e `cortes_ms` só no detalhe (#361)."""

from api.tests.test_lixeira import ADMIN, EDITOR, Mundo, _job


def _andamento(mundo: Mundo, ids: str, quem: dict[str, str]):  # type: ignore[no-untyped-def]
    return mundo.cliente.get("/v1/jobs/andamento", params={"ids": ids}, headers=quem)


def test_devolve_os_jobs_pedidos_na_ordem_sem_capa_e_sem_cortes() -> None:
    mundo = Mundo(
        _job("a", cortes_ms=[10, 20], capa="quadros/plano-1.jpg"),
        _job("b", estado="analisando"),
        _job("c"),
    )

    resposta = _andamento(mundo, "c,a,b", EDITOR)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [j["id"] for j in corpo] == ["c", "a", "b"]
    assert corpo[2]["estado"] == "analisando"
    for job in corpo:
        assert "cortes_ms" not in job
        assert "capa_url" not in job


def test_omite_o_que_nao_existe_e_o_job_de_outro_sistema() -> None:
    mundo = Mundo(
        _job("meu"), _job("alheio", sistema="Outro", criado_por="sistema:Outro")
    )

    corpo = _andamento(mundo, "meu,alheio,fantasma", mundo.chave).json()

    assert [j["id"] for j in corpo] == ["meu"]


def test_job_na_lixeira_so_aparece_para_o_administrador() -> None:
    mundo = Mundo(_job("j1"), _job("j2"))
    assert mundo.enviar("j1").status_code == 201

    assert [j["id"] for j in _andamento(mundo, "j1,j2", EDITOR).json()] == ["j2"]
    assert [j["id"] for j in _andamento(mundo, "j1,j2", mundo.chave).json()] == ["j2"]
    assert [j["id"] for j in _andamento(mundo, "j1,j2", ADMIN).json()] == ["j1", "j2"]


def test_aceita_200_ids_e_recusa_201_com_422() -> None:
    mundo = Mundo()

    assert (
        _andamento(mundo, ",".join(f"x{n}" for n in range(200)), EDITOR).status_code
        == 200
    )
    assert (
        _andamento(mundo, ",".join(f"x{n}" for n in range(201)), EDITOR).status_code
        == 422
    )
    # O teto conta o que veio, repetido ou não.
    assert _andamento(mundo, ",".join(["j1"] * 201), EDITOR).status_code == 422


def test_sem_ids_e_sem_permissao_de_ler() -> None:
    mundo = Mundo()

    assert _andamento(mundo, "", EDITOR).json() == []
    assert mundo.cliente.get("/v1/jobs/andamento?ids=j1").status_code == 401


def test_a_listagem_nao_traz_cortes_ms_e_o_detalhe_traz() -> None:
    mundo = Mundo(_job("a", cortes_ms=[10, 20]))

    listagem = mundo.cliente.get("/v1/jobs", headers=EDITOR).json()
    detalhe = mundo.cliente.get("/v1/jobs/a", headers=EDITOR).json()

    assert "cortes_ms" not in listagem[0]
    assert detalhe["cortes_ms"] == [10, 20]
