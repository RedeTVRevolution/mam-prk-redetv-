"""Provas de GC e de fala, conferidas pelo código (#109)."""

import json
from typing import Any

from api.analise_por_janelas import analisar_video
from api.catalogo import CatalogoEmMemoria, carregar_programas
from api.decupagem import Decupagem, Video
from api.identificacao import Candidato, candidatos_do_video, identificar
from api.programas import DADOS
from api.tests.test_correcoes import Mundo
from api.tests.test_gemini import TransporteFalso
from api.transcricao import Palavra, Transcricao

LEAO = Candidato("Leão Lobo", "comentarista", ("Leãozinho",))
NELSON = Candidato("Nelson Rubens", "apresentador")
CANDIDATOS = [LEAO, NELSON]


def pessoa(
    id: str, nome: str, aparicoes: list[tuple[int, int]], **campos: Any
) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "fontes_do_nome": ["rosto", "fala", "contexto"],
        "na_imagem": [
            {"inicio_ms": i, "fim_ms": f, "evidencia": "visto", "papel": "comentarista"}
            for i, f in aparicoes
        ],
        "citada_na_fala": [],
        "citada_no_texto": [],
        **campos,
    }


def gc(texto: str, inicio_ms: int, fim_ms: int, tipo: str = "gc") -> dict[str, Any]:
    return {"tipo": tipo, "texto": texto, "inicio_ms": inicio_ms, "fim_ms": fim_ms}


def decupagem(
    pessoas: list[dict[str, Any]],
    textos: list[dict[str, Any]] = (),  # type: ignore[assignment]
) -> Decupagem:
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.3",
            "video": {"sha256": "a" * 64, "duracao_ms": 600_000},
            "programa": {"resumo": "", "blocos": []},
            "pautas": [],
            "pessoas": pessoas,
            "planos": [],
            "comerciais": [],
            "transcricao": [],
            "textos_na_tela": list(textos),
        }
    )


def whisper(*falas: tuple[str, float]) -> Transcricao:
    """Uma palavra por tupla, com 0,5 s cada, a partir do segundo dado."""
    return Transcricao(
        modelo="falso",
        idioma="pt",
        palavras=[Palavra(texto=t, inicio_s=s, fim_s=s + 0.5) for t, s in falas],
    )


def test_apelido_dito_com_a_pessoa_na_imagem_confirma_o_nome() -> None:
    d = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])

    r = identificar(
        d,
        candidatos=CANDIDATOS,
        transcricao=whisper(("Leãozinho!", 103.0)),
    )

    [p] = r.pessoas
    assert (p.estado_do_nome, p.origem, p.fontes_do_nome) == (
        "confirmado",
        "modelo_forte",
        ["fala"],
    )


def test_nome_declarado_sem_o_nome_no_whisper_vira_palpite() -> None:
    d = decupagem([pessoa("pes01", "Nelson Rubens", [(100_000, 110_000)])])

    r = identificar(
        d,
        candidatos=CANDIDATOS,
        transcricao=whisper(("O", 103.0), ("que", 103.5), ("aconteceu", 104.0)),
    )

    [p] = r.pessoas
    assert (p.estado_do_nome, p.origem, p.fontes_do_nome) == ("palpite", "modelo", [])


def test_sem_transcricao_o_nome_declarado_e_palpite() -> None:
    d = decupagem([pessoa("pes01", "Nelson Rubens", [(100_000, 110_000)])])
    [p] = identificar(d, candidatos=CANDIDATOS).pessoas
    assert p.estado_do_nome == "palpite"


def test_fala_fora_da_imagem_nao_prova_mas_a_tolerancia_vale() -> None:
    d = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])

    longe = identificar(
        d, candidatos=CANDIDATOS, transcricao=whisper(("Leãozinho", 120.0))
    )
    perto = identificar(
        d,
        candidatos=CANDIDATOS,
        transcricao=whisper(("Leãozinho", 111.0)),
        tolerancia_ms=2000,
    )
    sem_folga = identificar(
        d,
        candidatos=CANDIDATOS,
        transcricao=whisper(("Leãozinho", 111.0)),
        tolerancia_ms=0,
    )

    assert longe.pessoas[0].estado_do_nome == "palpite"
    assert perto.pessoas[0].estado_do_nome == "confirmado"
    assert sem_folga.pessoas[0].estado_do_nome == "palpite"


