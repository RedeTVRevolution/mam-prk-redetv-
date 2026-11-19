"""Correções dos objetos dos planos (#740): apagar, nome e categoria, cor e marca, num
item do `Plano.inventario` ou no grupo inteiro."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

import api.registro_da_correcao as registro
import api.regras_das_correcoes as regras
from api.correcoes import Autoria, NovaCorrecao
from api.decupagem import Decupagem
from api.eventos_de_uso import EventosEmMemoria
from api.indexacao import _so_o_esquema
from api.tests.test_correcoes import AUTORIZACAO, MODELO, Mundo, _resolver
from api.tests.test_correcoes_de_objeto import CURADOR, _versao
from api.tests.test_indexacao import SABRINA_EXEMPLO


def _item(nome: str, **mais: Any) -> dict[str, Any]:
    return {
        "nome": nome,
        "categoria": "decoracao",
        "cor": None,
        "marca": None,
        "caixas": [
            {"quadro": "q/a.jpg", "x": 0.1, "y": 0.1, "largura": 0.2, "altura": 0.2}
        ],
        "destaque": 1,
        **mais,
    }


def _plano(
    id: str, inicio: int, fim: int, *inventario: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": id,
        "inicio_ms": inicio,
        "fim_ms": fim,
        "ambiente": "estúdio",
        "plano_limpo": False,
        "objetos": [],
        "inventario": list(inventario),
    }


def _modelo(*planos: dict[str, Any]) -> dict[str, Any]:
    if not planos:
        planos = (
            _plano(
                "pla01",
                0,
                10000,
                _item("relógio de parede"),
                _item("relógio de parede"),
            ),
            _plano("pla02", 10000, 20000, _item("relógio de parede"), _item("vaso")),
        )
    return {**MODELO, "planos": list(planos)}


M = _modelo()
V = _versao(M)


def _mundo(modelo: dict[str, Any] = M) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)
    return mundo


def _corrigir(mundo: Mundo, tipo: str, valor: str, **campos: Any) -> Any:
    campos.setdefault("versao", V)
    return mundo.corrigir(tipo=tipo, valor=valor, **campos)


def _inventarios(mundo: Mundo, params: str = "") -> list[list[dict[str, Any]]]:
    return [p["inventario"] for p in mundo.decupagem(params)["planos"]]


def test_apagar_um_de_dois_iguais_no_mesmo_plano_deixa_o_outro() -> None:
    mundo = _mundo()
    [primeiro, segundo] = _inventarios(mundo)[0]
    assert (primeiro["id"], segundo["id"]) == ("pla01:0", "pla01:1")

    r = _corrigir(mundo, "inventario.nao_existe", "nao_existe", item_id="pla01:1")

    assert r.status_code == 201, r.text
    [um], [relogio, vaso] = _inventarios(mundo)
    assert um["id"] == "pla01:0"
    assert (relogio["id"], vaso["id"]) == ("pla02:0", "pla02:1")
    assert len(_inventarios(mundo, "?versao=modelo")[0]) == 2


def test_nome_e_cor_corrigem_so_o_item_e_o_tipo_canonico_segue_o_nome_novo() -> None:
    mundo = _mundo()
    assert _inventarios(mundo)[0][1]["tipo_canonico"] == "relógio de parede"

    nome = json.dumps({"nome": "camiseta", "categoria": "roupa"})
    cor = json.dumps({"cor": "azul", "marca": "Nike"})
    assert (
        _corrigir(mundo, "inventario.nome", nome, item_id="pla01:1").status_code == 201
    )
    mundo.avancar()
    assert (
        _corrigir(mundo, "inventario.cor_marca", cor, item_id="pla01:1").status_code
        == 201
    )

    [intacto, corrigido] = _inventarios(mundo)[0]
    assert (intacto["nome"], intacto.get("cor"), intacto["tipo_canonico"]) == (
        "relógio de parede",
        None,
        "relógio de parede",
    )
    assert (
        corrigido["nome"],
        corrigido["categoria"],
        corrigido["cor"],
        corrigido["marca"],
        corrigido["tipo_canonico"],
    ) == ("camiseta", "roupa", "azul", "Nike", "camisa")
    historico = mundo.historico().json()
    assert [h["depois_legivel"] for h in historico] == [
        "azul · Nike",
        "camiseta (roupa)",
    ]


def test_cor_e_marca_vazias_apagam_os_campos() -> None:
    modelo = _modelo(_plano("pla01", 0, 10000, _item("vaso", cor="azul", marca="X")))
    mundo = _mundo(modelo)
    vazio = json.dumps({"cor": None, "marca": None})

    r = _corrigir(
        mundo, "inventario.cor_marca", vazio, item_id="pla01:0", versao=_versao(modelo)
    )

    assert r.status_code == 201, r.text
    [[item]] = _inventarios(mundo)
    assert "cor" not in item and "marca" not in item


def _fila(mundo: Mundo) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = mundo.cliente.get(
        "/v1/jobs/j1/fila", headers=AUTORIZACAO
    ).json()
    return itens


def test_reprocessado_casa_pelo_nome_no_plano_e_desempata_pela_posicao() -> None:
    mundo = _mundo()
    cid = _corrigir(mundo, "inventario.nao_existe", "nao_existe", item_id="pla01:1")
    mundo.avancar()
    # O plano mudou de id e de borda, mas segue o mesmo trecho com os dois relógios.
    mundo.reprocessar(
        _modelo(
            _plano(
                "pla01", 0, 9500, _item("relógio de parede"), _item("relógio de parede")
            ),
            _plano("pla02", 9500, 20000, _item("vaso"), _item("relógio de parede")),
        )
    )

    [um], [vaso, relogio] = _inventarios(mundo)

    assert (um["id"], vaso["nome"], relogio["nome"]) == (
        "pla01:0",
        "vaso",
        "relógio de parede",
    )
    assert _fila(mundo) == []
    assert mundo.desfazer(cid.json()["id"]).status_code == 201
    assert [len(i) for i in _inventarios(mundo)] == [2, 2]


def test_orfa_vai_para_a_fila_e_reaplica_num_objeto_do_plano() -> None:
    mundo = _mundo()
    cor = json.dumps({"cor": "azul", "marca": None})
    cid = _corrigir(mundo, "inventario.cor_marca", cor, item_id="pla02:1").json()["id"]
    mundo.avancar()
    mundo.reprocessar(
        _modelo(
            _plano("pla01", 0, 10000, _item("relógio de parede")),
            _plano("pla02", 10000, 20000, _item("jarro"), _item("relógio de parede")),
        )
    )

    [item] = _fila(mundo)

    assert item["id"] == cid
    assert [(c["item_id"], c["nome"]) for c in item["candidatos"]] == [
        ("pla02:0", "jarro"),
        ("pla02:1", "relógio de parede"),
    ]
    assert _resolver(mundo, cid, "reaplicar", item_id="pla02:0").status_code == 201
    assert _inventarios(mundo)[1][0]["cor"] == "azul"
    assert _fila(mundo) == []


def test_orfa_descartada_sai_da_fila() -> None:
    mundo = _mundo()
    cid = _corrigir(mundo, "inventario.nao_existe", "nao_existe", item_id="pla02:1")
    mundo.avancar()
    mundo.reprocessar(_modelo(_plano("pla02", 10000, 20000, _item("jarro"))))

    assert _resolver(mundo, cid.json()["id"], "descartar").status_code == 201
    assert _fila(mundo) == []
    assert [[i["nome"] for i in p] for p in _inventarios(mundo)] == [["jarro"]]


RELOGIOS = ["pla01:0", "pla01:1", "pla02:0"]


def _no_grupo(
    mundo: Mundo, tipo: str, valor: str, ids: list[str], **campos: Any
) -> Any:
    return _corrigir(mundo, tipo, valor, item_ids=ids, item_id="", **campos)


def _nomes(mundo: Mundo) -> list[list[str]]:
    return [[i["nome"] for i in p] for p in _inventarios(mundo)]


def test_grupo_corrige_todos_os_itens_e_desfazer_um_desfaz_todos() -> None:
    mundo = _mundo()
    nome = json.dumps({"nome": "quadro", "categoria": "decoracao"})

    r = _no_grupo(mundo, "inventario.nome", nome, RELOGIOS)

    assert r.status_code == 201, r.text
    assert _nomes(mundo) == [["quadro", "quadro"], ["quadro", "vaso"]]
    gravadas = mundo.correcoes.listar("j1")
    assert sorted(c.item_id for c in gravadas) == RELOGIOS
    assert len({c.grupo for c in gravadas}) == 1 and gravadas[0].grupo
    assert r.json()["id"] in {c.id for c in gravadas}

    mundo.avancar()
    assert mundo.desfazer(gravadas[1].id).status_code == 201

    assert _nomes(mundo) == [
        ["relógio de parede", "relógio de parede"],
        ["relógio de parede", "vaso"],
    ]
    assert {
        h["estado"] for h in mundo.historico().json() if h["tipo"] != "desfazer"
    } == {"desfeita"}
    assert mundo.desfazer(gravadas[0].id).status_code == 409


def test_grupo_de_cores_diferentes_muda_so_a_marca_e_cada_um_guarda_a_cor() -> None:
    modelo = _modelo(
        _plano("pla01", 0, 10000, _item("vaso", cor="azul"), _item("vaso", cor="verde"))
    )
    mundo = _mundo(modelo)

    r = _no_grupo(
        mundo,
        "inventario.cor_marca",
        json.dumps({"marca": "Tok"}),
        ["pla01:0", "pla01:1"],
        versao=_versao(modelo),
    )

    assert r.status_code == 201, r.text
    [itens] = _inventarios(mundo)
    assert [(i["cor"], i["marca"]) for i in itens] == [
        ("azul", "Tok"),
        ("verde", "Tok"),
    ]
    assert {h["depois_legivel"] for h in mundo.historico().json()} == {"marca Tok"}


def test_cor_e_marca_sem_nenhum_dos_dois_da_422() -> None:
    mundo = _mundo()

    r = _corrigir(mundo, "inventario.cor_marca", "{}", item_id="pla01:0")

    assert r.status_code == 422


@pytest.mark.parametrize(
    ("ids", "tipo"),
    [
        (["pla01:0", "pla01:0"], "inventario.nao_existe"),
        ([f"pla01:{k}" for k in range(501)], "inventario.nao_existe"),
        (["pes01"], "pessoa.renomear"),
        ([], "inventario.nao_existe"),
    ],
)
def test_grupo_invalido_da_422(ids: list[str], tipo: str) -> None:
    mundo = _mundo()

    r = _no_grupo(mundo, tipo, "nao_existe", ids)

    assert r.status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_grupo_com_um_item_inexistente_nao_grava_nenhum() -> None:
    mundo = _mundo()

    r = _no_grupo(mundo, "inventario.nao_existe", "nao_existe", ["pla01:0", "pla09:0"])

    assert r.status_code == 422
    assert mundo.correcoes.listar("j1") == []
    assert [len(i) for i in _inventarios(mundo)] == [2, 2]


@pytest.mark.parametrize(("acao", "fica"), [("aprovar", 1), ("recusar", 2)])
def test_grupo_sem_curador_fica_pendente_inteiro_e_a_decisao_vale_para_todos(
    acao: str, fica: int
) -> None:
    mundo = _mundo()
    mundo.aprovacao.definir(frozenset({"inventario.nao_existe"}))
    cid = _no_grupo(mundo, "inventario.nao_existe", "nao_existe", RELOGIOS).json()["id"]
    assert [len(i) for i in _inventarios(mundo)] == [2, 2]

    corpo = {"motivo": "não confere"} if acao == "recusar" else None
    r = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{cid}/{acao}", json=corpo, headers=CURADOR
    )

    assert r.status_code == 201, r.text
    assert [len(i) for i in _inventarios(mundo)] == [0 if fica == 1 else 2, fica]
    estados = {
        h["estado"]
        for h in mundo.historico().json()
        if h["tipo"] not in ("aprovar", "recusar")
    }
    assert estados == {"aprovada" if acao == "aprovar" else "recusada"}


def test_grupo_em_parte_orfao_deixa_o_resto_aplicado_e_a_orfa_na_fila() -> None:
    mundo = _mundo()
    _no_grupo(mundo, "inventario.nao_existe", "nao_existe", RELOGIOS)
    mundo.avancar()
    mundo.reprocessar(
        _modelo(
            _plano(
                "pla01",
                0,
                10000,
                _item("relógio de parede"),
                _item("relógio de parede"),
            ),
            _plano("pla02", 10000, 20000, _item("jarro"), _item("vaso")),
        )
    )

    assert _nomes(mundo) == [[], ["jarro", "vaso"]]
    [orfa] = _fila(mundo)
    assert orfa["item_id"] == "pla02:0"
    casada = next(c.id for c in mundo.correcoes.listar("j1") if c.id != orfa["id"])

    assert mundo.desfazer(casada).status_code == 201

    assert _nomes(mundo) == [
        ["relógio de parede", "relógio de parede"],
        ["jarro", "vaso"],
    ]
    assert [i["id"] for i in _fila(mundo)] == [orfa["id"]]


def test_membro_reaplicado_segue_no_grupo_e_desfazer_alcanca_ele() -> None:
    mundo = _mundo()
    _no_grupo(mundo, "inventario.nao_existe", "nao_existe", RELOGIOS)
    mundo.avancar()
    mundo.reprocessar(
        _modelo(
            _plano(
                "pla01",
                0,
                10000,
                _item("relógio de parede"),
                _item("relógio de parede"),
            ),
            _plano("pla02", 10000, 20000, _item("jarro"), _item("vaso")),
        )
    )
    [orfa] = _fila(mundo)
    assert (
        _resolver(mundo, orfa["id"], "reaplicar", item_id="pla02:0").status_code == 201
    )
    assert _nomes(mundo) == [[], ["vaso"]]
    casada = next(
        c.id
        for c in mundo.correcoes.listar("j1")
        if c.item_id == "pla01:0" and c.tipo == "inventario.nao_existe"
    )
    mundo.avancar()

    assert mundo.desfazer(casada).status_code == 201

    assert _nomes(mundo) == [
        ["relógio de parede", "relógio de parede"],
        ["jarro", "vaso"],
    ]


def _muitos(n: int) -> dict[str, Any]:
    return _modelo(
        *(
            _plano(f"p{k}", k * 1000, (k + 1) * 1000, _item("relógio de parede"))
            for k in range(n)
        )
    )


def _chamadas(monkeypatch: pytest.MonkeyPatch, n: int) -> dict[str, int]:
    """Quantas vezes cada passo caro roda num gesto de grupo com `n` itens."""
    contagem = {"aplicar": 0, "gravar": 0}
    original = regras.aplicar

    def contando(*args: Any, **kwargs: Any) -> dict[str, Any]:
        contagem["aplicar"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(regras, "aplicar", contando)
    monkeypatch.setattr(registro, "aplicar", contando)
    eventos = EventosEmMemoria()
    modelo = _muitos(n)
    mundo = Mundo(["editor"], eventos=eventos)
    mundo.reprocessar(modelo)
    mundo.aprovacao.definir(frozenset({"inventario.nao_existe"}))
    repo = mundo.correcoes
    for metodo in ("acrescentar", "acrescentar_varios"):
        gravar = getattr(repo, metodo)

        def gravando(*args: Any, _gravar: Any = gravar) -> None:
            contagem["gravar"] += 1
            _gravar(*args)

        monkeypatch.setattr(repo, metodo, gravando)
    ids = [f"p{k}:0" for k in range(n)]
    cid = _no_grupo(
        mundo, "inventario.nao_existe", "nao_existe", ids, versao=_versao(modelo)
    ).json()["id"]
    mundo.cliente.post(f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=CURADOR)
    mundo.avancar()
    assert mundo.desfazer(cid).status_code == 201
    assert len(mundo.correcoes.listar("j1")) == 3 * n
    return {**contagem, "eventos": len(eventos.publicados)}


def test_gesto_de_grupo_custa_o_mesmo_com_3_ou_30_itens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poucos = _chamadas(monkeypatch, 3)
    monkeypatch.undo()
    muitos = _chamadas(monkeypatch, 30)

    assert poucos == muitos
    assert muitos["gravar"] == 3 and muitos["eventos"] == 3


def test_decupagem_corrigida_com_os_ids_do_inventario_passa_no_esquema_do_indice() -> (
    None
):
    modelo = SABRINA_EXEMPLO.decupagem.model_dump(mode="json")
    modelo["planos"][0]["inventario"] = [_item("relógio de parede"), _item("vaso")]
    versao = _versao(modelo)
    autoria = Autoria("u1", "ana@redetv.com.br", datetime(2026, 11, 19, tzinfo=UTC))
    pedidos = [
        ("inventario.nao_existe", "nao_existe", "pla1:0"),
        (
            "inventario.cor_marca",
            json.dumps({"cor": "azul", "marca": "Nike"}),
            "pla1:1",
        ),
    ]
    correcoes = [
        c
        for tipo, valor, item in pedidos
        for c in regras.corrigir_grupo(
            modelo,
            versao,
            [],
            NovaCorrecao.model_validate(
                {
                    "tipo": tipo,
                    "item_ids": [item],
                    "valor": valor,
                    "motivo": "m",
                    "versao": versao,
                }
            ),
            "j1",
            autoria,
        )
    ]

    entregue = regras.decupagem_com_correcoes(modelo, versao, correcoes)
    validada = Decupagem.model_validate(_so_o_esquema(Decupagem, entregue))

    [vaso] = validada.planos[0].inventario
    assert (vaso.nome, vaso.cor, vaso.marca) == ("vaso", "azul", "Nike")


def test_sem_editar_a_decupagem_o_grupo_da_403() -> None:
    mundo = Mundo(["consulta"])
    mundo.reprocessar(M)

    r = _no_grupo(mundo, "inventario.nao_existe", "nao_existe", RELOGIOS)

    assert r.status_code == 403
