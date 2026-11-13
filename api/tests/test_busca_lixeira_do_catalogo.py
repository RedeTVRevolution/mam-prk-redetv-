"""A lixeira do catálogo vale na busca (#583, #592): a pessoa na lixeira ou purgada sai como
aparição, dona de objeto, faceta e filtro da tela; o texto que a cita continua achado.

Cada cenário roda com o dublê em memória do índice e com o adapter real (`AgentRetrieval`),
este sobre um servidor de índice simulado que entende o filtro JSON do `batchSearch`.
"""

import json
import zlib
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.agent_retrieval import AgentRetrieval, _dados
from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.busca import Ajustes, Busca, ListasDaBuscaEmMemoria, RankingEmOrdem
from api.catalogo import CopiaCurta, EnvioParaLixeira
from api.indice_da_busca import Consulta, IndiceEmMemoria, Registro
from api.jobs import CursorInvalido, agora_utc
from api.lixeira_na_leitura import VersaoDaLixeiraEmMemoria
from api.main import criar_app
from api.marcas import CatalogoDeMarcasEmMemoria
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_agent_retrieval import SEM_INDICES
from api.tests.test_auth import VerificadorFalso
from api.tests.test_busca import BASE, IndiceEspia, Mundo, job, objeto
from api.tests.test_jobs import ArmazenamentoFalso

ENVIO = EnvioParaLixeira(em=BASE, por_uid="u", por_email="u@redetv.com", motivo="teste")


def _passa(dados: dict[str, Any], filtro: dict[str, Any] | None) -> bool:
    """O filtro JSON do `batchSearch` sobre os dados de um registro."""
    for condicao in (filtro or {"$and": []})["$and"]:
        ((campo, teste),) = condicao.items()
        ((operador, valor),) = teste.items()
        assert operador in ("$eq", "$in"), operador  # o que os cenários usam
        atual = dados.get(campo)
        if operador == "$eq" and atual != valor:
            return False
        if operador == "$in" and not any(v in (atual or []) for v in valor):
            return False
    return True


class ServidorDoIndice:
    """O `batchSearch` simulado sobre o dublê em memória: o texto acha como o dublê, o
    significado devolve todo registro que passa no filtro, e a coleção de planos só tem
    planos (a de texto, o resto)."""

    def __init__(self, memoria: IndiceEmMemoria) -> None:
        self._memoria = memoria

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        assert corpo is not None
        if caminho.endswith(":predict"):
            return {"predictions": [{"embeddings": {"values": [0.0] * 256}}]}
        assert caminho.endswith("dataObjects:batchSearch")
        (nome, busca), *_ = corpo["searches"][0].items()
        de_planos = f"/collections/{SEM_INDICES.colecao}/" in caminho
        if nome == "textSearch":
            texto = busca["structuredQuery"]["text"]["text"]
            achados = self._memoria.buscar(Consulta(texto=texto, limite=10**6))
        else:
            achados = [
                r
                for rs in self._memoria._por_job.values()
                for r in rs
                if r.tipo == "plano"
            ]
        achados = [r for r in achados if (r.tipo == "plano") == de_planos]
        achados = [r for r in achados if _passa(_dados(r), busca.get("filter"))]
        return {
            "results": [
                {
                    "results": [
                        {"dataObject": {"data": _dados(r)}}
                        for r in achados[: busca["topK"]]
                    ]
                }
            ]
        }