def test_nome_com_mais_de_uma_palavra_e_sem_acento_ou_caixa() -> None:
    d = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])
    r = identificar(
        d,
        candidatos=CANDIDATOS,
        transcricao=whisper(("com", 102.0), ("LEAO", 102.5), ("lobo,", 103.0)),
    )
    assert r.pessoas[0].estado_do_nome == "confirmado"


def test_gc_com_o_nome_enquanto_a_pessoa_esta_na_imagem_confirma() -> None:
    d = decupagem(
        [pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])],
        [gc("LEÃO LOBO\nCOMENTARISTA", 101_000, 108_000)],
    )
    [p] = identificar(d, candidatos=CANDIDATOS).pessoas
    assert (p.estado_do_nome, p.fontes_do_nome) == ("confirmado", ["gc"])


def test_gc_de_outro_tipo_ou_fora_da_imagem_nao_confirma() -> None:
    d = decupagem(
        [pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])],
        [
            gc("Leão Lobo", 101_000, 108_000, tipo="legenda"),
            gc("Leão Lobo", 200_000, 208_000),
        ],
    )
    [p] = identificar(d, candidatos=CANDIDATOS).pessoas
    assert p.estado_do_nome == "palpite"


def test_gc_nao_confirma_com_outra_pessoa_sem_nome_na_imagem() -> None:
    d = decupagem(
        [
            pessoa("pes01", "Leão Lobo", [(100_000, 110_000)]),
            pessoa("pes02", "não identificado, mulher de blazer", [(105_000, 120_000)]),
        ],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    leao, outra = identificar(d, candidatos=CANDIDATOS).pessoas
    assert leao.estado_do_nome == "palpite"
    assert (outra.estado_do_nome, outra.fontes_do_nome) == (None, ["rosto", "fala"])


def test_fala_nao_confirma_com_outra_pessoa_sem_nome_na_imagem() -> None:
    d = decupagem(
        [
            pessoa("pes01", "Leão Lobo", [(100_000, 110_000)]),
            pessoa("pes02", "não identificado", [(100_000, 110_000)]),
        ]
    )
    [leao, _] = identificar(
        d, candidatos=CANDIDATOS, transcricao=whisper(("Leãozinho", 103.0))
    ).pessoas
    assert leao.estado_do_nome == "palpite"


def test_outra_pessoa_sem_nome_em_outro_intervalo_nao_atrapalha() -> None:
    d = decupagem(
        [
            pessoa("pes01", "Leão Lobo", [(100_000, 110_000)]),
            pessoa("pes02", "não identificado", [(300_000, 310_000)]),
        ],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    assert identificar(d, candidatos=CANDIDATOS).pessoas[0].estado_do_nome == (
        "confirmado"
    )


def test_o_nome_dito_so_confirma_quem_tem_aquele_nome() -> None:
    """O "Leãozinho" dito não confirma o Nelson que aparece junto."""
    d = decupagem([pessoa("pes01", "Nelson Rubens", [(100_000, 110_000)])])
    [p] = identificar(
        d, candidatos=CANDIDATOS, transcricao=whisper(("Leãozinho", 103.0))
    ).pessoas
    assert p.estado_do_nome == "palpite"


def test_apelido_so_vale_para_quem_esta_na_lista_de_candidatos() -> None:
    d = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])
    [p] = identificar(
        d, candidatos=[], transcricao=whisper(("Leãozinho", 103.0))
    ).pessoas
    assert p.estado_do_nome == "palpite"


def test_estar_na_lista_nao_confirma() -> None:
    d = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])
    [p] = identificar(d, candidatos=CANDIDATOS).pessoas
    assert p.estado_do_nome == "palpite"


def test_nome_confirmado_entra_no_catalogo_novo_com_o_id_gravado() -> None:
    catalogo = CatalogoEmMemoria()
    d = decupagem(
        [pessoa("pes01", "Fulana de Tal", [(100_000, 110_000)])],
        [gc("Fulana de Tal", 101_000, 108_000)],
    )

    [p] = identificar(d, catalogo=catalogo).pessoas

    [no_catalogo] = catalogo.todas()
    assert (no_catalogo.nome, no_catalogo.papel) == ("Fulana de Tal", "comentarista")
    assert p.catalogo_id == no_catalogo.id


def test_nome_confirmado_acha_a_pessoa_do_catalogo_por_nome_ou_apelido() -> None:
    catalogo = CatalogoEmMemoria()
    existente = catalogo.acrescentar("Leão Lobo", "comentarista", ["Leãozinho"])
    d = decupagem(
        [pessoa("pes01", "leãozinho", [(100_000, 110_000)])],
        [gc("Leãozinho", 101_000, 108_000)],
    )

    [p] = identificar(d, catalogo=catalogo).pessoas

    assert p.catalogo_id == existente.id
    assert len(catalogo.todas()) == 1


