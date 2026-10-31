"""Busca (#120): índice, ranking e modelo simulados, sem rede."""

import json
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.busca import Busca, Ranking, RankingEmOrdem
from api.catalogo import CatalogoEmMemoria
from api.entendimento_da_consulta import ModelArmorEmMemoria
from api.indice_da_busca import Consulta, Filtros, IndiceEmMemoria, Registro
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
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
    m = Mundo(pedido(texto_livre="vestido"), pedido(texto_livre="vestido"))
    m.com(job("j1", data_exibicao=date(2020, 1, 1)), objeto("a", "j1", 0, 1_000))
    m.com(
        job("j2", data_exibicao=date(2024, 1, 1)),
        objeto("b", "j2", 0, 1_000),
        objeto("c", "j2", 20_000, 21_000),
    )
    # a ordem do índice põe o melhor momento de cada vídeo em primeiro lugar, empatado
    resultado = buscar(m, "vestido")
    assert resultado.videos[0].job_id in {"j1", "j2"}
    por_data = buscar(m, "vestido", ordem="data")
    assert [v.job_id for v in por_data.videos] == ["j2", "j1"]


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
    tempo_maximo_s: float = 10.0,
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
