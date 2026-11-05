import json
from typing import Any

from api.correcoes import versao_do_modelo
from api.tests.test_correcoes import MODELO, Mundo

FALAS = [
    {"inicio_ms": 0, "fim_ms": 900, "texto": "Boa noite", "locutor": "Ana Souza"},
    {"inicio_ms": 900, "fim_ms": 1900, "texto": "Olá", "locutor": "ANA SOUZA"},
    {"inicio_ms": 2000, "fim_ms": 2900, "texto": "Oi", "locutor": "ana sôuza"},
    {"inicio_ms": 3000, "fim_ms": 3900, "texto": "Tchau", "locutor": "Carla Dias"},
    {"inicio_ms": 4000, "fim_ms": 4900, "texto": "Eu?", "locutor": "não identificado"},
]
NOVO = {**MODELO, "transcricao": FALAS}
VERSAO = versao_do_modelo(json.dumps(NOVO).encode())


def _mundo() -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(NOVO)
    return mundo


def _renomear(mundo: Mundo, item_id: str, valor: str) -> str:
    resposta = mundo.corrigir(item_id=item_id, valor=valor, versao=VERSAO)
    assert resposta.status_code == 201
    mundo.avancar()
    return str(resposta.json()["id"])


def _dar_a_primeira_fala_a_carla(mundo: Mundo) -> None:
    valor: dict[str, Any] = {"texto": "Boa noite", "locutor": "Carla Dias"}
    resposta = mundo.corrigir(
        tipo="fala.texto", item_id="fal000", valor=json.dumps(valor), versao=VERSAO
    )
    assert resposta.status_code == 201


def _locutores(mundo: Mundo) -> list[str]:
    return [f["locutor"] for f in mundo.decupagem()["transcricao"]]


def test_renomear_troca_o_locutor_das_falas_sem_acento_nem_maiuscula() -> None:
    mundo = _mundo()

    _renomear(mundo, "pes01", "Ana Souza Lima")

    assert _locutores(mundo) == [
        "Ana Souza Lima",
        "Ana Souza Lima",
        "Ana Souza Lima",
        "Carla Dias",
        "não identificado",
    ]
    textos = [f["texto"] for f in mundo.decupagem()["transcricao"]]
    assert textos == [f["texto"] for f in FALAS]


def test_renomear_pessoa_nao_identificada_nao_troca_nenhuma_fala() -> None:
    mundo = _mundo()

    _renomear(mundo, "pes02", "Beto Lima")

    assert _locutores(mundo) == [f["locutor"] for f in FALAS]


def test_desfazer_a_troca_devolve_o_locutor_do_modelo() -> None:
    mundo = _mundo()
    cid = _renomear(mundo, "pes01", "Ana Souza Lima")

    assert mundo.desfazer(cid).status_code == 201

    assert _locutores(mundo) == [f["locutor"] for f in FALAS]


def test_duas_trocas_seguidas_levam_as_falas_ate_o_ultimo_nome() -> None:
    mundo = _mundo()
    _renomear(mundo, "pes01", "Alberto")

    _renomear(mundo, "pes01", "Roberto")

    assert _locutores(mundo)[:3] == ["Roberto", "Roberto", "Roberto"]


def test_correcao_de_fala_depois_da_troca_vale_sobre_ela() -> None:
    mundo = _mundo()
    _renomear(mundo, "pes01", "Alberto")
    _dar_a_primeira_fala_a_carla(mundo)

    assert _locutores(mundo)[:2] == ["Carla Dias", "Alberto"]


def test_correcao_de_fala_antes_da_troca_com_outro_locutor_nao_e_tocada() -> None:
    mundo = _mundo()
    _dar_a_primeira_fala_a_carla(mundo)
    mundo.avancar()

    _renomear(mundo, "pes01", "Alberto")

    assert _locutores(mundo)[:2] == ["Carla Dias", "Alberto"]
