"""A medição do agrupamento de objetos (#544), em dado local."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from api.medir_agrupamento_de_objetos import (
    amostra_de_cobertura,
    amostra_de_precisao,
    grupos_por_programa,
    main,
    margem_de_confianca,
    medir,
    pares_para_margem,
)


def _video(nomes: list[tuple[str, str | None]]) -> dict[str, Any]:
    return {
        "planos": [
            {
                "inventario": [
                    {
                        "nome": n,
                        "categoria": "roupa",
                        "cor": c,
                        "caixas": [],
                        "destaque": 1,
                    }
                    for n, c in nomes
                ]
            }
        ],
        "objetos": [],
    }


def _pasta(tmp_path: Path) -> Path:
    escritos = {
        "jornal/a.json": _video(
            [
                ("camiseta", "azul"),
                ("camisa", "branco"),
                ("blusa", None),
                ("xablau", None),
            ]
        ),
        "novela/b.json": _video(
            [
                ("Camisas", "azul"),
                ("calça", None),
                ("calças jeans", "azul"),
                ("xablau raro", None),
            ]
        ),
    }
    for caminho, video in escritos.items():
        (tmp_path / caminho).parent.mkdir(exist_ok=True)
        (tmp_path / caminho).write_text(json.dumps(video))
    return tmp_path


def test_o_diagnostico_conta_antes_e_depois_sem_reprocessar(tmp_path: Path) -> None:
    resultado = medir(_pasta(tmp_path))

    # Antes: 8 nomes + cor + categoria quase todos diferentes; depois: camisa, calça, xablau, xablau raro.
    assert resultado["videos"] == 2
    assert resultado["diagnostico"] == {"ocorrencias": 8, "antes": 8, "depois": 4}


def test_a_amostra_de_precisao_e_um_par_por_grupo_e_estavel(tmp_path: Path) -> None:
    videos = {
        p: [
            json.loads(f.read_text())
            for f in sorted((_pasta(tmp_path) / p).glob("*.json"))
        ]
        for p in ("jornal", "novela")
    }
    grupos = grupos_por_programa(videos)

    amostra = amostra_de_precisao(grupos, 10)

    # Só entram os grupos com dois nomes diferentes: camisa no jornal e calça na novela.
    assert sorted((p["programa"], p["grupo"]) for p in amostra) == [
        ("jornal", "tipo:camisa"),
        ("novela", "tipo:calça"),
    ]
    assert all(p["a"] != p["b"] for p in amostra)
    assert amostra == amostra_de_precisao(grupos_por_programa(videos), 10)
    # Estratificado: o primeiro grupo de cada programa vem antes do segundo de qualquer um.
    assert {p["programa"] for p in amostra[:2]} == {"jornal", "novela"}


def test_a_cobertura_sorteia_vizinhos_pela_assinatura() -> None:
    grupos = grupos_por_programa(
        {
            "p": [
                _video([("xablau raro", None), ("xablau", None), ("outra coisa", None)])
            ]
        }
    )

    pares = amostra_de_cobertura(grupos, 10)

    assert [(x["a"], x["b"]) for x in pares] == [("xablau", "xablau raro")]


def test_a_margem_de_confianca_do_ticket() -> None:
    assert round(margem_de_confianca(100), 1) == 4.3
    assert 190 <= pares_para_margem(3) <= 210


def test_a_cobertura_inclui_tipo_canonico_vizinho_de_outro_no_mesmo_programa() -> None:
    grupos = grupos_por_programa(
        {
            "jornal": [_video([("camisa", None), ("camisa rara", None)])],
            "novela": [_video([("camisa rara", None)])],
        }
    )

    pares = amostra_de_cobertura(grupos, 10)

    # "camisa" (tipo) e "camisa rara" (outro) do jornal; o par não cruza programas.
    assert [(x["programa"], x["a"], x["b"]) for x in pares] == [
        ("jornal", "camisa", "camisa rara")
    ]


def test_margem_com_zero_pares_nao_divide_por_zero(tmp_path: Path) -> None:
    assert medir(_pasta(tmp_path), 0)["margem_com_essa_amostra_pontos"] is None
    assert margem_de_confianca(0) == math.inf
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    assert medir(vazia, 100)["margem_com_essa_amostra_pontos"] is None


def test_amostra_maior_que_a_disponivel_usa_os_pares_reais(tmp_path: Path) -> None:
    resultado = medir(_pasta(tmp_path), 1_000)
    pares = len(resultado["amostra_de_precisao"])
    assert 0 < pares < 1_000
    assert resultado["margem_com_essa_amostra_pontos"] == round(
        margem_de_confianca(pares), 1
    )


def test_main_com_amostra_zero_sai_com_zero(tmp_path: Path) -> None:
    assert main([str(_pasta(tmp_path)), "--amostra", "0"]) == 0


def test_os_grupos_por_programa_saem_uma_vez_por_medicao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chamadas: list[int] = []
    original = grupos_por_programa

    def contada(videos):  # type: ignore[no-untyped-def]
        chamadas.append(1)
        return original(videos)

    monkeypatch.setattr("api.medir_agrupamento_de_objetos.grupos_por_programa", contada)

    resultado = medir(_pasta(tmp_path))

    assert len(chamadas) == 1
    assert resultado["amostra_de_precisao"]
