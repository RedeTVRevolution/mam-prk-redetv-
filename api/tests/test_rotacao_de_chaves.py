from datetime import UTC, datetime, timedelta

import pytest

from api.auth import Escopo
from api.chaves import (
    LimiteDeChavesAtivas,
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
    listar_chaves_main,
    revogar_chave,
    revogar_chave_main,
)
from api.tests.test_chave_de_api import NOVO_JOB, _cliente

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
LER: list[Escopo] = ["ler"]


def _emitir(chaves: RepositorioDeChavesEmMemoria, sistema: str = "Legado"):  # type: ignore[no-untyped-def]
    return emitir_chave(sistema, LER, MAC, chaves, BASE)


def _status(chaves: RepositorioDeChavesEmMemoria, chave: str) -> int:
    return _cliente(chaves).get("/v1/jobs", headers={"X-API-Key": chave}).status_code


def test_duas_chaves_ativas_do_mesmo_sistema_funcionam_juntas() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    a, b = _emitir(chaves), _emitir(chaves)

    assert (_status(chaves, a.chave), _status(chaves, b.chave)) == (200, 200)


def test_terceira_chave_ativa_e_recusada_ate_revogar_uma() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    a, _ = _emitir(chaves), _emitir(chaves)

    with pytest.raises(LimiteDeChavesAtivas, match="revogue"):
        _emitir(chaves)

    revogar_chave(a.registro.id, chaves, BASE)
    _emitir(chaves)


def test_limite_e_por_sistema() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    _emitir(chaves), _emitir(chaves)

    _emitir(chaves, "Outro")


def test_chave_revogada_recebe_401_na_requisicao_seguinte() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = _emitir(chaves)
    cliente = _cliente(chaves)
    cabecalho = {"X-API-Key": emitida.chave}
    assert cliente.get("/v1/jobs", headers=cabecalho).status_code == 200

    revogar_chave(emitida.registro.id, chaves, BASE)

    assert cliente.get("/v1/jobs", headers=cabecalho).status_code == 401
    assert cliente.post("/v1/jobs", json=NOVO_JOB, headers=cabecalho).status_code == 401


def test_revogada_nao_e_apagada_e_guarda_a_data() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = _emitir(chaves)

    revogar_chave(emitida.registro.id, chaves, BASE)
    revogar_chave(emitida.registro.id, chaves, BASE + timedelta(hours=1))

    (registro,) = chaves.todas()
    assert registro.revogada_em == BASE


def test_revogar_id_desconhecido_falha() -> None:
    with pytest.raises(ValueError, match="não existe"):
        revogar_chave("nada", RepositorioDeChavesEmMemoria(), BASE)


def test_listagem_mostra_id_escopos_datas_e_nunca_hash_nem_chave() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    a, b = _emitir(chaves), _emitir(chaves)
    revogar_chave(a.registro.id, chaves, BASE)
    saida: list[str] = []

    codigo = listar_chaves_main(["Legado"], chaves, saida.append)

    texto = "\n".join(saida)
    assert codigo == 0
    assert a.registro.id in texto and b.registro.id in texto
    assert "ler" in texto and BASE.isoformat() in texto
    for segredo in (a.chave, b.chave, a.registro.hmac, b.registro.hmac):
        assert segredo not in texto
    assert a.chave.rsplit(".", 1)[1] not in texto


def test_comando_revoga_por_id() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = _emitir(chaves)
    saida: list[str] = []

    codigo = revogar_chave_main(
        [emitida.registro.id], chaves, saida.append, lambda: BASE
    )

    assert codigo == 0
    assert _status(chaves, emitida.chave) == 401
    assert revogar_chave_main(["x"], chaves, saida.append, lambda: BASE) == 2


def test_comando_de_emissao_recusa_a_terceira_com_mensagem_clara() -> None:
    from api.chaves import main

    chaves = RepositorioDeChavesEmMemoria()
    _emitir(chaves), _emitir(chaves)
    saida: list[str] = []

    codigo = main(["Legado", "ler"], MAC, chaves, saida.append, lambda: BASE)

    assert codigo == 2
    assert "revogue" in "\n".join(saida)
    assert len(chaves.todas()) == 2


def test_verificador_tambem_recusa_revogada_direto() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = _emitir(chaves)
    revogar_chave(emitida.registro.id, chaves, BASE)

    from api.auth import ChaveInvalida

    with pytest.raises(ChaveInvalida):
        VerificadorDeChaveDeApi(chaves, MAC).verificar(emitida.chave)
