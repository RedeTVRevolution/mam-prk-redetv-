import json
from pathlib import Path
from typing import get_args

import pytest

from api.catalogo_de_correcoes import (
    ROTULOS_DAS_FONTES,
    ROTULOS_DAS_LISTAS,
    ROTULOS_DAS_RELACOES,
    ROTULOS_DOS_TONS,
)
from api.correcoes import TIPOS, Lista, TipoDeCorrecao, TipoNovo, valor_legivel
from api.decupagem import (
    CATEGORIAS_DE_OBJETO,
    CORES_BASE,
    RELACOES_DO_OBJETO,
    Comercial,
    FonteDoNome,
    TextoNaTela,
    TomDaPauta,
)
from api.indice_da_busca import NOME_DA_CATEGORIA
from api.tests.test_correcoes import AUTORIZACAO, Mundo


def test_todo_tipo_tem_rotulo_e_valor_legivel_na_tabela() -> None:
    assert set(TIPOS) == set(get_args(TipoNovo))
    assert all(e.rotulo and callable(e.legivel) for e in TIPOS.values())


def test_rota_do_catalogo_lista_tipos_e_vocabularios() -> None:
    resposta = Mundo(["editor"]).cliente.get(
        "/v1/correcoes/catalogo", headers=AUTORIZACAO
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [t["valor"] for t in corpo["tipos"]] == list(get_args(TipoDeCorrecao))
    assert all(t["rotulo"] for t in corpo["tipos"])
    assert [o["valor"] for o in corpo["tipos_de_comercial"]] == list(
        get_args(Comercial.model_fields["tipo"].annotation)
    )
    assert [o["valor"] for o in corpo["tipos_de_texto_na_tela"]] == list(
        get_args(TextoNaTela.model_fields["tipo"].annotation)
    )
    assert [o["valor"] for o in corpo["tons_da_pauta"]] == list(get_args(TomDaPauta))
    assert [o["valor"] for o in corpo["fontes_do_nome"]] == list(get_args(FonteDoNome))
    assert {o["valor"]: o["rotulo"] for o in corpo["tons_da_pauta"]}["polemico"] == (
        "polêmico"
    )
    assert corpo["limites"] == {"nome": 200, "texto": 2000, "motivo": 500}
    assert corpo["prefixos"] == {"acrescentado": "acr-", "nao_identificado": "nid-"}


def test_catalogo_traz_as_listas_fechadas_do_objeto() -> None:
    resposta = Mundo(["editor"]).cliente.get(
        "/v1/correcoes/catalogo", headers=AUTORIZACAO
    )

    corpo = resposta.json()
    assert [o["valor"] for o in corpo["categorias_de_objeto"]] == list(
        CATEGORIAS_DE_OBJETO
    )
    assert {o["valor"]: o["rotulo"] for o in corpo["categorias_de_objeto"]} == (
        NOME_DA_CATEGORIA
    )
    assert [o["valor"] for o in corpo["cores_base"]] == list(CORES_BASE)
    assert [o["valor"] for o in corpo["relacoes_do_objeto"]] == list(RELACOES_DO_OBJETO)
    assert {o["valor"]: o["rotulo"] for o in corpo["relacoes_do_objeto"]} == (
        ROTULOS_DAS_RELACOES
    )


def test_rotulos_cobrem_os_vocabularios_do_esquema() -> None:
    assert set(ROTULOS_DOS_TONS) == set(get_args(TomDaPauta))
    assert set(ROTULOS_DAS_FONTES) == set(get_args(FonteDoNome))
    assert set(ROTULOS_DAS_LISTAS) == set(get_args(Lista))
    assert set(ROTULOS_DAS_RELACOES) == set(RELACOES_DO_OBJETO)


def test_rota_do_catalogo_exige_login() -> None:
    assert Mundo(["editor"]).cliente.get("/v1/correcoes/catalogo").status_code == 401


def test_o_catalogo_dos_testes_do_front_e_o_da_api() -> None:
    # web/src/Video.test.tsx serve este arquivo no msw; se a API mudar, regrave-o com
    # `catalogo().model_dump(mode="json")`.
    fixture = Path(__file__).parents[2] / "web" / "src" / "catalogo.fixture.json"
    resposta = Mundo(["editor"]).cliente.get(
        "/v1/correcoes/catalogo", headers=AUTORIZACAO
    )

    assert json.loads(fixture.read_text(encoding="utf-8")) == resposta.json()


COMERCIAL = {
    "marca": "Acme",
    "tipo": "testemunhal",
    "inicio_ms": 65000,
    "fim_ms": 70000,
}
TEXTO = {"tipo": "gc", "texto": "Olá", "inicio_ms": 1000, "fim_ms": 2000}


@pytest.mark.parametrize(
    ("tipo", "valor", "esperado"),
    [
        (
            "comercial.acrescentar",
            json.dumps(COMERCIAL),
            "Acme (testemunhal) 01:05–01:10",
        ),
        (
            "pessoa.acrescentar_aparicao",
            json.dumps(
                {"inicio_ms": 0, "fim_ms": 5000, "evidencia": "rosto", "nome": "Ana"}
            ),
            "Ana 00:00–00:05 (rosto)",
        ),
        (
            "pessoa.acrescentar_aparicao",
            json.dumps({"inicio_ms": 0, "fim_ms": 5000, "evidencia": "rosto"}),
            "00:00–00:05 (rosto)",
        ),
        ("texto_na_tela.texto", json.dumps({"tipo": "gc", "texto": "Olá"}), "gc: Olá"),
        ("texto_na_tela.acrescentar", json.dumps(TEXTO), "gc: Olá 00:01–00:02"),
        (
            "pauta.acrescentar",
            json.dumps(
                {
                    "titulo": "Bastidores",
                    "tom": "descontraido",
                    "inicio_ms": 0,
                    "fim_ms": 5000,
                }
            ),
            "Bastidores (descontraído) 00:00–00:05",
        ),
        (
            "aparicao.papel_visual",
            json.dumps({"papel": "âncora", "visual": "terno"}),
            "âncora · terno",
        ),
        (
            "aparicao.papel_visual",
            json.dumps({"papel": None, "visual": None}),
            "sem papel na cena e visual",
        ),
        ("pessoa.fontes_do_nome", json.dumps(["gc", "fala"]), "GC, fala"),
        ("pessoa.fontes_do_nome", "[]", "nenhuma fonte"),
        ("pessoa.fontes_do_nome", json.dumps(["referencia"]), "referência de rosto"),
        ("pauta.tom", "polemico", "polêmico"),
        ("pauta.tom", "outro texto", "outro texto"),
        ("plano.limpo", "true", "plano limpo"),
        ("plano.limpo", "false", "plano não limpo"),
        (
            "plano.descricao",
            json.dumps(
                {"ambiente": "estúdio", "acao": None, "objetos": ["mesa", "tv"]}
            ),
            "estúdio · mesa, tv",
        ),
        (
            "fala.texto",
            json.dumps({"locutor": "Ana", "texto": "Boa noite"}),
            "Ana: Boa noite",
        ),
        ("pessoa.nao_e", "na_imagem 1000-61000", "aparição 00:01–01:01"),
        (
            "pessoa.aparicao_para_mencao",
            "citada_na_fala 0-5000",
            "citada na fala 00:00–00:05",
        ),
        (
            "pessoa.mencao_para_aparicao",
            "citada_no_texto 0-5000",
            "citada no texto 00:00–00:05",
        ),
        ("item.tempos", "32000-60000", "00:32–01:00"),
        (
            "objeto.atributos",
            json.dumps(
                {
                    "tipo": "vestido",
                    "cor_base": ["vermelho", "branco"],
                    "cor": "vinho",
                    "detalhe": "renda",
                    "marca": "Zara",
                }
            ),
            "vestido · vermelho, branco · vinho · renda · Zara",
        ),
        (
            "objeto.atributos",
            json.dumps(
                {
                    "tipo": "carro",
                    "cor_base": [],
                    "cor": None,
                    "detalhe": None,
                    "marca": None,
                }
            ),
            "carro",
        ),
        (
            "objeto.dono",
            json.dumps({"pessoa": "pes01", "relacao": "veste"}),
            "dono: pes01 (veste)",
        ),
        (
            "objeto.dono",
            json.dumps({"pessoa": None, "relacao": None}),
            "sem dono",
        ),
        (
            "objeto.acrescentar",
            json.dumps(
                {
                    "categoria": "calcado",
                    "tipo": "sandália",
                    "cor_base": ["vermelho"],
                    "cor": None,
                    "detalhe": None,
                    "marca": None,
                    "pessoa": "pes01",
                    "relacao": "calca",
                    "inicio_ms": 12000,
                    "fim_ms": 19000,
                }
            ),
            "calçado sandália vermelho (dono: pes01) 00:12–00:19",
        ),
        ("objeto.nao_existe", "existe", "Objeto na imagem"),
        ("objeto.nao_existe", "nao_existe", "Objeto não está na imagem"),
        ("pauta.titulo", "Um título 1-2", "Um título 1-2"),
        ("pessoa.renomear", "Ana", "Ana"),
        ("comercial.marca", "Acme", "Acme"),
        ("comercial.tipo", "testemunhal", "testemunhal"),
        ("pauta.resumo", "Resumo", "Resumo"),
    ],
)
def test_valor_legivel_por_tipo(tipo: str, valor: str, esperado: str) -> None:
    assert valor_legivel(tipo, valor) == esperado


@pytest.mark.parametrize(
    "tipo",
    [
        "comercial.acrescentar",
        "pessoa.acrescentar_aparicao",
        "texto_na_tela.texto",
        "texto_na_tela.acrescentar",
        "pauta.acrescentar",
        "objeto.atributos",
        "objeto.dono",
        "objeto.acrescentar",
        "aparicao.papel_visual",
        "pessoa.fontes_do_nome",
        "plano.descricao",
        "fala.texto",
    ],
)
def test_valor_que_nao_e_o_json_esperado_sai_como_veio(tipo: str) -> None:
    malformados = ["texto solto", "{}", "null", '"x"', "1", "[" * 100_000]
    if tipo != "pessoa.fontes_do_nome":  # nele, a lista vazia é "nenhuma fonte"
        malformados.append("[]")
    for valor in malformados:
        assert valor_legivel(tipo, valor) == valor
    if tipo == "plano.descricao":
        valor = json.dumps({"ambiente": "a", "acao": None, "objetos": "mesa"})
        assert valor_legivel(tipo, valor) == valor


def test_historico_e_fila_trazem_o_valor_legivel() -> None:
    from datetime import UTC, datetime

    from api.correcoes import Ancora, Correcao, fila, historico

    def correcao(id: str, tipo: str, antes: str, depois: str, **resto: str) -> Correcao:
        return Correcao(
            id=id,
            job_id="j",
            autor_uid="u",
            autor_email="a@redetv.com.br",
            criada_em=datetime(2026, 1, 1, tzinfo=UTC),
            motivo="m",
            tipo=tipo,  # type: ignore[arg-type]
            antes=antes,
            depois=depois,
            ancora=Ancora(
                versao="v",
                tipo_do_item="pauta",
                inicio_ms=0,
                fim_ms=1000,
                identidade="x",
            ),
            **resto,  # type: ignore[arg-type]
        )

    alvo = correcao("c1", "pauta.tom", "informativo", "polemico")
    desfazer = correcao("c2", "desfazer", "polemico", "informativo", desfaz="c1")
    decisoes = [
        correcao(f"d-{campo}", tipo, "informativo", "polemico", **{campo: "c1"})
        for tipo, campo in (
            ("descartar", "descarta"),
            ("aprovar", "aprova"),
            ("recusar", "recusa"),
        )
    ]

    itens = {i.id: i for i in historico([alvo, desfazer, *decisoes])}

    for decisao in decisoes:
        assert (
            itens[decisao.id].antes_legivel,
            itens[decisao.id].depois_legivel,
        ) == ("informativo", "polêmico")

    assert (itens["c1"].antes_legivel, itens["c1"].depois_legivel) == (
        "informativo",
        "polêmico",
    )
    assert (itens["c2"].antes_legivel, itens["c2"].depois_legivel) == (
        "polêmico",
        "informativo",
    )
    # Na fila: nenhuma casa num modelo vazio.
    sem_casar = fila({}, "v2", [alvo])
    assert [i.depois_legivel for i in sem_casar] == ["polêmico"]
