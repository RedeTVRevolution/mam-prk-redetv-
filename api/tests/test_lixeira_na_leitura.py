"""A lixeira do catálogo vale no relatório de tempo de tela (#591): a regra de quem conta, o
relatório com o cache quente, duas instâncias, a pessoa fundida e purgada, a consulta real
do BigQuery e a versão do estado da lixeira."""

import os
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.cache_curto import CacheCurto
from api.catalogo import (
    Catalogo,
    CatalogoEmMemoria,
    EnvioParaLixeira,
    FusaoDaPessoa,
    PessoaDoCatalogo,
)
from api.copia_bigquery import CopiaEmMemoria, LinhaDoMomento, PessoaDoMomento
from api.jobs import RepositorioEmMemoria, agora_utc
from api.lixeira_do_catalogo import purgar_catalogo_vencido
from api.lixeira_na_leitura import (
    PurgaDeMarca,
    PurgasDeMarca,
    PurgasDeMarcaEmMemoria,
    PurgasDeMarcaFirestore,
    VersaoDaLixeira,
    VersaoDaLixeiraEmMemoria,
    VersaoDaLixeiraFirestore,
    pessoas_que_contam,
)
from api.main import criar_app
from api.marcas import CatalogoDeMarcasEmMemoria
from api.papeis import RepositorioDePapeisEmMemoria
from api.relatorio_de_marcas import ConsultaBigQuery as MarcasBigQuery
from api.relatorio_de_marcas import ConsultaComCache as MarcasComCache
from api.relatorio_de_marcas import ConsultaEmMemoria as MarcasEmMemoria
from api.relatorios import posicao_do_cursor
from api.tempo_de_tela import (
    ConsultaBigQuery,
    ConsultaDeMomentos,
    ConsultaEmMemoria,
)
from api.tempo_de_tela import ConsultaComCache as ComCache
from api.tests.sem_periodo_padrao import ClienteSemPeriodoPadrao
from api.tests.test_auth import VerificadorFalso
from api.tests.test_busca import job as _job
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_relatorio_de_marcas import CONFIG as CONFIG_DAS_MARCAS
from api.tests.test_relatorio_de_marcas import Transporte as TransporteDasMarcas
from api.tests.test_relatorio_de_marcas import _linha as _comercial
from api.tests.test_tempo_de_tela import CONFIG, Transporte, _linha_do_bq

ADMIN = {"Authorization": "Bearer admin"}
ROTA = "/v1/relatorios/tempo-de-tela"
LIXEIRA = "/v1/admin/lixeira"
ENVIO = EnvioParaLixeira(
    em=agora_utc(), por_uid="u", por_email="u@redetv.com", motivo="teste"
)


def _fusao(destino: PessoaDoCatalogo) -> FusaoDaPessoa:
    return FusaoDaPessoa(
        destino_id=destino.id,
        em=agora_utc(),
        por_uid="u",
        por_email="u@redetv.com",
        motivo="duplicada",
    )


# --- a regra ---------------------------------------------------------------------------


def test_conta_quem_existe_fora_da_lixeira_e_nao_conta_a_lixeira_nem_a_purgada() -> (
    None
):
    catalogo = CatalogoEmMemoria()
    ana = catalogo.acrescentar("Ana", "", [])
    bia = catalogo.acrescentar("Bia", "", [])
    cris = catalogo.acrescentar("Cris", "", [])
    catalogo.definir_lixeira(bia.id, ENVIO)
    catalogo.apagar(cris.id)

    assert pessoas_que_contam(catalogo, [ana.id, bia.id, cris.id, "nunca-existiu"]) == {
        ana.id
    }
    assert pessoas_que_contam(catalogo, []) == set()


def test_a_fundida_vale_o_que_vale_o_destino_final_da_cadeia() -> None:
    catalogo = CatalogoEmMemoria()
    a, b, c = (catalogo.acrescentar(n, "", []) for n in "ABC")
    catalogo.definir_fusao(a.id, _fusao(b))
    catalogo.definir_fusao(b.id, _fusao(c))

    assert pessoas_que_contam(catalogo, [a.id, b.id, c.id]) == {a.id, b.id, c.id}

    catalogo.definir_lixeira(c.id, ENVIO)
    assert pessoas_que_contam(catalogo, [a.id, b.id, c.id]) == set()

    catalogo.definir_lixeira(c.id, None)
    assert pessoas_que_contam(catalogo, [a.id, b.id, c.id]) == {a.id, b.id, c.id}

    catalogo.apagar(c.id)
    assert pessoas_que_contam(catalogo, [a.id, b.id, c.id]) == set()


def test_a_origem_na_lixeira_nao_conta_mesmo_com_o_destino_valendo() -> None:
    catalogo = CatalogoEmMemoria()
    a, b = (catalogo.acrescentar(n, "", []) for n in "AB")
    catalogo.definir_fusao(a.id, _fusao(b))
    catalogo.definir_lixeira(a.id, ENVIO)

    assert pessoas_que_contam(catalogo, [a.id, b.id]) == {b.id}


def test_ciclo_de_fusao_gravado_errado_nao_prende_e_nao_conta() -> None:
    catalogo = CatalogoEmMemoria()
    a, b = (catalogo.acrescentar(n, "", []) for n in "AB")
    catalogo.definir_fusao(a.id, _fusao(b))
    catalogo.definir_fusao(b.id, _fusao(a))

    assert pessoas_que_contam(catalogo, [a.id, b.id]) == set()


def test_cadeia_valida_de_qualquer_tamanho_conta() -> None:
    catalogo = CatalogoEmMemoria()
    elos = [catalogo.acrescentar(f"P{i}", "", []) for i in range(13)]  # 12 fusões
    for de, para in pairwise(elos):
        catalogo.definir_fusao(de.id, _fusao(para))

    assert pessoas_que_contam(catalogo, [elos[0].id]) == {elos[0].id}

    catalogo.definir_lixeira(elos[-1].id, ENVIO)
    assert pessoas_que_contam(catalogo, [elos[0].id]) == set()