class Cenario:
    """Um `Mundo` com Ana e Bia no catálogo e o índice que o teste pediu."""

    def __init__(self, indice: str) -> None:
        self.m = Mundo()
        self.ana = self.m.catalogo.acrescentar("Ana", "", []).id
        self.bia = self.m.catalogo.acrescentar("Bia", "", []).id
        self._indice = indice
        # Como no servidor, o marcador avança a cada mudança do catálogo (#591).
        self.versao = VersaoDaLixeiraEmMemoria()
        self.marcas = CatalogoDeMarcasEmMemoria()

    def busca(
        self,
        copia: CopiaCurta[Any] | None = None,
        listas: ListasDaBuscaEmMemoria | None = None,
    ) -> Busca:
        indice: Any = (
            self.m.indice
            if self._indice == "memoria"
            else AgentRetrieval(SEM_INDICES, ServidorDoIndice(self.m.indice))
        )
        return Busca(
            transporte=self.m.transporte,
            catalogo=self.m.catalogo,
            indice=indice,
            ranking=RankingEmOrdem(),
            repositorio=self.m.jobs,
            armazenamento=self.m.armazenamento,
            relogio=lambda: BASE,
            copia_do_catalogo=copia,
            listas=listas,
            versao_da_lixeira=self.versao,
            marcas=self.marcas,
        )

    def plano(self, job_id: str, descricao: str, *pessoas: str) -> None:
        self.m.com(
            job(job_id),
            Registro(
                id=f"{job_id}:plano:0",
                tipo="plano",
                job_id=job_id,
                inicio_ms=0,
                fim_ms=5_000,
                programa="TV Fama",
                pessoas=list(pessoas),
                descricao=descricao,
            ),
        )

    def lixeira(self, id: str) -> None:
        self.m.catalogo.definir_lixeira(id, ENVIO)
        self.versao.avancar()

    def restaurar(self, id: str) -> None:
        self.m.catalogo.definir_lixeira(id, None)
        self.versao.avancar()

    def purgar(self, id: str) -> None:
        self.m.catalogo.apagar(id)
        self.versao.avancar()

    def marca_na_lixeira(self, id: str) -> None:
        self.marcas.definir_lixeira(id, ENVIO)
        self.versao.avancar()

    def restaurar_marca(self, id: str) -> None:
        self.marcas.definir_lixeira(id, None)
        self.versao.avancar()


@pytest.fixture(params=["memoria", "adaptador"])
def cenario(request: pytest.FixtureRequest) -> Cenario:
    return Cenario(request.param)


def _jobs(resultado: Any) -> list[str]:
    return [v.job_id for v in resultado.videos]


def _faceta_de_pessoas(resultado: Any) -> list[str]:
    return [v.valor for v in resultado.facetas.pessoa]


def test_filtro_da_tela_por_pessoa_que_nao_conta_devolve_vazio(
    cenario: Cenario,
) -> None:
    cenario.plano("j1", "estúdio de tv", cenario.ana)
    busca = cenario.busca()
    pelo_filtro = Ajustes(pessoa=cenario.ana)
    assert _jobs(busca.buscar("estúdio", ajustes=pelo_filtro)) == ["j1"]

    cenario.lixeira(cenario.ana)

    assert busca.buscar("estúdio", ajustes=pelo_filtro).videos == []
    # Sem o filtro da tela, o plano continua achado pelo texto.
    assert _jobs(busca.buscar("estúdio")) == ["j1"]


def test_plano_com_duas_pessoas_e_uma_na_lixeira_fica_sem_ela_na_faceta(
    cenario: Cenario,
) -> None:
    cenario.plano("j1", "estúdio de tv", cenario.ana, cenario.bia)
    busca = cenario.busca()
    antes = busca.buscar("estúdio")
    assert sorted(_faceta_de_pessoas(antes)) == sorted([cenario.ana, cenario.bia])

    cenario.lixeira(cenario.ana)
    depois = busca.buscar("estúdio")

    assert _jobs(depois) == ["j1"]
    assert _faceta_de_pessoas(depois) == [cenario.bia]
    # Quem sobra no plano ainda filtra a tela.
    assert _jobs(busca.buscar("estúdio", ajustes=Ajustes(pessoa=cenario.bia))) == ["j1"]


def test_fala_com_a_pessoa_na_imagem_continua_achada_pelo_texto(
    cenario: Cenario,
) -> None:
    cenario.m.com(
        job("j1"),
        Registro(
            id="j1:fala:0",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=2_000,
            programa="TV Fama",
            pessoas=[cenario.ana],
            texto="Ana disse bom dia",
        ),
    )
    cenario.lixeira(cenario.ana)

    resultado = cenario.busca().buscar("bom dia")

    assert _jobs(resultado) == ["j1"]
    assert resultado.videos[0].momentos[0].motivo == "Fala: 'Ana disse bom dia'"
    assert _faceta_de_pessoas(resultado) == []


def test_objeto_da_pessoa_na_lixeira_continua_achado_pela_descricao_sem_dono(
    cenario: Cenario,
) -> None:
    cenario.m.com(job("j1"), objeto("j1:objeto:0", "j1", 0, 1_000, dono=cenario.ana))
    busca = cenario.busca()

    def motivo() -> str:
        return busca.buscar("vestido vermelho").videos[0].momentos[0].motivo

    assert motivo() == "Objeto: vestido vermelho · Ana"

    cenario.lixeira(cenario.ana)

    assert motivo() == "Objeto: vestido vermelho"
    # O filtro da tela por dona também some.
    assert (
        busca.buscar(
            "vestido", ajustes=Ajustes(pessoa=cenario.ana, tipo="objeto")
        ).videos
        == []
    )


