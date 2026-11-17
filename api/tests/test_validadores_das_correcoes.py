"""Mensagens dos validadores que os modelos de correção compartilham (#695)."""

from typing import Any

import pytest
from pydantic import ValidationError

from api.correcoes import (
    TIPOS_DE_COMERCIAL,
    NovaAparicao,
    NovaPauta,
    NovoComercial,
    NovoObjeto,
    NovoTextoAcrescentado,
    Ocorrencia,
    _DonoDoObjeto,
    tempos_de,
)

_TRECHO_INVERTIDO = {"inicio_ms": 5000, "fim_ms": 1000}

_COM_INTERVALO_INVERTIDO: list[tuple[type, dict[str, Any]]] = [
    (Ocorrencia, {"lista": "na_imagem", **_TRECHO_INVERTIDO}),
    (
        NovoComercial,
        {
            "marca": "Marca",
            "tipo": TIPOS_DE_COMERCIAL[0],
            "evidencias": ["fala"],
            **_TRECHO_INVERTIDO,
        },
    ),
    (NovaAparicao, {"evidencia": "x", **_TRECHO_INVERTIDO}),
    (
        NovoObjeto,
        {
            "categoria": "roupa",
            "tipo": "vestido",
            "cor_base": ["vermelho"],
            **_TRECHO_INVERTIDO,
        },
    ),
    (NovoTextoAcrescentado, {"tipo": "legenda", "texto": "oi", **_TRECHO_INVERTIDO}),
    (NovaPauta, {"titulo": "T", "tom": "informativo", **_TRECHO_INVERTIDO}),
]


@pytest.mark.parametrize(("modelo", "dados"), _COM_INTERVALO_INVERTIDO)
def test_inicio_depois_do_fim_tem_a_mesma_mensagem(
    modelo: type, dados: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError, match="início depois do fim"):
        modelo(**dados)


def test_tempos_com_inicio_depois_do_fim() -> None:
    with pytest.raises(ValueError, match="^início depois do fim$"):
        tempos_de("5000-1000")


def test_pessoa_sem_relacao_tem_a_mesma_mensagem_no_dono_e_no_objeto() -> None:
    msg = "pessoa e relação vêm juntas ou nenhuma das duas"
    with pytest.raises(ValidationError, match=msg):
        _DonoDoObjeto(pessoa="pes01", relacao=None)
    with pytest.raises(ValidationError, match=msg):
        NovoObjeto(
            categoria="roupa",
            tipo="vestido",
            cor_base=["vermelho"],
            pessoa="pes01",
            inicio_ms=0,
            fim_ms=1,
        )
