"""#720: para cada tipo de `TIPOS`, uma Correção real sobre uma Decupagem com pessoas e
comerciais do catálogo; o conjunto de `catalogo_id` com e sem ela, em várias sequências.
Um tipo que muda o conjunto sem estar em `pode_mudar_os_ids` derruba o teste."""

import json
from datetime import timedelta
from itertools import permutations
from typing import Any

from api.catalogo import CatalogoEmMemoria
from api.catalogo_apagado import ids_do_catalogo
from api.correcoes import TIPOS, Autoria, Correcao, NovaCorrecao, versao_do_modelo
from api.marcas import CatalogoDeMarcasEmMemoria
from api.registro_da_correcao import pode_mudar_os_ids
from api.regras_das_correcoes import aplicar, corrigir
from api.tests.test_correcoes import BASE, MODELO, _pauta, _pessoa
from api.tests.test_planos_e_falas import _fala, _plano

MODELO_RICO: dict[str, Any] = {
    **MODELO,
    "pautas": [
        {**_pauta("pau01", "Economia", 0, 20000), "tom": "informativo"},
        {**_pauta("pau02", "Esporte", 20000, 50000), "tom": "informativo"},
    ],
    "pessoas": [
        {
            **_pessoa("p1", "Ana Souza", 1000, 5000),
            "citada_na_fala": [],
            "fontes_do_nome": ["gc"],
        },
        _pessoa("p2", "Beto Lima", 7000, 9000),
        # juntada de duas origens (Quem conta, #209): o que o `pessoa.separar` separa
        {
            **_pessoa("p3", "Davi Nunes", 30000, 31000),
            "na_imagem": [
                {"inicio_ms": 30000, "fim_ms": 31000, "evidencia": "rosto"},
                {"inicio_ms": 40000, "fim_ms": 41000, "evidencia": "rosto"},
            ],
            "origens": [
                {
                    "chave": c,
                    "nome": "Davi Nunes",
                    "janela": None,
                    "na_imagem": [
                        {"inicio_ms": i, "fim_ms": i + 1000, "evidencia": "rosto"}
                    ],
                    "pautas": [],
                    "objetos": [],
                }
                for c, i in (("a", 30000), ("b", 40000))
            ],
        },
    ],
    "comerciais": [
        {
            "marca": "Banco Azul",
            "tipo": "patrocinio_vinheta",
            "inicio_ms": 10000,
            "fim_ms": 15000,
            "evidencias": ["logo"],
        },
        {
            "marca": "Refri Cola",
            "tipo": "intervalo",
            "inicio_ms": 30000,
            "fim_ms": 35000,
            "evidencias": ["logo"],
        },
    ],
    "planos": [_plano("pla01", 0, 10000), _plano("pla02", 10000, 20000)],
    "transcricao": [_fala(0, 4000, "bom dia"), _fala(4000, 9000, "hoje temos")],
    "textos_na_tela": [
        {"inicio_ms": 0, "fim_ms": 3000, "tipo": "gc", "texto": "Ana Souza"}
    ],
    "objetos": [
        {
            "id": "obj01",
            "categoria": "roupa",
            "tipo": "vestido",
            "cor_base": ["vermelho"],
            "ocorrencias": [{"inicio_ms": 1000, "fim_ms": 5000}],
            "pessoa": "p1",
            "relacao": "veste",
        }
    ],
}
VERSAO = versao_do_modelo(json.dumps(MODELO_RICO).encode())
NA_IMAGEM = {"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000}
NAO_E: dict[str, Any] = {
    "tipo": "pessoa.nao_e",
    "item_id": "p1",
    "valor": "Não identificado",
    "ocorrencia": NA_IMAGEM,
}


for _p in MODELO_RICO["pessoas"]:
    for _a in _p["na_imagem"]:
        _a.setdefault("papel", "convidado")
        _a.setdefault("visual", None)


def _j(**campos: Any) -> str:
    return json.dumps(campos)


# O pedido de cada tipo de `TIPOS`.
PEDIDOS: dict[str, dict[str, Any]] = {
    "pessoa.renomear": {"item_id": "p1", "valor": "Ana Nova"},
    "pauta.titulo": {"item_id": "pau01", "valor": "Outro título"},
    "pauta.resumo": {"item_id": "pau01", "valor": "Outro resumo"},
    "item.tempos": {
        "item_id": "p1",
        "tipo_do_item": "pessoa",
        "ocorrencia": NA_IMAGEM,
        "valor": "10000-14000",
    },
    "comercial.marca": {"item_id": "com000", "valor": "Outra marca"},
    "comercial.tipo": {"item_id": "com001", "valor": "marca_incidental"},
    "comercial.acrescentar": {
        "item_id": "",
        "valor": _j(
            marca="Loja Sol",
            tipo="merchan_apresentador",
            inicio_ms=40000,
            fim_ms=42000,
            evidencias=["fala"],
        ),
    },
    "pessoa.nao_e": NAO_E,
    "pessoa.separar": {"item_id": "p3", "valor": "b"},
    "pessoa.aparicao_para_mencao": {
        "item_id": "p1",
        "ocorrencia": NA_IMAGEM,
        "valor": "citada_na_fala",
    },
    "pessoa.mencao_para_aparicao": {
        "item_id": "p2",
        "ocorrencia": {"lista": "citada_na_fala", "inicio_ms": 9005, "fim_ms": 9009},
        "valor": "rosto",
    },
    "pessoa.acrescentar_aparicao": {
        "item_id": "p1",
        "valor": _j(inicio_ms=20000, fim_ms=22000, evidencia="rosto"),
    },
    "plano.descricao": {
        "item_id": "pla01",
        "valor": _j(ambiente="externa", acao="chuva", objetos=["guarda-chuva"]),
    },
    "plano.limpo": {"item_id": "pla01", "valor": "true"},
    "fala.texto": {
        "item_id": "fal000",
        "valor": _j(locutor="Ana", texto="boa noite"),
    },
    "pauta.tom": {"item_id": "pau01", "valor": "polemico"},
    "pessoa.fontes_do_nome": {"item_id": "p1", "valor": '["fala", "rosto"]'},
    "aparicao.papel_visual": {
        "item_id": "p1",
        "ocorrencia": NA_IMAGEM,
        "valor": _j(papel="entrevistado", visual=None),
    },
    "texto_na_tela.texto": {
        "item_id": "txt000",
        "valor": _j(tipo="gc", texto="Outro texto"),
    },
    "texto_na_tela.acrescentar": {
        "item_id": "",
        "valor": _j(inicio_ms=8000, fim_ms=9000, tipo="gc", texto="Placar"),
    },
    "pauta.acrescentar": {
        "item_id": "",
        "valor": _j(titulo="Clima", tom="informativo", inicio_ms=50000, fim_ms=60000),
    },
    "pauta.juntar": {
        "item_id": "pau01",
        "valor": _j(ids=["pau01", "pau02"], titulo="Geral"),
    },
    "pauta.dividir": {
        "item_id": "pau02",
        "valor": _j(em_ms=30000, titulos=["Primeira", "Segunda"]),
    },
    "objeto.atributos": {
        "item_id": "obj01",
        "valor": _j(tipo="saia", cor_base=["azul"]),
    },
    "objeto.dono": {
        "item_id": "obj01",
        "valor": _j(pessoa="p2", relacao="veste"),
    },
    "objeto.nao_existe": {"item_id": "obj01", "valor": "nao_existe"},
    "objeto.acrescentar": {
        "item_id": "",
        "valor": _j(
            categoria="calcado",
            tipo="sandália",
            cor_base=["vermelho"],
            cor=None,
            detalhe=None,
            marca=None,
            pessoa="p1",
            relacao="calca",
            inicio_ms=12000,
            fim_ms=19000,
        ),
    },
}


class Cenario:
    def __init__(self) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.marcas = CatalogoDeMarcasEmMemoria()
        self.ana = self.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
        self.beto = self.catalogo.acrescentar("Beto Lima Neto", "repórter", [])
        self.banco = self.marcas.acrescentar("Banco Azul S.A.", [])
        # As três que dão `catalogo_id` à Decupagem: o ponto de partida de toda sequência.
        self.base = [
            {"item_id": "p1", "tipo": "pessoa.renomear", "valor": "Ana Souza Lima"},
            {"item_id": "p2", "tipo": "pessoa.renomear", "valor": "Beto Lima Neto"},
            {
                "item_id": "com000",
                "tipo": "comercial.marca",
                "valor": "Banco Azul S.A.",
                "catalogo_id": self.banco.id,
            },
        ]

    def montar(self, pedidos: list[dict[str, Any]]) -> list[Correcao]:
        """As Correções na ordem dada, cada uma um minuto depois da outra."""
        correcoes: list[Correcao] = []
        for minuto, pedido in enumerate(pedidos):
            correcoes.append(
                corrigir(
                    MODELO_RICO,
                    VERSAO,
                    correcoes,
                    NovaCorrecao(motivo="m", versao=VERSAO, **pedido),
                    "j1",
                    Autoria("u1", "a@b.c", BASE + timedelta(minutes=minuto)),
                    catalogo=self.catalogo,
                    marcas=self.marcas,
                )
            )
        return correcoes


def ids(correcoes: list[Correcao]) -> tuple[set[str], set[str]]:
    entregue = aplicar(MODELO_RICO, VERSAO, correcoes)
    return (
        set(ids_do_catalogo(entregue, "pessoas")),
        set(ids_do_catalogo(entregue, "comerciais")),
    )


def test_ha_um_pedido_para_cada_tipo() -> None:
    assert set(PEDIDOS) == set(TIPOS)


def test_todo_tipo_que_muda_o_conjunto_de_ids_esta_em_pode_mudar_os_ids() -> None:
    cenario = Cenario()
    # O `nao_e` do intervalo que só existe depois do `item.tempos` (o contraexemplo do #720).
    nao_e_depois_dos_tempos = {
        **NAO_E,
        "ocorrencia": {**NA_IMAGEM, "inicio_ms": 10000, "fim_ms": 14000},
    }
    contextos: list[list[dict[str, Any]]] = [
        cenario.base,
        [*cenario.base, NAO_E],
        [*cenario.base, nao_e_depois_dos_tempos],
    ]
    mudaram: set[str] = set()
    for tipo, pedido in PEDIDOS.items():
        x = {"tipo": tipo, **pedido}
        for contexto in contextos:
            # A Correção depois das outras e antes delas; com e sem ela é o que a criação,
            # o desfazer e a aprovação (ou a recusa) mudam.
            for ordem in ([*contexto, x], [x, *contexto]):
                try:
                    todas = cenario.montar(ordem)
                except Exception:  # noqa: BLE001
                    # o contexto não cabe depois dela (ex.: o intervalo já mudou)
                    assert contexto is not cenario.base or ordem[-1] is not x, tipo
                    continue
                sem = [c for c in todas if c.tipo != tipo]
                if ids(todas) != ids(sem):
                    mudaram.add(tipo)
                    assert pode_mudar_os_ids(tipo), tipo
    # a bancada enxerga o que se sabe que muda
    assert {
        "pessoa.renomear",
        "comercial.marca",
        "pessoa.nao_e",
        "pessoa.acrescentar_aparicao",
        "item.tempos",
    } <= mudaram


def test_nao_e_que_esvazia_e_aparicao_do_mesmo_nome_depois_mudam_a_remocao_final() -> (
    None
):
    cenario = Cenario()
    aparicao = {
        "tipo": "pessoa.acrescentar_aparicao",
        **PEDIDOS["pessoa.acrescentar_aparicao"],
    }
    so_nao_e = cenario.montar([*cenario.base, NAO_E])
    com_aparicao = cenario.montar([*cenario.base, NAO_E, aparicao])

    assert cenario.ana.id not in ids(so_nao_e)[0]
    assert cenario.ana.id in ids(com_aparicao)[0]
    # desfazer o `nao_e` (aqui, tirá-lo) devolve a pessoa; decidir só o `nao_e` tira
    assert cenario.ana.id in ids(cenario.montar(cenario.base))[0]


def test_toda_ordem_das_tres_que_dao_id_leva_ao_mesmo_conjunto() -> None:
    cenario = Cenario()
    esperado = ids(cenario.montar(cenario.base))
    for ordem in permutations(cenario.base):
        assert ids(cenario.montar(list(ordem))) == esperado
