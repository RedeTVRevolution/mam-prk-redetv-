"""Importar o gabarito de famosos (#353): CSV -> casos anotados do conjunto de regressão."""

from pathlib import Path

import pytest

from api.importar_gabarito import importar, main
from api.regressao import ler_casos, reservado_pelo_sorteio

SHA = "b" * 64
CSV = f"""# sha256: {SHA}
tipo,identidade,inicio,fim
aparicao,Ana Maria Braga,00:00:10,00:01:05
aparicao,Louro José,01:05,01:20
comercial,Ambev,01:00:00,01:00:30
"""


def _gabarito(tmp_path: Path) -> Path:
    pasta = tmp_path / "gabarito"
    pasta.mkdir()
    (pasta / "clipe.csv").write_text(CSV, encoding="utf-8")
    return pasta


def test_csv_vira_caso_anotado_que_passa_em_ler_casos(tmp_path: Path) -> None:
    casos = importar(_gabarito(tmp_path), tmp_path / "casos", lambda _: None)

    lidos = ler_casos(tmp_path / "casos")
    assert lidos == casos
    [caso] = lidos
    assert caso.origem == "anotado"
    assert caso.sha256 == SHA
    assert (caso.inicio_ms, caso.fim_ms) == (10_000, 3_630_000)
    assert [(e.identidade, e.inicio_ms) for e in caso.esperado] == [
        ("Ana Maria Braga", 10_000),
        ("Louro José", 65_000),
        ("Ambev", 3_600_000),
    ]
    assert caso.reservado == reservado_pelo_sorteio(caso.id)


def test_rodar_duas_vezes_nao_duplica(tmp_path: Path) -> None:
    gabarito = _gabarito(tmp_path)
    importar(gabarito, tmp_path / "casos", lambda _: None)
    importar(gabarito, tmp_path / "casos", lambda _: None)

    assert len(list((tmp_path / "casos").glob("*.json"))) == 1


def test_pasta_sem_csv_e_csv_ruim_dao_erro_sem_gravar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    assert main([str(vazia), str(tmp_path / "casos")]) == 2
    assert "nenhum CSV" in capsys.readouterr().err

    ruim = _gabarito(tmp_path)
    (ruim / "ruim.csv").write_text(
        f"# sha256: {SHA}\ntipo,identidade,inicio,fim\naparicao,Ana,00:60:00,01:00:00\n",
        encoding="utf-8",
    )
    assert main([str(ruim), str(tmp_path / "casos")]) == 2
    assert "ruim.csv, linha 3" in capsys.readouterr().err
    assert not (tmp_path / "casos").exists()


def test_trecho_novo_no_csv_tira_o_caso_antigo_do_video(tmp_path: Path) -> None:
    gabarito = _gabarito(tmp_path)
    casos = tmp_path / "casos"
    outro = "c" * 64
    (gabarito / "outro.csv").write_text(
        f"# sha256: {outro}\ntipo,identidade,inicio,fim\naparicao,Ana,00:10,00:20\n",
        encoding="utf-8",
    )
    importar(gabarito, casos, lambda _: None)
    (gabarito / "clipe.csv").write_text(
        CSV.replace("00:00:10", "00:00:05"), encoding="utf-8"
    )

    [caso, do_outro] = importar(gabarito, casos, lambda _: None)

    assert sorted(c.id for c in ler_casos(casos)) == sorted([caso.id, do_outro.id])
    assert caso.inicio_ms == 5_000
