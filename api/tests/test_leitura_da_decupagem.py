"""As duas leituras da Decupagem do Job (#584), pelo seam do módulo, com os dublês em memória."""

import json
import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from api.catalogo import (
    CatalogoEmMemoria,
    EnvioParaLixeira,
    FusaoDaPessoa,
    PessoaDoCatalogo,
    RenomeacaoDaPessoa,
)
from api.correcoes import Correcao, RepositorioDeCorrecoesEmMemoria, versao_do_modelo
from api.jobs import FiltroDeJobs, RepositorioEmMemoria
from api.leitura_da_decupagem import (
    LeituraDaDecupagem,
    decupagens_corrigidas,
    decupagens_dos_jobs,
)
from api.marcas import CatalogoDeMarcasEmMemoria, MarcaDoCatalogo

BASE = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
ENVIO = EnvioParaLixeira(em=BASE, por_uid="u1", por_email="a@r.com", motivo="teste")


def _pessoa(
    id: str,
    nome: str,
    catalogo_id: str | None = None,
    fontes: list[str] | None = None,
) -> dict[str, Any]:
    pessoa: dict[str, Any] = {
        "id": id,
        "nome": nome,
        "origem": "modelo_forte",
        "estado_do_nome": "confirmado",
        "fontes_do_nome": fontes if fontes is not None else ["gc"],
        "na_imagem": [{"inicio_ms": 1000, "fim_ms": 5000, "evidencia": "rosto"}],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }
    if catalogo_id is not None:
        pessoa["catalogo_id"] = catalogo_id
    return pessoa


def _modelo(
    *pessoas: dict[str, Any], comerciais: list[dict[str, Any]] | None = None
) -> bytes:
    return json.dumps(
        {
            "versao_esquema": "1.2",
            "video": {"duracao_ms": 60000},
            "pautas": [],
            "pessoas": list(pessoas),
            "comerciais": comerciais or [],
        }
    ).encode()


def _comercial(id: str, marca: str, catalogo_id: str | None) -> dict[str, Any]:
    c: dict[str, Any] = {"id": id, "marca": marca, "inicio_ms": 0, "fim_ms": 1}
    if catalogo_id is not None:
        c["catalogo_id"] = catalogo_id
    return c


class Decupagens:
    def __init__(self, conteudo: bytes | None) -> None:
        self.conteudo = conteudo

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        if self.conteudo is None:
            raise FileNotFoundError(job_id)
        yield self.conteudo


