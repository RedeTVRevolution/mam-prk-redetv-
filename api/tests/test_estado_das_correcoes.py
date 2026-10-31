from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from api.correcoes import Ancora, Correcao, estado_das

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _c(id: str, minuto: int = 0, **campos: Any) -> Correcao:
    base: dict[str, Any] = {
        "id": id,
        "job_id": "j1",
        "autor_uid": "u",
        "autor_email": "u@x",
        "criada_em": BASE + timedelta(minutes=minuto),
        "motivo": "m",
        "tipo": "pessoa.renomear",
        "item_id": "p1",
        "antes": "a",
        "depois": "b",
        "ancora": Ancora(
            versao="v", tipo_do_item="pessoa", identidade="a", inicio_ms=0, fim_ms=1
        ),
    }
    return Correcao(**{**base, **campos})


def test_correcao_comum_esta_em_vigor() -> None:
    estado = estado_das([_c("c1")])
    assert estado.de("c1") == "ativa"
    assert estado.em_vigor("c1")


def test_desfeita_sai_de_vigor() -> None:
    estado = estado_das([_c("c1"), _c("d1", 1, tipo="desfazer", desfaz="c1")])
    assert estado.de("c1") == "desfeita"
    assert not estado.em_vigor("c1")


def test_pendente_aprovada_e_recusada() -> None:
    correcoes = [
        _c("p", exige_aprovacao=True),
        _c("a", exige_aprovacao=True),
        _c("r", exige_aprovacao=True),
        _c("ap", 1, tipo="aprovar", aprova="a"),
        _c("re", 1, tipo="recusar", recusa="r"),
    ]
    estado = estado_das(correcoes)
    assert [estado.de(i) for i in ("p", "a", "r")] == [
        "pendente",
        "aprovada",
        "recusada",
    ]
    assert [estado.em_vigor(i) for i in ("p", "a", "r")] == [False, True, False]
    assert estado.espera_decisao("p")
    assert not estado.espera_decisao("a")
    assert not estado.espera_decisao("r")


def test_saiu_da_fila_reaplicada_ou_descartada() -> None:
    correcoes = [
        _c("x"),
        _c("y"),
        _c("z", 1, reaplica="x"),
        _c("w", 1, tipo="descartar", descarta="y"),
    ]
    estado = estado_das(correcoes)
    assert estado.de("x") == "reaplicada"
    assert estado.de("y") == "descartada"
    assert estado.saiu_da_fila("x") and estado.saiu_da_fila("y")
    assert not estado.saiu_da_fila("z")


def test_aprovada_que_saiu_da_fila_mostra_o_ultimo_destino() -> None:
    correcoes = [
        _c("a", exige_aprovacao=True),
        _c("ap", 1, tipo="aprovar", aprova="a"),
        _c("w", 2, tipo="descartar", descarta="a"),
    ]
    assert estado_das(correcoes).de("a") == "descartada"


@pytest.mark.parametrize("id_", ["c1", "nada"])
def test_id_desconhecido_nao_derruba(id_: str) -> None:
    assert estado_das([_c("c1")]).de(id_) == "ativa"