def test_ciclo_mais_longo_que_o_pedido_nao_trava_nem_conta() -> None:
    catalogo = CatalogoEmMemoria()
    a, b, c, d = (catalogo.acrescentar(n, "", []) for n in "ABCD")
    catalogo.definir_fusao(a.id, _fusao(b))  # A→B→C→D→B
    catalogo.definir_fusao(b.id, _fusao(c))
    catalogo.definir_fusao(c.id, _fusao(d))
    catalogo.definir_fusao(d.id, _fusao(b))

    assert pessoas_que_contam(catalogo, [a.id, b.id, c.id, d.id]) == set()


def test_o_filtro_vale_mesmo_quando_o_criar_app_nao_recebe_o_catalogo() -> None:
    mundo = Mundo()
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("adm", ["administrador"])
    cliente = ClienteSemPeriodoPadrao(
        criar_app(
            VerificadorFalso({"admin": Usuario(uid="adm", email="a@redetv.com")}),
            RepositorioEmMemoria(),
            papeis=papeis,
            tempo_de_tela=ConsultaEmMemoria(mundo.copia),  # sem `catalogo`
        )
    )

    assert _ranking(cliente)["pessoas"] == []  # ninguém existe no catálogo vazio


class CatalogoEspiao:
    """O catálogo de verdade, anotando os ids de cada leitura em lote."""

    def __init__(self, catalogo: Catalogo) -> None:
        self._catalogo = catalogo
        self.leituras: list[list[str]] = []

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        lidos = list(ids)
        self.leituras.append(lidos)
        return self._catalogo.obter_varios(lidos)

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._catalogo, nome)


# --- o relatório -----------------------------------------------------------------------


def _momento(job: str, pessoa: PessoaDoCatalogo, ini: int, fim: int, dia: date) -> Any:
    return LinhaDoMomento(
        job_id=job,
        programa="Jornal",
        data_de_exibicao=dia,
        tipo="aparicao",
        inicio_ms=ini,
        fim_ms=fim,
        pessoas=[PessoaDoMomento(pessoa.id, pessoa.nome)],
    )


DIA = date(2026, 10, 1)


class Mundo:
    """Três pessoas: Ana 5 s em 2 vídeos, Bia 3 s em 1, Cris 1 s em 1."""

    def __init__(self) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.ana, self.bia, self.cris = (
            self.catalogo.acrescentar(n, "", []) for n in ("Ana", "Bia", "Cris")
        )
        self.copia = CopiaEmMemoria()
        self.copia.gravar(
            "j1",
            [
                _momento("j1", self.ana, 0, 4_000, DIA),
                _momento("j1", self.bia, 0, 3_000, DIA),
            ],
        )
        self.copia.gravar(
            "j2",
            [
                _momento("j2", self.ana, 0, 1_000, DIA),
                _momento("j2", self.cris, 0, 1_000, DIA),
            ],
        )

    def instancia(
        self, consulta: ConsultaDeMomentos | None = None, **extras: Any
    ) -> TestClient:
        """Uma instância da API: cache próprio, o mesmo catálogo e a mesma cópia."""
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        app = criar_app(
            VerificadorFalso(
                {
                    "admin": Usuario(
                        uid="adm", email="a@redetv.com", login_em=agora_utc()
                    )
                }
            ),
            extras.pop("repositorio", None) or RepositorioEmMemoria(),
            ArmazenamentoFalso(),
            papeis=papeis,
            catalogo=extras.pop("catalogo", self.catalogo),
            marcas=extras.pop("marcas", CatalogoDeMarcasEmMemoria()),
            tempo_de_tela=consulta
            or ComCache(ConsultaEmMemoria(self.copia), CacheCurto()),
            auditoria=RepositorioDeAuditoriaEmMemoria(),
            **extras,
        )
        return ClienteSemPeriodoPadrao(app)


def _ranking(cliente: TestClient, **params: Any) -> dict[str, Any]:
    resposta = cliente.get(ROTA, params={"limite": 10, **params}, headers=ADMIN)
    assert resposta.status_code == 200
    corpo: dict[str, Any] = resposta.json()
    return corpo


def _nomes(corpo: dict[str, Any]) -> list[str]:
    return [p["nome"] for p in corpo["pessoas"]]


def test_pessoa_na_lixeira_some_e_volta_ao_restaurar_com_o_cache_quente() -> None:
    mundo = Mundo()
    cliente = mundo.instancia()
    assert _nomes(_ranking(cliente)) == ["Ana", "Bia", "Cris"]  # esquenta o cache

    mundo.catalogo.definir_lixeira(mundo.ana.id, ENVIO)
    depois = _ranking(cliente)

    assert _nomes(depois) == ["Bia", "Cris"]
    assert depois["total"] == {
        "pessoas": 2,
        "tempo_de_tela_ms": 4_000,
        "videos": 2,
        "aparicoes": 2,
        "mencoes_na_fala": 0,
        "mencoes_no_texto": 0,
    }
    csv_ = cliente.get(ROTA, params={"formato": "csv"}, headers=ADMIN).text
    assert "Ana" not in csv_
    completo = cliente.get(ROTA, headers=ADMIN).json()
    assert [p["nome"] for p in completo["pessoas"]] == ["Bia", "Cris"]
    videos = cliente.get(
        f"{ROTA}/videos", params={"pessoa_id": mundo.ana.id}, headers=ADMIN
    ).json()
    assert videos == []

    mundo.catalogo.definir_lixeira(mundo.ana.id, None)
    de_volta = _ranking(cliente)
    assert _nomes(de_volta) == ["Ana", "Bia", "Cris"]
    assert de_volta["pessoas"][0]["tempo_de_tela_ms"] == 5_000
    assert de_volta["pessoas"][0]["videos"] == 2  # todos os vídeos dela voltam
    assert (
        len(
            cliente.get(
                f"{ROTA}/videos", params={"pessoa_id": mundo.ana.id}, headers=ADMIN
            ).json()
        )
        == 2
    )


def test_totais_e_posicoes_saem_depois_da_exclusao_e_a_paginacao_a_acompanha() -> None:
    mundo = Mundo()
    cliente = mundo.instancia()
    _ranking(cliente)
    mundo.catalogo.definir_lixeira(mundo.ana.id, ENVIO)  # a primeira do ranking

    primeira = cliente.get(ROTA, params={"limite": 1}, headers=ADMIN)
    segunda = cliente.get(
        ROTA,
        params={"limite": 1, "cursor": primeira.headers["X-Proximo-Cursor"]},
        headers=ADMIN,
    )

    assert [p["nome"] for p in primeira.json()["pessoas"]] == ["Bia"]
    assert [p["nome"] for p in segunda.json()["pessoas"]] == ["Cris"]
    assert "X-Proximo-Cursor" not in segunda.headers
    assert primeira.json()["total"]["pessoas"] == 2
    assert primeira.json()["total"]["tempo_de_tela_ms"] == 4_000


