"""Busca (#120): índice, ranking e modelo simulados, sem rede."""

import json
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.busca import Ajustes, Busca, Ranking, RankingEmOrdem
from api.catalogo import CatalogoEmMemoria
from api.entendimento_da_consulta import TEMPO_DA_CONSULTA_S, ModelArmorEmMemoria
from api.gemini import ErroHttp
from api.indice_da_busca import Consulta, Filtros, IndiceEmMemoria, Registro
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.rota_da_busca import TEMPO_MAXIMO_S
from api.tests.test_auth import VerificadorFalso
from api.tests.test_gemini import TransporteFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}
PROGRAMAS = ["TV Fama", "Leo Dias"]


def pedido(**mudancas: Any) -> str:
    base: dict[str, Any] = {
        "pessoas": [],
        "objetos": [],
        "marcas": [],
        "frase_exata": None,
        "evidencias": [],
        "programa": None,
        "exibido_desde": None,
        "exibido_ate": None,
        "texto_livre": None,
    }
    return json.dumps({**base, **mudancas})


VESTIDO = {
    "categoria": "roupa",
    "tipo": "vestido",
    "cor_base": "vermelho",
    "pessoa": "Sabrina Sato",
}


def objeto(id: str, job: str, inicio: int, fim: int, **mudancas: Any) -> Registro:
    base: dict[str, Any] = {
        "categoria": "roupa",
        "tipo_do_objeto": "vestido",
        "cor_base": ["vermelho"],
        "cor": "vermelho",
        "texto": "vestido vermelho",
        "programa": "TV Fama",
    }
    return Registro(
        id=id,
        tipo="objeto",
        job_id=job,
        inicio_ms=inicio,
        fim_ms=fim,
        **base | mudancas,
    )


def job(id: str, **mudancas: Any) -> Job:
    base: dict[str, Any] = {
        "id": id,
        "nome": f"{id}.mp4",
        "tamanho_bytes": 10,
        "estado": "concluido",
        "criado_por": "u1",
        "programa": "TV Fama",
        "data_exibicao": date(2024, 5, 1),
        "duracao_s": 120.0,
        "criado_em": BASE,
        "atualizado_em": BASE,
    }
    return Job(**base | mudancas)