def test_plano_trazido_pela_aparicao_da_excluida_e_pelo_texto_fica_so_pelo_texto(
    cenario: Cenario,
) -> None:
    cenario.plano("j1", "Ana no estúdio", cenario.ana)
    # A cópia curta do catálogo (#364) ainda reconhece o nome por até 30 s.
    copia = CopiaCurta(cenario.m.catalogo.todas, lambda: BASE)
    busca = cenario.busca(copia)
    antes = busca.buscar("Ana")
    assert antes.videos[0].momentos[0].motivo == "Na imagem: Ana"

    cenario.lixeira(cenario.ana)
    depois = busca.buscar("Ana")

    assert [m.motivo for m in depois.videos[0].momentos] == ["Plano: Ana no estúdio"]
    assert depois.sem_aparicoes == []


def test_pessoa_volta_na_hora_ao_restaurar_com_o_cache_de_candidatos_quente(
    cenario: Cenario,
) -> None:
    cenario.plano("j1", "estúdio de tv", cenario.ana)
    busca = cenario.busca()
    pelo_filtro = Ajustes(pessoa=cenario.ana)
    assert _jobs(busca.buscar("estúdio", ajustes=pelo_filtro)) == ["j1"]

    cenario.lixeira(cenario.ana)
    assert busca.buscar("estúdio", ajustes=pelo_filtro).videos == []

    cenario.restaurar(cenario.ana)
    de_volta = busca.buscar("estúdio", ajustes=pelo_filtro)
    assert _jobs(de_volta) == ["j1"]
    assert _faceta_de_pessoas(de_volta) == [cenario.ana]


def test_purgada_some_e_a_homonima_nova_aparece_so_nos_videos_novos(
    cenario: Cenario,
) -> None:
    cenario.plano("antigo", "estúdio de tv", cenario.ana)
    busca = cenario.busca()
    assert _faceta_de_pessoas(busca.buscar("estúdio")) == [cenario.ana]

    cenario.m.catalogo.apagar(cenario.ana)
    nova = cenario.m.catalogo.acrescentar("Ana", "", []).id
    cenario.plano("novo", "estúdio de tv", nova)
    busca = cenario.busca()  # o vídeo novo, indexado depois do cache da busca anterior
    resultado = busca.buscar("estúdio")

    assert sorted(_jobs(resultado)) == ["antigo", "novo"]
    assert [(v.valor, v.videos) for v in resultado.facetas.pessoa] == [(nova, 1)]
    assert busca.buscar("estúdio", ajustes=Ajustes(pessoa=cenario.ana)).videos == []
    assert _jobs(busca.buscar("estúdio", ajustes=Ajustes(pessoa=nova))) == ["novo"]


def test_video_novo_processado_com_a_pessoa_na_lixeira_nao_a_traz_de_volta(
    cenario: Cenario,
) -> None:
    cenario.plano("j1", "estúdio de tv", cenario.ana)
    cenario.lixeira(cenario.ana)
    cenario.plano("j2", "estúdio de tv", cenario.ana)

    resultado = cenario.busca().buscar("estúdio")

    assert sorted(_jobs(resultado)) == ["j1", "j2"]
    assert _faceta_de_pessoas(resultado) == []
    assert (
        cenario.busca().buscar("estúdio", ajustes=Ajustes(pessoa=cenario.ana)).videos
        == []
    )


# --- pela API, sem escrever no índice ----------------------------------------------------


class IndiceQueAnotaEscritas(IndiceEspia):
    """O índice em memória, anotando toda escrita."""

    def __init__(self) -> None:
        super().__init__()
        self.escritas: list[str] = []

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        self.escritas.append("gravar")
        super().gravar(job_id, registros)

    def apagar(self, job_id: str) -> None:
        self.escritas.append("apagar")
        super().apagar(job_id)

    def marcar_lixeira(self, job_id: str, na_lixeira: bool) -> None:
        self.escritas.append("marcar_lixeira")
        super().marcar_lixeira(job_id, na_lixeira)

    def preencher_filtros(
        self, job_id: str, sistema: str | None, na_lixeira: bool
    ) -> int:
        self.escritas.append("preencher_filtros")
        return super().preencher_filtros(job_id, sistema, na_lixeira)


