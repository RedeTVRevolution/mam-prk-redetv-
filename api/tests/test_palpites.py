"""Fotos de referência de palpites fora do catálogo (#222)."""

from datetime import timedelta
from pathlib import Path

from api.catalogo import CatalogoEmMemoria, Rosto
from api.comparacao import comparar
from api.nomes_a_buscar import NomesABuscar, nomes_a_buscar
from api.referencias import BuscaComLimite
from api.rostos_dos_palpites import PREFIXO_DOS_PALPITES, Palpites, pasta_do_palpite
from api.tests.test_comparacao import (
    AGORA,
    Cenario,
    confianca,
    escolha,
    palpite,
    quadros,
)
from api.tests.test_gemini import TransporteFalso
from api.tests.test_identificacao import decupagem
from api.tests.test_jobs_de_identificacao import (  # noqa: F401 (fixture autouse do ffmpeg)
    com_gc,
    identificar,
    nome_do_modelo_forte,
    quadros_falsos,
)
from api.tests.test_referencias import (
    VALIDADE,
    Bucket,
    BuscaFalsa,
    ConferidorFalso,
    cenas,
    referenciar_nome,
    resultado,
)


def rosto(i: int) -> Rosto:
    return Rosto(
        origem="web", referencia="", pagina_url=f"https://x/{i}", obtida_em=AGORA
    )


def sem_ninguem() -> Cenario:
    """Um cenário de catálogo vazio: o único candidato é o palpite."""
    c = Cenario()
    c.catalogo = CatalogoEmMemoria()
    return c


def com_palpite(c: Cenario, nome: str = "Fulano Novo") -> Palpites:
    palpites = Palpites(c.fotos)
    palpites.guardar(nome, [(f"foto-{i}".encode(), rosto(i)) for i in range(3)])
    return palpites


def comparar_palpite(c: Cenario, palpites: Palpites, *confiancas: float):  # type: ignore[no-untyped-def]
    d = decupagem([palpite("pes01", "Fulano Novo", [(10_000, 40_000)])])
    transporte = TransporteFalso(escolha("A"), *[confianca(v) for v in confiancas])
    return comparar(
        d,
        transporte=transporte,
        quadros_em=quadros,
        fotos=c.fotos,
        catalogo=c.catalogo,
        job_id="job-1",
        agora=AGORA,
        validade=timedelta(days=180),
        dormir=lambda _: None,
        embaralhar=lambda lista: None,
        palpites=palpites,
        limiar=0.8,
    )


def test_pasta_do_palpite_e_o_nome_normalizado_sob_o_prefixo() -> None:
    assert pasta_do_palpite("Fulano  Nóvo") == "palpites/fulano-novo/"
    assert pasta_do_palpite("FULANO novo") == pasta_do_palpite("fulano Novo")
    assert pasta_do_palpite("李小龍").startswith(PREFIXO_DOS_PALPITES)
    assert pasta_do_palpite("李小龍") != pasta_do_palpite("王")


def test_palpite_fora_do_catalogo_confirmado_entra_no_catalogo_e_esvazia_o_prefixo() -> (
    None
):
    c = sem_ninguem()
    palpites = com_palpite(c)
    guardadas = {o for o in c.fotos.objetos if o.startswith(PREFIXO_DOS_PALPITES)}
    assert len(guardadas) == 4  # 3 JPEGs e os dados

    r = comparar_palpite(c, palpites, 0.9, 0.95, 0.85)

    [p] = r.decupagem.pessoas
    assert (p.nome, p.estado_do_nome, p.fontes_do_nome) == (
        "Fulano Novo",
        "confirmado",
        ["referencia"],
    )
    [nova] = c.catalogo.achar("Fulano Novo")
    assert p.catalogo_id == nova.id
    assert nova.papel == "comentarista"  # o papel vem da aparição
    assert len(nova.rostos) == 3
    for ro in nova.rostos:
        assert ro.referencia.startswith(f"referencias/{nova.id}/")
        assert ro.referencia in c.fotos.objetos
    assert not [o for o in c.fotos.objetos if o.startswith(PREFIXO_DOS_PALPITES)]


def test_palpite_nao_confirmado_deixa_as_fotos_so_no_prefixo() -> None:
    c = sem_ninguem()
    palpites = com_palpite(c)
    antes = dict(c.fotos.objetos)

    r = comparar_palpite(c, palpites, 0.9, 0.5, 0.9)

    assert [v.estado for v in r.vereditos] == ["palpite_nao_confirmado"]
    assert c.catalogo.achar("Fulano Novo") == []
    assert c.fotos.objetos == antes


