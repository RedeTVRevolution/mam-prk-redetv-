"""O banco de cada coleção (#368): papéis, chaves e auditoria no banco de segurança."""

import os
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from api import bancos, correcao_de_estado, purga, reprocessar_versao
from api.bancos import (
    BANCO_PADRAO,
    VARIAVEL_DO_BANCO,
    VARIAVEL_DO_BANCO_DE_SEGURANCA,
    auditoria_do_firestore,
    banco_da_colecao,
    chaves_do_firestore,
    cliente_da_colecao,
    cliente_de_seguranca,
    cliente_do_firestore,
    papeis_do_firestore,
)
from api.nuvem import (
    COLECAO_DA_AUDITORIA,
    COLECAO_DA_REVISAO,
    COLECAO_DE_CHAVES,
    COLECAO_DE_CORRECOES,
    COLECAO_DE_JOBS,
    COLECAO_DE_PAPEIS,
    RepositorioDeAuditoriaFirestore,
    RepositorioDeChavesFirestore,
    RepositorioDePapeisFirestore,
)

COM_BANCO = {VARIAVEL_DO_BANCO_DE_SEGURANCA: "seguranca-teste"}


@pytest.mark.parametrize(
    "colecao", [COLECAO_DE_PAPEIS, COLECAO_DE_CHAVES, COLECAO_DA_AUDITORIA]
)
def test_com_a_variavel_as_colecoes_de_seguranca_vao_para_o_banco_de_seguranca(
    colecao: str,
) -> None:
    assert banco_da_colecao(colecao, COM_BANCO) == "seguranca-teste"


@pytest.mark.parametrize(
    "colecao", [COLECAO_DE_JOBS, COLECAO_DE_CORRECOES, COLECAO_DA_REVISAO, "outra"]
)
def test_com_a_variavel_as_outras_colecoes_ficam_no_default(colecao: str) -> None:
    assert banco_da_colecao(colecao, COM_BANCO) == BANCO_PADRAO


@pytest.mark.parametrize("ambiente", [{}, {VARIAVEL_DO_BANCO_DE_SEGURANCA: ""}])
@pytest.mark.parametrize(
    "colecao", [COLECAO_DE_PAPEIS, COLECAO_DE_CHAVES, COLECAO_DA_AUDITORIA]
)
def test_sem_a_variavel_tudo_fica_no_default(
    colecao: str, ambiente: dict[str, str]
) -> None:
    assert banco_da_colecao(colecao, ambiente) == BANCO_PADRAO


def test_le_a_variavel_do_ambiente_do_processo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VARIAVEL_DO_BANCO_DE_SEGURANCA, "seguranca-teste")
    assert banco_da_colecao(COLECAO_DE_PAPEIS) == "seguranca-teste"
    monkeypatch.delenv(VARIAVEL_DO_BANCO_DE_SEGURANCA)
    assert banco_da_colecao(COLECAO_DE_PAPEIS) == BANCO_PADRAO


def test_o_cliente_nasce_apontado_para_o_banco_da_colecao() -> None:
    chamadas: list[dict[str, Any]] = []

    def fabrica(**kwargs: Any) -> object:
        chamadas.append(kwargs)
        return object()

    cliente_da_colecao("proj", COLECAO_DE_PAPEIS, COM_BANCO, fabrica)
    cliente_da_colecao("proj", COLECAO_DE_JOBS, COM_BANCO, fabrica)
    assert chamadas == [
        {"project": "proj", "database": "seguranca-teste"},
        {"project": "proj", "database": BANCO_PADRAO},
    ]


def test_as_colecoes_comuns_vao_para_o_banco_da_configuracao() -> None:
    ambiente = {VARIAVEL_DO_BANCO: "mam-teste", **COM_BANCO}

    assert banco_da_colecao(COLECAO_DE_JOBS, ambiente) == "mam-teste"
    # A de segurança segue no banco próprio.
    assert banco_da_colecao(COLECAO_DE_PAPEIS, ambiente) == "seguranca-teste"
    # Variável vazia é o mesmo que ausente.
    assert banco_da_colecao(COLECAO_DE_JOBS, {VARIAVEL_DO_BANCO: ""}) == BANCO_PADRAO


def test_o_cliente_do_firestore_abre_o_banco_da_configuracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas: list[dict[str, Any]] = []

    def fabrica(**kwargs: Any) -> object:
        chamadas.append(kwargs)
        return object()

    cliente_do_firestore("proj", {VARIAVEL_DO_BANCO: "mam-teste"}, fabrica)
    cliente_do_firestore("proj", {}, fabrica)
    # Sem ambiente, lê o do processo, e a fábrica padrão é a `firestore.Client` de agora.
    monkeypatch.setenv(VARIAVEL_DO_BANCO, "do-processo")
    monkeypatch.setattr(firestore, "Client", fabrica)
    cliente_do_firestore("proj")
    assert chamadas == [
        {"project": "proj", "database": "mam-teste"},
        {"project": "proj", "database": BANCO_PADRAO},
        {"project": "proj", "database": "do-processo"},
    ]


