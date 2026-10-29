import copy
from typing import Any

import pytest
from pydantic import ValidationError

from api.decupagem import Decupagem, esquema_do_modelo

DURACAO_MS = 60_000


def decupagem_valida() -> dict[str, Any]:
    return {
        "versao_esquema": "1.1",
        "video": {"sha256": "a" * 64, "duracao_ms": DURACAO_MS},
        "programa": {
            "resumo": "Jornal da noite",
            "blocos": [{"inicio_ms": 0, "fim_ms": 30_000, "titulo": "Abertura"}],
        },
        "pautas": [
            {
                "id": "pau01",
                "titulo": "Chuvas",
                "inicio_ms": 1_000,
                "fim_ms": 20_000,
                "resumo": "Chuva forte em SP",
                "pessoas": ["pes01"],
            }
        ],
        "pessoas": [
            {
                "id": "pes01",
                "nome": "Fulana",
                "origem": "modelo",
                "na_imagem": [
                    {"inicio_ms": 1_000, "fim_ms": 5_000, "evidencia": "rosto+gc"}
                ],
                "citada_na_fala": [{"inicio_ms": 2_000, "fim_ms": 3_000}],
                "citada_no_texto": [
                    {"inicio_ms": 1_000, "fim_ms": 4_000, "texto": "FULANA"}
                ],
            }
        ],
        "planos": [
            {
                "id": "pla001",
                "inicio_ms": 0,
                "fim_ms": 4_200,
                "ambiente": "estúdio",
                "plano_limpo": False,
            }
        ],
        "comerciais": [
            {
                "marca": "Marca",
                "tipo": "merchan_apresentador",
                "inicio_ms": 40_000,
                "fim_ms": 50_000,
                "evidencia": "fala+logo",
            }
        ],
        "transcricao": [
            {
                "inicio_ms": 0,
                "fim_ms": 3_800,
                "locutor": "apresentador",
                "texto": "Boa noite",
            }
        ],
    }


def test_aceita_decupagem_completa_com_as_tres_listas_de_pessoa() -> None:
    d = Decupagem.model_validate(decupagem_valida())

    pessoa = d.pessoas[0]
    assert len(pessoa.na_imagem) == 1
    assert len(pessoa.citada_na_fala) == 1
    assert len(pessoa.citada_no_texto) == 1
    assert pessoa.na_imagem[0].quadro is None  # vazio na E0


def test_recusa_campo_desconhecido_na_raiz_e_aninhado() -> None:
    raiz = decupagem_valida()
    raiz["extra"] = 1
    with pytest.raises(ValidationError):
        Decupagem.model_validate(raiz)

    aninhado = decupagem_valida()
    aninhado["pessoas"][0]["na_imagem"][0]["campo_novo"] = "x"
    with pytest.raises(ValidationError):
        Decupagem.model_validate(aninhado)


def test_recusa_inicio_depois_do_fim() -> None:
    d = decupagem_valida()
    d["planos"][0]["inicio_ms"] = 5_000
    d["planos"][0]["fim_ms"] = 4_000
    with pytest.raises(ValidationError):
        Decupagem.model_validate(d)


@pytest.mark.parametrize(
    "caminho",
    [
        ("programa", "blocos", 0),
        ("pautas", 0),
        ("pessoas", 0, "na_imagem", 0),
        ("pessoas", 0, "citada_na_fala", 0),
        ("pessoas", 0, "citada_no_texto", 0),
        ("planos", 0),
        ("comerciais", 0),
        ("transcricao", 0),
    ],
)
def test_recusa_tempo_alem_da_duracao_em_qualquer_lista(
    caminho: tuple[Any, ...],
) -> None:
    d = copy.deepcopy(decupagem_valida())
    alvo: Any = d
    for chave in caminho:
        alvo = alvo[chave]
    alvo["fim_ms"] = DURACAO_MS + 1
    with pytest.raises(ValidationError):
        Decupagem.model_validate(d)


def test_json_schema_e_estrito() -> None:
    esquema = Decupagem.model_json_schema()
    assert esquema["additionalProperties"] is False


def test_esquema_do_modelo_omite_o_bloco_video() -> None:
    esquema = esquema_do_modelo()
    assert "video" not in esquema["properties"]
    assert "video" not in esquema["required"]
    assert "Video" not in esquema["$defs"]
    assert esquema["additionalProperties"] is False
    assert (
        "video" in Decupagem.model_json_schema()["properties"]
    )  # sem efeito colateral