class PessoasContadas(CatalogoEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lotes: list[list[str]] = []
        self.individuais: list[str] = []

    def obter(self, id: str) -> PessoaDoCatalogo | None:
        self.individuais.append(id)
        return super().obter(id)

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        ids = list(ids)
        self.lotes.append(ids)
        return super().obter_varios(ids)


def _leitura(
    conteudo: bytes | None,
    pessoas: CatalogoEmMemoria | None = None,
    marcas: CatalogoDeMarcasEmMemoria | None = None,
    correcoes: RepositorioDeCorrecoesEmMemoria | None = None,
) -> LeituraDaDecupagem:
    return LeituraDaDecupagem(
        Decupagens(conteudo),
        correcoes or RepositorioDeCorrecoesEmMemoria(),
        pessoas,
        marcas,
    )


def _renomear(conteudo: bytes, **campos: Any) -> Correcao:
    base: dict[str, Any] = {
        "id": "c1",
        "job_id": "j1",
        "autor_uid": "u1",
        "autor_email": "a@r.com",
        "criada_em": BASE,
        "motivo": "sobrenome",
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "antes": "Ana Souza",
        "depois": "Ana Souza Lima",
        "ancora": {
            "versao": versao_do_modelo(conteudo),
            "tipo_do_item": "pessoa",
            "identidade": "ana souza",
            "inicio_ms": 1000,
            "fim_ms": 5000,
        },
    }
    return Correcao(**{**base, **campos})


def _nome(lida: dict[str, Any], id: str = "pes01") -> str:
    return str(next(p["nome"] for p in lida["pessoas"] if p["id"] == id))


def _vinculo(lida: dict[str, Any], id: str = "pes01") -> str | None:
    achada = next(p for p in lida["pessoas"] if p["id"] == id)
    return achada.get("catalogo_id")  # type: ignore[no-any-return]


# --- Correções -----------------------------------------------------------------------


def test_correcao_em_vigor_entra_nas_duas_leituras() -> None:
    conteudo = _modelo(_pessoa("pes01", "Ana Souza"))
    correcoes = RepositorioDeCorrecoesEmMemoria()
    correcoes.acrescentar(_renomear(conteudo))
    leitura = _leitura(conteudo, correcoes=correcoes)
    assert _nome(leitura.corrigida("j1")) == "Ana Souza Lima"
    assert _nome(leitura.entregue("j1")) == "Ana Souza Lima"


def test_correcao_pendente_fica_fora() -> None:
    conteudo = _modelo(_pessoa("pes01", "Ana Souza"))
    correcoes = RepositorioDeCorrecoesEmMemoria()
    correcoes.acrescentar(_renomear(conteudo, exige_aprovacao=True))
    leitura = _leitura(conteudo, correcoes=correcoes)
    assert _nome(leitura.corrigida("j1")) == "Ana Souza"
    assert _nome(leitura.entregue("j1")) == "Ana Souza"


# --- Fusão e renomeação -----------------------------------------------------------------


def _fundida_em(pessoa: PessoaDoCatalogo, destino_id: str) -> PessoaDoCatalogo:
    fusao = FusaoDaPessoa(
        destino_id=destino_id, em=BASE, por_uid="u1", por_email="a@r.com", motivo="x"
    )
    return pessoa.model_copy(update={"fundida": fusao})


def test_fusao_simples_leva_ao_destino() -> None:
    catalogo = CatalogoEmMemoria()
    a = catalogo.acrescentar("Ana A", "p", [])
    b = catalogo.acrescentar("Ana B", "p", [])
    catalogo.definir_fusao(a.id, _fundida_em(a, b.id).fundida)
    leitura = _leitura(_modelo(_pessoa("pes01", "Ana A", a.id)), catalogo)
    for lida in (leitura.corrigida("j1"), leitura.entregue("j1")):
        assert (_nome(lida), _vinculo(lida)) == ("Ana B", b.id)


def test_fusao_em_cadeia_leva_ao_ultimo_destino() -> None:
    catalogo = CatalogoEmMemoria()
    a, b, c = (catalogo.acrescentar(n, "p", []) for n in ("A", "B", "C"))
    catalogo.definir_fusao(a.id, _fundida_em(a, b.id).fundida)
    catalogo.definir_fusao(b.id, _fundida_em(b, c.id).fundida)
    leitura = _leitura(_modelo(_pessoa("pes01", "A", a.id)), catalogo)
    lida = leitura.corrigida("j1")
    assert (_nome(lida), _vinculo(lida)) == ("C", c.id)


def _renomeada(catalogo: CatalogoEmMemoria, de: str, para: str) -> PessoaDoCatalogo:
    p = catalogo.acrescentar(de, "p", [])
    renomeacao = RenomeacaoDaPessoa(
        nome_antigo=de,
        nome_novo=para,
        nomes_anteriores=[de],
        em=BASE,
        por_uid="u1",
        por_email="a@r.com",
        total=0,
        pendentes=[],
        estado="concluida",
    )
    return catalogo.definir_renomeacao(p.id, renomeacao).model_copy(
        update={"nome": para}
    )


def test_renomeacao_troca_o_nome_antigo_pelo_atual() -> None:
    catalogo = CatalogoEmMemoria()
    p = _renomeada(catalogo, "Ana Souza", "Ana Souza Lima")
    catalogo._pessoas[p.id] = p
    leitura = _leitura(_modelo(_pessoa("pes01", "Ana Souza", p.id)), catalogo)
    assert _nome(leitura.corrigida("j1")) == "Ana Souza Lima"


def test_destino_purgado_na_corrigida_a_renomeacao_da_origem_vale() -> None:
    """A corrigida não muda (#612): sem destino, vale a renomeação da própria origem."""
    catalogo = CatalogoEmMemoria()
    a = _renomeada(catalogo, "Ana Souza", "Ana Souza Lima")
    b = catalogo.acrescentar("Ana B", "p", [])
    catalogo._pessoas[a.id] = _fundida_em(a, b.id)
    catalogo.apagar(b.id)
    leitura = _leitura(_modelo(_pessoa("pes01", "Ana Souza", a.id)), catalogo)
    lida = leitura.corrigida("j1")
    assert (_nome(lida), _vinculo(lida)) == ("Ana Souza Lima", a.id)


def test_renomeacao_respeita_o_nome_corrigido_no_video() -> None:
    catalogo = CatalogoEmMemoria()
    p = _renomeada(catalogo, "Ana Souza", "Ana Souza Lima")
    catalogo._pessoas[p.id] = p
    leitura = _leitura(_modelo(_pessoa("pes01", "Ana Outra", p.id)), catalogo)
    assert _nome(leitura.corrigida("j1")) == "Ana Outra"


# --- Lixeira e purga -----------------------------------------------------------------------


def _lixeira(catalogo: CatalogoEmMemoria, id: str) -> None:
    catalogo.definir_lixeira(id, ENVIO)


def test_lixeira_so_com_rosto_volta_a_nao_identificado_na_entregue() -> None:
    catalogo = CatalogoEmMemoria()
    a = catalogo.acrescentar("Ana", "p", [])
    _lixeira(catalogo, a.id)
    leitura = _leitura(
        _modelo(_pessoa("pes01", "Ana", a.id, fontes=["rosto", "referencia"])), catalogo
    )
    corrigida, entregue = leitura.corrigida("j1"), leitura.entregue("j1")
    assert (_nome(corrigida), _vinculo(corrigida)) == ("Ana", a.id)
    assert (_nome(entregue), _vinculo(entregue)) == ("não identificado", None)


def test_lixeira_com_gc_ou_fala_mantem_o_nome_e_perde_o_vinculo_na_entregue() -> None:
    catalogo = CatalogoEmMemoria()
    a = catalogo.acrescentar("Ana", "p", [])
    _lixeira(catalogo, a.id)
    leitura = _leitura(_modelo(_pessoa("pes01", "Ana", a.id, fontes=["gc"])), catalogo)
    corrigida, entregue = leitura.corrigida("j1"), leitura.entregue("j1")
    assert (_nome(corrigida), _vinculo(corrigida)) == ("Ana", a.id)
    assert (_nome(entregue), _vinculo(entregue)) == ("Ana", None)


def test_pessoa_purgada_perde_o_vinculo_so_na_entregue() -> None:
    leitura = _leitura(
        _modelo(_pessoa("pes01", "Ana", "sumiu", fontes=["gc"])), CatalogoEmMemoria()
    )
    assert _vinculo(leitura.corrigida("j1")) == "sumiu"
    assert _vinculo(leitura.entregue("j1")) is None


def test_marca_na_lixeira_ou_purgada_mantem_o_texto_e_perde_o_vinculo_na_entregue() -> (
    None
):
    marcas = CatalogoDeMarcasEmMemoria()
    acme = marcas.acrescentar("Acme", [])
    marcas.definir_lixeira(acme.id, ENVIO)
    comerciais = [
        _comercial("c1", "Acme", acme.id),
        _comercial("c2", "Zeta", "purgada"),
    ]
    leitura = _leitura(_modelo(comerciais=comerciais), CatalogoEmMemoria(), marcas)
    corrigida, entregue = leitura.corrigida("j1"), leitura.entregue("j1")
    assert [(c["marca"], c.get("catalogo_id")) for c in corrigida["comerciais"]] == [
        ("Acme", acme.id),
        ("Zeta", "purgada"),
    ]
    assert [(c["marca"], c.get("catalogo_id")) for c in entregue["comerciais"]] == [
        ("Acme", None),
        ("Zeta", None),
    ]


def test_marca_viva_mantem_o_vinculo() -> None:
    marcas = CatalogoDeMarcasEmMemoria()
    acme: MarcaDoCatalogo = marcas.acrescentar("Acme", [])
    leitura = _leitura(
        _modelo(comerciais=[_comercial("c1", "Acme", acme.id)]), marcas=marcas
    )
    assert leitura.entregue("j1")["comerciais"][0]["catalogo_id"] == acme.id


# --- Catálogo não fornecido ------------------------------------------------------------------


def test_sem_catalogo_os_vinculos_ficam_como_estao() -> None:
    conteudo = _modelo(
        _pessoa("pes01", "Ana", "qualquer", fontes=["rosto"]),
        comerciais=[_comercial("c1", "Acme", "marca-qualquer")],
    )
    leitura = _leitura(conteudo)
    for lida in (leitura.corrigida("j1"), leitura.entregue("j1")):
        assert (_nome(lida), _vinculo(lida)) == ("Ana", "qualquer")
        assert lida["comerciais"][0]["catalogo_id"] == "marca-qualquer"


def test_so_marcas_fornecidas_nao_filtra_pessoas() -> None:
    leitura = _leitura(
        _modelo(_pessoa("pes01", "Ana", "qualquer")), marcas=CatalogoDeMarcasEmMemoria()
    )
    assert _vinculo(leitura.entregue("j1")) == "qualquer"


def test_so_pessoas_fornecidas_nao_filtra_marcas() -> None:
    leitura = _leitura(
        _modelo(comerciais=[_comercial("c1", "Acme", "m")]), CatalogoEmMemoria()
    )
    assert leitura.entregue("j1")["comerciais"][0]["catalogo_id"] == "m"


# --- Independência e erros -------------------------------------------------------------------


def test_as_leituras_sao_independentes() -> None:
    catalogo = CatalogoEmMemoria()
    a = catalogo.acrescentar("Ana", "p", [])
    _lixeira(catalogo, a.id)
    leitura = _leitura(_modelo(_pessoa("pes01", "Ana", a.id)), catalogo)
    corrigida = leitura.corrigida("j1")
    entregue = leitura.entregue("j1")
    assert _vinculo(corrigida) == a.id
    assert _vinculo(entregue) is None
    corrigida["pessoas"][0]["nome"] = "mudou"
    assert _nome(entregue) == "Ana"


def test_arquivo_ausente_e_json_invalido_sobem() -> None:
    with pytest.raises(FileNotFoundError):
        _leitura(None).entregue("j1")
    with pytest.raises(ValueError):
        _leitura(b"{nao e json").corrigida("j1")


# --- Leitura em lote ---------------------------------------------------------------------------


def test_lote_inicial_com_ids_distintos_e_id_inexistente_sem_nova_leitura() -> None:
    catalogo = PessoasContadas()
    a = catalogo.acrescentar("Ana", "p", [])
    leitura = _leitura(
        _modelo(
            _pessoa("pes01", "Ana", a.id),
            _pessoa("pes02", "Ana Maria", a.id),
            _pessoa("pes03", "Fantasma", "inexistente"),
        ),
        catalogo,
    )
    leitura.entregue("j1")
    # Três pessoas, dois ids distintos: o lote leva cada id uma vez só.
    assert [sorted(lote) for lote in catalogo.lotes] == [sorted([a.id, "inexistente"])]
    assert catalogo.individuais == []


def test_destino_da_fusao_fora_do_lote_e_lido_uma_vez() -> None:
    catalogo = PessoasContadas()
    a = catalogo.acrescentar("A", "p", [])
    b = catalogo.acrescentar("B", "p", [])
    catalogo.definir_fusao(a.id, _fundida_em(a, b.id).fundida)
    leitura = _leitura(
        _modelo(_pessoa("pes01", "A", a.id), _pessoa("pes02", "A2", a.id)), catalogo
    )
    leitura.entregue("j1")
    # Um lote por elo da cadeia, cada id uma vez; nada em leitura avulsa.
    assert catalogo.lotes == [[a.id], [b.id]]
    assert catalogo.individuais == []


# --- Iteradores sobre os Jobs --------------------------------------------------------


def test_iteradores_dao_a_corrigida_dos_concluidos_e_pulam_a_que_nao_abre(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from api.tests.test_lixeira import _job

    catalogo = CatalogoEmMemoria()
    a = catalogo.acrescentar("Ana A", "p", [])
    b = catalogo.acrescentar("Ana B", "p", [])
    catalogo.definir_fusao(a.id, _fundida_em(a, b.id).fundida)
    jobs = RepositorioEmMemoria()
    for id in ("j1", "j2"):
        jobs.salvar(_job(id))
    jobs.salvar(_job("j3", estado="analisando"))
    por_job = {"j1": _modelo(_pessoa("pes01", "Ana A", a.id))}

    class _PorJob:
        def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
            yield por_job[job_id]  # j2 não tem: KeyError, a leitura não abre

    decupagens = _PorJob()
    corr = RepositorioDeCorrecoesEmMemoria()

    # `configurar` do log estruturado troca os handlers da raiz (e o do caplog): ligo direto.
    logger = logging.getLogger("api.leitura_da_decupagem")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING"):
            lidas = list(decupagens_dos_jobs(jobs, corr, decupagens, catalogo))
    finally:
        logger.removeHandler(caplog.handler)

    assert [(j.id, _nome(d), _vinculo(d)) for j, d in lidas] == [("j1", "Ana B", b.id)]
    assert "j2" in caplog.text
    so_decupagens = list(decupagens_corrigidas(jobs, corr, decupagens, catalogo))
    assert [_nome(d) for d in so_decupagens] == ["Ana B"]
    filtradas = decupagens_dos_jobs(
        jobs, corr, decupagens, catalogo, FiltroDeJobs(pessoa_do_catalogo="x")
    )
    assert list(filtradas) == []