def test_enviar_restaurar_e_purgar_mudam_a_busca_na_hora_sem_escrever_no_indice() -> (
    None
):
    c = Cenario("memoria")
    indice = IndiceQueAnotaEscritas()
    c.m.indice = indice
    c.plano("j1", "estúdio de tv", c.ana, c.bia)
    gravou = len(indice.escritas)
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("adm", ["administrador"])
    cliente = TestClient(
        criar_app(
            VerificadorFalso(
                {
                    "admin": Usuario(
                        uid="adm", email="a@redetv.com", login_em=agora_utc()
                    )
                }
            ),
            c.m.jobs,
            ArmazenamentoFalso(),
            papeis=papeis,
            catalogo=c.m.catalogo,
            indice=indice,
            auditoria=RepositorioDeAuditoriaEmMemoria(),
        )
    )
    admin = {"Authorization": "Bearer admin"}

    def na_faceta() -> list[str]:
        r = cliente.get("/v1/busca", params={"q": "estúdio"}, headers=admin)
        assert r.status_code == 200
        return sorted(v["valor"] for v in r.json()["facetas"]["pessoa"])

    assert na_faceta() == sorted([c.ana, c.bia])
    base = f"/v1/admin/lixeira/pessoas/{c.ana}"
    assert cliente.post(base, json={"motivo": "x"}, headers=admin).status_code == 201
    assert na_faceta() == [c.bia]
    assert cliente.post(f"{base}/restaurar", headers=admin).status_code == 200
    assert na_faceta() == sorted([c.ana, c.bia])
    cliente.post(base, json={"motivo": "x"}, headers=admin)
    purga = cliente.post(f"{base}/purgar", json={"nome": "Ana"}, headers=admin)
    assert purga.status_code == 200
    assert na_faceta() == [c.bia]

    assert indice.escritas[gravou:] == []


# --- a busca já aberta (#598): o cursor velho é recusado ---------------------------------


def _quatro_planos(c: Cenario) -> None:
    for i in range(1, 5):
        c.plano(f"j{i}", "estúdio de tv", c.ana, c.bia)


def _abrir(busca: Busca) -> str:
    cursor = busca.buscar("estúdio", limite=2, dono="u1")._proximo_cursor
    assert cursor is not None
    return cursor


def _segunda(busca: Busca, cursor: str) -> Any:
    return busca.buscar("estúdio", limite=2, dono="u1", cursor=cursor)


def test_cursor_sem_mudanca_na_lixeira_continua_valendo(cenario: Cenario) -> None:
    _quatro_planos(cenario)
    busca = cenario.busca()
    cursor = _abrir(busca)

    assert len(_segunda(busca, cursor).videos) == 2


def test_cursor_aberto_antes_do_envio_e_recusado(cenario: Cenario) -> None:
    _quatro_planos(cenario)
    busca = cenario.busca()
    cursor = _abrir(busca)

    cenario.lixeira(cenario.ana)

    with pytest.raises(CursorInvalido):
        _segunda(busca, cursor)


def test_cursor_aberto_antes_da_restauracao_e_recusado(cenario: Cenario) -> None:
    _quatro_planos(cenario)
    cenario.lixeira(cenario.ana)
    busca = cenario.busca()
    cursor = _abrir(busca)

    cenario.restaurar(cenario.ana)

    with pytest.raises(CursorInvalido):
        _segunda(busca, cursor)


def test_cursor_aberto_antes_do_envio_e_da_purga_e_recusado_com_duas_instancias(
    cenario: Cenario,
) -> None:
    _quatro_planos(cenario)
    busca = cenario.busca(listas=ListasDaBuscaEmMemoria())
    outra = cenario.busca(listas=ListasDaBuscaEmMemoria())  # caches e listas próprios
    cursor = _abrir(busca)

    cenario.lixeira(cenario.ana)
    cenario.purgar(cenario.ana)

    with pytest.raises(CursorInvalido):
        _segunda(busca, cursor)
    # A instância que não recebeu a mudança também lê o marcador do catálogo.
    nova = _abrir(outra)
    assert len(_segunda(outra, nova).videos) == 2


