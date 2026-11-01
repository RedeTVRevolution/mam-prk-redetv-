import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from api import gemini
from api.cassete import CASSETE, gravar, instrucao_sha256
from api.decupagem import VERSAO_ESQUEMA, Video
from api.gemini import MODELO, VERSAO_DO_MODELO, analisar
from api.tests.test_gemini import BOA, VIDEO, VIDEO_CONFIAVEL, TransporteFalso


class TransporteComVersaoFalso(TransporteFalso):
    versao_do_modelo = VERSAO_DO_MODELO


def _cassete() -> dict[str, Any]:
    if not CASSETE.exists():
        pytest.fail("cassete do Gemini ausente: grave com `make gravar-cassetes`")
    dados: dict[str, Any] = json.loads(CASSETE.read_text())
    return dados


def test_cassete_foi_gravado_com_o_modelo_em_uso() -> None:
    """Trocar o modelo derruba o contrato até o cassete ser regravado."""
    assert _cassete()["modelo"] == MODELO


def _exige_instrucao_atual(cassete: dict[str, Any]) -> None:
    """O contrato do cassete: a resposta gravada vale para a `INSTRUCAO` de hoje."""
    assert cassete.get("instrucao_sha256") == instrucao_sha256(), (
        "a INSTRUCAO de api/gemini.py mudou desde a gravação do cassete: "
        "regrave com `make gravar-cassetes`."
    )


@pytest.mark.skip(reason="cassete sem instrucao_sha256; pendente de regravação no #229")
def test_cassete_foi_gravado_com_a_instrucao_em_uso() -> None:
    _exige_instrucao_atual(_cassete())


def test_mudar_uma_letra_da_instrucao_derruba_o_contrato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cassete = {"instrucao_sha256": instrucao_sha256()}
    original = gemini.INSTRUCAO

    monkeypatch.setattr(gemini, "INSTRUCAO", original + "x")
    with pytest.raises(AssertionError, match="make gravar-cassetes"):
        _exige_instrucao_atual(cassete)

    monkeypatch.setattr(gemini, "INSTRUCAO", original)
    _exige_instrucao_atual(cassete)


def test_cassete_foi_gravado_com_a_versao_fixada() -> None:
    """`MODELO` pode ser um apelido que o Google atualiza por baixo."""
    gravada = _cassete()["versao_do_modelo"]
    assert gravada == VERSAO_DO_MODELO, (
        f"a Vertex respondeu com {gravada!r}, e o fixado é {VERSAO_DO_MODELO!r}: "
        "a versão do modelo mudou. Confira a resposta e atualize VERSAO_DO_MODELO."
    )


def test_cassete_nao_guarda_nada_alem_das_chaves_previstas() -> None:
    """Vale antes e depois da regravação do #229: nenhum cabeçalho nem credencial."""
    assert set(_cassete()) <= {
        "modelo",
        "versao_do_modelo",
        "video",
        "texto",
        "instrucao_sha256",
    }


@pytest.mark.skip(reason="cassete sem instrucao_sha256; pendente de regravação no #229")
def test_cassete_guarda_so_modelo_versao_video_texto_e_instrucao_sem_cabecalhos() -> (
    None
):
    assert set(_cassete()) == {
        "modelo",
        "versao_do_modelo",
        "video",
        "texto",
        "instrucao_sha256",
    }


@pytest.mark.skip(
    reason="cassete gravado com o esquema 1.3; pendente de regravação no #229"
)
def test_resposta_gravada_passa_no_esquema_e_nos_invariantes_de_primeira() -> None:
    """O esquema 1.1 confere início ≤ fim e todo tempo dentro da duração."""
    cassete = _cassete()
    transporte = TransporteFalso(cassete["texto"])

    d = analisar(
        transporte,
        video_uri=VIDEO,
        job_id="contrato",
        video=Video(**cassete["video"]),
    )

    assert d.versao_esquema == VERSAO_ESQUEMA
    assert d.programa.resumo
    assert len(transporte.chamadas) == 1


def test_grava_so_a_resposta_que_passou_no_esquema(tmp_path: Path) -> None:
    destino = tmp_path / "cassete.json"

    gravar(
        TransporteComVersaoFalso("lixo", BOA),
        video_uri=VIDEO,
        video=VIDEO_CONFIAVEL,
        destino=destino,
    )

    cassete = json.loads(destino.read_text())
    assert cassete == {
        "modelo": MODELO,
        "versao_do_modelo": VERSAO_DO_MODELO,
        "video": {"sha256": "b" * 64, "duracao_ms": VIDEO_CONFIAVEL.duracao_ms},
        "texto": BOA,
        "instrucao_sha256": hashlib.sha256(
            gemini.INSTRUCAO.encode("utf-8")
        ).hexdigest(),
    }


def test_nao_grava_sem_a_versao_do_modelo(tmp_path: Path) -> None:
    transporte = TransporteComVersaoFalso(BOA)
    transporte.versao_do_modelo = ""
    destino = tmp_path / "cassete.json"

    with pytest.raises(RuntimeError, match="versão do modelo"):
        gravar(transporte, video_uri=VIDEO, video=VIDEO_CONFIAVEL, destino=destino)

    assert not destino.exists()
