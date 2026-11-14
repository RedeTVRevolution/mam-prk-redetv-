"""`api/texto.py`: o único lugar que tira acento (#658)."""

from api.jobs import palavras_do_nome
from api.teste_dos_jobs import normalizar as normalizar_do_teste_dos_jobs
from api.texto import normalizar, sem_acento


def test_sem_acento_tira_so_as_marcas_e_mantem_maiuscula_e_pontuacao() -> None:
    assert sem_acento("Ação, São José!") == "Acao, Sao Jose!"


def test_sem_acento_mantem_a_letra_nao_latina() -> None:
    assert sem_acento("olá Привет 日本") == "ola Привет 日本"


def test_normalizar_usa_sem_acento_e_junta_espacos() -> None:
    assert normalizar("  Ação   SÃO\tJosé ") == "acao sao jose"


def test_o_nome_do_arquivo_vira_palavras_sem_acento() -> None:
    assert palavras_do_nome("Jornal_Nacional-Ação (São Paulo).mp4") == [
        "jornal",
        "nacional",
        "acao",
        "sao",
        "paulo",
        "mp4",
    ]


def test_o_teste_dos_jobs_descarta_a_letra_nao_latina() -> None:
    assert (
        normalizar_do_teste_dos_jobs("Olá, Привет 日本 São-Paulo!") == "ola sao paulo"
    )