def test_duas_instancias_com_caches_proprios_enxergam_a_mudanca_na_hora() -> None:
    mundo = Mundo()
    uma, outra = mundo.instancia(), mundo.instancia()
    assert _nomes(_ranking(uma)) == _nomes(_ranking(outra))

    mundo.catalogo.definir_lixeira(mundo.bia.id, ENVIO)

    assert _nomes(_ranking(uma)) == ["Ana", "Cris"]
    assert _nomes(_ranking(outra)) == ["Ana", "Cris"]


def test_purgada_some_e_a_nova_com_o_mesmo_nome_conta_so_nos_videos_do_id_novo() -> (
    None
):
    mundo = Mundo()
    cliente = mundo.instancia()
    _ranking(cliente)
    mundo.catalogo.apagar(mundo.ana.id)
    nova = mundo.catalogo.acrescentar("Ana", "", [])
    assert _nomes(_ranking(cliente)) == ["Bia", "Cris"]

    mundo.copia.gravar("j3", [_momento("j3", nova, 0, 2_000, DIA)])

    depois = _ranking(mundo.instancia())
    por_nome = {p["nome"]: p for p in depois["pessoas"]}
    assert por_nome["Ana"]["pessoa_id"] == nova.id
    assert (por_nome["Ana"]["tempo_de_tela_ms"], por_nome["Ana"]["videos"]) == (
        2_000,
        1,
    )


def test_fundida_conta_enquanto_o_destino_conta_e_aparece_como_ela_mesma() -> None:
    mundo = Mundo()
    b, c = mundo.bia, mundo.cris
    mundo.catalogo.definir_fusao(mundo.ana.id, _fusao(b))
    mundo.catalogo.definir_fusao(b.id, _fusao(c))
    cliente = mundo.instancia()

    antes = _ranking(cliente)
    assert {p["pessoa_id"] for p in antes["pessoas"]} == {mundo.ana.id, b.id, c.id}
    assert antes["total"]["pessoas"] == 3  # sem juntar a origem ao destino

    mundo.catalogo.definir_lixeira(c.id, ENVIO)
    assert _ranking(cliente)["pessoas"] == []

    mundo.catalogo.definir_lixeira(c.id, None)
    assert len(_ranking(cliente)["pessoas"]) == 3

    mundo.catalogo.apagar(c.id)
    assert _ranking(cliente)["pessoas"] == []


def test_a_leitura_em_lote_do_catalogo_recebe_cada_id_do_periodo_uma_vez() -> None:
    mundo = Mundo()
    for i in range(40):  # 40 pessoas em vídeos de dias diferentes
        pessoa = mundo.catalogo.acrescentar(f"P{i}", "", [])
        dia = date(2026, 9, 1) + timedelta(days=i)
        mundo.copia.gravar(f"x{i}", [_momento(f"x{i}", pessoa, 0, 1_000, dia)])
    espiao = CatalogoEspiao(mundo.catalogo)
    cliente = mundo.instancia(catalogo=espiao)

    def ids_da_regra(**periodo: str) -> int:
        espiao.leituras.clear()
        assert (
            cliente.get(
                ROTA, params={"limite": 5, **periodo}, headers=ADMIN
            ).status_code
            == 200
        )
        regra = espiao.leituras[0]  # a regra lê antes dos nomes da página
        assert len(regra) == len(set(regra))
        return len(regra)

    assert ids_da_regra(desde="2026-09-01", ate="2026-09-10") == 10
    assert ids_da_regra() == 43  # o pior período testado: tudo, as 3 de antes e as 40


# --- a consulta real do BigQuery e o que o Curador faz ----------------------------------


def _linhas_do_bq(mundo: Mundo) -> dict[str, Any]:
    return {
        "jobComplete": True,
        "rows": [
            _linha_do_bq(
                "j1", mundo.ana.id, "4000", "1", "0", "0", '[{"nome":"Ana","linhas":1}]'
            ),
            _linha_do_bq(
                "j2", mundo.ana.id, "1000", "1", "0", "0", '[{"nome":"Ana","linhas":1}]'
            ),
            _linha_do_bq(
                "j1", mundo.bia.id, "3000", "1", "0", "0", '[{"nome":"Bia","linhas":1}]'
            ),
        ],
    }


def test_com_a_consulta_real_o_curador_envia_restaura_e_purga_sem_escrever_no_bigquery() -> (
    None
):
    mundo = Mundo()
    transporte = Transporte(_linhas_do_bq(mundo))
    versao = VersaoDaLixeiraEmMemoria()
    cliente = mundo.instancia(
        ComCache(ConsultaBigQuery(CONFIG, transporte), CacheCurto()),
        versao_da_lixeira=versao,
    )
    assert _nomes(_ranking(cliente)) == ["Ana", "Bia"]

    enviada = cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}", json={"motivo": "duplicada"}, headers=ADMIN
    )
    assert enviada.status_code == 201
    assert _nomes(_ranking(cliente)) == ["Bia"]

    restaurada = cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/restaurar", headers=ADMIN
    )
    assert restaurada.status_code == 200
    assert _nomes(_ranking(cliente)) == ["Ana", "Bia"]

    cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}", json={"motivo": "duplicada"}, headers=ADMIN
    )
    purgada = cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.ana.id}/purgar", json={"nome": "Ana"}, headers=ADMIN
    )
    assert purgada.status_code == 200
    assert _nomes(_ranking(cliente)) == ["Bia"]

    assert len(transporte.corpos) == 1  # o cache guardou a soma sem exclusão
    escritas = ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP")
    for corpo in transporte.corpos:
        assert not any(w in corpo["query"].upper().split() for w in escritas)
    assert (
        versao.atual() == 10
    )  # envio 3 (inclui antes das fotos), restaurar 2, envio 3, purga 2


# --- a versão do estado da lixeira ------------------------------------------------------