class _BancoFalso:
    """Cliente que só diz em qual banco foi aberto e quais coleções lhe pediram."""

    def __init__(self, **kwargs: Any) -> None:
        self.banco = kwargs["database"]
        self.colecoes: list[str] = []

    def collection(self, nome: str) -> object:
        self.colecoes.append(nome)
        return object()


@pytest.mark.parametrize(
    ("montar", "classe", "colecao"),
    [
        (papeis_do_firestore, RepositorioDePapeisFirestore, COLECAO_DE_PAPEIS),
        (chaves_do_firestore, RepositorioDeChavesFirestore, COLECAO_DE_CHAVES),
        (auditoria_do_firestore, RepositorioDeAuditoriaFirestore, COLECAO_DA_AUDITORIA),
    ],
)
@pytest.mark.parametrize(
    ("ambiente", "banco"),
    [(COM_BANCO, "seguranca-teste"), ({}, BANCO_PADRAO)],
)
def test_o_repositorio_de_seguranca_sai_montado_no_banco_certo(
    monkeypatch: pytest.MonkeyPatch,
    montar: Callable[..., Any],
    classe: type,
    colecao: str,
    ambiente: dict[str, str],
    banco: str,
) -> None:
    monkeypatch.setattr(firestore, "Client", _BancoFalso)
    assert cliente_de_seguranca("proj", ambiente).banco == banco
    dado = _BancoFalso(database="x")
    assert isinstance(montar("proj", ambiente, cliente=dado), classe)
    assert dado.colecoes == [colecao]


def test_o_repositorio_de_seguranca_abre_o_banco_pelo_ambiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    abertos: list[_BancoFalso] = []

    def fabrica(**kwargs: Any) -> _BancoFalso:
        abertos.append(_BancoFalso(**kwargs))
        return abertos[-1]

    monkeypatch.setattr(firestore, "Client", fabrica)
    papeis_do_firestore("proj", COM_BANCO)
    assert [(a.banco, a.colecoes) for a in abertos] == [
        ("seguranca-teste", [COLECAO_DE_PAPEIS])
    ]


class _Parou(Exception):
    pass


AMBIENTE_DO_ENTRYPOINT = {
    "GCP_PROJECT_ID": "proj",
    "BUCKET_QUARENTENA": "q",
    "BUCKET_ACEITOS": "a",
    "BUCKET_DECUPAGENS": "d",
    "BUCKET_REFERENCIAS": "f",
    "BUSCA_COLECAO": "c",
    "PUBSUB_TOPICO_EVENTOS": "te",
    "PUBSUB_TOPICO_USO": "tu",
    "WORKFLOW_REGIAO": "r",
    "WORKFLOW_VALIDACAO": "w",
    **COM_BANCO,
}


@pytest.mark.parametrize(
    ("modulo", "rodar"),
    [
        (bancos, lambda a: correcao_de_estado._do_ambiente(["j1"], a)),
        (bancos, purga.main),
        (bancos, lambda a: reprocessar_versao.main([], a)),
    ],
)
def test_os_comandos_escolhem_o_banco_pelo_ambiente_que_recebem(
    monkeypatch: pytest.MonkeyPatch,
    modulo: object,
    rodar: Callable[[Mapping[str, str]], int],
) -> None:
    monkeypatch.delenv(VARIAVEL_DO_BANCO_DE_SEGURANCA, raising=False)
    monkeypatch.setattr(firestore, "Client", lambda **_: MagicMock())
    monkeypatch.setattr("google.cloud.storage.Client", lambda **_: MagicMock())
    monkeypatch.setattr(reprocessar_versao, "ClienteStorage", lambda **_: MagicMock())

    def cliente(projeto: str, colecao: str, ambiente: Any = None) -> object:
        raise _Parou(banco_da_colecao(colecao, ambiente))

    monkeypatch.setattr(modulo, "cliente_da_colecao", cliente)
    with pytest.raises(_Parou, match="seguranca-teste"):
        rodar(AMBIENTE_DO_ENTRYPOINT)


@pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="sem emulador do Firestore"
)
def test_no_emulador_os_papeis_sao_gravados_e_lidos_so_no_banco_de_seguranca() -> None:
    # O emulador aceita banco com nome e o mantém separado do `(default)`.
    def fabrica(**kwargs: Any) -> firestore.Client:
        return firestore.Client(credentials=AnonymousCredentials(), **kwargs)  # type: ignore[no-untyped-call]

    ambiente = {VARIAVEL_DO_BANCO_DE_SEGURANCA: f"seguranca-{uuid.uuid4().hex[:8]}"}
    uid = f"uid-{uuid.uuid4().hex}"
    seguranca = RepositorioDePapeisFirestore(
        cliente_da_colecao("teste", COLECAO_DE_PAPEIS, ambiente, fabrica)
    )
    padrao = RepositorioDePapeisFirestore(
        cliente_da_colecao("teste", COLECAO_DE_PAPEIS, {}, fabrica)
    )

    seguranca.salvar(uid, ["administrador"])

    assert seguranca.obter(uid) == ["administrador"]
    assert padrao.obter(uid) is None
