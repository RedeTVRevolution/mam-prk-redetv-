"""Adaptador do Cloud KMS para a porta `Mac` (#272), com transporte falso e sem rede."""

import base64
import hmac
from hashlib import sha256
from typing import Any

import pytest

from api.auth import ChaveInvalida
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
    revogar_chave,
)
from api.jobs import ServicoIndisponivel, agora_utc
from api.mac_kms import ErroDoKms, MacKms, mac_do_ambiente

CHAVE = "projects/p/locations/l/keyRings/r/cryptoKeys/k"


class KmsFalso:
    """Faz o papel do Cloud KMS: guarda as versões e registra os pedidos."""

    def __init__(
        self, versoes: dict[int, bytes], estados: dict[int, str] | None = None
    ):
        self.versoes = versoes
        self.estados = estados or {}
        self.pedidos: list[tuple[str, str, dict[str, Any] | None]] = []
        self.erro: tuple[int, dict[str, Any]] | None = None
        self.tamanho_da_pagina = 100

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        self.pedidos.append((metodo, caminho, corpo))
        if self.erro:
            return self.erro
        if caminho.endswith((":macSign", ":macVerify")):
            versao = int(caminho.split("/cryptoKeyVersions/")[1].split(":")[0])
            if versao not in self.versoes:
                return 404, {"error": {"status": "NOT_FOUND"}}
            if self.estados.get(versao, "ENABLED") != "ENABLED":
                return 400, {"error": {"status": "FAILED_PRECONDITION"}}
            assert corpo is not None
            dados = base64.b64decode(corpo["data"])
            mac = hmac.digest(self.versoes[versao], dados, sha256)
            if caminho.endswith(":macSign"):
                return 200, {"mac": base64.b64encode(mac).decode()}
            esperado = base64.b64decode(corpo["mac"])
            return 200, {"success": hmac.compare_digest(mac, esperado)}
        assert metodo == "GET" and caminho.split("?")[0].endswith("/cryptoKeyVersions")
        numeros = sorted(self.versoes)
        token = int(caminho.split("pageToken=")[1]) if "pageToken=" in caminho else 0
        pagina = numeros[token : token + self.tamanho_da_pagina]
        resposta: dict[str, Any] = {
            "cryptoKeyVersions": [
                {
                    "name": f"{CHAVE}/cryptoKeyVersions/{n}",
                    "state": self.estados.get(n, "ENABLED"),
                }
                for n in pagina
            ]
        }
        if token + self.tamanho_da_pagina < len(numeros):
            resposta["nextPageToken"] = str(token + self.tamanho_da_pagina)
        return 200, resposta


def test_calcular_pede_macsign_na_versao_com_a_mensagem_em_base64() -> None:
    kms = KmsFalso({3: b"k3"})
    mac = MacKms(CHAVE, kms)

    resultado = mac.calcular(3, b"chave-de-api")

    assert resultado == hmac.digest(b"k3", b"chave-de-api", sha256)
    metodo, caminho, corpo = kms.pedidos[0]
    assert (metodo, caminho) == ("POST", f"{CHAVE}/cryptoKeyVersions/3:macSign")
    assert corpo == {"data": base64.b64encode(b"chave-de-api").decode()}


def test_verificar_usa_macverify_e_diz_se_confere() -> None:
    kms = KmsFalso({1: b"k1"})
    mac = MacKms(CHAVE, kms)
    certo = hmac.digest(b"k1", b"x", sha256)

    assert mac.verificar(1, b"x", certo) is True
    assert mac.verificar(1, b"y", certo) is False
    metodo, caminho, corpo = kms.pedidos[0]
    assert (metodo, caminho) == ("POST", f"{CHAVE}/cryptoKeyVersions/1:macVerify")
    assert corpo == {
        "data": base64.b64encode(b"x").decode(),
        "mac": base64.b64encode(certo).decode(),
    }


def test_versao_atual_e_a_mais_alta_ativa_mesmo_em_varias_paginas() -> None:
    kms = KmsFalso({1: b"a", 2: b"b", 3: b"c", 4: b"d"}, {4: "DISABLED"})
    kms.tamanho_da_pagina = 2

    assert MacKms(CHAVE, kms).versao_atual == 3
    assert [p[1].split("?")[0] for p in kms.pedidos] == [
        f"{CHAVE}/cryptoKeyVersions"
    ] * 2


def test_versao_atual_fica_guardada_por_um_tempo_e_depois_e_lida_de_novo() -> None:
    kms = KmsFalso({1: b"a"})
    agora = [0.0]
    mac = MacKms(CHAVE, kms, relogio=lambda: agora[0], validade_s=60)

    assert mac.versao_atual == 1
    kms.versoes[2] = b"b"
    agora[0] = 59
    assert mac.versao_atual == 1
    agora[0] = 61
    assert mac.versao_atual == 2
    assert len(kms.pedidos) == 2


def test_sem_versao_ativa_e_erro() -> None:
    with pytest.raises(ErroDoKms):
        _ = MacKms(CHAVE, KmsFalso({1: b"a"}, {1: "DESTROYED"})).versao_atual


def test_versao_que_nao_existe_ou_desligada_e_keyerror() -> None:
    kms = KmsFalso({1: b"a", 2: b"b"}, {2: "DISABLED"})
    mac = MacKms(CHAVE, kms)

    for versao in (9, 2):
        with pytest.raises(KeyError):
            mac.calcular(versao, b"x")
        with pytest.raises(KeyError):
            mac.verificar(versao, b"x", b"\0")


