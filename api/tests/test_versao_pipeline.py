"""A versão do pipeline (#250): o manifesto fixado, a gravação na decupagem e a leitura da antiga."""

import json
from pathlib import Path

from api.decupagem import Decupagem
from api.tests.test_analise import SHA, _ambiente, _analisar
from api.tests.test_gemini import BOA
from api.versao_pipeline import VERSAO_PIPELINE, manifesto

FIXADO = Path(__file__).parent / "versao_pipeline_fixada.json"


def test_o_manifesto_so_muda_junto_com_a_versao_do_pipeline() -> None:
    fixado = json.loads(FIXADO.read_text())

    atual = {"versao_pipeline": VERSAO_PIPELINE, "manifesto": manifesto()}

    assert atual == fixado, (
        "Modelo, instrução, esquema ou motor mudou (ou a versão mudou sozinha): "
        "troque `VERSAO_PIPELINE` em api/versao_pipeline.py e regrave "
        "api/tests/versao_pipeline_fixada.json com o `atual` deste teste. "
        "Uma versão nova permite reprocessar o acervo (`make reprocessar-versao`)."
    )


def test_a_decupagem_nova_traz_a_versao_e_o_manifesto() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j1")

    _analisar(ambiente, "j1")

    gravada = Decupagem.model_validate_json(ambiente.decupagens.gravadas["j1"])
    assert gravada.versao_pipeline == VERSAO_PIPELINE
    assert gravada.manifesto_do_pipeline == manifesto()


def test_a_decupagem_antiga_sem_a_versao_continua_sendo_lida() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j1")
    _analisar(ambiente, "j1")
    antiga = json.loads(ambiente.decupagens.gravadas["j1"])
    del antiga["versao_pipeline"], antiga["manifesto_do_pipeline"]

    lida = Decupagem.model_validate(antiga)

    assert (lida.versao_pipeline, lida.manifesto_do_pipeline) == (None, None)
    assert lida.video.sha256 == SHA


def test_busca_nao_faz_parte_das_etapas_da_decupagem() -> None:
    fixado = manifesto()
    assert all(
        "consulta" not in fixado[parte] for parte in ("modelos", "modos", "instrucoes")
    )
