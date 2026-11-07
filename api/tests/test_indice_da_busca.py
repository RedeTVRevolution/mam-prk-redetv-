import json
from dataclasses import asdict
from typing import Any

from api.decupagem import CATEGORIAS_DE_OBJETO, Decupagem, ObjetoDoInventario
from api.exemplos_da_busca import (
    EXEMPLOS,
    OUTRA,
    SABRINA,
    _decupagem,
    _objeto,
    _pessoa,
)
from api.indice_da_busca import (
    NOME_DA_CATEGORIA,
    Consulta,
    Filtros,
    IndiceEmMemoria,
    Registro,
    registros_da_decupagem,
)


def _indice() -> IndiceEmMemoria:
    indice = IndiceEmMemoria()
    for exemplo in EXEMPLOS:
        indice.gravar(exemplo.job_id, exemplo.registros())
    return indice


def test_filtro_composto_devolve_so_o_objeto_da_sabrina() -> None:
    achados = _indice().buscar(
        Consulta(
            filtros=Filtros(
                tipo="objeto", categoria="roupa", cor_base="vermelho", dono=SABRINA
            )
        )
    )
    assert [(r.job_id, r.dono, r.cor_base) for r in achados] == [
        ("ex-sabrina", SABRINA, ["vermelho"])
    ]


def test_sem_dono_no_filtro_volta_o_vestido_vermelho_da_outra_pessoa() -> None:
    achados = _indice().buscar(
        Consulta(filtros=Filtros(tipo="objeto", categoria="roupa", cor_base="vermelho"))
    )
    assert sorted(r.job_id for r in achados) == ["ex-outra", "ex-sabrina"]


def test_objeto_sem_dono_nao_casa_com_filtro_de_dono() -> None:
    achados = _indice().buscar(
        Consulta(filtros=Filtros(tipo="objeto", categoria="calcado", dono=SABRINA))
    )
    assert achados == []
    sem_dono = _indice().buscar(
        Consulta(filtros=Filtros(tipo="objeto", categoria="calcado"))
    )
    assert [(r.job_id, r.dono) for r in sem_dono] == [("ex-sapato", None)]


def test_apagar_tira_so_os_registros_do_video() -> None:
    indice = _indice()
    indice.apagar("ex-sabrina")
    achados = indice.buscar(Consulta(filtros=Filtros(dono=SABRINA)))
    assert achados == []
    assert indice.buscar(Consulta(filtros=Filtros(tipo="objeto", cor_base="vermelho")))


def test_gravar_de_novo_substitui_os_registros_do_video() -> None:
    indice = _indice()
    exemplo = EXEMPLOS[0]
    indice.gravar(exemplo.job_id, exemplo.registros())
    assert indice.total() == sum(len(e.registros()) for e in EXEMPLOS)


def test_texto_casa_sem_acento_nem_maiuscula() -> None:
    achados = _indice().buscar(Consulta(texto="SANDALIA"))
    assert {r.job_id for r in achados} == {"ex-sapato"}


def test_texto_casa_qualquer_palavra_inteira_como_o_indice_real() -> None:
    indice = IndiceEmMemoria()
    indice.gravar(
        "j",
        [
            Registro(
                id="a",
                tipo="fala",
                job_id="j",
                inicio_ms=0,
                fim_ms=1,
                texto="A Angélica, de azul",
            ),
            Registro(
                id="b",
                tipo="fala",
                job_id="j",
                inicio_ms=0,
                fim_ms=1,
                texto="vestido azul",
            ),
            Registro(
                id="c",
                tipo="fala",
                job_id="j",
                inicio_ms=0,
                fim_ms=1,
                texto="calça vinho",
            ),
        ],
    )

    def ids(texto: str) -> set[str]:
        return {r.id for r in indice.buscar(Consulta(texto=texto))}

    assert ids("ANGELICA") == {"a"}
    assert ids("angelica vestido") == {"a", "b"}
    assert ids("vest") == set()  # palavra inteira, não pedaço


def test_registros_tem_um_por_plano_fala_texto_e_objeto() -> None:
    tipos = [r.tipo for r in EXEMPLOS[0].registros()]
    assert set(tipos) == {"plano", "fala", "texto_na_tela", "objeto"}


def test_pessoas_do_plano_sao_as_que_aparecem_nele() -> None:
    planos = [r for r in EXEMPLOS[0].registros() if r.tipo == "plano"]
    assert planos[0].pessoas == [SABRINA, OUTRA]


def test_registro_de_objeto_leva_atributos_e_tempos() -> None:
    [vestido, *_] = [
        r for r in EXEMPLOS[0].registros() if r.tipo == "objeto" and r.dono == SABRINA
    ]
    assert isinstance(vestido, Registro)
    assert (vestido.categoria, vestido.relacao, vestido.inicio_ms, vestido.fim_ms) == (
        "roupa",
        "veste",
        0,
        4_000,
    )


