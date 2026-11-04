from typing import get_args

import pytest

from api.papeis import (
    PERMISSOES_DO_PAPEL,
    ContaNaoEncontrada,
    Permissao,
    RepositorioDePapeisEmMemoria,
    admins_de,
    atribuir_papeis_main,
    papeis_do_usuario,
    papeis_efetivos,
    permissoes_de,
)


def test_consulta_so_ve_a_decupagem() -> None:
    assert permissoes_de(["consulta"]) == {"decupagem.ver"}


def test_operador_e_consulta_mais_enviar_video() -> None:
    assert permissoes_de(["operador"]) == {
        "decupagem.ver",
        "video.enviar",
        "video.reprocessar",
    }


def test_editor_e_consulta_mais_editar() -> None:
    assert permissoes_de(["editor"]) == {"decupagem.ver", "decupagem.editar"}


def test_curador_e_editor_mais_aprovar_correcao_e_reprocessar_etapa() -> None:
    assert permissoes_de(["curador"]) == {
        "decupagem.ver",
        "decupagem.editar",
        "correcao.aprovar",
        "video.reprocessar_etapa",
        "catalogo.apagar",
        "catalogo.fundir",
    }


def test_so_o_curador_aprova_correcao() -> None:
    for papel in ("consulta", "operador", "editor"):
        assert "correcao.aprovar" not in permissoes_de([papel])


def test_varios_papeis_somam_permissoes() -> None:
    assert permissoes_de(["operador", "editor"]) == {
        "decupagem.ver",
        "video.enviar",
        "video.reprocessar",
        "decupagem.editar",
    }


def test_sem_papeis_nao_ha_permissao() -> None:
    assert permissoes_de([]) == set()


def test_conta_sem_documento_vale_consulta_e_operador() -> None:
    assert papeis_efetivos(None) == ["consulta", "operador"]
    assert permissoes_de(papeis_efetivos(None)) == {
        "decupagem.ver",
        "video.enviar",
        "video.reprocessar",
    }


def test_conta_com_documento_usa_so_os_papeis_dele() -> None:
    assert papeis_efetivos(["consulta"]) == ["consulta"]


def _uids(email: str) -> str:
    if email != "ana@redetv.com.br":
        raise ContaNaoEncontrada(email)
    return "u1"


def test_atribuir_grava_os_papeis_do_uid_do_email() -> None:
    repo = RepositorioDePapeisEmMemoria()
    saida: list[str] = []

    codigo = atribuir_papeis_main(
        ["ana@redetv.com.br", "editor,curador"], repo, _uids, saida.append
    )

    assert codigo == 0
    assert repo.obter("u1") == ["editor", "curador"]
    assert any("u1" in linha for linha in saida)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["ana@redetv.com.br"],
        ["ana@redetv.com.br", ""],
        ["ana@redetv.com.br", "chefe"],
        ["nao@redetv.com.br", "editor"],
    ],
)
def test_atribuir_recusa_pedido_invalido_sem_gravar(argv: list[str]) -> None:
    repo = RepositorioDePapeisEmMemoria()
    saida: list[str] = []

    assert atribuir_papeis_main(argv, repo, _uids, saida.append) == 2
    assert repo.obter("u1") is None
    assert saida


def test_administrador_tem_todas_as_permissoes() -> None:
    assert permissoes_de(["administrador"]) == set(get_args(Permissao))


@pytest.mark.parametrize(
    ("email", "verificado", "admins", "esperado"),
    [
        (" Ana@RedeTV.com.br", True, "ana@redetv.com.br", True),
        ("ana@redetv.com.br", True, "x@y.z, ANA@redetv.com.br ,", True),
        ("ana@redetv.com.br", False, "ana@redetv.com.br", False),
        ("ana@redetv.com.br", True, "outra@redetv.com.br", False),
        ("ana@redetv.com.br", True, None, False),
        ("", True, "", False),
    ],
)
def test_so_email_verificado_da_lista_vira_administrador(
    email: str, verificado: bool, admins: str | None, esperado: bool
) -> None:
    papeis = papeis_do_usuario(["consulta"], email, verificado, admins_de(admins))

    assert ("administrador" in papeis) is esperado
    assert "consulta" in papeis


def test_administrador_sem_documento_soma_aos_papeis_padrao() -> None:
    papeis = papeis_do_usuario(None, "a@b.c", True, admins_de("a@b.c"))

    assert papeis == ["consulta", "operador", "administrador"]


def test_atribuir_aceita_administrador() -> None:
    repo = RepositorioDePapeisEmMemoria()

    codigo = atribuir_papeis_main(
        ["ana@redetv.com.br", "administrador"], repo, _uids, lambda _: None
    )

    assert codigo == 0
    assert repo.obter("u1") == ["administrador"]


def test_administrador_ja_guardado_nao_se_repete() -> None:
    papeis = papeis_do_usuario(["administrador"], "a@b.c", True, admins_de("a@b.c"))

    assert papeis == ["administrador"]


def test_so_o_administrador_ve_a_auditoria() -> None:
    for papel in ("consulta", "operador", "editor", "curador", "diretoria"):
        assert "auditoria.ver" not in permissoes_de([papel])
    assert "auditoria.ver" in permissoes_de(["administrador"])


def test_so_o_operador_e_o_administrador_reprocessam() -> None:
    assert "video.reprocessar" not in permissoes_de(["consulta", "editor", "curador"])
    assert "video.reprocessar" in permissoes_de(["operador"])
    assert "video.reprocessar" in permissoes_de(["administrador"])


def test_so_curador_e_administrador_reprocessam_a_partir_de_uma_etapa() -> None:
    com = {
        p
        for p, permissoes in PERMISSOES_DO_PAPEL.items()
        if "video.reprocessar_etapa" in permissoes
    }

    assert com == {"curador", "administrador"}


def test_diretoria_so_tem_painel_ver() -> None:
    assert permissoes_de(["diretoria"]) == {"painel.ver"}


def test_so_a_diretoria_e_o_administrador_veem_o_painel() -> None:
    com = {p for p, perms in PERMISSOES_DO_PAPEL.items() if "painel.ver" in perms}

    assert com == {"diretoria", "administrador"}
