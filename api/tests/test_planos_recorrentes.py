"""O agrupamento dos planos recorrentes (#546), em quadros gerados na hora."""

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from api.decupagem import Decupagem
from api.planos_recorrentes import (
    Sinal,
    agrupar,
    com_os_planos_recorrentes,
    contagem,
    main,
    resumo,
)


def _quadro(variante: int, brilho: int = 0) -> bytes:
    """Três quadros bem diferentes (degradê crescente, decrescente, listras), com brilho."""
    imagem = Image.new("RGB", (64, 64))
    colunas = [
        [x * 4 for x in range(64)],
        [255 - x * 4 for x in range(64)],
        [255 * (x // 4 % 2) for x in range(64)],
    ][variante]
    imagem.putdata([(min(c + brilho, 255),) * 3 for c in colunas] * 64)
    saida = io.BytesIO()
    imagem.save(saida, "PNG")
    return saida.getvalue()


def _plano(id: str, n: int, quadro: str | None, **campos: Any) -> dict[str, Any]:
    return {
        "id": id,
        "inicio_ms": n * 1000,
        "fim_ms": n * 1000 + 1000,
        "ambiente": "estúdio",
        "plano_limpo": False,
        "quadro": quadro,
        "quadros": [quadro] if quadro else [],
        **campos,
    }


def _decupagem(planos: list[dict[str, Any]]) -> Decupagem:
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.5",
            "video": {"sha256": "a" * 64, "duracao_ms": 100_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": [],
            "planos": planos,
            "comerciais": [],
            "transcricao": [],
            "textos_na_tela": [],
        }
    )


def _grupos(
    planos: list[dict[str, Any]], quadros: dict[str, bytes]
) -> list[str | None]:
    pronta = com_os_planos_recorrentes(_decupagem(planos), lambda c: quadros[c])
    return [p.plano_recorrente for p in pronta.planos]


# A câmera A volta com um brilho quase igual; B e C são outros quadros.
_QUADROS = {
    "a1": _quadro(0),
    "a2": _quadro(0, brilho=3),
    "b1": _quadro(1),
    "b2": _quadro(1),
    "c1": _quadro(2),
}


def test_quadros_quase_iguais_se_juntam_e_os_diferentes_nao() -> None:
    planos = [
        _plano("p0", 0, "a1"),
        _plano("p1", 1, "b1"),
        _plano("p2", 2, "a2"),
        _plano("p3", 3, "b2"),
        _plano("p4", 4, "c1"),
    ]

    assert _grupos(planos, _QUADROS) == ["rec01", "rec02", "rec01", "rec02", None]


def test_enquadramento_canonico_diferente_nao_junta() -> None:
    planos = [
        _plano("p0", 0, "a1", enquadramento_canonico="plano médio"),
        _plano("p1", 1, "b1"),
        _plano("p2", 2, "a2", enquadramento_canonico="plano geral"),
    ]

    assert _grupos(planos, _QUADROS) == [None, None, None]


def test_decupagem_antiga_usa_o_dicionario_sobre_o_texto_livre() -> None:
    planos = [
        _plano("p0", 0, "a1", enquadramento="Close-up"),
        _plano("p1", 1, "b1"),
        _plano("p2", 2, "a2", enquadramento="close"),
    ]

    assert _grupos(planos, _QUADROS) == ["rec01", None, "rec01"]


def test_corte_real_entre_planos_seguidos_impede_a_juncao_mas_o_falso_nao() -> None:
    # Quadros iguais dos dois lados do corte: corte falso, os dois planos viram um grupo.
    falso = [_plano("p0", 0, "a1"), _plano("p1", 1, "a2")]
    assert _grupos(falso, _QUADROS) == ["rec01", "rec01"]

    # O último quadro de p0 e o primeiro de p1 diferem: o corte é real. O quadro-chave
    # (`quadro`) é o mesmo, mas dois planos seguidos com corte real não são do mesmo grupo.
    quadros = {**_QUADROS, "fim": _quadro(1), "ini": _quadro(2)}
    real = [
        {**_plano("p0", 0, "a1"), "quadros": ["a1", "fim"]},
        {**_plano("p1", 1, "a2"), "quadros": ["ini", "a2"]},
    ]
    assert _grupos(real, quadros) == [None, None]


def test_quadro_que_falta_deixa_o_plano_sem_grupo_e_a_ordem_do_tempo_vale() -> None:
    planos = [
        _plano("p2", 2, "a2"),
        _plano("p1", 1, "b1"),
        _plano("p0", 0, "a1"),
        _plano("sem", 3, None),
        _plano("ausente", 4, "nao-existe"),
    ]
    quadros = {**_QUADROS}

    def ler(caminho: str) -> bytes:
        return quadros[caminho]

    pronta = com_os_planos_recorrentes(_decupagem(planos), ler)

    # Os planos chegam fora de ordem e voltam na mesma; o id do grupo segue o tempo.
    assert [p.plano_recorrente for p in pronta.planos] == [
        "rec01",
        None,
        "rec01",
        None,
        None,
    ]


def test_agrupar_nao_junta_sinais_diferentes_nem_planos_sem_sinal() -> None:
    igual = Sinal(0, (1.0,) + (0.0,) * 63)
    outro = Sinal((1 << 40) - 1, (1.0,) + (0.0,) * 63)

    assert agrupar([igual, outro, igual, None], ["x"] * 4, [False] * 4) == [
        0,
        None,
        0,
        None,
    ]


def test_cor_diferente_com_o_mesmo_hash_nao_junta() -> None:
    a = Sinal(0, (1.0,) + (0.0,) * 63)
    b = Sinal(0, (0.0,) + (1.0,) + (0.0,) * 62)

    assert agrupar([a, b], ["x", "x"], [False, False]) == [None, None]


def test_a_ligacao_e_completa_um_intermediario_nao_une_os_extremos() -> None:
    # a~b e a~c estão dentro do limiar, b~c não: a junta com um deles, nunca os três.
    a = Sinal(0, (1.0,) + (0.0,) * 63)
    b = Sinal(0b1111111, (1.0,) + (0.0,) * 63)  # 7 bits de a
    c = Sinal(0b1111111 << 7, (1.0,) + (0.0,) * 63)  # 7 bits de a, 14 de b

    grupos = agrupar([a, b, c], ["x"] * 3, [False] * 3)

    assert len({g for g in grupos if g is not None}) == 1
    assert grupos.count(None) == 1


def test_repetir_da_o_mesmo_resultado_e_a_contagem_mostra_planos_e_grupos() -> None:
    planos = [_plano("p0", 0, "a1"), _plano("p1", 1, "b1"), _plano("p2", 2, "a2")]
    uma = com_os_planos_recorrentes(_decupagem(planos), lambda c: _QUADROS[c])
    duas = com_os_planos_recorrentes(uma, lambda c: _QUADROS[c])

    assert duas == uma
    assert contagem(uma) == {"planos": 2, "grupos": 1}


def test_a_pasta_local_mostra_o_numero_de_grupos_e_os_maiores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pasta = tmp_path / "v1"
    (pasta / "quadros").mkdir(parents=True)
    nomes = ["a1", "b1", "a2", "b2", "a1", "c1"]
    planos = [_plano(f"p{n}", n, f"quadros/{q}.png") for n, q in enumerate(nomes)]
    (pasta / "decupagem.json").write_text(_decupagem(planos).model_dump_json())
    for nome in set(nomes):
        (pasta / f"quadros/{nome}.png").write_bytes(_QUADROS[nome])

    assert main([str(pasta)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "v1: 6 planos, 5 em 2 grupos",
        "  rec01: 3 planos, 0.1 min",
        "  rec02: 2 planos, 0.0 min",
    ]
    pronta = com_os_planos_recorrentes(
        _decupagem(planos), lambda c: _QUADROS[Path(c).stem]
    )
    assert resumo(pronta, quantos=1) == [("rec01", 3, 3000)]
    assert main([]) == 2
