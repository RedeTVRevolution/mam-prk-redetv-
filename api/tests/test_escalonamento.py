import pytest

from api.decupagem import Decupagem
from api.escalonamento import FRACAO_PADRAO, janelas_a_escalonar


def decupagem(
    *pessoas: tuple[str, bool], textos: list[dict[str, object]] | None = None
) -> Decupagem:
    """Pessoas como (nome, aparece): `aparece` False deixa só uma menção na fala."""
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.2",
            "video": {"sha256": "a" * 64, "duracao_ms": 60_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": [
                {
                    "id": f"pes{i:02d}",
                    "nome": nome,
                    "na_imagem": (
                        [{"inicio_ms": 0, "fim_ms": 1000, "evidencia": "rosto"}]
                        if aparece
                        else []
                    ),
                    "citada_na_fala": (
                        [] if aparece else [{"inicio_ms": 0, "fim_ms": 1000}]
                    ),
                    "citada_no_texto": [],
                }
                for i, (nome, aparece) in enumerate(pessoas, start=1)
            ],
            "planos": [],
            "comerciais": [],
            "transcricao": [],
            "textos_na_tela": textos or [],
        }
    )


LIMPA = decupagem(("Ana", True))


def amostra(chave: str, total: int, fracao: float) -> set[int]:
    resultados = {i: LIMPA for i in range(total)}
    return set(janelas_a_escalonar(chave, resultados, fracao))


def test_fracao_padrao_e_dez_por_cento() -> None:
    assert FRACAO_PADRAO == 0.1


def test_mesma_chave_sorteia_as_mesmas_janelas() -> None:
    assert amostra("abc:v1", 200, 0.3) == amostra("abc:v1", 200, 0.3)


def test_outra_chave_sorteia_outras_janelas() -> None:
    assert amostra("abc:v1", 200, 0.3) != amostra("def:v1", 200, 0.3)


def test_fracao_zero_nao_sorteia_nenhuma() -> None:
    assert amostra("abc:v1", 500, 0) == set()


def test_fracao_um_sorteia_todas() -> None:
    assert amostra("abc:v1", 500, 1) == set(range(500))


@pytest.mark.parametrize("fracao", [-0.1, 1.1, float("nan")])
def test_fracao_fora_de_zero_a_um_e_erro(fracao: float) -> None:
    with pytest.raises(ValueError, match="fração"):
        janelas_a_escalonar("abc:v1", {0: LIMPA}, fracao)


def test_fracao_sorteada_fica_perto_da_pedida() -> None:
    sorteadas = len(amostra("abc:v1", 10_000, 0.1))

    assert 800 <= sorteadas <= 1200


def test_amostra_leva_o_motivo_amostra() -> None:
    escalonadas = janelas_a_escalonar("abc:v1", {0: LIMPA}, 1)

    assert escalonadas == {0: {"amostra"}}


def test_nao_identificado_na_imagem_e_duvida() -> None:
    resultados = {0: LIMPA, 1: decupagem(("Não Identificado", True))}

    assert janelas_a_escalonar("abc:v1", resultados, 0) == {1: {"duvida"}}


def test_nao_identificado_com_descricao_na_imagem_e_duvida() -> None:
    resultados = {0: decupagem(("não identificado, repórter de cabelo curto", True))}

    assert janelas_a_escalonar("abc:v1", resultados, 0) == {0: {"duvida"}}


def test_nao_identificado_so_mencionado_nao_e_duvida() -> None:
    resultados = {0: decupagem(("não identificado", False))}

    assert janelas_a_escalonar("abc:v1", resultados, 0) == {}


def test_janela_com_duvida_tambem_pode_cair_na_amostra() -> None:
    resultados = {0: decupagem(("não identificado", True))}

    assert janelas_a_escalonar("abc:v1", resultados, 1) == {0: {"duvida", "amostra"}}


def test_sorteio_nao_olha_o_resultado_da_janela() -> None:
    com_duvida = {i: decupagem(("não identificado", True)) for i in range(200)}
    sem_duvida = {i: LIMPA for i in range(200)}

    sorteadas = {
        i
        for i, motivos in janelas_a_escalonar("abc:v1", com_duvida, 0.3).items()
        if "amostra" in motivos
    }
    # com fracao 0.3 e todas com dúvida, as sorteadas são as mesmas da amostra pura
    assert sorteadas == set(janelas_a_escalonar("abc:v1", sem_duvida, 0.3))


def com_texto(medido: bool | None) -> Decupagem:
    dados = decupagem(("Ana", True)).model_dump()
    dados["textos_na_tela"] = [
        {
            "inicio_ms": 0,
            "fim_ms": 2_000,
            "tipo": "gc",
            "texto": "OFERTA",
            "medido": medido,
        }
    ]
    return Decupagem.model_validate(dados)


def test_texto_que_o_ocr_nao_achou_e_duvida() -> None:
    assert janelas_a_escalonar("abc:v1", {0: com_texto(False)}, 0) == {0: {"duvida"}}


def test_texto_medido_ou_sem_medicao_nao_e_duvida() -> None:
    assert janelas_a_escalonar("abc:v1", {0: com_texto(True)}, 0) == {}
    assert janelas_a_escalonar("abc:v1", {0: com_texto(None)}, 0) == {}


def test_texto_longo_com_a_duracao_do_bloco_nao_e_mais_duvida() -> None:
    dados = com_texto(None).model_dump()
    dados["video"]["duracao_ms"] = 90_000
    dados["textos_na_tela"][0]["fim_ms"] = 84_000
    dados["programa"]["blocos"] = [{"inicio_ms": 0, "fim_ms": 84_000, "titulo": "B"}]

    assert janelas_a_escalonar("abc:v1", {0: Decupagem.model_validate(dados)}, 0) == {}
