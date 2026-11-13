"""A lixeira do catálogo vale na busca (#583, #592): a pessoa na lixeira ou purgada sai como
aparição, dona de objeto, faceta e filtro da tela; o texto que a cita continua achado.

Cada cenário roda com o dublê em memória do índice e com o adapter real (`AgentRetrieval`),
este sobre um servidor de índice simulado que entende o filtro JSON do `batchSearch`.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.agent_retrieval import AgentRetrieval, _dados
from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.busca import Ajustes, Busca, RankingEmOrdem
from api.catalogo import CopiaCurta, EnvioParaLixeira
from api.indice_da_busca import Consulta, IndiceEmMemoria, Registro
from api.jobs import agora_utc
from api.main import criar_app
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

    def busca(self, copia: CopiaCurta[Any] | None = None) -> Busca:
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

    def restaurar(self, id: str) -> None:
        self.m.catalogo.definir_lixeira(id, None)


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