def test_a_versao_avanca_a_cada_envio_restauracao_purga_e_fusao_e_nunca_repete() -> (
    None
):
    mundo = Mundo()
    versao = VersaoDaLixeiraEmMemoria()
    cliente = mundo.instancia(versao_da_lixeira=versao)
    vistas = [versao.atual()]

    def passo(resposta: Any) -> None:
        assert resposta.status_code in (200, 201), resposta.text
        vistas.append(versao.atual())

    pessoa = f"{LIXEIRA}/pessoas/{mundo.cris.id}"
    passo(cliente.post(pessoa, json={"motivo": "x"}, headers=ADMIN))
    passo(cliente.post(f"{pessoa}/restaurar", headers=ADMIN))
    passo(cliente.post(pessoa, json={"motivo": "x"}, headers=ADMIN))
    passo(cliente.post(f"{pessoa}/purgar", json={"nome": "Cris"}, headers=ADMIN))
    passo(
        cliente.post(
            f"/v1/catalogo/pessoas/{mundo.bia.id}/fundir",
            json={"destino_id": mundo.ana.id, "motivo": "duplicada"},
            headers=ADMIN,
        )
    )
    marca = mundo.catalogo.acrescentar("Dani", "", [])
    mundo.catalogo.definir_lixeira(
        marca.id, ENVIO.model_copy(update={"em": agora_utc() - timedelta(days=31)})
    )
    purgas = purgar_catalogo_vencido(
        mundo.catalogo,
        CatalogoDeMarcasEmMemoria(),
        RepositorioDeAuditoriaEmMemoria(),
        agora_utc(),
        PurgasDeMarcaEmMemoria(),
        versao.avancar,
    )
    assert purgas == 1  # a purga automática
    vistas.append(versao.atual())

    assert vistas == sorted(set(vistas)) and len(vistas) == 7  # sempre para cima


# --- o marcador: dublê e adapter Firestore, o mesmo contrato ----------------------------

sem_emulador = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="sem emulador do Firestore"
)


def _cliente_do_firestore() -> firestore.Client:
    return firestore.Client(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
    )


@pytest.fixture(
    params=["memoria", pytest.param("firestore", marks=sem_emulador)],
)
def versao(request: pytest.FixtureRequest) -> VersaoDaLixeira:
    if request.param == "memoria":
        return VersaoDaLixeiraEmMemoria()
    return VersaoDaLixeiraFirestore(
        _cliente_do_firestore(), colecao=f"estado-da-lixeira-{uuid.uuid4().hex}"
    )


def test_contrato_comeca_em_zero_e_so_cresce(versao: VersaoDaLixeira) -> None:
    assert versao.atual() == 0
    valores = []
    for _ in range(3):
        versao.avancar()
        valores.append(versao.atual())

    assert valores == [1, 2, 3]
    assert versao.atual() == 3  # ler não muda


@sem_emulador
def test_firestore_duas_instancias_enxergam_o_mesmo_marcador() -> None:
    colecao = f"estado-da-lixeira-{uuid.uuid4().hex}"
    uma = VersaoDaLixeiraFirestore(_cliente_do_firestore(), colecao=colecao)
    outra = VersaoDaLixeiraFirestore(_cliente_do_firestore(), colecao=colecao)

    uma.avancar()
    outra.avancar()

    assert uma.atual() == outra.atual() == 2


# --- a versão não se perde quando o avanço falha (#591) ---------------------------------


