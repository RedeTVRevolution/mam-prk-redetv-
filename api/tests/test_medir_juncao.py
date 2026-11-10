"""A medição da junção em dado local (#547)."""

import json
from pathlib import Path

import pytest

from api.medir_juncao import amostra, main, medir
from api.tests.test_juncao_de_pessoas import decupagem, pessoa


def test_a_medicao_conta_pessoas_antes_e_depois_e_o_tamanho_do_lote() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)]),
            pessoa(
                "pes03",
                2,
                [(700_000, 710_000)],
                nome="Não identificado, blusa vermelha, calvo",
            ),
        ]
    )

    m = medir("a.json", d)

    assert (m.pessoas_antes, m.pessoas_depois) == (3, 2)
    assert m.unidas_sem_perguntar == 1
    assert (m.na_duvida, m.pares_no_lote, m.quadros_no_lote) == (2, 2, 3)


def test_a_amostra_e_estavel_e_traz_um_par_por_grupo() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)]),
            pessoa("pes03", 2, [(700_000, 710_000)]),
        ]
    )

    a = amostra({"a.json": d}, 10)

    assert len(a) == 1 and a[0]["grupo"] == "a.json:pes01"
    assert a[0]["a"] != a[0]["b"]
    assert amostra({"a.json": d}, 10) == a


def test_o_script_le_o_arquivo_local_e_imprime_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arquivo = tmp_path / "d.json"
    arquivo.write_text(
        decupagem(
            [
                pessoa("pes01", 0, [(100_000, 110_000)]),
                pessoa("pes02", 1, [(400_000, 410_000)]),
            ]
        ).model_dump_json()
    )

    assert main([str(arquivo)]) == 0

    saida = json.loads(capsys.readouterr().out)
    assert (saida["pessoas_antes"], saida["pessoas_depois"]) == (2, 1)
