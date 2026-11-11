"""`POST /v1/jobs/quadros` e a rota unitária lendo o Job uma vez (#481)."""

import threading
import time
from collections.abc import Iterable
from typing import Any

from api.jobs import Job
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import ADMIN, EDITOR, Mundo, _job

ROTA = "/v1/jobs/quadros"


def _par(job: str, arquivo: str = "plano-0.jpg") -> dict[str, str]:
    return {"job": job, "arquivo": arquivo}


def _pedir(mundo: Mundo, pares: list[dict[str, str]], quem: dict[str, str] = EDITOR):  # type: ignore[no-untyped-def]
    return mundo.cliente.post(ROTA, json={"quadros": pares}, headers=quem)


def _contar_leituras(mundo: Mundo) -> list[str]:
    lidos: list[str] = []
    obter, varios = mundo.jobs.obter, mundo.jobs.obter_varios

    def obter_contando(job_id: str) -> Job | None:
        lidos.append(job_id)
        return obter(job_id)

    def varios_contando(job_ids: Iterable[str]) -> list[Job]:
        ids = list(job_ids)
        lidos.extend(ids)
        return varios(ids)

    mundo.jobs.obter = obter_contando  # type: ignore[method-assign]
    mundo.jobs.obter_varios = varios_contando  # type: ignore[method-assign]
    return lidos


def test_devolve_a_url_de_cada_par_na_ordem_pedida() -> None:
    mundo = Mundo(_job("a"), _job("b"))

    resposta = _pedir(mundo, [_par("b", "x.jpg"), _par("a", "y.jpg")])

    assert resposta.status_code == 200
    corpo: list[dict[str, Any]] = resposta.json()
    assert [(q["job"], q["arquivo"]) for q in corpo] == [("b", "x.jpg"), ("a", "y.jpg")]
    unitaria = mundo.cliente.get("/v1/jobs/b/quadros/x.jpg", headers=EDITOR).json()
    assert corpo[0]["url"] == unitaria["url"]
    assert corpo[0]["expira_em"] == unitaria["expira_em"]


def test_job_inexistente_na_lixeira_ou_nao_concluido_volta_sem_url() -> None:
    mundo = Mundo(_job("ok"), _job("lixo"), _job("andando", estado="analisando"))
    assert mundo.enviar("lixo").status_code == 201

    resposta = _pedir(
        mundo, [_par("fantasma"), _par("lixo"), _par("andando"), _par("ok")]
    )

    assert resposta.status_code == 200
    urls = {q["job"]: q["url"] for q in resposta.json()}
    assert urls["fantasma"] is None
    assert urls["lixo"] is None
    assert urls["andando"] is None
    assert urls["ok"] is not None
    # Sem URL também não há validade a informar.
    assert all(q["expira_em"] is None for q in resposta.json() if q["url"] is None)


def test_job_de_outro_sistema_volta_sem_url() -> None:
    mundo = Mundo(
        _job("meu"), _job("alheio", sistema="Outro", criado_por="sistema:Outro")
    )

    urls = {
        q["job"]: q["url"]
        for q in _pedir(mundo, [_par("meu"), _par("alheio")], mundo.chave).json()
    }

    assert urls["meu"] is not None
    assert urls["alheio"] is None


def test_le_cada_job_uma_vez_mesmo_com_varios_quadros_dele() -> None:
    mundo = Mundo(_job("a"), _job("b"))
    lidos = _contar_leituras(mundo)

    _pedir(
        mundo, [_par("a", "1.jpg"), _par("a", "2.jpg"), _par("b"), _par("a", "3.jpg")]
    )

    assert sorted(lidos) == ["a", "b"]


def test_aceita_100_pares_e_recusa_101_com_422() -> None:
    mundo = Mundo()

    assert _pedir(mundo, [_par(f"j{n}") for n in range(100)]).status_code == 200
    assert _pedir(mundo, [_par(f"j{n}") for n in range(101)]).status_code == 422


def test_arquivo_fora_do_formato_e_422() -> None:
    mundo = Mundo()

    assert _pedir(mundo, [_par("j1", "../x.jpg")]).status_code == 422


def test_id_de_job_fora_do_formato_e_422() -> None:
    # Com "/", o Firestore leria o id como caminho e derrubaria o lote com 500.
    mundo = Mundo()

    for job in ["a/b", "", "../x"]:
        assert _pedir(mundo, [_par(job)]).status_code == 422