def _com_quadros(d: Decupagem) -> Decupagem:
    planos = [p.model_copy(update={"quadro": f"{p.id}.jpg"}) for p in d.planos]
    return d.model_copy(update={"planos": planos})


def test_cada_ocorrencia_do_objeto_e_um_registro_com_os_seus_tempos() -> None:
    # A calça vinho aparece aos 0 s e aos 5 s: dois momentos, e não um bloco de 0 a 6 s.
    calca = _objeto("obj01", "roupa", "calça", "vermelho", None, 1_000)
    calca["ocorrencias"].append({"inicio_ms": 5_000, "fim_ms": 6_000})
    calca["quadro"] = "obj01.jpg"
    decupagem = _com_quadros(_decupagem([], [calca], []))
    objetos = [
        r
        for r in registros_da_decupagem("j", decupagem, None, None)
        if r.tipo == "objeto"
    ]
    # A primeira ocorrência leva o quadro do objeto; as outras, o do plano em que começam.
    assert [(r.id, r.inicio_ms, r.fim_ms, r.quadro) for r in objetos] == [
        ("j:objeto:obj01:0", 0, 1_000, "obj01.jpg"),
        ("j:objeto:obj01:1", 5_000, 6_000, "pla2.jpg"),
    ]


def test_fala_e_gc_levam_o_quadro_do_plano_em_que_comecam() -> None:
    decupagem = _com_quadros(_decupagem([], [], ["Boa noite"]))
    quadros = {
        r.tipo: r.quadro
        for r in registros_da_decupagem("j", decupagem, None, None)
        if r.tipo in ("fala", "texto_na_tela")
    }
    assert quadros == {"fala": "pla1.jpg", "texto_na_tela": "pla1.jpg"}


def _com_inventario(d: Decupagem) -> Decupagem:
    def objeto(
        nome: str, categoria: str, cor: str | None, destaque: int
    ) -> ObjetoDoInventario:
        return ObjetoDoInventario.model_validate(
            {
                "nome": nome,
                "categoria": categoria,
                "cor": cor,
                "caixas": [
                    {
                        "quadro": "pla1-a.jpg",
                        "x": 0.1,
                        "y": 0.1,
                        "largura": 0.5,
                        "altura": 0.5,
                    }
                ],
                "destaque": destaque,
            }
        )

    inventario = [
        objeto("carro", "veiculo", "azul", 3),
        objeto("microfone", "eletronico", None, 2),
        objeto("livro", "documento", "vermelho", 1),
    ]
    planos = [
        p.model_copy(update={"inventario": inventario if p.id == "pla1" else []})
        for p in d.planos
    ]
    return d.model_copy(update={"planos": planos})


def test_o_plano_com_inventario_leva_todos_os_objetos_no_registro_do_plano() -> None:
    decupagem = _com_inventario(_decupagem([], [], []))
    [plano, outro] = [
        r
        for r in registros_da_decupagem("j", decupagem, None, None)
        if r.tipo == "plano"
    ]
    for palavra in ("carro", "azul", "microfone", "livro", "vermelho", "documento"):
        assert palavra in (plano.descricao or "")
    assert "carro" not in (outro.descricao or "")


def test_todo_objeto_do_inventario_ganha_registro_proprio_com_o_destaque() -> None:
    decupagem = _com_inventario(_decupagem([], [], []))
    objetos = {
        r.tipo_do_objeto: r
        for r in registros_da_decupagem("j", decupagem, None, None)
        if r.tipo == "objeto"
    }
    assert {n: (o.destaque, o.categoria) for n, o in objetos.items()} == {
        "carro": (3, "veiculo"),
        "microfone": (2, "eletronico"),
        "livro": (1, "documento"),
    }
    for o in objetos.values():
        assert (o.inicio_ms, o.fim_ms, o.quadro) == (0, 4_000, "pla1-a.jpg")
    assert objetos["carro"].cor == "azul"
    assert objetos["carro"].cor_base == ["azul"]


def test_o_objeto_de_cena_curto_leva_a_categoria_e_passa_do_piso_de_palavras() -> None:
    decupagem = _com_inventario(_decupagem([], [], []))
    [carro] = [
        r
        for r in registros_da_decupagem("j", decupagem, None, None)
        if r.tipo == "objeto" and r.tipo_do_objeto == "carro"
    ]
    assert carro.texto == "carro azul, veículo, objeto de cena"
    assert len((carro.texto or "").split()) >= 3


def test_o_objeto_de_uma_palavra_sem_dono_passa_do_piso_de_palavras() -> None:
    decupagem = _com_inventario(_decupagem([], [], []))
    planos = [
        p.model_copy(
            update={
                "inventario": [
                    i.model_copy(update={"nome": "microfone", "cor": None})
                    for i in p.inventario
                    if i.destaque == 3
                ]
            }
        )
        for p in decupagem.planos
    ]
    [microfone] = [
        r
        for r in registros_da_decupagem(
            "j", decupagem.model_copy(update={"planos": planos}), None, None
        )
        if r.tipo == "objeto"
    ]
    assert microfone.texto == "microfone, veículo, objeto de cena"
    assert len((microfone.texto or "").split()) >= 3