def test_lista_no_formato_antigo_sem_versao_e_recusada(cenario: Cenario) -> None:
    _quatro_planos(cenario)
    listas = ListasDaBuscaEmMemoria()
    busca = cenario.busca(listas=listas)
    cursor = _abrir(busca)
    documento = listas.documentos[cursor.partition(".")[0]]
    conteudo = json.loads(zlib.decompress(documento["conteudo"]))
    assert "versao_da_lixeira" in conteudo
    del conteudo["versao_da_lixeira"]
    documento["conteudo"] = zlib.compress(json.dumps(conteudo).encode())

    with pytest.raises(CursorInvalido):
        _segunda(busca, cursor)


class IndiceQueMudaNaLeitura(IndiceEspia):
    """Na primeira leitura, outra instância muda a lixeira do catálogo."""

    def __init__(self) -> None:
        super().__init__()
        self.ao_ler: Callable[[], None] | None = None

    def buscar(self, consulta: Consulta) -> list[Registro]:
        if self.ao_ler is not None:
            mudar, self.ao_ler = self.ao_ler, None
            mudar()
        return super().buscar(consulta)


def test_mudanca_durante_a_leitura_do_indice_recusa_a_pagina_seguinte(
    cenario: Cenario,
) -> None:
    indice = IndiceQueMudaNaLeitura()
    cenario.m.indice = indice
    _quatro_planos(cenario)
    busca = cenario.busca()
    indice.ao_ler = lambda: cenario.lixeira(cenario.ana)

    cursor = _abrir(busca)  # a 1ª página mistura os dois estados do catálogo

    with pytest.raises(CursorInvalido):
        _segunda(busca, cursor)


# --- a lixeira do vídeo nunca devolve trecho ---------------------------------------------


def test_video_na_lixeira_do_video_nunca_aparece_pelo_texto_nem_nas_paginas(
    cenario: Cenario,
) -> None:
    _quatro_planos(cenario)
    cenario.m.com(
        job("j5"),
        Registro(
            id="j5:fala:0",
            tipo="fala",
            job_id="j5",
            inicio_ms=0,
            fim_ms=2_000,
            programa="TV Fama",
            texto="bom dia da Ana",
        ),
    )
    busca = cenario.busca()
    assert "j5" in _jobs(busca.buscar("bom dia", dono="u1"))

    cenario.m.jobs.salvar(job("j5", lixeira=ENVIO))
    assert "j5" not in _jobs(busca.buscar("bom dia", dono="u1"))

    primeira = busca.buscar("estúdio", limite=2, dono="u1")
    cursor = primeira._proximo_cursor
    assert cursor is not None
    # Um vídeo ainda não entregue vai para a lixeira: a página seguinte relê o Job.
    alvo = next(j for j in ("j1", "j2", "j3", "j4") if j not in _jobs(primeira))
    cenario.m.jobs.salvar(job(alvo, lixeira=ENVIO))
    segunda = _segunda(busca, cursor)

    assert alvo not in _jobs(segunda)
    assert "j5" not in _jobs(primeira) + _jobs(segunda)


def test_pela_api_a_busca_aberta_numa_instancia_da_422_apos_envio_e_purga_noutra() -> (
    None
):
    c = Cenario("memoria")
    _quatro_planos(c)
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("adm", ["administrador"])
    admin = {"Authorization": "Bearer admin"}

    def instancia() -> TestClient:
        # Listas, caches e cópias próprios; o catálogo e o marcador são os mesmos.
        return TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(
                            uid="adm", email="a@redetv.com", login_em=agora_utc()
                        )
                    }
                ),
                c.m.jobs,
                ArmazenamentoFalso(),
                papeis=papeis,
                catalogo=c.m.catalogo,
                indice=c.m.indice,
                auditoria=RepositorioDeAuditoriaEmMemoria(),
                versao_da_lixeira=c.versao,
            )
        )

    a, b = instancia(), instancia()
    primeira = a.get("/v1/busca", params={"q": "estúdio", "limite": 2}, headers=admin)
    cursor = primeira.headers["X-Proximo-Cursor"]

    base = f"/v1/admin/lixeira/pessoas/{c.ana}"
    assert b.post(base, json={"motivo": "x"}, headers=admin).status_code == 201
    purga = b.post(f"{base}/purgar", json={"nome": "Ana"}, headers=admin)
    assert purga.status_code == 200

    velha = a.get("/v1/busca", params={"q": "estúdio", "cursor": cursor}, headers=admin)
    assert velha.status_code == 422
    # A busca nova, sem cursor, já sai com a exclusão.
    nova = a.get("/v1/busca", params={"q": "estúdio", "limite": 2}, headers=admin)
    assert nova.status_code == 200
    assert [v["valor"] for v in nova.json()["facetas"]["pessoa"]] == [c.bia]


