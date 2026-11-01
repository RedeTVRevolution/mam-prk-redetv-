from api.decupagem import Decupagem
from api.exemplos_da_busca import EXEMPLOS, OUTRA, SABRINA, _decupagem, _objeto
from api.indice_da_busca import (
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
        ("j:objeto:0:0", 0, 1_000, "obj01.jpg"),
        ("j:objeto:0:1", 5_000, 6_000, "pla2.jpg"),
    ]


def test_fala_e_gc_levam_o_quadro_do_plano_em_que_comecam() -> None:
    decupagem = _com_quadros(_decupagem([], [], ["Boa noite"]))
    quadros = {
        r.tipo: r.quadro
        for r in registros_da_decupagem("j", decupagem, None, None)
        if r.tipo in ("fala", "texto_na_tela")
    }
    assert quadros == {"fala": "pla1.jpg", "texto_na_tela": "pla1.jpg"}
