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
from api.jobs import ServicoIndisponivel, agora_utc


class Mac(Protocol):
    """Porta para o Cloud KMS (`api.mac_kms.MacKms`); os testes e a máquina local usam
    `MacSimulado`."""

    @property
    def versao_atual(self) -> int: ...

    def calcular(self, versao: int, mensagem: bytes) -> bytes:
        """HMAC-SHA256 da mensagem com a versão da chave MAC. `KeyError` se a versão não existe."""
        ...

    def verificar(self, versao: int, mensagem: bytes, mac: bytes) -> bool:
        """Se `mac` é o HMAC da mensagem com a versão. `KeyError` se a versão não existe."""
        ...


class MacSimulado:
    """Uma chave por versão, com o `hmac` da stdlib."""

    def __init__(self, chaves: dict[int, bytes], versao_atual: int) -> None:
        self._chaves = chaves
        self.versao_atual = versao_atual

    def calcular(self, versao: int, mensagem: bytes) -> bytes:
        return hmac.digest(self._chaves[versao], mensagem, sha256)

    def verificar(self, versao: int, mensagem: bytes, mac: bytes) -> bool:
        return hmac.compare_digest(self.calcular(versao, mensagem), mac)


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
    # Revogada não é apagada: o registro fica para auditoria.
    revogada_em: datetime | None = None

    @property
    def ativa(self) -> bool:
        return self.revogada_em is None


MAXIMO_DE_CHAVES_ATIVAS = 2


class LimiteDeChavesAtivas(ValueError):
    def __init__(self, sistema: str) -> None:
        super().__init__(
            f"o sistema {sistema} já tem {MAXIMO_DE_CHAVES_ATIVAS} chaves ativas: "
            "revogue uma antes de emitir outra"
        )


class RepositorioDeChaves(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, registro: RegistroDeChave) -> None: ...

    def obter(self, chave_id: str) -> RegistroDeChave | None: ...

    def listar_por_sistema(self, sistema: str) -> list[RegistroDeChave]: ...

    def listar(self) -> list[RegistroDeChave]:
        """Todas as chaves, das mais novas para as mais antigas."""
        ...

    def salvar_nova(self, registro: RegistroDeChave, maximo_ativas: int) -> None:
        """Grava a chave nova se o sistema tiver menos de `maximo_ativas` ativas.
        Contagem e gravação são atômicas. `LimiteDeChavesAtivas` se estourar."""
        ...


class RepositorioDeChavesEmMemoria:
    def __init__(self) -> None:
        self._registros: dict[str, RegistroDeChave] = {}

    def salvar(self, registro: RegistroDeChave) -> None:
        self._registros[registro.id] = registro

    def obter(self, chave_id: str) -> RegistroDeChave | None:
        return self._registros.get(chave_id)

    def listar_por_sistema(self, sistema: str) -> list[RegistroDeChave]:
        return sorted(
            (r for r in self._registros.values() if r.sistema == sistema),
            key=lambda r: r.criada_em,
        )

    def salvar_nova(self, registro: RegistroDeChave, maximo_ativas: int) -> None:
        ativas = [r for r in self.listar_por_sistema(registro.sistema) if r.ativa]
        if len(ativas) >= maximo_ativas:
            raise LimiteDeChavesAtivas(registro.sistema)
        self.salvar(registro)

    def listar(self) -> list[RegistroDeChave]:
        return sorted(self._registros.values(), key=lambda r: r.criada_em, reverse=True)

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
    Exige ao menos um escopo: nada é dado por padrão. No máximo duas ativas por sistema."""
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
    repositorio.salvar_nova(registro, MAXIMO_DE_CHAVES_ATIVAS)
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
        if registro is None or not registro.ativa:
            raise ChaveInvalida
        try:
            confere = self._mac.verificar(
                registro.versao_mac, chave.encode(), bytes.fromhex(registro.hmac)
            )
        except (KeyError, ValueError):
            raise ChaveInvalida from None
        if not confere:
            raise ChaveInvalida
        # Trocar de versão é só manutenção: se o KMS falhar aqui, a chave já conferiu e
        # a troca fica para o próximo uso.
        try:
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
        except ServicoIndisponivel:
            pass
        return Sistema(sistema=registro.sistema, escopos=registro.escopos)


def revogar_chave(
    chave_id: str, repositorio: RepositorioDeChaves, revogada_em: datetime
) -> RegistroDeChave:
    """Vale na hora: a API lê o registro a cada requisição. Repetir não muda a data.
    Devolve o registro revogado."""
    registro = repositorio.obter(chave_id)
    if registro is None:
        raise ValueError(f"a chave {chave_id} não existe")
    if registro.ativa:
        registro = registro.model_copy(update={"revogada_em": revogada_em})
        repositorio.salvar(registro)
    return registro


def listar_chaves_main(
    argv: list[str],
    repositorio: RepositorioDeChaves,
    imprimir: Callable[[str], None] = print,
) -> int:
    if len(argv) != 1 or not argv[0]:
        imprimir("uso: make listar-chaves SISTEMA=<nome do sistema>")
        return 2
    for r in repositorio.listar_por_sistema(argv[0]):
        revogada = r.revogada_em.isoformat() if r.revogada_em else "-"
        imprimir(
            f"id: {r.id} · escopos: {', '.join(r.escopos)}"
            f" · criada em: {r.criada_em.isoformat()} · revogada em: {revogada}"
        )
    return 0


def revogar_chave_main(
    argv: list[str],
    repositorio: RepositorioDeChaves,
    imprimir: Callable[[str], None] = print,
    relogio: Callable[[], datetime] = agora_utc,
) -> int:
    if len(argv) != 1 or not argv[0]:
        imprimir("uso: make revogar-chave ID=<id da chave>")
        return 2
    try:
        revogar_chave(argv[0], repositorio, relogio())
    except ValueError as erro:
        imprimir(str(erro))
        return 2
    imprimir(f"Chave {argv[0]} revogada.")
    return 0


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