class IndiceEspia(IndiceEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.consultas: list[Consulta] = []

    def buscar(self, consulta: Consulta) -> list[Registro]:
        self.consultas.append(consulta)
        return super().buscar(consulta)


class Mundo:
    def __init__(self, *respostas: str | Exception) -> None:
        self.catalogo = CatalogoEmMemoria()
        self.sabrina = self.catalogo.acrescentar(
            "Sabrina Sato", "apresentadora", ["Sabrina"]
        ).id
        self.indice = IndiceEspia()
        self.jobs = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.transporte = TransporteFalso(*respostas)

    def busca(self, ranking: Ranking | None = None) -> Busca:
        return Busca(
            transporte=self.transporte,
            catalogo=self.catalogo,
            armor=ModelArmorEmMemoria(),
            programas=PROGRAMAS,
            indice=self.indice,
            ranking=ranking or RankingEmOrdem(),
            repositorio=self.jobs,
            armazenamento=self.armazenamento,
            relogio=lambda: BASE,
        )

    def com(self, j: Job, *registros: Registro) -> None:
        self.jobs.salvar(j)
        self.indice.gravar(j.id, list(registros))


def buscar(m: Mundo, texto: str = "vestido vermelho da Sabrina Sato", **kw: Any) -> Any:
    return m.busca().buscar(texto, **kw)


def test_vestido_vermelho_da_sabrina_devolve_so_o_momento_do_objeto_dela() -> None:
    m = Mundo(pedido(pessoas=["Sabrina Sato"], objetos=[VESTIDO]))
    m.com(
        job("j1"),
        objeto(
            "j1:objeto:0",
            "j1",
            12_000,
            19_000,
            dono=m.sabrina,
            quadro="quadros/objeto-0.jpg",
        ),
        objeto("j1:objeto:1", "j1", 40_000, 50_000, dono="outra"),
        Registro(
            id="j1:plano:0",
            tipo="plano",
            job_id="j1",
            inicio_ms=0,
            fim_ms=60_000,
            pessoas=[m.sabrina],
            descricao="estúdio",
        ),
    )
    m.com(job("j2"), objeto("j2:objeto:0", "j2", 1_000, 2_000, dono="outra"))

    resultado = buscar(m)

    assert [v.job_id for v in resultado.videos] == ["j1"]
    video = resultado.videos[0]
    assert (video.programa, video.data_exibicao, video.duracao_s) == (
        "TV Fama",
        date(2024, 5, 1),
        120.0,
    )
    assert video.n_momentos == 1
    momento = video.momentos[0]
    assert (momento.inicio_ms, momento.fim_ms) == (12_000, 19_000)
    assert momento.motivo == "Objeto: vestido vermelho · Sabrina Sato"
    assert momento.quadro_url is not None
    assert "quadros/objeto-0.jpg" in momento.quadro_url


def test_dois_momentos_a_2_s_pelo_mesmo_motivo_viram_um_trecho_e_a_5_s_ficam_dois() -> (
    None
):
    m = Mundo(
        pedido(objetos=[{**VESTIDO, "pessoa": None}]),
        pedido(objetos=[{**VESTIDO, "pessoa": None}]),
    )
    m.com(
        job("j1"),
        objeto("a", "j1", 0, 1_000),
        objeto("b", "j1", 3_000, 4_000),
    )
    junto = buscar(m, "vestido vermelho")
    assert [(x.inicio_ms, x.fim_ms) for x in junto.videos[0].momentos] == [(0, 4_000)]
    assert junto.videos[0].n_momentos == 1

    m.com(
        job("j1"),
        objeto("a", "j1", 0, 1_000),
        objeto("b", "j1", 6_000, 7_000),
    )
    separado = buscar(m, "vestido vermelho")
    assert [(x.inicio_ms, x.fim_ms) for x in separado.videos[0].momentos] == [
        (0, 1_000),
        (6_000, 7_000),
    ]


def test_momentos_de_motivos_diferentes_nao_se_juntam() -> None:
    m = Mundo(pedido(texto_livre="promoção"))
    m.com(
        job("j1"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="promoção hoje",
        ),
        Registro(
            id="f2",
            tipo="fala",
            job_id="j1",
            inicio_ms=1_500,
            fim_ms=2_500,
            texto="promoção amanhã",
        ),
    )
    resultado = buscar(m, "promoção")
    assert resultado.videos[0].n_momentos == 2


def test_filtro_do_servidor_nao_e_sobrescrito_pela_consulta() -> None:
    m = Mundo(pedido(programa="Leo Dias", texto_livre="vestido"))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000, programa="TV Fama"))
    m.com(
        job("j2", programa="Leo Dias"), objeto("b", "j2", 0, 1_000, programa="Leo Dias")
    )

    resultado = m.busca().buscar(
        "vestido no Leo Dias", filtros_do_servidor=Filtros(programa="TV Fama")
    )

    assert {c.filtros.programa for c in m.indice.consultas} == {"TV Fama"}
    assert [v.job_id for v in resultado.videos] == ["j1"]


def test_video_fora_de_concluido_ou_de_outro_sistema_nao_aparece() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    m.com(job("j1", estado="analisando"), objeto("a", "j1", 0, 1_000))
    m.com(job("j2", sistema="legado"), objeto("b", "j2", 0, 1_000))
    m.com(job("j3", sistema="outro"), objeto("c", "j3", 0, 1_000))
    m.indice.gravar("fantasma", [objeto("d", "fantasma", 0, 1_000)])

    resultado = m.busca().buscar("vestido", sistema="outro")

    assert [v.job_id for v in resultado.videos] == ["j3"]


def test_videos_pelo_melhor_momento_e_no_empate_pelo_numero_de_momentos() -> None:
    sandalia = {
        "categoria": "calcado",
        "tipo": "sandalia",
        "cor_base": None,
        "pessoa": None,
    }
    pedido_dos_dois = pedido(objetos=[{**VESTIDO, "pessoa": None}, sandalia])
    m = Mundo(pedido_dos_dois, pedido_dos_dois)
    m.com(job("j1", data_exibicao=date(2024, 1, 1)), objeto("a", "j1", 0, 1_000))
    m.com(
        job("j2", data_exibicao=date(2020, 1, 1)),
        *(
            objeto(
                id,
                "j2",
                inicio,
                inicio + 1_000,
                categoria="calcado",
                tipo_do_objeto="sandalia",
                texto="sandalia",
            )
            for id, inicio in (("b", 0), ("c", 20_000))
        ),
    )
    # o melhor momento de cada vídeo é o primeiro da sua cláusula: empatam no RRF
    resultado = buscar(m, "vestido vermelho e sandália")
    assert [v.job_id for v in resultado.videos] == ["j2", "j1"]
    por_data = buscar(m, "vestido vermelho e sandália", ordem="data")
    assert [v.job_id for v in por_data.videos] == ["j1", "j2"]