def test_toda_categoria_tem_nome_em_portugues() -> None:
    assert set(NOME_DA_CATEGORIA) == set(CATEGORIAS_DE_OBJETO)


def test_o_registro_proprio_leva_o_quadro_da_maior_caixa() -> None:
    decupagem = _com_inventario(_decupagem([], [], []))

    def caixa(quadro: str, lado: float) -> dict[str, Any]:
        return {"quadro": quadro, "x": 0.0, "y": 0.0, "largura": lado, "altura": lado}

    # Cada objeto tem a maior caixa num quadro diferente, e nem sempre na mesma posição.
    caixas = {
        "carro": [caixa("pla1-b.jpg", 0.1), caixa("pla1-c.jpg", 0.6)],
        "microfone": [caixa("pla1-d.jpg", 0.6), caixa("pla1-b.jpg", 0.1)],
        "livro": [caixa("pla1-b.jpg", 0.1), caixa("pla1-e.jpg", 0.3)],
    }
    planos = [
        p.model_copy(
            update={
                "inventario": [
                    ObjetoDoInventario.model_validate(
                        {**i.model_dump(), "caixas": caixas[i.nome]}
                    )
                    for i in p.inventario
                ]
            }
        )
        for p in decupagem.planos
    ]
    objetos = {
        r.tipo_do_objeto: (r.destaque, r.quadro)
        for r in registros_da_decupagem(
            "j", decupagem.model_copy(update={"planos": planos}), None, None
        )
        if r.tipo == "objeto"
    }
    assert objetos == {
        "carro": (3, "pla1-c.jpg"),
        "microfone": (2, "pla1-d.jpg"),
        "livro": (1, "pla1-e.jpg"),
    }


def test_a_roupa_curta_leva_a_categoria_e_o_dono_sem_o_nome_dele() -> None:
    blazer = _objeto("obj01", "roupa", "blazer", "preto", "pes01", 1_000)
    decupagem = _decupagem(
        [_pessoa("pes01", "Flávia Noronha", "cat-flavia", 0, 4_000)], [blazer], []
    )
    registros = registros_da_decupagem("j", decupagem, None, None)
    [roupa] = [r for r in registros if r.tipo == "objeto"]
    assert roupa.texto == "blazer preto, roupa, de pessoa"
    assert roupa.dono == "cat-flavia"
    assert len((roupa.texto or "").split()) >= 3
    # Nenhum campo do índice leva o nome: renomear no catálogo não muda registro algum.
    assert "Flávia" not in json.dumps([asdict(r) for r in registros], default=str)


def test_o_texto_do_objeto_nao_muda_com_o_nome_da_pessoa() -> None:
    blazer = _objeto("obj01", "roupa", "blazer", "preto", "pes01", 1_000)

    def registros(nome: str) -> list[Registro]:
        decupagem = _decupagem(
            [_pessoa("pes01", nome, "cat-flavia", 0, 4_000)], [blazer], []
        )
        return registros_da_decupagem("j", decupagem, None, None)

    assert registros("Flávia Noronha") == registros("Flávia Noronha Silva")


def test_decupagem_sem_inventario_segue_como_antes() -> None:
    decupagem = _decupagem([], [], [])
    registros = registros_da_decupagem("j", decupagem, None, None)
    assert [r.tipo for r in registros] == ["plano", "plano", "texto_na_tela"]
    assert all(r.destaque is None for r in registros)
    assert [r.descricao for r in registros if r.tipo == "plano"] == [
        "estúdio",
        "bastidor",
    ]


def test_fala_e_texto_sem_id_ganham_o_id_que_a_entrega_daria() -> None:
    decupagem = EXEMPLOS[0].decupagem
    assert decupagem.transcricao and decupagem.textos_na_tela
    assert decupagem.transcricao[0].id is None

    ids = [r.id for r in registros_da_decupagem("j", decupagem, "p", None)]

    assert "j:fala:fal000" in ids and "j:texto:txt000" in ids


def test_registros_levam_o_sistema_e_a_lixeira_do_video() -> None:
    exemplo = EXEMPLOS[0]
    registros = registros_da_decupagem(
        exemplo.job_id, exemplo.decupagem, None, None, "Playout", True
    )
    assert registros
    assert {(r.sistema, r.na_lixeira) for r in registros} == {("Playout", True)}
    padrao = registros_da_decupagem(exemplo.job_id, exemplo.decupagem, None, None)
    assert {(r.sistema, r.na_lixeira) for r in padrao} == {(None, False)}
