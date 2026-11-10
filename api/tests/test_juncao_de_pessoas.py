"""Junção das pessoas sem nome entre as janelas (#547)."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from api.decupagem import Decupagem, Pessoa
from api.juncao_de_pessoas import chave_da_pessoa, juntar_sem_nome

NAO = "Não identificado, "


def pessoa(
    id: str,
    janela: int | None,
    aparicoes: Sequence[tuple[int, int]],
    nome: str = NAO + "blusa vermelha",
    papel: str | None = "apresentador",
    **campos: Any,
) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "janela": janela,
        "na_imagem": [
            {"inicio_ms": i, "fim_ms": f, "evidencia": "visto", "papel": papel}
            for i, f in aparicoes
        ],
        "citada_na_fala": [],
        "citada_no_texto": [],
        **campos,
    }


def decupagem(
    pessoas: list[dict[str, Any]],
    pautas: list[dict[str, Any]] = (),  # type: ignore[assignment]
    objetos: list[dict[str, Any]] = (),  # type: ignore[assignment]
) -> Decupagem:
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.5",
            "video": {"sha256": "a" * 64, "duracao_ms": 900_000},
            "programa": {"resumo": "", "blocos": []},
            "pautas": list(pautas),
            "pessoas": pessoas,
            "objetos": list(objetos),
            "planos": [],
            "comerciais": [],
            "transcricao": [],
        }
    )


def ids(d: Decupagem) -> list[str]:
    return [p.id for p in d.pessoas]


def test_duas_sem_nome_com_a_mesma_descricao_em_janelas_vizinhas_se_juntam() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)]),
        ]
    )

    r = juntar_sem_nome(d)

    [p] = r.pessoas
    assert p.id == "pes01"
    assert [(a.inicio_ms, a.fim_ms) for a in p.na_imagem] == [
        (100_000, 110_000),
        (400_000, 410_000),
    ]
    assert [(o.id, o.janela) for o in p.origens] == [("pes01", 0), ("pes02", 1)]
    assert p.origens[0].motivo is None
    assert "descrição" in (p.origens[1].motivo or "")
    assert (p.nome, p.estado_do_nome, p.catalogo_id, p.fontes_do_nome) == (
        NAO + "blusa vermelha",
        None,
        None,
        [],
    )


def test_descricoes_diferentes_nao_se_juntam() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)], nome=NAO + "senhora de verde"),
        ]
    )

    assert ids(juntar_sem_nome(d)) == ["pes01", "pes02"]


def test_mesma_janela_com_aparicoes_sobrepostas_nunca_se_junta_nem_por_transitividade() -> (
    None
):
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 120_000)]),
            pessoa("pes02", 0, [(110_000, 130_000)]),  # o modelo as viu juntas
            pessoa("pes03", 1, [(400_000, 410_000)]),
        ]
    )

    r = juntar_sem_nome(d)

    # A pes03 se une a uma delas, nunca às duas.
    assert len(r.pessoas) == 2
    assert not any(
        {"pes01", "pes02"} <= {o.id for o in p.origens} for p in r.pessoas
    )


def test_sobreposicao_entre_janelas_diferentes_nao_proibe_nada() -> None:
    # O fim de uma janela e o começo da seguinte: a mesma pessoa, vista duas vezes.
    d = decupagem(
        [
            pessoa("pes01", 0, [(290_000, 310_000)]),
            pessoa("pes02", 1, [(300_000, 320_000)]),
        ]
    )

    assert len(juntar_sem_nome(d).pessoas) == 1


def test_pessoa_com_nome_confirmada_ou_palpite_nunca_se_junta() -> None:
    confirmada = pessoa(
        "pes02",
        1,
        [(400_000, 410_000)],
        nome="Toninho",
        estado_do_nome="confirmado",
        fontes_do_nome=["gc"],
        catalogo_id="cat-1",
    )
    palpite = pessoa(
        "pes03",
        1,
        [(500_000, 510_000)],
        nome="Toninho",
        estado_do_nome="palpite",
    )
    d = decupagem([pessoa("pes01", 0, [(100_000, 110_000)]), confirmada, palpite])

    r = juntar_sem_nome(d)

    assert ids(r) == ["pes01", "pes02", "pes03"]
    assert r.pessoas[1:] == d.pessoas[1:]
    assert all(p.origens == [] for p in r.pessoas)


def test_papel_incompativel_nao_junta() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)], papel="apresentador"),
            pessoa("pes02", 1, [(400_000, 410_000)], papel="entrevistado"),
        ]
    )

    assert len(juntar_sem_nome(d).pessoas) == 2


def test_pares_proibidos_por_uma_pessoa_na_tela_sao_respeitados() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)]),
        ]
    )
    chaves = [chave_da_pessoa(p) for p in d.pessoas]

    r = juntar_sem_nome(d, proibidos={frozenset(chaves)})

    assert ids(r) == ["pes01", "pes02"]


def test_pautas_e_donos_de_objetos_vao_para_a_pessoa_juntada_e_a_origem_lembra() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)]),
        ],
        pautas=[
            {
                "id": "pau01",
                "inicio_ms": 0,
                "fim_ms": 200_000,
                "titulo": "A",
                "resumo": "a",
                "pessoas": ["pes01"],
            },
            {
                "id": "pau02",
                "inicio_ms": 300_000,
                "fim_ms": 500_000,
                "titulo": "B",
                "resumo": "b",
                "pessoas": ["pes02", "pes01"],
            },
        ],
        objetos=[
            {
                "id": "obj01",
                "categoria": "roupa",
                "tipo": "blusa",
                "cor_base": ["vermelho"],
                "pessoa": "pes02",
                "relacao": "veste",
                "ocorrencias": [{"inicio_ms": 400_000, "fim_ms": 410_000}],
            }
        ],
    )

    r = juntar_sem_nome(d)

    assert [p.pessoas for p in r.pautas] == [["pes01"], ["pes01"]]
    assert r.objetos[0].pessoa == "pes01"
    origem = {o.id: o for o in r.pessoas[0].origens}
    assert origem["pes01"].pautas == ["pau01", "pau02"]
    assert origem["pes02"].pautas == ["pau02"]
    assert origem["pes02"].objetos == ["obj01"]


def test_na_faixa_ambigua_o_modelo_decide_e_incerto_nao_junta() -> None:
    def d() -> Decupagem:
        return decupagem(
            [
                pessoa("pes01", 0, [(100_000, 110_000)]),
                pessoa(
                    "pes02",
                    1,
                    [(400_000, 410_000)],
                    nome=NAO + "blusa vermelha, calvo",
                ),
            ]
        )

    perguntas: list[int] = []

    def juiz(respostas: list[str]) -> Any:
        def julgar(pares: Sequence[tuple[Pessoa, Pessoa]]) -> list[str]:
            perguntas.append(len(pares))
            return respostas

        return julgar

    assert len(juntar_sem_nome(d(), julgar=juiz(["sim"])).pessoas) == 1
    assert len(juntar_sem_nome(d(), julgar=juiz(["incerto"])).pessoas) == 2
    assert len(juntar_sem_nome(d(), julgar=juiz(["nao"])).pessoas) == 2
    assert len(juntar_sem_nome(d()).pessoas) == 2  # sem juiz, ninguém junta
    assert perguntas == [1, 1, 1]


def test_o_juiz_nao_e_chamado_para_o_que_ja_se_decide() -> None:
    d = decupagem(
        [
            pessoa("pes01", 0, [(100_000, 110_000)]),
            pessoa("pes02", 1, [(400_000, 410_000)]),
        ]
    )

    def julgar(pares: Sequence[tuple[Pessoa, Pessoa]]) -> list[str]:
        raise AssertionError("não devia perguntar")

    assert len(juntar_sem_nome(d, julgar=julgar).pessoas) == 1


# ---- propriedades -------------------------------------------------------------

_DESCRICOES = [NAO + "blusa vermelha", NAO + "camisa azul", NAO + "blusa vermelha"]


@st.composite
def _decupagens(draw: st.DrawFn) -> Decupagem:
    n = draw(st.integers(2, 7))
    pessoas = []
    for k in range(n):
        inicio = draw(st.integers(0, 800_000))
        nome = draw(st.sampled_from([*_DESCRICOES, "Ana", "Bia"]))
        com_nome = not nome.startswith("Não")
        pessoas.append(
            pessoa(
                f"pes{k + 1:02d}",
                None if com_nome else draw(st.integers(0, 2)),
                [(inicio, inicio + draw(st.integers(1_000, 60_000)))],
                nome=nome,
                **({"estado_do_nome": "confirmado"} if com_nome else {}),
            )
        )
    return decupagem(pessoas)


@given(_decupagens(), st.randoms(use_true_random=False))
def test_propriedades_da_juncao(d: Decupagem, aleatorio: Any) -> None:
    embaralhada = list(d.pessoas)
    aleatorio.shuffle(embaralhada)
    r = juntar_sem_nome(d.model_copy(update={"pessoas": embaralhada}))

    # nenhuma aparição se perde nem se duplica
    def aparicoes(x: Decupagem) -> Counter[tuple[int, int]]:
        return Counter((a.inicio_ms, a.fim_ms) for p in x.pessoas for a in p.na_imagem)

    assert aparicoes(r) == aparicoes(d)
    # a pessoa com nome não muda
    com_nome = {p.id: p for p in d.pessoas if p.estado_do_nome}
    assert {p.id: p for p in r.pessoas if p.estado_do_nome} == com_nome
    # nunca no mesmo grupo duas da mesma janela com aparições sobrepostas
    for p in r.pessoas:
        for i, a in enumerate(p.origens):
            for b in p.origens[i + 1 :]:
                if a.janela == b.janela:
                    assert not any(
                        x.inicio_ms < y.fim_ms and y.inicio_ms < x.fim_ms
                        for x in a.na_imagem
                        for y in b.na_imagem
                    )
    # o resultado não depende da ordem da entrada
    ordenado = juntar_sem_nome(d)
    assert sorted((p.id, len(p.origens)) for p in r.pessoas) == sorted(
        (p.id, len(p.origens)) for p in ordenado.pessoas
    )