def test_nenhuma_clausula_vai_ao_indice_so_com_filtros() -> None:
    m = Mundo(
        pedido(
            pessoas=["Sabrina Sato"],
            marcas=["Farm"],
            objetos=[
                {"categoria": "roupa", "tipo": None, "cor_base": None, "pessoa": None}
            ],
        )
    )
    m.com(job("j1"), objeto("a", "j1", 0, 1_000, marca="Farm", texto="vestido Farm"))
    resultado = buscar(m, "Sabrina Sato e Farm")
    assert m.indice.consultas
    assert all(c.texto or c.significado for c in m.indice.consultas)
    assert [v.job_id for v in resultado.videos] == ["j1"]


def test_o_melhor_momento_decide_a_ordem_dos_videos() -> None:
    class Inverte:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            return sorted(registros, key=lambda r: r.id, reverse=True)

    m = Mundo(pedido(texto_livre="vestido"))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    m.com(job("j2"), objeto("z", "j2", 0, 1_000))
    resultado = m.busca(Inverte()).buscar("vestido")
    assert [v.job_id for v in resultado.videos] == ["j2", "j1"]


def test_ranking_so_roda_com_texto_livre() -> None:
    chamadas: list[str] = []

    class Espia:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            chamadas.append(consulta)
            return registros

    m = Mundo(
        pedido(objetos=[{**VESTIDO, "pessoa": None}]), pedido(texto_livre="estúdio")
    )
    m.com(
        job("j1"),
        objeto("a", "j1", 0, 1_000),
        Registro(
            id="p",
            tipo="plano",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            descricao="estúdio",
        ),
    )
    m.busca(Espia()).buscar("vestido vermelho")
    assert chamadas == []
    m.busca(Espia()).buscar("estúdio")
    assert chamadas == ["estúdio"]


def test_falha_do_ranking_mantem_a_ordem_do_indice() -> None:
    class Quebra:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            raise RuntimeError("fora do ar")

    m = Mundo(pedido(texto_livre="vestido"))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    assert [v.job_id for v in m.busca(Quebra()).buscar("vestido").videos] == ["j1"]


def test_sem_aparicoes_diz_quantas_mencoes_ha_na_fala_e_na_tela() -> None:
    m = Mundo(pedido(pessoas=["Sabrina Sato"]))
    m.com(
        job("j1"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="a Sabrina Sato chegou",
        ),
        Registro(
            id="f2",
            tipo="fala",
            job_id="j1",
            inicio_ms=5_000,
            fim_ms=6_000,
            texto="oi Sabrina Sato",
        ),
        Registro(
            id="t1",
            tipo="texto_na_tela",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="SABRINA SATO",
        ),
    )

    resultado = buscar(m, "Sabrina Sato")

    assert resultado.videos == []
    (vazio,) = resultado.sem_aparicoes
    assert (vazio.nome, vazio.mencoes_na_fala, vazio.mencoes_na_tela) == (
        "Sabrina Sato",
        2,
        1,
    )


def test_sem_aparicoes_vem_mesmo_com_outros_resultados_e_no_programa_pedido() -> None:
    m = Mundo(
        pedido(pessoas=["Sabrina Sato"], programa="Leo Dias", texto_livre="praia")
    )
    m.com(
        job("j1", programa="Leo Dias"),
        Registro(
            id="p",
            tipo="plano",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            programa="Leo Dias",
            descricao="praia",
        ),
        Registro(
            id="f",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            programa="Leo Dias",
            texto="a Sabrina Sato",
        ),
    )
    m.com(
        job("j2"),
        Registro(
            id="g",
            tipo="fala",
            job_id="j2",
            inicio_ms=0,
            fim_ms=1_000,
            texto="Sabrina Sato de novo",
        ),
    )

    resultado = buscar(m, "Sabrina Sato na praia no Leo Dias")

    assert [v.job_id for v in resultado.videos] == ["j1"]
    (vazio,) = resultado.sem_aparicoes
    assert (vazio.mencoes_na_fala, vazio.mencoes_na_tela) == (1, 0)