def test_referenciar_nome_fora_do_catalogo_guarda_sob_o_prefixo_e_nao_repete() -> None:
    catalogo = CatalogoEmMemoria()
    bucket = Bucket()
    busca = BuscaFalsa([resultado(i) for i in range(4)])

    assert (
        referenciar_nome("Fulano Novo", catalogo, busca, bucket) == "palpite_guardado"
    )
    assert catalogo.achar("Fulano Novo") == []
    assert all(o.startswith("palpites/fulano-novo/") for o in bucket.objetos)
    assert len(Palpites(bucket).rostos("Fulano Novo")) == 3
    assert len(busca.consultas) == 1

    assert referenciar_nome("Fulano Novo", catalogo, busca, bucket) == "ja_tinha"
    assert len(busca.consultas) == 1

    vencida = AGORA + VALIDADE + timedelta(days=1)
    assert (
        referenciar_nome("Fulano Novo", catalogo, busca, bucket, agora=vencida)
        == "palpite_guardado"
    )
    assert len(busca.consultas) == 2


def test_referenciar_sem_tres_fotos_boas_nao_guarda_o_palpite() -> None:
    bucket = Bucket()
    busca = BuscaFalsa([resultado(i) for i in range(2)])

    r = referenciar_nome(
        "Fulano Novo", CatalogoEmMemoria(), busca, bucket, sementes=(1, 2)
    )

    assert r == "sem_referencia"
    assert bucket.objetos == {}


def executar_job(nomes: list[str], limite: int, rotulos: list[dict[str, str]]):  # type: ignore[no-untyped-def]
    from api.referencias import SugestoesEmMemoria
    from api.referencias_job import executar

    bucket = Bucket()
    fotos = cenas(1, 2, 3, 4)
    busca = BuscaFalsa([resultado(i) for i in range(4)])
    r = executar(
        nomes,
        None,
        catalogo=CatalogoEmMemoria(),
        busca=busca,
        baixar_thumbnail_de=lambda url: fotos[url.rsplit("/", 1)[1]] or b"",
        baixar_original_de=lambda url: b"",
        conferidor=ConferidorFalso(),
        extrator=None,  # type: ignore[arg-type]
        armazenamento=bucket,
        sugestoes=SugestoesEmMemoria(),
        palpites=Palpites(bucket),
        validade=VALIDADE,
        agora=AGORA,
        limite_de_buscas=limite,
        job_id="job-9",
        registrar=rotulos.append,
    )
    return r, busca


def test_job_para_de_buscar_no_limite_e_marca_o_resto() -> None:
    rotulos: list[dict[str, str]] = []

    r, busca = executar_job(["Ana Um", "Beto Dois", "Caio Tres"], 2, rotulos)

    assert r == {
        "Ana Um": "palpite_guardado",
        "Beto Dois": "palpite_guardado",
        "Caio Tres": "limite_de_buscas",
    }
    assert len(busca.consultas) == 2


def test_cada_busca_leva_o_rotulo_de_custo() -> None:
    rotulos: list[dict[str, str]] = []

    executar_job(["Ana Um"], 5, rotulos)

    assert rotulos == [
        {
            "custo": "serpapi",
            "etapa": "referencias",
            "engine": "google_images",
            "job_id": "job-9",
        }
    ]


def test_busca_com_limite_zero_nao_faz_nenhuma() -> None:
    import pytest

    from api.referencias import LimiteDeBuscas

    busca = BuscaFalsa()
    contada = BuscaComLimite(busca, 0, lambda _: None, "j")

    with pytest.raises(LimiteDeBuscas):
        contada.web("x")
    assert busca.consultas == []


def test_nomes_a_buscar_palpites_primeiro_e_so_os_sem_as_tres_fotos() -> None:
    c = Cenario()  # Leão Lobo e Nelson Rubens já têm as 3 fotos
    sem_fotos = c.catalogo.acrescentar("Sem Fotos", "repórter", [])
    d = decupagem(
        [
            palpite("p1", "Fulano Novo", [(1_000, 5_000)]),
            palpite("p2", "Leão Lobo", [(1_000, 5_000)]),
            palpite("p3", sem_fotos.nome, [(1_000, 5_000)]),
            palpite("p4", "Fulano Novo", [(6_000, 9_000)]),
        ]
    )

    lista = nomes_a_buscar(d, "Programa", c.catalogo, AGORA, timedelta(days=180))

    assert lista == NomesABuscar(
        programa="Programa", nomes=["Fulano Novo", "Sem Fotos"]
    )


def test_identificacao_grava_a_lista_de_nomes_a_buscar(tmp_path: Path) -> None:
    _, decupagens = identificar(com_gc(), nome_do_modelo_forte(), tmp_path=tmp_path)

    assert decupagens.nomes is not None
    # Confirmado pelo modelo e sem fotos no catálogo: vai para a busca.
    assert NomesABuscar.model_validate_json(decupagens.nomes).nomes == ["Leão Lobo"]