def test_rodar_de_novo_nao_duplica_no_catalogo() -> None:
    catalogo = CatalogoEmMemoria()
    d = decupagem(
        [pessoa("pes01", "Fulana de Tal", [(100_000, 110_000)])],
        [gc("Fulana de Tal", 101_000, 108_000)],
    )
    primeira = identificar(d, catalogo=catalogo)
    segunda = identificar(d, catalogo=catalogo)
    assert len(catalogo.todas()) == 1
    assert primeira.pessoas[0].catalogo_id == segunda.pessoas[0].catalogo_id


def test_palpite_nao_entra_no_catalogo() -> None:
    catalogo = CatalogoEmMemoria()
    d = decupagem([pessoa("pes01", "Fulana de Tal", [(100_000, 110_000)])])
    identificar(d, catalogo=catalogo)
    assert catalogo.todas() == []


def test_nome_ambiguo_no_catalogo_confirma_sem_id_e_sem_acrescentar() -> None:
    catalogo = CatalogoEmMemoria()
    catalogo.acrescentar("Ana Silva", "repórter", ["Aninha"])
    catalogo.acrescentar("Ana Lima", "repórter", ["Aninha"])
    d = decupagem(
        [pessoa("pes01", "Aninha", [(100_000, 110_000)])],
        [gc("Aninha", 101_000, 108_000)],
    )
    [p] = identificar(d, catalogo=catalogo).pessoas
    assert (p.estado_do_nome, p.catalogo_id) == ("confirmado", None)
    assert len(catalogo.todas()) == 2