def test_motivos_da_fala_e_do_gc_com_destaques_por_posicao() -> None:
    m = Mundo(
        pedido(frase_exata="promoção imperdível"), pedido(texto_livre="sabrina sato")
    )
    m.com(
        job("j1"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="É a Promoção Imperdível da semana",
        ),
        Registro(
            id="t1",
            tipo="texto_na_tela",
            job_id="j1",
            inicio_ms=9_000,
            fim_ms=10_000,
            texto="SABRINA SATO",
        ),
    )
    fala = buscar(m, '"promoção imperdível"').videos[0].momentos[0]
    assert fala.motivo == "Fala: 'É a Promoção Imperdível da semana'"
    d = fala.destaques[0]
    assert fala.motivo[d.inicio : d.fim] == "Promoção Imperdível"

    gc = buscar(m, "sabrina sato").videos[0].momentos[0]
    assert gc.motivo == "GC: SABRINA SATO"
    assert (gc.destaques[0].inicio, gc.destaques[0].fim) == (4, 16)


def test_texto_do_indice_segue_como_texto_puro_com_destaque_por_posicao() -> None:
    m = Mundo(pedido(texto_livre="promoção"))
    m.com(
        job("j1"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="<b>promoção</b>",
        ),
    )
    momento = buscar(m, "promoção").videos[0].momentos[0]
    assert momento.motivo == "Fala: '<b>promoção</b>'"
    d = momento.destaques[0]
    assert momento.motivo[d.inicio : d.fim] == "promoção"


def test_a_busca_registra_o_tempo_no_log(caplog: pytest.LogCaptureFixture) -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    with caplog.at_level(logging.INFO, logger="api.busca"):
        buscar(m, "vestido")
    assert any("busca" in r.message and " ms" in r.message for r in caplog.records)


def test_o_teto_de_videos_corta_o_resultado() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    for i in range(3):
        m.com(job(f"j{i}"), objeto(f"o{i}", f"j{i}", 0, 1_000))
    assert len(buscar(m, "vestido", limite=2).videos) == 2


# --- a rota ---------------------------------------------------------------------------


def cliente(
    papeis: list[Papel] | None = None,
    *respostas: str,
    maximo_por_minuto: int = 30,
    tempo_maximo_s: float = TEMPO_MAXIMO_S,
    indice: IndiceEmMemoria | None = None,
) -> tuple[TestClient, Mundo]:
    m = Mundo(*respostas)
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    repo_papeis = RepositorioDePapeisEmMemoria()
    if papeis is not None:
        repo_papeis.salvar("u1", papeis)
    app = criar_app(
        VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
        m.jobs,
        m.armazenamento,
        papeis=repo_papeis,
        catalogo=m.catalogo,
        indice=indice or m.indice,
        transporte_da_consulta=m.transporte,
        armor=ModelArmorEmMemoria(),
        busca_por_minuto=maximo_por_minuto,
        tempo_maximo_da_busca_s=tempo_maximo_s,
    )
    return TestClient(app), m


def test_rota_devolve_os_videos_agrupados() -> None:
    c, _ = cliente(["consulta"], pedido(texto_livre="vestido"))
    r = c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["videos"][0]["job_id"] == "j1"
    assert corpo["videos"][0]["momentos"][0]["motivo"] == "Objeto: vestido vermelho"


def test_sem_decupagem_ver_a_rota_responde_403() -> None:
    c, _ = cliente([], pedido(texto_livre="vestido"))
    assert (
        c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO).status_code
        == 403
    )


def test_sem_login_a_rota_responde_401() -> None:
    c, _ = cliente(["consulta"])
    assert c.get("/v1/busca", params={"q": "vestido"}).status_code == 401


def test_acima_do_limite_por_usuario_responde_429() -> None:
    c, _ = cliente(
        ["consulta"],
        pedido(texto_livre="vestido"),
        pedido(texto_livre="vestido"),
        maximo_por_minuto=2,
    )
    codigos = [
        c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO).status_code
        for _ in range(3)
    ]
    assert codigos == [200, 200, 429]


