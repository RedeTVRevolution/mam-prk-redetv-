"""`make comparar-leituras` (#233): duas leituras da tela sintéticas."""

import json
from pathlib import Path

import pytest

from api.comparar_leituras import (
    AparicaoMudada,
    Execucao,
    comparar,
    formatar,
    main,
)
from api.leitura_da_tela import Caixa, LeituraDaTela, LinhaLida, QuadroLido


def _leitura(por_segundo: dict[int, list[str]], total: int = 20) -> LeituraDaTela:
    return LeituraDaTela(
        modelo="m",
        quadros=[
            QuadroLido(
                segundo=s,
                linhas=[
                    LinhaLida(
                        texto=t,
                        confianca=0.9,
                        caixa=Caixa(x=0, y=0.8, largura=0.5, altura=0.1),
                    )
                    for t in por_segundo.get(s, [])
                ],
            )
            for s in range(total)
        ],
    )


def _de(texto: str, inicio: int, fim: int) -> dict[int, list[str]]:
    return {s: [texto] for s in range(inicio, fim + 1)}


def test_textos_que_so_um_dos_lados_achou() -> None:
    referencia = _leitura({**_de("ULTRAFARMA", 2, 5), **_de("Só na referência", 8, 9)})
    nova = _leitura({**_de("ultrafarma!", 2, 5), **_de("Só na nova", 12, 13)})

    resultado = comparar(referencia, nova)

    assert resultado.so_na_referencia == ["so na referencia"]
    assert resultado.so_na_nova == ["so na nova"]
    assert resultado.aparicoes_mudadas == []


def test_aparicao_com_inicio_ou_fim_mudado_em_mais_de_1_s() -> None:
    referencia = _leitura(_de("GC", 3, 8))
    # Começa 2 s depois e termina 1 s antes (1 s é a tolerância, só o início passa).
    nova = _leitura(_de("GC", 5, 7))

    resultado = comparar(referencia, nova)

    assert resultado.aparicoes_mudadas == [
        AparicaoMudada("gc", referencia=(3, 9), nova=(5, 8))
    ]


def test_mudanca_de_ate_1_s_nao_conta() -> None:
    referencia = _leitura(_de("GC", 3, 8))
    nova = _leitura(_de("GC", 4, 8))

    assert comparar(referencia, nova).aparicoes_mudadas == []


def test_aparicao_que_a_nova_nao_achou_naquele_trecho() -> None:
    # O mesmo texto aparece duas vezes; a nova só achou a primeira.
    referencia = _leitura({**_de("GC", 1, 3), **_de("GC", 12, 14)})
    nova = _leitura(_de("GC", 1, 3))

    resultado = comparar(referencia, nova)

    assert resultado.so_na_referencia == []
    assert resultado.aparicoes_mudadas == [
        AparicaoMudada("gc", referencia=(12, 15), nova=None)
    ]


def test_falha_isolada_do_ocr_nao_parte_a_aparicao() -> None:
    referencia = _leitura(_de("GC", 1, 8))
    nova = _leitura({s: ["GC"] for s in (1, 2, 3, 5, 6, 7, 8)})

    assert comparar(referencia, nova).aparicoes_mudadas == []


def test_o_relatorio_traz_quadros_e_tempo() -> None:
    referencia = _leitura(_de("GC", 1, 3))
    nova = _leitura(_de("GC", 1, 3))

    texto = formatar(
        comparar(referencia, nova, Execucao(20, 2970.0), Execucao(7, 1200.0))
    )

    assert "referência: quadros lidos 20 de 20; tempo de processamento 2970 s" in texto
    assert "nova: quadros lidos 7 de 20; tempo de processamento 1200 s" in texto
    assert "nenhum" in texto and "nenhuma" in texto


def test_o_relatorio_sem_opcoes_diz_que_nao_foi_informado() -> None:
    texto = formatar(comparar(_leitura({}), _leitura({})))

    assert (
        "referência: quadros lidos 20 de 20; tempo de processamento não informado"
        in texto
    )
    assert (
        "nova: quadros lidos não informado; tempo de processamento não informado"
        in texto
    )


def test_o_comando_le_os_json_e_imprime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "ref.json").write_text(_leitura(_de("GC", 1, 3)).model_dump_json())
    (tmp_path / "nova.json").write_text(_leitura(_de("OUTRO", 1, 3)).model_dump_json())

    main(
        [
            str(tmp_path / "ref.json"),
            str(tmp_path / "nova.json"),
            "--lidos-nova",
            "5",
            "--segundos-nova",
            "60",
        ]
    )

    saida = capsys.readouterr().out
    assert "só a referência achou:\n  gc" in saida
    assert "só a nova achou:\n  outro" in saida
    assert "nova: quadros lidos 5 de 20; tempo de processamento 60 s" in saida
    assert json.loads((tmp_path / "ref.json").read_text())["modelo"] == "m"


def test_o_make_e_o_readme_conhecem_o_comando() -> None:
    raiz = Path(__file__).parents[2]

    assert "comparar-leituras:" in (raiz / "Makefile").read_text()
    assert "make comparar-leituras" in (raiz / "README.md").read_text()