class VersaoQueFalha(VersaoDaLixeiraEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.falha = False
        self.vistos: list[bool] = []
        self.observar: Any = lambda: False

    def avancar(self) -> None:
        if self.falha:
            raise RuntimeError("Firestore fora")
        self.vistos.append(self.observar())
        super().avancar()


def test_a_purga_automatica_nao_apaga_se_o_avanco_da_versao_falha_e_tenta_de_novo() -> (
    None
):
    mundo = Mundo()
    mundo.catalogo.definir_lixeira(
        mundo.cris.id, ENVIO.model_copy(update={"em": agora_utc() - timedelta(days=31)})
    )
    versao = VersaoQueFalha()
    versao.falha = True

    def varrer() -> int:
        return purgar_catalogo_vencido(
            mundo.catalogo,
            CatalogoDeMarcasEmMemoria(),
            RepositorioDeAuditoriaEmMemoria(),
            agora_utc(),
            PurgasDeMarcaEmMemoria(),
            versao.avancar,
        )

    assert varrer() == 0
    assert mundo.catalogo.obter(mundo.cris.id) is not None  # nada mudou

    versao.falha = False
    assert varrer() == 1
    assert mundo.catalogo.obter(mundo.cris.id) is None
    assert versao.atual() == 2  # antes e depois da mudança


def test_a_versao_avanca_antes_e_depois_da_mudanca_no_catalogo() -> None:
    mundo = Mundo()
    versao = VersaoQueFalha()
    versao.observar = lambda: mundo.catalogo.obter(mundo.cris.id).lixeira is not None  # type: ignore[union-attr]
    cliente = mundo.instancia(versao_da_lixeira=versao)

    cliente.post(
        f"{LIXEIRA}/pessoas/{mundo.cris.id}", json={"motivo": "x"}, headers=ADMIN
    )

    assert versao.vistos == [
        False,
        False,
        True,
    ]  # antes das fotos, antes da mudança, depois


@pytest.mark.parametrize("acao", ["enviar", "restaurar", "purgar", "fundir"])
def test_se_o_avanco_falha_a_acao_do_curador_nao_muda_o_catalogo(acao: str) -> None:
    mundo = Mundo()
    versao = VersaoQueFalha()
    cliente = mundo.instancia(versao_da_lixeira=versao)
    pessoa = f"{LIXEIRA}/pessoas/{mundo.cris.id}"
    if acao in ("restaurar", "purgar"):
        mundo.catalogo.definir_lixeira(mundo.cris.id, ENVIO)
    versao.falha = True

    with pytest.raises(RuntimeError):
        if acao == "enviar":
            cliente.post(pessoa, json={"motivo": "x"}, headers=ADMIN)
        elif acao == "restaurar":
            cliente.post(f"{pessoa}/restaurar", headers=ADMIN)
        elif acao == "purgar":
            cliente.post(f"{pessoa}/purgar", json={"nome": "Cris"}, headers=ADMIN)
        else:
            cliente.post(
                f"/v1/catalogo/pessoas/{mundo.cris.id}/fundir",
                json={"destino_id": mundo.ana.id, "motivo": "x"},
                headers=ADMIN,
            )

    cris = mundo.catalogo.obter(mundo.cris.id)
    assert cris is not None
    assert (cris.lixeira is not None) == (acao in ("restaurar", "purgar"))
    assert cris.fundida is None


def test_se_o_avanco_falha_a_marca_nao_vai_para_a_lixeira() -> None:
    mundo = Mundo()
    marcas = CatalogoDeMarcasEmMemoria()
    marca = marcas.acrescentar("Acme", [])
    versao = VersaoQueFalha()
    cliente = mundo.instancia(versao_da_lixeira=versao, marcas=marcas)
    versao.falha = True

    with pytest.raises(RuntimeError):
        cliente.post(
            f"{LIXEIRA}/marcas/{marca.id}", json={"motivo": "x"}, headers=ADMIN
        )

    assert marcas.obter(marca.id).lixeira is None  # type: ignore[union-attr]


# --- a marca na lixeira sai do relatório de marcas (#593) --------------------------------

ROTA_DAS_MARCAS = "/v1/relatorios/marcas"
TODAS_AS_MARCAS = ["AB INBEV", "Ambev", "NESTLE", "Natura"]


class MundoDasMarcas:
    """Marcas na cópia: Ambev (apelido "AB InBev") 2 inserções em 2 vídeos, Nestlé e Natura
    1 cada, no vídeo j1. A cópia traz a grafia de cada uma sem acento e em maiúsculas."""

    def __init__(self) -> None:
        self.mundo = Mundo()
        self.marcas = CatalogoDeMarcasEmMemoria()
        self.ambev = self.marcas.acrescentar("Ambev", ["AB InBev"])
        self.nestle = self.marcas.acrescentar("Nestlé", [])
        self.natura = self.marcas.acrescentar("Natura", [])
        self.copia = CopiaEmMemoria()
        self.copia.gravar(
            "j1",
            [
                _comercial("j1", "Jornal", DIA, "AB INBEV", "intervalo"),
                _comercial("j1", "Jornal", DIA, "NESTLE", "intervalo"),
                _comercial("j1", "Jornal", DIA, "Natura", "intervalo"),
            ],
        )
        self.copia.gravar(
            "j2", [_comercial("j2", "Jornal", DIA, "Ambev", "merchan_apresentador")]
        )

    def instancia(self, consulta: Any = None, **extras: Any) -> TestClient:
        return self.mundo.instancia(
            marcas=self.marcas,
            relatorio_de_marcas=consulta
            or MarcasComCache(MarcasEmMemoria(self.copia), CacheCurto()),
            **extras,
        )


def _marcas(cliente: TestClient, **params: Any) -> dict[str, Any]:
    resposta = cliente.get(
        ROTA_DAS_MARCAS, params={"limite": 10, **params}, headers=ADMIN
    )
    assert resposta.status_code == 200
    corpo: dict[str, Any] = resposta.json()
    return corpo


def _nomes_das_marcas(corpo: dict[str, Any]) -> list[str]:
    return [m["marca"] for m in corpo["marcas"]]


def test_marca_na_lixeira_some_pelo_nome_e_pelo_apelido_e_volta_com_o_cache_quente() -> (
    None
):
    m = MundoDasMarcas()
    cliente = m.instancia()
    assert _nomes_das_marcas(_marcas(cliente)) == TODAS_AS_MARCAS  # esquenta o cache

    m.marcas.definir_lixeira(m.ambev.id, ENVIO)
    depois = _marcas(cliente)

    assert _nomes_das_marcas(depois) == ["NESTLE", "Natura"]  # apelido e maiúscula
    assert depois["total"] == {
        "marcas": 2,
        "insercoes": 2,
        "tempo_ms": 2_000,
        "videos": 1,
    }
    completo = cliente.get(ROTA_DAS_MARCAS, headers=ADMIN).json()
    assert [x["marca"] for x in completo["marcas"]] == ["NESTLE", "Natura"]
    csv_ = cliente.get(ROTA_DAS_MARCAS, params={"formato": "csv"}, headers=ADMIN).text
    assert "Ambev" not in csv_ and "INBEV" not in csv_ and "NESTLE" in csv_
    lista = cliente.get(
        f"{ROTA_DAS_MARCAS}/insercoes", params={"marca": "Ambev"}, headers=ADMIN
    )
    assert lista.json() == []

    m.marcas.definir_lixeira(m.ambev.id, None)
    de_volta = _marcas(cliente)
    assert _nomes_das_marcas(de_volta) == TODAS_AS_MARCAS
    assert de_volta["total"]["insercoes"] == 4
    lista = cliente.get(
        f"{ROTA_DAS_MARCAS}/insercoes", params={"marca": "Ambev"}, headers=ADMIN
    )
    assert len(lista.json()) == 1


def test_nome_com_acento_na_lixeira_tira_a_grafia_sem_acento() -> None:
    m = MundoDasMarcas()
    cliente = m.instancia()
    _marcas(cliente)

    m.marcas.definir_lixeira(m.nestle.id, ENVIO)

    assert "NESTLE" not in _nomes_das_marcas(_marcas(cliente))


def test_totais_posicoes_e_paginacao_das_marcas_saem_depois_da_exclusao() -> None:
    m = MundoDasMarcas()
    cliente = m.instancia()
    _marcas(cliente)
    m.marcas.definir_lixeira(m.ambev.id, ENVIO)  # as duas primeiras do ranking

    primeira = cliente.get(ROTA_DAS_MARCAS, params={"limite": 1}, headers=ADMIN)
    segunda = cliente.get(
        ROTA_DAS_MARCAS,
        params={"limite": 1, "cursor": primeira.headers["X-Proximo-Cursor"]},
        headers=ADMIN,
    )

    assert _nomes_das_marcas(primeira.json()) == ["NESTLE"]
    assert _nomes_das_marcas(segunda.json()) == ["Natura"]
    # A posição numérica (o cursor é a posição em base64) conta só as marcas que ficaram:
    # com a Ambev e o apelido dela fora, a próxima página começa na posição 1, não na 3.
    assert posicao_do_cursor(primeira.headers["X-Proximo-Cursor"]) == 1
    ate_o_fim = cliente.get(ROTA_DAS_MARCAS, params={"limite": 2}, headers=ADMIN)
    assert "X-Proximo-Cursor" not in ate_o_fim.headers  # só duas posições existem
    assert "X-Proximo-Cursor" not in segunda.headers
    assert primeira.json()["total"]["marcas"] == 2


def test_video_novo_com_a_marca_na_lixeira_nao_a_faz_contar() -> None:
    m = MundoDasMarcas()
    cliente = m.instancia()
    m.marcas.definir_lixeira(m.ambev.id, ENVIO)
    _marcas(cliente)

    m.copia.gravar("j3", [_comercial("j3", "Jornal", DIA, "Ambev", "intervalo")])

    assert _nomes_das_marcas(_marcas(m.instancia())) == ["NESTLE", "Natura"]
    assert _nomes_das_marcas(_marcas(cliente)) == ["NESTLE", "Natura"]


def test_marca_purgada_deixa_de_estar_na_lixeira_e_volta_a_contar() -> None:
    m = MundoDasMarcas()
    cliente = m.instancia()
    m.marcas.definir_lixeira(m.nestle.id, ENVIO)
    assert "NESTLE" not in _nomes_das_marcas(_marcas(cliente))

    m.marcas.apagar(m.nestle.id)

    assert "NESTLE" in _nomes_das_marcas(_marcas(cliente))


def test_o_filtro_das_marcas_vale_com_duas_instancias_e_sem_o_cache() -> None:
    m = MundoDasMarcas()
    uma, outra = m.instancia(), m.instancia()
    _marcas(uma), _marcas(outra)

    m.marcas.definir_lixeira(m.natura.id, ENVIO)

    assert "Natura" not in _nomes_das_marcas(_marcas(uma))
    assert "Natura" not in _nomes_das_marcas(_marcas(outra))
    assert "Natura" not in _nomes_das_marcas(
        _marcas(m.instancia(MarcasEmMemoria(m.copia)))
    )


def _somas_do_bq() -> dict[str, Any]:
    def linha(marca: str, job: str) -> dict[str, Any]:
        intervalos = '[{"inicio_ms":0,"fim_ms":1000}]'
        valores = (marca, "intervalo", job, "1", "1000", intervalos)
        return {"f": [{"v": v} for v in valores]}

    return {
        "jobComplete": True,
        "rows": [linha("AB INBEV", "j1"), linha("Ambev", "j2"), linha("NESTLE", "j1")],
    }


def test_com_a_consulta_real_o_curador_envia_restaura_e_purga_a_marca_sem_escrever_no_bigquery() -> (
    None
):
    m = MundoDasMarcas()
    transporte = TransporteDasMarcas(_somas_do_bq())
    versao = VersaoDaLixeiraEmMemoria()
    cliente = m.instancia(
        MarcasComCache(MarcasBigQuery(CONFIG_DAS_MARCAS, transporte), CacheCurto()),
        versao_da_lixeira=versao,
    )
    todas = ["AB INBEV", "Ambev", "NESTLE"]
    assert _nomes_das_marcas(_marcas(cliente)) == todas
    inicial = versao.atual()

    enviada = cliente.post(
        f"{LIXEIRA}/marcas/{m.ambev.id}", json={"motivo": "teste"}, headers=ADMIN
    )
    assert enviada.status_code == 201
    depois_do_envio = versao.atual()
    assert depois_do_envio > inicial  # enviar troca a versão
    enviado = _marcas(cliente)
    assert _nomes_das_marcas(enviado) == ["NESTLE"]
    assert enviado["total"]["insercoes"] == 1

    restaurada = cliente.post(f"{LIXEIRA}/marcas/{m.ambev.id}/restaurar", headers=ADMIN)
    assert restaurada.status_code == 200
    assert versao.atual() > depois_do_envio  # restaurar também
    assert _nomes_das_marcas(_marcas(cliente)) == todas

    cliente.post(f"{LIXEIRA}/marcas/{m.ambev.id}", json={"motivo": "x"}, headers=ADMIN)
    purgada = cliente.post(
        f"{LIXEIRA}/marcas/{m.ambev.id}/purgar", json={"nome": "Ambev"}, headers=ADMIN
    )
    assert purgada.status_code == 200
    # Purgada, não está mais na lixeira; os Jobs não existem aqui, então contam como
    # anteriores à purga (#595) e as ocorrências da Ambev e do apelido seguem fora.
    assert _nomes_das_marcas(_marcas(cliente)) == ["NESTLE"]

    assert len(transporte.corpos) == 1  # o cache guardou a soma sem exclusão
    escritas = ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP")
    for corpo in transporte.corpos:
        assert not any(w in corpo["query"].upper().split() for w in escritas)


# --- a purga da marca deixa registro e corta pela criação do Job no relatório (#595) -----

CORTE = datetime(2026, 10, 10, tzinfo=UTC)
ANTES, DEPOIS = CORTE - timedelta(days=1), CORTE + timedelta(days=1)


@pytest.fixture(
    params=["memoria", pytest.param("firestore", marks=sem_emulador)],
)
def purgas(request: pytest.FixtureRequest) -> PurgasDeMarca:
    if request.param == "memoria":
        return PurgasDeMarcaEmMemoria()
    return PurgasDeMarcaFirestore(
        _cliente_do_firestore(), colecao=f"purgas-de-marca-{uuid.uuid4().hex}"
    )


def test_registro_da_purga_guarda_nome_apelidos_e_data(purgas: PurgasDeMarca) -> None:
    assert purgas.todas() == []
    ambev = CatalogoDeMarcasEmMemoria().acrescentar("Ambev", ["AB InBev"])

    purgas.gravar(ambev, CORTE)

    (registro,) = purgas.todas()
    assert (registro.nome, registro.apelidos, registro.em) == (
        "Ambev",
        ["AB InBev"],
        CORTE,
    )
    assert registro.marca_id == ambev.id
    assert registro.nomes == ["ab inbev", "ambev"]  # o texto que o relatório compara


@sem_emulador
def test_firestore_outra_instancia_le_o_registro_gravado() -> None:
    colecao = f"purgas-de-marca-{uuid.uuid4().hex}"
    uma = PurgasDeMarcaFirestore(_cliente_do_firestore(), colecao=colecao)
    outra = PurgasDeMarcaFirestore(_cliente_do_firestore(), colecao=colecao)

    uma.gravar(CatalogoDeMarcasEmMemoria().acrescentar("Natura", []), CORTE)

    assert [r.nome for r in outra.todas()] == ["Natura"]


class JobsEspiao(RepositorioEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lotes: list[list[str]] = []
        self.falha = False
        self.erro: Exception = RuntimeError("Firestore fora")

    def obter_varios(self, job_ids: Any) -> Any:
        if self.falha:
            raise self.erro
        self.lotes.append(list(job_ids))
        return super().obter_varios(self.lotes[-1])


def _job_criado_em(id: str, quando: datetime) -> Any:
    return _job(id, criado_em=quando, atualizado_em=quando)


class MundoDaPurga(MundoDasMarcas):
    """O de `MundoDasMarcas`, com o Job de j1 criado antes do corte e o de j2 depois, e
    a purga da Ambev (apelido "AB InBev") registrada em `CORTE`."""

    def __init__(self) -> None:
        super().__init__()
        self.jobs = JobsEspiao()
        self.purgas: PurgasDeMarca = PurgasDeMarcaEmMemoria()
        self.jobs.salvar(_job_criado_em("j1", ANTES))
        self.jobs.salvar(_job_criado_em("j2", DEPOIS))
        self.purgas.gravar(self.ambev, CORTE)
        self.marcas.apagar(self.ambev.id)

    def instancia(self, consulta: Any = None, **extras: Any) -> TestClient:
        extras.setdefault("repositorio", self.jobs)
        extras.setdefault("purgas_de_marca", self.purgas)
        return super().instancia(consulta, **extras)


def test_marca_purgada_nao_conta_no_job_criado_antes_e_conta_no_criado_depois() -> None:
    corpo = _marcas(MundoDaPurga().instancia())

    # j1 (antes): "AB INBEV" fora; j2 (depois): "Ambev" fica. As outras não mudam.
    assert _nomes_das_marcas(corpo) == ["Ambev", "NESTLE", "Natura"]
    assert corpo["total"]["insercoes"] == 3


def test_lista_de_insercoes_da_marca_purgada_tambem_respeita_o_corte() -> None:
    cliente = MundoDaPurga().instancia()

    resposta = cliente.get(
        "/v1/relatorios/marcas/insercoes", params={"marca": "AB INBEV"}, headers=ADMIN
    )

    assert resposta.status_code == 200
    assert resposta.json() == []


def test_recopiar_o_video_antigo_nao_ressuscita_a_marca() -> None:
    m = MundoDaPurga()
    # A recópia grava de novo as linhas de j1 (a data do BigQuery muda, o Job não).
    m.copia.gravar("j1", [_comercial("j1", "Jornal", DIA, "AB INBEV", "intervalo")])

    assert "AB INBEV" not in _nomes_das_marcas(_marcas(m.instancia()))


def test_marca_recriada_no_catalogo_conta_so_nos_videos_novos() -> None:
    m = MundoDaPurga()
    m.marcas.acrescentar("Ambev", [])  # a carga recria depois da purga
    m.jobs.salvar(_job_criado_em("j3", DEPOIS))
    m.copia.gravar("j3", [_comercial("j3", "Jornal", DIA, "Ambev", "intervalo")])

    corpo = _marcas(m.instancia())

    por_marca = {x["marca"]: x["insercoes"] for x in corpo["marcas"]}
    assert por_marca["Ambev"] == 2  # j2 e j3
    assert "AB INBEV" not in por_marca  # j1 é anterior


def test_job_ausente_conta_como_anterior_a_purga() -> None:
    m = MundoDaPurga()
    m.jobs._jobs.pop("j2")

    assert "Ambev" not in _nomes_das_marcas(_marcas(m.instancia()))


def test_job_criado_no_instante_da_purga_conta_como_anterior() -> None:
    m = MundoDaPurga()
    m.jobs.salvar(_job_criado_em("j2", CORTE))

    assert "Ambev" not in _nomes_das_marcas(_marcas(m.instancia()))


def test_o_relatorio_le_em_lote_so_os_jobs_da_marca_purgada_sem_repetir_id() -> None:
    m = MundoDaPurga()
    m.copia.gravar(
        "j1",
        [
            _comercial("j1", "Jornal", DIA, "AB INBEV", "intervalo"),
            _comercial("j1", "Jornal", DIA, "AB INBEV", "merchan_apresentador"),
            _comercial("j1", "Jornal", DIA, "NESTLE", "intervalo"),
        ],
    )

    _marcas(m.instancia())

    assert len(m.jobs.lotes) == 1
    assert sorted(m.jobs.lotes[0]) == ["j1", "j2"]  # só as somas de Ambev e AB InBev


def test_sem_registro_de_purga_o_relatorio_nao_le_job_nenhum() -> None:
    m = MundoDasMarcas()
    jobs = JobsEspiao()

    _marcas(m.instancia(repositorio=jobs, purgas_de_marca=PurgasDeMarcaEmMemoria()))

    assert jobs.lotes == []


def test_falha_na_leitura_do_job_vira_503_nao_job_ausente() -> None:
    m = MundoDaPurga()
    cliente = m.instancia()
    m.jobs.falha = True

    resposta = cliente.get(ROTA_DAS_MARCAS, params={"limite": 10}, headers=ADMIN)

    assert resposta.status_code == 503


class PurgasQueFalham(PurgasDeMarcaEmMemoria):
    falha = False

    def gravar(self, marca: Any, em: datetime) -> None:
        if self.falha:
            raise RuntimeError("Firestore fora")
        super().gravar(marca, em)


def test_purga_manual_grava_o_registro_antes_de_apagar_e_troca_a_versao() -> None:
    m = MundoDasMarcas()
    purgas = PurgasQueFalham()
    versao = VersaoDaLixeiraEmMemoria()
    cliente = m.instancia(purgas_de_marca=purgas, versao_da_lixeira=versao)
    m.marcas.definir_lixeira(m.nestle.id, ENVIO)
    antes = versao.atual()

    resposta = cliente.post(
        f"{LIXEIRA}/marcas/{m.nestle.id}/purgar", json={"nome": "Nestlé"}, headers=ADMIN
    )

    assert resposta.status_code == 200
    (registro,) = purgas.todas()
    assert registro.nome == "Nestlé"
    assert versao.atual() > antes


def test_purga_manual_nao_apaga_a_marca_se_o_registro_falha() -> None:
    m = MundoDasMarcas()
    purgas = PurgasQueFalham()
    cliente = m.instancia(purgas_de_marca=purgas)
    m.marcas.definir_lixeira(m.nestle.id, ENVIO)
    purgas.falha = True

    with pytest.raises(RuntimeError):
        cliente.post(
            f"{LIXEIRA}/marcas/{m.nestle.id}/purgar",
            json={"nome": "Nestlé"},
            headers=ADMIN,
        )

    assert m.marcas.obter(m.nestle.id) is not None


def test_purga_automatica_grava_o_registro_e_se_falha_a_marca_fica_para_amanha() -> (
    None
):
    marcas = CatalogoDeMarcasEmMemoria()
    acme = marcas.acrescentar("Acme", ["Acme SA"])
    marcas.definir_lixeira(
        acme.id, ENVIO.model_copy(update={"em": agora_utc() - timedelta(days=31)})
    )
    purgas = PurgasQueFalham()
    versao = VersaoDaLixeiraEmMemoria()

    def varrer() -> int:
        return purgar_catalogo_vencido(
            CatalogoEmMemoria(),
            marcas,
            RepositorioDeAuditoriaEmMemoria(),
            agora_utc(),
            purgas,
            versao.avancar,
        )

    purgas.falha = True
    assert varrer() == 0
    assert marcas.obter(acme.id) is not None  # a gravação falhou: não apagou

    purgas.falha = False
    assert varrer() == 1
    assert marcas.obter(acme.id) is None
    (registro,) = purgas.todas()
    assert registro.apelidos == ["Acme SA"]


@sem_emulador
def test_com_a_consulta_real_e_o_registro_no_firestore_o_corte_vale_no_ranking() -> (
    None
):
    m = MundoDaPurga()
    purgas = PurgasDeMarcaFirestore(
        _cliente_do_firestore(), colecao=f"purgas-de-marca-{uuid.uuid4().hex}"
    )
    purgas.gravar(m.ambev, CORTE)
    consulta = MarcasComCache(
        MarcasBigQuery(CONFIG_DAS_MARCAS, TransporteDasMarcas(_somas_do_bq())),
        CacheCurto(),
    )

    cliente = m.instancia(consulta, purgas_de_marca=purgas)

    assert _nomes_das_marcas(_marcas(cliente)) == ["Ambev", "NESTLE"]


def test_falha_real_do_firestore_na_leitura_do_job_vira_503() -> None:
    m = MundoDaPurga()
    cliente = m.instancia()
    m.jobs.falha = True
    m.jobs.erro = ServiceUnavailable("Firestore fora")

    resposta = cliente.get(ROTA_DAS_MARCAS, params={"limite": 10}, headers=ADMIN)

    assert resposta.status_code == 503


class PurgasQueLeemMal(PurgasDeMarcaEmMemoria):
    def todas(self) -> Any:
        raise ServiceUnavailable("Firestore fora")


def test_falha_real_do_firestore_na_leitura_dos_registros_vira_503() -> None:
    m = MundoDasMarcas()
    cliente = m.instancia(purgas_de_marca=PurgasQueLeemMal())

    resposta = cliente.get(ROTA_DAS_MARCAS, params={"limite": 10}, headers=ADMIN)

    assert resposta.status_code == 503


class MarcasQueLeemMal(CatalogoDeMarcasEmMemoria):
    falha = False

    def obter_varios(self, ids: Any) -> Any:
        if self.falha:
            raise ServiceUnavailable("Firestore fora")
        return super().obter_varios(ids)


def test_falha_real_do_firestore_na_leitura_do_catalogo_dos_registros_vira_503() -> (
    None
):
    m = MundoDaPurga()
    marcas = MarcasQueLeemMal()
    m.marcas = marcas
    cliente = m.instancia()
    marcas.falha = True

    resposta = cliente.get(ROTA_DAS_MARCAS, params={"limite": 10}, headers=ADMIN)

    assert resposta.status_code == 503


class MarcasQueNaoApagam(CatalogoDeMarcasEmMemoria):
    def apagar(self, id: str) -> None:
        raise RuntimeError("Firestore fora")


def test_registro_orfao_nao_corta_a_marca_restaurada_depois_de_apagar_falhar() -> None:
    m = MundoDasMarcas()
    m.marcas = MarcasQueNaoApagam()
    ambev = m.marcas.acrescentar("Ambev", ["AB InBev"])
    jobs = JobsEspiao()
    jobs.salvar(_job_criado_em("j1", ANTES))
    jobs.salvar(_job_criado_em("j2", ANTES))
    purgas = PurgasDeMarcaEmMemoria()
    cliente = m.instancia(repositorio=jobs, purgas_de_marca=purgas)
    cliente.post(f"{LIXEIRA}/marcas/{ambev.id}", json={"motivo": "x"}, headers=ADMIN)

    with pytest.raises(RuntimeError):  # o registro foi gravado, o apagar falhou
        cliente.post(
            f"{LIXEIRA}/marcas/{ambev.id}/purgar", json={"nome": "Ambev"}, headers=ADMIN
        )
    assert len(purgas.todas()) == 1
    cliente.post(f"{LIXEIRA}/marcas/{ambev.id}/restaurar", headers=ADMIN)

    assert "Ambev" in _nomes_das_marcas(_marcas(cliente))
    assert "AB INBEV" in _nomes_das_marcas(_marcas(cliente))


def test_registro_sem_id_de_marca_continua_valendo() -> None:
    m = MundoDaPurga()
    antigo = PurgasDeMarcaEmMemoria()
    antigo._purgas.append(  # um registro gravado antes de existir o id
        PurgaDeMarca(nome="Ambev", apelidos=[], nomes=["ambev", "ab inbev"], em=CORTE)
    )
    m.marcas.acrescentar("Ambev", ["AB InBev"])  # existe uma marca de mesmo nome

    cliente = m.instancia(purgas_de_marca=antigo)

    assert "AB INBEV" not in _nomes_das_marcas(_marcas(cliente))