def test_consulta_que_passa_do_tempo_maximo_responde_504() -> None:
    class Lento(IndiceEmMemoria):
        def buscar(self, consulta: Consulta) -> list[Registro]:
            time.sleep(0.5)
            return []

    c, _ = cliente(
        ["consulta"], pedido(texto_livre="vestido"), tempo_maximo_s=0.05, indice=Lento()
    )
    assert (
        c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO).status_code
        == 504
    )


def test_sem_modelo_nem_model_armor_a_busca_cai_no_plano_b() -> None:
    m = Mundo()
    app = criar_app(
        VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
        m.jobs,
        m.armazenamento,
        indice=m.indice,
    )
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    r = TestClient(app).get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO)
    assert r.status_code == 200
    assert r.json()["videos"][0]["job_id"] == "j1"


def test_pedido_sem_consulta_responde_422() -> None:
    c, _ = cliente(["consulta"])
    assert c.get("/v1/busca", headers=AUTORIZACAO).status_code == 422


def test_o_tempo_maximo_da_rota_passa_do_teto_do_modelo() -> None:
    # senão a rota responde 504 antes de o plano B chegar
    assert TEMPO_MAXIMO_S > TEMPO_DA_CONSULTA_S


# --- chips e filtros da tela (#169) ---------------------------------------------------


def _fala(id: str, texto: str) -> Registro:
    return Registro(
        id=id, tipo="fala", job_id="j1", inicio_ms=0, fim_ms=1_000, texto=texto
    )


def test_o_resultado_diz_quais_chips_estao_ligados_e_o_programa_entendido() -> None:
    m = Mundo(pedido(pessoas=["Sabrina Sato"], objetos=[VESTIDO], programa="TV Fama"))
    m.com(job("j1"))

    entendida = buscar(m, "x").entendida

    assert entendida.evidencias == ["imagem", "objeto"]
    assert entendida.programa == "TV Fama"


def test_ligar_citada_e_fala_traz_as_mencoes_que_o_padrao_deixava_de_fora() -> None:
    m = Mundo(pedido(pessoas=["Sabrina Sato"]), pedido(pessoas=["Sabrina Sato"]))
    m.com(job("j1"), _fala("f1", "oi Sabrina Sato"))

    assert buscar(m, "Sabrina Sato").videos == []

    de_novo = buscar(m, "Sabrina Sato", ajustes=Ajustes(evidencias=("imagem", "fala")))
    assert [v.momentos[0].motivo for v in de_novo.videos] == ["Fala: 'oi Sabrina Sato'"]
    assert de_novo.entendida.evidencias == ["imagem", "fala"]


def test_desligar_o_chip_de_objeto_tira_as_clausulas_de_objeto() -> None:
    m = Mundo(pedido(objetos=[VESTIDO]))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))

    resultado = buscar(m, "vestido", ajustes=Ajustes(evidencias=("fala",)))

    assert resultado.videos == []
    assert resultado.entendida.evidencias == ["fala"]


def test_programa_e_periodo_da_tela_valem_sobre_o_entendido() -> None:
    m = Mundo(pedido(texto_livre="vestido", programa="Leo Dias"))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))

    buscar(
        m,
        "vestido",
        ajustes=Ajustes(
            programa="TV Fama", desde=date(2024, 1, 1), ate=date(2024, 12, 31)
        ),
    )

    (consulta,) = m.indice.consultas
    assert consulta.filtros.programa == "TV Fama"
    assert consulta.filtros.exibido_desde == date(2024, 1, 1)
    assert consulta.filtros.exibido_ate == date(2024, 12, 31)


def test_a_rota_aceita_ev_programa_e_periodo() -> None:
    c, _ = cliente(["consulta"], pedido(texto_livre="vestido"))
    r = c.get(
        "/v1/busca",
        params={
            "q": "vestido",
            "ev": ["fala", "gc"],
            "programa": "TV Fama",
            "desde": "2024-01-01",
            "ate": "2024-12-31",
        },
        headers=AUTORIZACAO,
    )
    assert r.status_code == 200
    assert r.json()["entendida"]["programa"] == "TV Fama"
    assert r.json()["entendida"]["desde"] == "2024-01-01"
    assert (
        c.get(
            "/v1/busca", params={"q": "v", "ev": "inventada"}, headers=AUTORIZACAO
        ).status_code
        == 422
    )