def test_erro_http_vira_erro_do_kms_com_o_status() -> None:
    kms = KmsFalso({1: b"a"})
    kms.erro = (403, {"error": {"status": "PERMISSION_DENIED", "message": "sem papel"}})
    mac = MacKms(CHAVE, kms)

    for chamada in (
        lambda: mac.calcular(1, b"x"),
        lambda: mac.verificar(1, b"x", b"\0"),
        lambda: mac.versao_atual,
    ):
        with pytest.raises(ErroDoKms, match="403"):
            chamada()


def test_com_a_variavel_a_montagem_usa_o_kms() -> None:
    kms = KmsFalso({1: b"a"})

    mac = mac_do_ambiente(
        {"KMS_CHAVE_MAC": CHAVE, "MAC_SIMULADO_CHAVE": "00"}, lambda: kms
    )

    assert isinstance(mac, MacKms)
    mac.calcular(1, b"x")
    assert kms.pedidos


def test_sem_a_variavel_a_montagem_usa_o_simulado() -> None:
    def sem_transporte() -> Any:
        raise AssertionError("não devia abrir o transporte")

    mac = mac_do_ambiente({"MAC_SIMULADO_CHAVE": "6b31"}, sem_transporte)

    assert isinstance(mac, MacSimulado)
    assert mac.versao_atual == 1
    assert mac.calcular(1, b"x") == hmac.digest(b"k1", b"x", sha256)


def test_sem_nenhuma_das_duas_nao_ha_mac() -> None:
    assert mac_do_ambiente({}, lambda: KmsFalso({})) is None


def test_erro_do_kms_e_servico_indisponivel_para_a_api_dar_503() -> None:
    assert issubclass(ErroDoKms, ServicoIndisponivel)


def test_o_token_da_pagina_vai_codificado() -> None:
    pedidos: list[str] = []

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        pedidos.append(caminho)
        if len(pedidos) == 1:
            return 200, {"nextPageToken": "a+b/c="}
        return 200, {
            "cryptoKeyVersions": [
                {"name": f"{CHAVE}/cryptoKeyVersions/1", "state": "ENABLED"}
            ]
        }

    assert MacKms(CHAVE, transporte).versao_atual == 1
    assert pedidos[1] == f"{CHAVE}/cryptoKeyVersions?pageToken=a%2Bb%2Fc%3D"


def test_chave_que_confere_vale_mesmo_se_o_kms_falha_na_troca_de_versao() -> None:
    kms = KmsFalso({1: b"a"})
    repositorio = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave(
        "Legado", ["ler"], MacKms(CHAVE, kms), repositorio, agora_utc()
    )

    def lista_falha(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        if metodo == "GET":
            return 503, {"error": {"status": "UNAVAILABLE"}}
        return kms(metodo, caminho, corpo)

    sistema = VerificadorDeChaveDeApi(
        repositorio, MacKms(CHAVE, lista_falha)
    ).verificar(emitida.chave)

    assert sistema.sistema == "Legado"
    assert repositorio.obter(emitida.registro.id) == emitida.registro


def _macverify(kms: KmsFalso) -> int:
    return sum(1 for _, c, _ in kms.pedidos if c.endswith(":macVerify"))


def test_macverify_positivo_do_mesmo_segredo_vai_ao_kms_uma_vez() -> None:
    kms = KmsFalso({1: b"k1"})
    mac = MacKms(CHAVE, kms)
    certo = hmac.digest(b"k1", b"x", sha256)

    assert mac.verificar(1, b"x", certo) is True
    assert mac.verificar(1, b"x", certo) is True
    assert _macverify(kms) == 1


def test_segredo_errado_sempre_chama_o_kms() -> None:
    kms = KmsFalso({1: b"k1"})
    mac = MacKms(CHAVE, kms)
    certo = hmac.digest(b"k1", b"x", sha256)

    assert mac.verificar(1, b"x", certo) is True
    assert mac.verificar(1, b"errado", certo) is False
    assert mac.verificar(1, b"errado", certo) is False
    assert _macverify(kms) == 3


def test_resultado_positivo_vale_por_versao_e_expira() -> None:
    kms = KmsFalso({1: b"k1", 2: b"k1"})
    agora = [0.0]
    mac = MacKms(CHAVE, kms, relogio=lambda: agora[0], validade_do_mac_s=60.0)
    certo = hmac.digest(b"k1", b"x", sha256)

    mac.verificar(1, b"x", certo)
    mac.verificar(2, b"x", certo)
    assert _macverify(kms) == 2
    agora[0] = 61.0
    mac.verificar(1, b"x", certo)
    assert _macverify(kms) == 3


def test_o_cache_do_mac_tem_tamanho_maximo() -> None:
    kms = KmsFalso({1: b"k1"})
    mac = MacKms(CHAVE, kms, maximo_do_mac=2)
    for m in (b"a", b"b", b"c"):
        mac.verificar(1, m, hmac.digest(b"k1", m, sha256))
    mac.verificar(1, b"a", hmac.digest(b"k1", b"a", sha256))
    assert _macverify(kms) == 4


def test_chave_revogada_e_recusada_no_pedido_seguinte_mesmo_com_o_mac_guardado() -> (
    None
):
    kms = KmsFalso({1: b"k1"})
    repositorio = RepositorioDeChavesEmMemoria()
    mac = MacKms(CHAVE, kms)
    emitida = emitir_chave("Legado", ["ler"], mac, repositorio, agora_utc())
    verificador = VerificadorDeChaveDeApi(repositorio, mac)

    assert verificador.verificar(emitida.chave).sistema == "Legado"
    assert verificador.verificar(emitida.chave).sistema == "Legado"
    assert _macverify(kms) == 1
    revogar_chave(emitida.registro.id, repositorio, agora_utc())

    with pytest.raises(ChaveInvalida):
        verificador.verificar(emitida.chave)