# --- Marca na lixeira do catálogo (#594): sai do campo `marca`, da faceta e do filtro. ---


def _faceta_de_marcas(resultado: Any) -> list[str]:
    return [v.valor for v in resultado.facetas.marca]


def _vestido(c: Cenario, job_id: str, marca: str) -> None:
    c.m.com(job(job_id), objeto(f"{job_id}:objeto:0", job_id, 0, 1_000, marca=marca))


def test_filtro_da_tela_por_marca_na_lixeira_devolve_vazio(cenario: Cenario) -> None:
    nike = cenario.marcas.acrescentar("Nike", [])
    _vestido(cenario, "j1", "Nike")
    busca = cenario.busca()
    pelo_filtro = Ajustes(marca="Nike")
    assert _jobs(busca.buscar("vestido", ajustes=pelo_filtro)) == ["j1"]

    cenario.marca_na_lixeira(nike.id)

    assert busca.buscar("vestido", ajustes=pelo_filtro).videos == []
    # O objeto continua achado pela descrição, sem a marca.
    assert _jobs(busca.buscar("vestido")) == ["j1"]


def test_marca_na_lixeira_some_da_faceta_pelo_nome_e_pelo_apelido(
    cenario: Cenario,
) -> None:
    nike = cenario.marcas.acrescentar("Nike", ["Nik"])
    cenario.marcas.acrescentar("Adidas", [])
    _vestido(cenario, "j1", "Nike")
    _vestido(cenario, "j2", "NIK")
    _vestido(cenario, "j3", "Adidas")
    busca = cenario.busca()
    assert sorted(_faceta_de_marcas(busca.buscar("vestido"))) == [
        "Adidas",
        "NIK",
        "Nike",
    ]

    cenario.marca_na_lixeira(nike.id)
    depois = busca.buscar("vestido")

    assert _faceta_de_marcas(depois) == ["Adidas"]
    assert sorted(_jobs(depois)) == ["j1", "j2", "j3"]
    assert busca.buscar("vestido", ajustes=Ajustes(marca="NIK")).videos == []


def test_marca_volta_na_hora_ao_restaurar(cenario: Cenario) -> None:
    nike = cenario.marcas.acrescentar("Nike", [])
    _vestido(cenario, "j1", "Nike")
    busca = cenario.busca()
    cenario.marca_na_lixeira(nike.id)
    assert _faceta_de_marcas(busca.buscar("vestido")) == []

    cenario.restaurar_marca(nike.id)

    assert _faceta_de_marcas(busca.buscar("vestido")) == ["Nike"]
    assert _jobs(busca.buscar("vestido", ajustes=Ajustes(marca="Nike"))) == ["j1"]


def test_video_novo_com_a_marca_na_lixeira_nao_a_traz_de_volta(
    cenario: Cenario,
) -> None:
    nike = cenario.marcas.acrescentar("Nike", [])
    cenario.marca_na_lixeira(nike.id)
    _vestido(cenario, "j2", "Nike")

    resultado = cenario.busca().buscar("vestido")

    assert _jobs(resultado) == ["j2"]
    assert _faceta_de_marcas(resultado) == []


def test_marca_purgada_volta_a_contar(cenario: Cenario) -> None:
    nike = cenario.marcas.acrescentar("Nike", [])
    _vestido(cenario, "j1", "Nike")
    cenario.marca_na_lixeira(nike.id)
    cenario.marcas.apagar(nike.id)
    cenario.versao.avancar()

    assert _faceta_de_marcas(cenario.busca().buscar("vestido")) == ["Nike"]


def test_cursor_aberto_antes_do_envio_de_marca_para_a_lixeira_e_recusado(
    cenario: Cenario,
) -> None:
    nike = cenario.marcas.acrescentar("Nike", [])
    for i in range(1, 5):
        _vestido(cenario, f"j{i}", "Nike")
    busca = cenario.busca()
    cursor = busca.buscar("vestido", limite=2, dono="u1")._proximo_cursor
    assert cursor is not None

    cenario.marca_na_lixeira(nike.id)

    with pytest.raises(CursorInvalido):
        busca.buscar("vestido", limite=2, dono="u1", cursor=cursor)