def test_pessoa_da_revisora_nao_e_sobrescrita() -> None:
    d = decupagem(
        [pessoa("pes01", "Nelson Rubens", [(100_000, 110_000)], origem="revisao")],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    [p] = identificar(d, candidatos=CANDIDATOS).pessoas
    assert p == d.pessoas[0]


def test_nao_identificado_fica_como_esta() -> None:
    d = decupagem(
        [pessoa("pes01", "não identificado", [(100_000, 110_000)])],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    assert identificar(d, candidatos=CANDIDATOS).pessoas == d.pessoas


def test_candidatos_unem_perfil_e_catalogo_com_os_apelidos() -> None:
    catalogo = CatalogoEmMemoria()
    catalogo.acrescentar("leão lobo", "comentarista", ["Leão"])
    catalogo.acrescentar("Outra Pessoa", "repórter", [])
    perfis = {
        "TV Fama": {
            "pessoas": [
                {
                    "nome": "Leão Lobo",
                    "papel": "apresentador",
                    "apelidos": ["Leãozinho"],
                }
            ]
        }
    }

    candidatos = candidatos_do_video("TV Fama", catalogo, perfis)

    assert [(c.nome, c.apelidos) for c in candidatos] == [
        ("Leão Lobo", ("Leãozinho", "Leão")),
        ("Outra Pessoa", ()),
    ]
    assert candidatos_do_video(None, None, perfis) == []


def test_fonte_contexto_das_versoes_anteriores_e_descartada_ao_ler() -> None:
    d = decupagem([pessoa("pes01", "Leão Lobo", [(100_000, 110_000)])])
    assert d.pessoas[0].fontes_do_nome == ["rosto", "fala"]


def _resposta_do_modelo(nome: str, fontes: list[str]) -> str:
    """O que o Gemini devolve para um vídeo de 6 min: o homem de barba nomeado."""
    return json.dumps(
        {
            "programa": {"resumo": "", "blocos": []},
            "pautas": [],
            "pessoas": [
                {
                    "id": "p1",
                    "nome": nome,
                    "fontes_do_nome": fontes,
                    "na_imagem": [
                        {"inicio": "01:44", "fim": "01:54", "evidencia": "barba"}
                    ],
                    "citada_na_fala": [],
                    "citada_no_texto": [],
                }
            ],
            "planos": [],
            "comerciais": [],
            "transcricao": [],
            "textos_na_tela": [],
        }
    )


def _analisar(nome: str, transcricao: Transcricao, catalogo: CatalogoEmMemoria) -> Any:
    return analisar_video(
        TransporteFalso(_resposta_do_modelo(nome, ["rosto", "fala", "contexto"])),
        video_uri="gs://aceitos/j/proxy.mp4",
        job_id="j",
        video=Video(sha256="a" * 64, duracao_ms=290_000),
        programa="TV Fama",
        transcricao=transcricao,
        catalogo=catalogo,
    )


def test_leaozinho_dito_com_o_homem_de_barba_na_imagem_confirma_leao_lobo() -> None:
    catalogo = CatalogoEmMemoria()
    carregar_programas(catalogo, DADOS)

    d = _analisar("Leão Lobo", whisper(("Leãozinho!", 103.5)), catalogo)

    [p] = d.pessoas
    assert (p.estado_do_nome, p.origem, p.fontes_do_nome) == (
        "confirmado",
        "modelo_forte",
        ["fala"],
    )
    [leao] = catalogo.achar("Leão Lobo")
    assert p.catalogo_id == leao.id
    assert d.versao_esquema == "1.3"


def test_nelson_rubens_com_fala_e_contexto_sem_o_nome_no_whisper_vira_palpite() -> None:
    catalogo = CatalogoEmMemoria()
    carregar_programas(catalogo, DADOS)

    d = _analisar(
        "Nelson Rubens",
        whisper(
            ("O", 103.0), ("que", 103.5), ("aconteceu,", 104.0), ("Leãozinho", 104.5)
        ),
        catalogo,
    )

    [p] = d.pessoas
    assert (p.estado_do_nome, p.origem, p.fontes_do_nome) == ("palpite", "modelo", [])
    assert p.catalogo_id is None


def test_correcao_da_revisora_sobrevive_a_um_reprocessamento() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()  # pes01: "Ana Souza" → "Ana Souza Lima"
    reprocessada = Decupagem.model_validate(
        {
            **identificar(
                decupagem([pessoa("pes01", "Ana Souza", [(1000, 5000)])]),
                candidatos=[Candidato("Ana Souza", "repórter")],
                transcricao=whisper(("Ana", 2.0), ("Souza", 2.5)),
            ).model_dump(),
            "video": {"duracao_ms": 60_000, "sha256": "a" * 64},
        }
    )
    assert reprocessada.pessoas[0].origem == "modelo_forte"

    mundo.reprocessar(reprocessada.model_dump(mode="json"))

    [ana] = mundo.decupagem()["pessoas"]
    assert (ana["nome"], ana["origem"]) == ("Ana Souza Lima", "revisao")


def _reprocessada(nome: str, transcricao: Transcricao | None) -> dict[str, Any]:
    d = identificar(
        decupagem([pessoa("pes01", nome, [(1000, 5000)])]),
        candidatos=[Candidato(nome, "repórter")],
        transcricao=transcricao,
    )
    return Decupagem.model_validate(
        {**d.model_dump(), "video": {"duracao_ms": 60_000, "sha256": "a" * 64}}
    ).model_dump(mode="json")


def test_nome_confirmado_chega_a_leitura_com_a_origem_modelo_forte() -> None:
    mundo = Mundo(["editor"])
    mundo.reprocessar(_reprocessada("Ana Souza", whisper(("Ana", 2.0), ("Souza", 2.5))))

    [ana] = mundo.decupagem()["pessoas"]
    assert (ana["origem"], ana["estado_do_nome"]) == ("modelo_forte", "confirmado")


def test_nome_da_revisora_sobre_um_palpite_fica_confirmado() -> None:
    mundo = Mundo(["editor"])
    mundo.reprocessar(_reprocessada("Ana Souza", None))
    entregue = mundo.decupagem()
    assert entregue["pessoas"][0]["estado_do_nome"] == "palpite"

    mundo.corrigir(versao=entregue["versao_decupagem"])  # pes01: → "Ana Souza Lima"

    [ana] = mundo.decupagem()["pessoas"]
    assert (ana["nome"], ana["origem"], ana["estado_do_nome"]) == (
        "Ana Souza Lima",
        "revisao",
        "confirmado",
    )


def test_correcao_atendida_mantem_a_origem_e_o_estado_do_modelo() -> None:
    mundo = Mundo(["editor"])
    mundo.corrigir()  # pes01: "Ana Souza" → "Ana Souza Lima"
    mundo.reprocessar(
        _reprocessada(
            "Ana Souza Lima", whisper(("Ana", 2.0), ("Souza", 2.5), ("Lima", 3.0))
        )
    )

    [ana] = mundo.decupagem()["pessoas"]
    assert (ana["nome"], ana["origem"], ana["estado_do_nome"]) == (
        "Ana Souza Lima",
        "modelo_forte",
        "confirmado",
    )
