"""Chaves de API dos sistemas da RedeTV (E7): emissão e conferência.

A chave tem a forma `<prefixo>.<id público>.<segredo>`. O repositório guarda só o
HMAC dela, calculado pela porta `Mac` (no plano, uma chave MAC do Cloud KMS).
"""

import hmac
import re
import secrets
from collections.abc import Callable, Iterable
from datetime import datetime
from hashlib import sha256
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict

from api.auth import ESCOPOS, ChaveInvalida, Escopo, Sistema
from api.jobs import agora_utc


class Mac(Protocol):
    """Porta para o Cloud KMS; os testes e a máquina local usam `MacSimulado`."""

    @property
    def versao_atual(self) -> int: ...

    def calcular(self, versao: int, mensagem: bytes) -> bytes:
        """HMAC-SHA256 da mensagem com a versão da chave MAC. `KeyError` se a versão não existe."""
        ...


class MacSimulado:
    """Uma chave por versão, com o `hmac` da stdlib."""

    def __init__(self, chaves: dict[int, bytes], versao_atual: int) -> None:
        self._chaves = chaves
        self.versao_atual = versao_atual

    def calcular(self, versao: int, mensagem: bytes) -> bytes:
        return hmac.digest(self._chaves[versao], mensagem, sha256)


class RegistroDeChave(BaseModel):
    """O que fica no repositório: nunca a chave em texto."""

    model_config = ConfigDict(frozen=True)

    id: str
    sistema: str
    # Registro sem escopos (anterior à E7 isolada) não pode nada.
    escopos: list[Escopo] = []
    hmac: str
    versao_mac: int
    criada_em: datetime


class RepositorioDeChaves(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, registro: RegistroDeChave) -> None: ...

    def obter(self, chave_id: str) -> RegistroDeChave | None: ...


class RepositorioDeChavesEmMemoria:
    def __init__(self) -> None:
        self._registros: dict[str, RegistroDeChave] = {}

    def salvar(self, registro: RegistroDeChave) -> None:
        self._registros[registro.id] = registro

    def obter(self, chave_id: str) -> RegistroDeChave | None:
        return self._registros.get(chave_id)

    def todas(self) -> list[RegistroDeChave]:
        return list(self._registros.values())


class ChaveEmitida(BaseModel):
    chave: str
    registro: RegistroDeChave


def _prefixo(sistema: str) -> str:
    prefixo = re.sub(r"[^a-z0-9]+", "-", sistema.lower()).strip("-")
    if not prefixo:
        raise ValueError("nome do sistema sem letras ou números")
    return prefixo


def emitir_chave(
    sistema: str,
    escopos: Iterable[Escopo],
    mac: Mac,
    repositorio: RepositorioDeChaves,
    criada_em: datetime,
) -> ChaveEmitida:
    """Gera a chave (256 bits aleatórios) e grava só o HMAC. A chave sai só daqui.
    Exige ao menos um escopo: nada é dado por padrão."""
    escopos = sorted(set(escopos))
    if not escopos:
        raise ValueError("informe ao menos um escopo")
    id_publico = secrets.token_hex(8)
    chave = f"{_prefixo(sistema)}.{id_publico}.{secrets.token_urlsafe(32)}"
    versao = mac.versao_atual
    registro = RegistroDeChave(
        id=id_publico,
        sistema=sistema,
        escopos=escopos,
        hmac=mac.calcular(versao, chave.encode()).hex(),
        versao_mac=versao,
        criada_em=criada_em,
    )
    repositorio.salvar(registro)
    return ChaveEmitida(chave=chave, registro=registro)


class VerificadorDeChaveDeApi:
    def __init__(self, repositorio: RepositorioDeChaves, mac: Mac) -> None:
        self._repositorio = repositorio
        self._mac = mac

    def verificar(self, chave: str) -> Sistema:
        partes = chave.split(".")
        if len(partes) != 3:
            raise ChaveInvalida
        # Procura pelo id público: nunca compara com todos os hashes.
        registro = self._repositorio.obter(partes[1])
        if registro is None:
            raise ChaveInvalida
        try:
            esperado = self._mac.calcular(registro.versao_mac, chave.encode())
        except KeyError:
            raise ChaveInvalida from None
        if not hmac.compare_digest(esperado.hex(), registro.hmac):
            raise ChaveInvalida
        versao = self._mac.versao_atual
        if registro.versao_mac != versao:
            self._repositorio.salvar(
                registro.model_copy(
                    update={
                        "hmac": self._mac.calcular(versao, chave.encode()).hex(),
                        "versao_mac": versao,
                    }
                )
            )
        return Sistema(sistema=registro.sistema, escopos=registro.escopos)


def main(
    argv: list[str],
    mac: Mac,
    repositorio: RepositorioDeChaves,
    imprimir: Callable[[str], None] = print,
    relogio: Callable[[], datetime] = agora_utc,
) -> int:
    uso = (
        "uso: make emitir-chave SISTEMA=<nome do sistema> ESCOPOS=<criar,ler,cancelar>"
    )
    if len(argv) != 2:
        imprimir(uso)
        return 2
    pedidos = [e.strip() for e in argv[1].split(",") if e.strip()]
    desconhecidos = [e for e in pedidos if e not in ESCOPOS]
    if desconhecidos:
        imprimir(f"escopo desconhecido: {', '.join(desconhecidos)}. {uso}")
        return 2
    try:
        emitida = emitir_chave(
            argv[0],
            cast(list[Escopo], pedidos),
            mac,
            repositorio,
            relogio(),
        )
    except ValueError as erro:
        imprimir(f"{erro}. {uso}")
        return 2
    imprimir(
        f"Sistema: {argv[0]} · escopos: {', '.join(emitida.registro.escopos)}"
        f" · id: {emitida.registro.id}"
    )
    imprimir("Guarde a chave agora: ela não será mostrada de novo.")
    imprimir(emitida.chave)
    return 0