def test_sem_periodo_tira_o_periodo_entendido() -> None:
    m = Mundo(
        pedido(
            texto_livre="vestido",
            exibido_desde="2024-01-01",
            exibido_ate="2024-12-31",
        )
    )
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))

    resultado = buscar(m, "vestido em 2024", ajustes=Ajustes(sem_periodo=True))

    (consulta,) = m.indice.consultas
    assert consulta.filtros.exibido_desde is None
    assert consulta.filtros.exibido_ate is None
    assert resultado.entendida.desde is None


def test_periodo_com_inicio_depois_do_fim_responde_422() -> None:
    c, _ = cliente(["consulta"], pedido(texto_livre="vestido"))
    r = c.get(
        "/v1/busca",
        params={"q": "vestido", "desde": "2025-01-01", "ate": "2024-12-31"},
        headers=AUTORIZACAO,
    )
    assert r.status_code == 422


def test_dentro_do_video_os_momentos_seguem_a_relevancia() -> None:
    class Inverte:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            return sorted(registros, key=lambda r: r.id, reverse=True)

    m = Mundo(pedido(texto_livre="vestido"))
    m.com(
        job("j1"),
        objeto("a", "j1", 0, 1_000),
        objeto("b", "j1", 60_000, 61_000),
    )
    [video] = m.busca(Inverte()).buscar("vestido").videos
    assert [x.inicio_ms for x in video.momentos] == [60_000, 0]


def test_so_a_clausula_do_texto_livre_corta_o_significado() -> None:
    # Na cláusula da pessoa na imagem, o significado só leva o filtro ao índice.
    m = Mundo(pedido(pessoas=["Sabrina Sato"], texto_livre="no estúdio"))
    buscar(m, "Sabrina Sato no estúdio")
    com_significado = [c for c in m.indice.consultas if c.significado]
    assert {(c.filtros.pessoa, c.cortar_significado) for c in com_significado} == {
        (m.sabrina, False),
        (None, True),
    }


def _por_destaque(destaque: int | None, id: str, inicio: int) -> Registro:
    return objeto(
        id,
        "j1",
        inicio,
        inicio + 1_000,
        destaque=destaque,
        texto="carro azul, veículo, objeto de cena",
    )


def test_com_a_mesma_relevancia_o_destaque_maior_vem_antes() -> None:
    # Dois carros colados na lista do índice: a diferença de posição é menor que o peso.
    m = Mundo(pedido(texto_livre="carro"))
    m.com(
        job("j1"),
        _por_destaque(1, "baixo", 0),
        _por_destaque(3, "alto", 60_000),
    )
    [video] = m.busca().buscar("carro").videos
    assert [x.inicio_ms for x in video.momentos] == [60_000, 0]


def test_o_peso_do_destaque_vale_tambem_depois_do_ranking() -> None:
    class Ordem:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            return sorted(registros, key=lambda r: r.id)  # "a" antes de "b"

    m = Mundo(pedido(texto_livre="carro"))
    m.com(
        job("j1"),
        _por_destaque(1, "a", 0),
        _por_destaque(3, "b", 60_000),
    )
    [video] = m.busca(Ordem()).buscar("carro").videos
    assert [x.inicio_ms for x in video.momentos] == [60_000, 0]


def test_o_destaque_nao_passa_na_frente_de_quem_e_bem_mais_relevante() -> None:
    class Ordem:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            return sorted(registros, key=lambda r: r.id)

    m = Mundo(pedido(texto_livre="carro"))
    m.com(
        job("j1"),
        _por_destaque(1, "a", 0),
        _por_destaque(None, "b", 10_000),
        _por_destaque(None, "c", 20_000),
        _por_destaque(None, "d", 30_000),
        _por_destaque(None, "e", 40_000),
        _por_destaque(3, "f", 60_000),
    )
    [video] = m.busca(Ordem()).buscar("carro").videos
    assert video.momentos[0].inicio_ms == 0


# --- facetas (#257) -------------------------------------------------------------


