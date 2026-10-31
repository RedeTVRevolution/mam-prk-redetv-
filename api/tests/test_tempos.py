from typing import Any

from api.decupagem import Decupagem
from api.tempos import LIMITE_DE_AJUSTE_MS, aplicar_regra_de_tempos

DURACAO_MS = 60_000


def decupagem(
    *,
    planos: list[tuple[int, int]] | None = None,
    aparicoes: list[tuple[int, int]] | None = None,
    comerciais: list[tuple[str, int, int]] | None = None,
    falas: list[tuple[int, int]] | None = None,
) -> Decupagem:
    pessoa: dict[str, Any] = {
        "id": "pes01",
        "nome": "Fulana",
        "na_imagem": [
            {"inicio_ms": i, "fim_ms": f, "evidencia": "rosto"}
            for i, f in aparicoes or []
        ],
        "citada_na_fala": [{"inicio_ms": i, "fim_ms": f} for i, f in falas or []],
        "citada_no_texto": [
            {"inicio_ms": i, "fim_ms": f, "texto": "X"} for i, f in falas or []
        ],
    }
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.2",
            "video": {"sha256": "a" * 64, "duracao_ms": DURACAO_MS},
            "programa": {
                "resumo": "r",
                "blocos": [{"inicio_ms": 1_010, "fim_ms": 9_990, "titulo": "B"}],
            },
            "pautas": [
                {
                    "id": "pau01",
                    "titulo": "P",
                    "inicio_ms": 1_010,
                    "fim_ms": 9_990,
                    "resumo": "r",
                }
            ],
            "pessoas": [pessoa],
            "planos": [
                {
                    "id": f"pla{n}",
                    "inicio_ms": i,
                    "fim_ms": f,
                    "ambiente": "estúdio",
                    "plano_limpo": False,
                }
                for n, (i, f) in enumerate(planos or [])
            ],
            "comerciais": [
                {
                    "marca": "M",
                    "tipo": t,
                    "inicio_ms": i,
                    "fim_ms": f,
                    "evidencias": ["logo"],
                }
                for t, i, f in comerciais or []
            ],
            "transcricao": [
                {"inicio_ms": i, "fim_ms": f, "locutor": "L", "texto": "t"}
                for i, f in falas or []
            ],
        }
    )


def test_limite_de_ajuste_e_um_segundo() -> None:
    assert LIMITE_DE_AJUSTE_MS == 1000


def test_aparicao_com_corte_a_1000_ms_e_ajustada() -> None:
    d = decupagem(aparicoes=[(5_000, 9_000)])
    r = aplicar_regra_de_tempos(d, [6_000, 8_000])
    a = r.pessoas[0].na_imagem[0]
    assert (a.inicio_ms, a.fim_ms) == (6_000, 8_000)


def test_aparicao_com_corte_a_1001_ms_fica_intacta() -> None:
    d = decupagem(aparicoes=[(5_000, 9_000)])
    r = aplicar_regra_de_tempos(d, [6_001, 7_999])
    a = r.pessoas[0].na_imagem[0]
    assert (a.inicio_ms, a.fim_ms) == (5_000, 9_000)
    assert a.inicio_modelo_ms is None


def test_comercial_segue_o_limite_de_um_segundo() -> None:
    d = decupagem(comerciais=[("merchan_apresentador", 40_000, 50_000)])
    r = aplicar_regra_de_tempos(d, [40_500, 52_000])
    c = r.comerciais[0]
    assert (c.inicio_ms, c.fim_ms) == (40_500, 50_000)


def test_mencoes_fala_e_mencao_editorial_ficam_intactas() -> None:
    d = decupagem(
        falas=[(5_000, 9_000)],
        comerciais=[("mencao_editorial", 20_000, 25_000)],
    )
    r = aplicar_regra_de_tempos(d, [5_010, 8_990, 20_010, 24_990])
    p = r.pessoas[0]
    assert (p.citada_na_fala[0].inicio_ms, p.citada_na_fala[0].fim_ms) == (5_000, 9_000)
    assert p.citada_no_texto[0].inicio_ms == 5_000
    assert (r.transcricao[0].inicio_ms, r.transcricao[0].fim_ms) == (5_000, 9_000)
    assert (r.comerciais[0].inicio_ms, r.comerciais[0].fim_ms) == (20_000, 25_000)


def test_pautas_e_blocos_nao_mudam() -> None:
    d = decupagem()
    r = aplicar_regra_de_tempos(d, [1_000, 10_000])
    assert r.pautas == d.pautas
    assert r.programa == d.programa


def test_inicio_e_fim_pela_propria_distancia() -> None:
    d = decupagem(aparicoes=[(5_000, 9_000)])
    r = aplicar_regra_de_tempos(d, [4_100, 9_900])
    a = r.pessoas[0].na_imagem[0]
    assert (a.inicio_ms, a.fim_ms) == (4_100, 9_900)
    # só o fim está a menos de 1 s do corte
    r = aplicar_regra_de_tempos(d, [3_000, 9_500])
    a = r.pessoas[0].na_imagem[0]
    assert (a.inicio_ms, a.fim_ms) == (5_000, 9_500)


def test_sem_cortes_nada_muda() -> None:
    d = decupagem(planos=[(300, 59_800)], aparicoes=[(5_000, 9_000)])
    assert aplicar_regra_de_tempos(d, []) == d


