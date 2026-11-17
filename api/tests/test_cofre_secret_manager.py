import base64
import json
from typing import Any

import pytest

from api.cofre_secret_manager import CofreSecretManager, ErroDoCofre, cofre_do_ambiente

SEGREDO = "projects/p/secrets/s"


def _versao(mapa: dict[str, str]) -> dict[str, Any]:
    return {"payload": {"data": base64.b64encode(json.dumps(mapa).encode()).decode()}}


class Transporte:
    def __init__(self, *respostas: tuple[int, dict[str, Any]]) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        self.chamadas.append((metodo, caminho, corpo))
        return self.respostas.pop(0)


def test_obter_le_a_versao_mais_recente_do_mapa() -> None:
    t = Transporte((200, _versao({"Legado": "abc"})))
    assert CofreSecretManager(SEGREDO, t).obter("Legado") == "abc"
    assert t.chamadas == [("GET", f"{SEGREDO}/versions/latest:access", None)]


def test_sistema_fora_do_mapa_nao_tem_segredo() -> None:
    t = Transporte((200, _versao({"Outro": "x"})))
    assert CofreSecretManager(SEGREDO, t).obter("Legado") is None


def test_segredo_ainda_sem_versao_e_mapa_vazio() -> None:
    t = Transporte((404, {}))
    assert CofreSecretManager(SEGREDO, t).obter("Legado") is None


@pytest.mark.parametrize("status", [400, 403, 500, 503])
def test_outro_erro_do_secret_manager_nao_vira_sem_segredo(status: int) -> None:
    # Sem segredo o evento é descartado; erro passageiro tem de virar 503 para o
    # Pub/Sub tentar de novo (versão desligada é 400 FAILED_PRECONDITION).
    t = Transporte((status, {"error": {"status": "X", "message": "y"}}))
    with pytest.raises(ErroDoCofre):
        CofreSecretManager(SEGREDO, t).obter("Legado")


def test_guardar_soma_ao_mapa_numa_versao_nova() -> None:
    t = Transporte((200, _versao({"Outro": "x"})), (200, {}))
    CofreSecretManager(SEGREDO, t).guardar("Legado", "abc")
    metodo, caminho, corpo = t.chamadas[1]
    assert (metodo, caminho) == ("POST", f"{SEGREDO}:addVersion")
    assert corpo is not None
    dados = base64.b64decode(corpo["payload"]["data"])
    assert json.loads(dados) == {"Outro": "x", "Legado": "abc"}


def test_guardar_no_segredo_sem_versao_comeca_do_zero() -> None:
    t = Transporte((404, {}), (200, {}))
    CofreSecretManager(SEGREDO, t).guardar("Legado", "abc")
    corpo = t.chamadas[1][2]
    assert corpo is not None
    assert json.loads(base64.b64decode(corpo["payload"]["data"])) == {"Legado": "abc"}


def test_guardar_que_falha_levanta() -> None:
    t = Transporte((404, {}), (403, {}))
    with pytest.raises(ErroDoCofre):
        CofreSecretManager(SEGREDO, t).guardar("Legado", "abc")


def test_cofre_do_ambiente_so_com_o_nome_do_segredo() -> None:
    assert cofre_do_ambiente({}) is None
    cofre = cofre_do_ambiente({"WEBHOOK_SEGREDOS": SEGREDO}, lambda: Transporte())
    assert isinstance(cofre, CofreSecretManager)