def mundo_das_facetas() -> Mundo:
    m = Mundo(*[pedido(texto_livre="vestido")] * 3)
    m.com(
        job("j1", programa="TV Fama", data_exibicao=date(2024, 5, 1)),
        objeto("a", "j1", 0, 1_000, marca="Nike", dono=m.sabrina),
        objeto("b", "j1", 5_000, 6_000, marca="Nike", dono=m.sabrina),
    )
    m.com(
        job("j2", programa="Leo Dias", data_exibicao=date(2024, 6, 2)),
        objeto("c", "j2", 0, 1_000, marca="Adidas", programa="Leo Dias"),
    )
    return m


def contagens(faceta: Any) -> dict[str, int]:
    return {
        (v["valor"] if isinstance(v, dict) else v.valor): (
            v["videos"] if isinstance(v, dict) else v.videos
        )
        for v in faceta
    }


def test_facetas_contam_videos_distintos_por_valor() -> None:
    m = mundo_das_facetas()

    f = buscar(m, "vestido").facetas

    assert contagens(f.programa) == {"TV Fama": 1, "Leo Dias": 1}
    assert contagens(f.mes) == {"2024-06": 1, "2024-05": 1}
    assert [v.valor for v in f.mes] == ["2024-06", "2024-05"]
    assert contagens(f.marca) == {"Nike": 1, "Adidas": 1}
    assert contagens(f.tipo) == {"objeto": 2}
    assert f.tipo[0].rotulo == "Objeto"
    assert [(v.valor, v.rotulo, v.videos) for v in f.pessoa] == [
        (m.sabrina, "Sabrina Sato", 1)
    ]


def test_facetas_mudam_com_o_programa_filtrado() -> None:
    m = mundo_das_facetas()

    sem = buscar(m, "vestido").facetas
    com = buscar(m, "vestido", ajustes=Ajustes(programa="Leo Dias")).facetas

    assert contagens(sem.marca) == {"Nike": 1, "Adidas": 1}
    assert contagens(com.marca) == {"Adidas": 1}
    assert com.pessoa == []
    assert contagens(com.programa) == {"Leo Dias": 1}


def test_faceta_de_marca_pessoa_e_tipo_filtra_os_resultados_e_as_contagens() -> None:
    m = mundo_das_facetas()

    por_marca = buscar(m, "vestido", ajustes=Ajustes(marca="Adidas"))
    por_pessoa = buscar(m, "vestido", ajustes=Ajustes(pessoa=m.sabrina))
    por_tipo = buscar(m, "vestido", ajustes=Ajustes(tipo="fala"))

    assert [v.job_id for v in por_marca.videos] == ["j2"]
    assert contagens(por_marca.facetas.programa) == {"Leo Dias": 1}
    assert [v.job_id for v in por_pessoa.videos] == ["j1"]
    assert contagens(por_pessoa.facetas.marca) == {"Nike": 1}
    assert por_tipo.videos == []
    assert por_tipo.facetas.programa == []


def test_facetas_ignoram_video_que_o_usuario_nao_ve() -> None:
    m = mundo_das_facetas()
    m.jobs.salvar(job("j2", estado="analisando"))

    f = buscar(m, "vestido").facetas

    assert contagens(f.programa) == {"TV Fama": 1}


def test_plano_b_tambem_devolve_as_facetas() -> None:
    m = Mundo(ErroHttp(400))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000, marca="Nike"))

    r = buscar(m, "vestido")

    assert r.plano_b
    assert contagens(r.facetas.marca) == {"Nike": 1}


def test_busca_sem_resultado_tem_facetas_vazias() -> None:
    m = Mundo(pedido(texto_livre="nada"))

    f = buscar(m, "nada").facetas

    assert f.programa == f.mes == f.pessoa == f.marca == f.tipo == []


def test_a_rota_devolve_facetas_e_aceita_pessoa_marca_e_tipo() -> None:
    c, _ = cliente(["consulta"], *[pedido(texto_livre="vestido")] * 2)
    r = c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO)
    assert contagens(r.json()["facetas"]["programa"]) == {"TV Fama": 1}

    filtrada = c.get(
        "/v1/busca",
        params={"q": "vestido", "marca": "Nike", "tipo": "objeto", "pessoa": "p1"},
        headers=AUTORIZACAO,
    )
    assert filtrada.status_code == 200
    assert filtrada.json()["videos"] == []
    assert (
        c.get(
            "/v1/busca", params={"q": "v", "tipo": "inventado"}, headers=AUTORIZACAO
        ).status_code
        == 422
    )