def test_nao_altera_a_decupagem_de_entrada() -> None:
    d = decupagem(planos=[(4_800, 10_300)])
    aplicar_regra_de_tempos(d, [5_000, 10_000])
    assert [(p.inicio_ms, p.fim_ms) for p in d.planos] == [(4_800, 10_300)]
    assert d.planos[0].inicio_modelo_ms is None


def test_resultado_continua_valido() -> None:
    d = decupagem(planos=[(4_800, 10_300)], aparicoes=[(5_000, 9_000)])
    r = aplicar_regra_de_tempos(d, [5_000, 10_000])
    assert Decupagem.model_validate(r.model_dump()) == r


def test_aparicao_e_comercial_ajustados_guardam_os_tempos_do_modelo() -> None:
    d = decupagem(
        aparicoes=[(5_000, 9_000)],
        comerciais=[("merchan_apresentador", 40_000, 50_000)],
    )
    r = aplicar_regra_de_tempos(d, [5_500, 8_200, 40_500, 49_900])
    a = r.pessoas[0].na_imagem[0]
    assert (a.inicio_modelo_ms, a.fim_modelo_ms) == (5_000, 9_000)
    c = r.comerciais[0]
    assert (c.inicio_modelo_ms, c.fim_modelo_ms) == (40_000, 50_000)


def _planos(r: Decupagem) -> list[tuple[int, int, int | None, int | None]]:
    return [
        (p.inicio_ms, p.fim_ms, p.inicio_modelo_ms, p.fim_modelo_ms) for p in r.planos
    ]


def test_plano_do_modelo_que_cobre_tres_cortes_vira_tres_planos() -> None:
    d = decupagem(planos=[(0, 60_000)])
    r = aplicar_regra_de_tempos(d, [10_000, 20_000])
    assert [(p.inicio_ms, p.fim_ms) for p in r.planos] == [
        (0, 10_000),
        (10_000, 20_000),
        (20_000, 60_000),
    ]
    assert {p.ambiente for p in r.planos} == {"estúdio"}
    assert len({p.id for p in r.planos}) == 3
    # Os tempos do modelo ficam guardados: o plano original, 0–60 s.
    assert {(p.inicio_modelo_ms, p.fim_modelo_ms) for p in r.planos} == {(0, 60_000)}


def test_plano_herda_a_descricao_do_plano_do_modelo_que_mais_se_sobrepoe() -> None:
    d = decupagem(planos=[(0, 12_000), (12_000, 60_000)])
    d = d.model_copy(
        update={
            "planos": [
                d.planos[0].model_copy(update={"ambiente": "estúdio"}),
                d.planos[1].model_copy(update={"ambiente": "rua"}),
            ]
        }
    )
    r = aplicar_regra_de_tempos(d, [10_000, 30_000])
    assert [(p.inicio_ms, p.fim_ms, p.ambiente) for p in r.planos] == [
        (0, 10_000, "estúdio"),
        (10_000, 30_000, "rua"),  # 2 s com o estúdio, 18 s com a rua
        (30_000, 60_000, "rua"),
    ]
    assert _planos(r)[0][2:] == (0, 12_000)
    assert _planos(r)[1][2:] == (12_000, 60_000)


def test_plano_que_ja_e_um_intervalo_entre_cortes_fica_como_esta() -> None:
    d = decupagem(planos=[(0, 5_000), (5_000, 60_000)])
    r = aplicar_regra_de_tempos(d, [5_000])
    assert _planos(r) == [(0, 5_000, None, None), (5_000, 60_000, None, None)]


def test_plano_do_modelo_fora_dos_cortes_vira_o_intervalo_dos_cortes() -> None:
    d = decupagem(planos=[(4_800, 10_300)])
    r = aplicar_regra_de_tempos(d, [5_000, 10_000])
    assert [(p.inicio_ms, p.fim_ms) for p in r.planos] == [
        (0, 5_000),
        (5_000, 10_000),
        (10_000, 60_000),
    ]
    assert r.planos[1].inicio_modelo_ms == 4_800


def test_segunda_passada_mantem_os_tempos_do_modelo() -> None:
    d = decupagem(planos=[(0, 10_300)])
    r = aplicar_regra_de_tempos(d, [10_000])
    r = aplicar_regra_de_tempos(r, [10_000])
    assert [(p.inicio_ms, p.fim_ms) for p in r.planos] == [
        (0, 10_000),
        (10_000, 60_000),
    ]
    assert r.planos[0].inicio_modelo_ms == 0
    assert r.planos[0].fim_modelo_ms == 10_300


def test_sem_planos_do_modelo_os_cortes_nao_inventam_planos() -> None:
    d = decupagem(aparicoes=[(5_000, 9_000)])
    assert aplicar_regra_de_tempos(d, [10_000]).planos == []


def test_intervalo_que_nenhum_plano_do_modelo_toca_fica_sem_plano() -> None:
    d = decupagem(planos=[(0, 10_000), (30_000, 60_000)])
    r = aplicar_regra_de_tempos(d, [10_000, 20_000, 30_000])
    assert [(p.inicio_ms, p.fim_ms) for p in r.planos] == [
        (0, 10_000),
        (30_000, 60_000),
    ]
    assert [p.id for p in r.planos] == ["pla001", "pla002"]
