"""O programa "TV Fama" dos testes: o perfil e as quatro pessoas que a carga única levou
para o cadastro, em memória."""

from api.catalogo import Catalogo, CatalogoEmMemoria
from api.programas import (
    Perfis,
    Programa,
    ProgramasEmMemoria,
    VinculoDaPessoa,
    perfis_dos_programas,
)

PERFIL_DA_TV_FAMA = (
    "Revista diária de notícias de celebridades e entretenimento da RedeTV!.\n"
    "Merchandising frequente: Ultrafarma, feito pelo apresentador no estúdio, "
    "com GC e QR code."
)
PESSOAS_DA_TV_FAMA = [
    ("Flávia Noronha", "apresentador ou comentarista", []),
    ("Leão Lobo", "apresentador ou comentarista", ["Leãozinho"]),
    ("Nelson Rubens", "apresentador", []),
    ("Andréa Corazza", "repórter", []),
]


def cadastro_com_tv_fama(
    catalogo: Catalogo | None = None,
) -> tuple[ProgramasEmMemoria, Catalogo]:
    catalogo = catalogo or CatalogoEmMemoria()
    vinculos = []
    for nome, papel, apelidos in PESSOAS_DA_TV_FAMA:
        achadas = catalogo.achar(nome)
        pessoa = achadas[0] if achadas else catalogo.acrescentar(nome, "", apelidos)
        vinculos.append(VinculoDaPessoa(pessoa_id=pessoa.id, papel=papel))
    programas = ProgramasEmMemoria(
        [
            Programa(
                id="tv-fama", nome="TV Fama", perfil=PERFIL_DA_TV_FAMA, pessoas=vinculos
            )
        ]
    )
    return programas, catalogo


def perfis_da_tv_fama() -> Perfis:
    programas, catalogo = cadastro_com_tv_fama()
    return perfis_dos_programas(programas, catalogo)