def test_exige_o_escopo_de_ler_e_a_autenticacao() -> None:
    mundo = Mundo()

    assert mundo.cliente.post(ROTA, json={"quadros": []}).status_code == 401
    assert _pedir(mundo, [], ADMIN).status_code == 200
    assert _pedir(mundo, []).json() == []


def test_a_rota_unitaria_le_o_job_uma_vez() -> None:
    mundo = Mundo(_job("j1"))
    lidos = _contar_leituras(mundo)

    resposta = mundo.cliente.get("/v1/jobs/j1/quadros/plano-0.jpg", headers=EDITOR)

    assert resposta.status_code == 200
    assert lidos == ["j1"]


def test_a_rota_unitaria_le_uma_vez_o_job_que_nao_existe() -> None:
    mundo = Mundo()
    lidos = _contar_leituras(mundo)

    resposta = mundo.cliente.get(
        "/v1/jobs/fantasma/quadros/plano-0.jpg", headers=EDITOR
    )

    assert resposta.status_code == 404
    assert lidos == ["fantasma"]


def _assinaturas_lentas(monkeypatch: Any, atraso: float = 0.2) -> list[tuple[str, str]]:
    """Cada assinatura demora `atraso` s (a ida ao IAM) e fica anotada."""
    chamadas: list[tuple[str, str]] = []

    def url_do_quadro(self: Any, job_id: str, caminho: str, validade: Any) -> str:
        chamadas.append((job_id, caminho))
        time.sleep(atraso)
        return f"https://storage.exemplo/{job_id}/{caminho}"

    monkeypatch.setattr(ArmazenamentoFalso, "url_do_quadro", url_do_quadro)
    return chamadas


def test_assina_os_quadros_em_paralelo_com_teto_de_8(monkeypatch: Any) -> None:
    ativas = 0
    pico = 0
    trava = threading.Lock()
    cheio = threading.Event()  # as 8 vagas ocupadas ao mesmo tempo

    def url_do_quadro(self: Any, job_id: str, caminho: str, validade: Any) -> str:
        nonlocal ativas, pico
        with trava:
            ativas += 1
            pico = max(pico, ativas)
            if ativas == 8:
                cheio.set()
        cheio.wait(
            timeout=5
        )  # só protege contra travamento: com pool menor, o pico fica abaixo de 8
        with trava:
            ativas -= 1
        return f"https://storage.exemplo/{job_id}/{caminho}"

    monkeypatch.setattr(ArmazenamentoFalso, "url_do_quadro", url_do_quadro)
    mundo = Mundo(_job("a"))

    resposta = _pedir(mundo, [_par("a", f"plano-{n}.jpg") for n in range(12)])

    assert all(q["url"] for q in resposta.json())
    assert pico == 8


def test_repetido_e_assinado_uma_vez_e_a_ordem_e_os_vazios_ficam(
    monkeypatch: Any,
) -> None:
    chamadas = _assinaturas_lentas(monkeypatch, 0)
    mundo = Mundo(_job("a"), _job("b"))

    pares = [
        _par("a", "1.jpg"),
        _par("fantasma"),
        _par("b", "2.jpg"),
        _par("a", "1.jpg"),
        _par("fantasma"),
    ]
    corpo = _pedir(mundo, pares).json()

    assert [(q["job"], q["arquivo"]) for q in corpo] == [
        (p["job"], p["arquivo"]) for p in pares
    ]
    assert [q["url"] is None for q in corpo] == [False, True, False, False, True]
    assert corpo[0]["url"] == corpo[3]["url"]
    assert sorted(chamadas) == [("a", "quadros/1.jpg"), ("b", "quadros/2.jpg")]


def test_so_assina_o_que_o_chamador_pode_ver(monkeypatch: Any) -> None:
    chamadas = _assinaturas_lentas(monkeypatch, 0)
    mundo = Mundo(
        _job("meu"),
        _job("alheio", sistema="Outro", criado_por="sistema:Outro"),
        _job("lixo"),
    )
    assert mundo.enviar("lixo").status_code == 201

    _pedir(mundo, [_par("meu"), _par("alheio"), _par("lixo")], mundo.chave)

    assert chamadas == [("meu", "quadros/plano-0.jpg")]
