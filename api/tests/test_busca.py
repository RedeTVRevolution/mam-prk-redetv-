"""Busca (#120): índice, ranking e modelo simulados, sem rede."""

import json
import logging
import random
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.busca import (
    TETO_DA_LISTA_BYTES,
    TETO_DE_ASSINATURAS,
    TETO_DE_CONSULTAS_AO_INDICE,
    TETO_DE_REGISTROS,
    TETO_DO_RANKING,
    Ajustes,
    Busca,
    BuscaCancelada,
    Entendida,
    Facetas,
    ListaDaBusca,
    MomentoGuardado,
    Ranking,
    RankingEmOrdem,
    VideoGuardado,
    filtros_do_servidor,
)
from api.catalogo import CatalogoEmMemoria, EnvioParaLixeira
from api.entendimento_da_consulta import (
    TEMPO_DA_CONSULTA_S,
    ModelArmor,
    ModelArmorEmMemoria,
)
from api.eventos_de_uso import Eventos
from api.gemini import ErroHttp
from api.indice_da_busca import Consulta, Filtros, IndiceEmMemoria, Registro
from api.jobs import CursorInvalido, Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.rota_da_busca import LIMITES_DA_IMAGEM, TEMPO_MAXIMO_S, LimitesDaImagem
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

    def busca(
        self,
        ranking: Ranking | None = None,
        relogio: Callable[[], datetime] = lambda: BASE,
        armor: ModelArmor | None = None,
    ) -> Busca:
        return Busca(
            transporte=self.transporte,
            catalogo=self.catalogo,
            armor=armor or ModelArmorEmMemoria(),
            programas=PROGRAMAS,
            indice=self.indice,
            ranking=ranking or RankingEmOrdem(),
            repositorio=self.jobs,
            armazenamento=self.armazenamento,
            relogio=relogio,
        )

    def com(self, j: Job, *registros: Registro) -> None:
        self.jobs.salvar(j)
        # Como a indexação: o objeto leva o sistema do Job (#483).
        self.indice.gravar(
            j.id, [replace(r, sistema=r.sistema or j.sistema) for r in registros]
        )


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
    # Sem chave de sistema (a web), a busca não assina: leva só o caminho do quadro.
    assert momento.quadro == "quadros/objeto-0.jpg"
    assert momento.quadro_url is None
    assert resultado.sem_aparicoes == []


OUTROS_OBJETOS = [("chapéu", "azul"), ("bolsa", "preto"), ("sapato", "branco")]


def _mundo_de_varias_clausulas(indice: IndiceEspia | None = None) -> Mundo:
    """Quatro cláusulas, uma consulta ao índice cada: mais que o teto."""
    outros = [{**VESTIDO, "tipo": t, "cor_base": c} for t, c in OUTROS_OBJETOS]
    m = Mundo(pedido(pessoas=["Sabrina Sato"], objetos=[VESTIDO, *outros]))
    m.indice = indice or m.indice
    dos_outros = [
        objeto(
            f"j{n % 2 + 1}:objeto:{n + 1}",
            f"j{n % 2 + 1}",
            40_000 + 20_000 * n,
            50_000 + 20_000 * n,
            dono=m.sabrina,
            tipo_do_objeto=t,
            cor_base=[c],
            cor=c,
            texto=f"{t} {c}",
        )
        for n, (t, c) in enumerate(OUTROS_OBJETOS)
    ]
    m.com(
        job("j1"),
        objeto("j1:objeto:0", "j1", 12_000, 19_000, dono=m.sabrina),
        *(r for r in dos_outros if r.job_id == "j1"),
    )
    m.com(job("j2"), *(r for r in dos_outros if r.job_id == "j2"))
    return m


def test_as_clausulas_vao_ao_indice_ao_mesmo_tempo_e_com_limite() -> None:
    class IndiceLento(IndiceEspia):
        """As primeiras consultas só passam quando o teto inteiro está em voo."""

        def __init__(self) -> None:
            super().__init__()
            self.em_voo = 0
            self.pico = 0
            self.chegadas = 0
            self.trava = threading.Lock()
            self.turma = threading.Barrier(TETO_DE_CONSULTAS_AO_INDICE, timeout=5)

        def buscar(self, consulta: Consulta) -> list[Registro]:
            with self.trava:
                self.em_voo += 1
                self.pico = max(self.pico, self.em_voo)
                self.chegadas += 1
                da_turma = self.chegadas <= TETO_DE_CONSULTAS_AO_INDICE
            try:
                if da_turma:
                    self.turma.wait()
                return super().buscar(consulta)
            finally:
                with self.trava:
                    self.em_voo -= 1

    lento = IndiceLento()
    resultado = buscar(_mundo_de_varias_clausulas(lento))
    assert len(lento.consultas) > TETO_DE_CONSULTAS_AO_INDICE
    assert lento.pico == TETO_DE_CONSULTAS_AO_INDICE
    assert resultado.videos


def test_o_resultado_em_paralelo_e_o_da_execucao_em_serie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    em_paralelo = buscar(_mundo_de_varias_clausulas())
    monkeypatch.setattr("api.busca.TETO_DE_CONSULTAS_AO_INDICE", 1)
    em_serie = buscar(_mundo_de_varias_clausulas())
    assert [v.n_momentos for v in em_paralelo.videos] == [3, 1]
    assert em_paralelo.videos == em_serie.videos
    assert em_paralelo.sem_aparicoes == em_serie.sem_aparicoes


def test_se_uma_consulta_ao_indice_falha_o_erro_sobe_como_em_serie() -> None:
    class IndiceQueFalha(IndiceEspia):
        def buscar(self, consulta: Consulta) -> list[Registro]:
            super().buscar(consulta)
            raise RuntimeError("índice fora do ar")

    indice = IndiceQueFalha()
    with pytest.raises(RuntimeError, match="índice fora do ar"):
        buscar(_mundo_de_varias_clausulas(indice))


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


def test_video_na_lixeira_nao_aparece_na_busca() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    m.com(
        job(
            "j2",
            lixeira=EnvioParaLixeira(
                em=datetime(2026, 11, 2, tzinfo=UTC),
                por_uid="adm",
                por_email="adm@redetv.com",
                motivo="duplicado",
            ),
        ),
        objeto("b", "j2", 0, 1_000),
    )

    resultado = m.busca().buscar("vestido")

    assert [v.job_id for v in resultado.videos] == ["j1"]


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


def test_pessoa_fora_do_catalogo_em_consulta_composta_volta_vazia_com_aviso() -> None:
    fulano = {**VESTIDO, "pessoa": "Fulano"}
    m = Mundo(pedido(pessoas=["Fulano"], objetos=[fulano]))
    m.com(
        job("j1"),
        objeto("j1:objeto:0", "j1", 0, 1_000, dono="outra"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="o Fulano chegou",
        ),
        Registro(
            id="f2",
            tipo="fala",
            job_id="j1",
            inicio_ms=5_000,
            fim_ms=6_000,
            texto="Fulano de novo",
        ),
    )

    resultado = buscar(m, "Fulano de vestido vermelho")

    assert resultado.videos == []
    (vazio,) = resultado.sem_aparicoes
    assert (vazio.pessoa_id, vazio.nome) == (None, "Fulano")
    assert (vazio.mencoes_na_fala, vazio.mencoes_na_tela) == (2, 0)


def test_ver_as_mencoes_de_um_nome_fora_do_catalogo_traz_a_fala() -> None:
    fulano = {**VESTIDO, "pessoa": "Fulano"}
    m = Mundo(pedido(pessoas=["Fulano"], objetos=[fulano]))
    m.com(
        job("j1"),
        objeto("j1:objeto:0", "j1", 0, 1_000, dono="outra"),
        _fala("f1", "o Fulano chegou"),
    )

    resultado = buscar(
        m,
        "Fulano de vestido vermelho",
        ajustes=Ajustes(evidencias=("imagem", "citada", "fala")),
    )

    assert [mo.motivo for v in resultado.videos for mo in v.momentos] == [
        "Fala: 'o Fulano chegou'"
    ]


def test_objeto_sem_pessoa_continua_trazendo_os_momentos() -> None:
    sem_dono = {**VESTIDO, "pessoa": None}
    m = Mundo(pedido(objetos=[sem_dono]))
    m.com(job("j1"), objeto("j1:objeto:0", "j1", 0, 1_000, dono="outra"))

    resultado = buscar(m, "vestido vermelho")

    assert [v.job_id for v in resultado.videos] == ["j1"]
    assert resultado.sem_aparicoes == []


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
    *respostas: str | Exception,
    maximo_por_minuto: int = 30,
    tempo_maximo_s: float = TEMPO_MAXIMO_S,
    indice: IndiceEmMemoria | None = None,
    limites_da_imagem: LimitesDaImagem = LIMITES_DA_IMAGEM,
    eventos: Eventos | None = None,
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
        limites_da_imagem=limites_da_imagem,
        eventos=eventos,
    )
    return TestClient(app), m


def test_rota_devolve_os_videos_agrupados() -> None:
    c, _ = cliente(["consulta"], pedido(texto_livre="vestido"))
    r = c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["videos"][0]["job_id"] == "j1"
    assert corpo["videos"][0]["momentos"][0]["motivo"] == "Objeto: vestido vermelho"


# --- páginas por cursor (#426) ------------------------------------------------------


def cliente_com_videos(n: int, consultas: int) -> TestClient:
    """`n` vídeos com um vestido cada; `consultas` é quantas vezes o modelo responde
    (uma resposta a menos do que as chamadas faz o teste falhar)."""
    c, m = cliente(["consulta"], *[pedido(texto_livre="vestido")] * consultas)
    for i in range(2, n + 1):
        m.com(job(f"j{i}"), objeto(f"o{i}", f"j{i}", 0, 1_000))
    return c


def pagina_da_busca(
    c: TestClient, cursor: str | None = None, limite: int = 50, q: str = "vestido"
) -> tuple[list[str], str | None]:
    params: dict[str, Any] = {"q": q, "limite": limite}
    if cursor is not None:
        params["cursor"] = cursor
    r = c.get("/v1/busca", params=params, headers=AUTORIZACAO)
    assert r.status_code == 200, r.text
    return [v["job_id"] for v in r.json()["videos"]], r.headers.get("X-Proximo-Cursor")


def test_120_videos_vem_em_paginas_de_50_50_e_20_sem_repetir() -> None:
    # Uma resposta do modelo só: as páginas seguintes não entendem a consulta de novo.
    c = cliente_com_videos(120, consultas=1)

    primeira, cursor = pagina_da_busca(c)
    assert cursor is not None
    segunda, cursor = pagina_da_busca(c, cursor)
    assert cursor is not None
    terceira, fim = pagina_da_busca(c, cursor)

    assert [len(primeira), len(segunda), len(terceira)] == [50, 50, 20]
    assert len(set(primeira + segunda + terceira)) == 120
    assert fim is None


def test_a_mesma_pagina_vem_na_mesma_ordem_entre_chamadas() -> None:
    c = cliente_com_videos(5, consultas=2)

    primeira = pagina_da_busca(c, limite=2)
    # Cada 1ª página grava a própria lista: o cursor muda, os vídeos não.
    assert pagina_da_busca(c, limite=2)[0] == primeira[0]
    assert pagina_da_busca(c, primeira[1], 2) == pagina_da_busca(c, primeira[1], 2)


def test_cursor_invalido_ou_de_outra_consulta_responde_422() -> None:
    c = cliente_com_videos(3, consultas=1)
    _, cursor = pagina_da_busca(c, limite=1)

    for q, ruim in [("vestido", "nao-existe"), ("vermelho", cursor)]:
        r = c.get("/v1/busca", params={"q": q, "cursor": ruim}, headers=AUTORIZACAO)
        assert r.status_code == 422
        assert r.json()["detail"] == "Cursor inválido"


class RankingQueCaiDepois:
    """Reordena (invertendo) na 1ª chamada e cai em todas as outras."""

    def __init__(self) -> None:
        self.recebidos: list[int] = []

    def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
        self.recebidos.append(len(registros))
        if len(self.recebidos) > 1:
            raise ConnectionError("ranking fora")
        return registros[::-1]


def mundo_de_videos(n: int, *respostas: str) -> Mundo:
    m = Mundo(*(respostas or (pedido(texto_livre="vestido"),)))
    for i in range(1, n + 1):
        m.com(job(f"j{i}"), objeto(f"o{i}", f"j{i}", 0, 1_000))
    return m


def todas_as_paginas(busca: Busca, limite: int = 50) -> list[str]:
    r = busca.buscar("vestido", limite=limite, dono="u1")
    ids = [v.job_id for v in r.videos]
    while r._proximo_cursor:
        r = busca.buscar("vestido", limite=limite, dono="u1", cursor=r._proximo_cursor)
        ids += [v.job_id for v in r.videos]
    return ids


def test_as_paginas_seguintes_nao_chamam_modelo_indice_nem_ranking() -> None:
    m = mundo_de_videos(5, *[pedido(texto_livre="vestido")] * 2)
    em_ordem = todas_as_paginas(m.busca())
    ranking = RankingQueCaiDepois()
    busca = m.busca(ranking=ranking)

    primeira = busca.buscar("vestido", limite=2, dono="u1")
    consultas = len(m.indice.consultas)
    segunda = busca.buscar(
        "vestido", limite=2, dono="u1", cursor=primeira._proximo_cursor
    )
    terceira = busca.buscar(
        "vestido", limite=2, dono="u1", cursor=segunda._proximo_cursor
    )

    ids = [v.job_id for r in (primeira, segunda, terceira) for v in r.videos]
    # A ordem é a do ranking da 1ª página, mesmo com ele fora nas seguintes.
    assert ids == em_ordem[::-1]
    assert terceira._proximo_cursor is None
    assert len(m.transporte.chamadas) == 2  # uma por 1ª página
    assert len(m.indice.consultas) == consultas
    assert ranking.recebidos == [5]


def test_o_ranking_so_reordena_os_100_primeiros_e_o_resto_vem_depois() -> None:
    m = mundo_de_videos(150, *[pedido(texto_livre="vestido")] * 2)
    em_ordem = todas_as_paginas(m.busca())
    ranking = RankingQueCaiDepois()

    ranqueados = todas_as_paginas(m.busca(ranking=ranking))

    assert ranking.recebidos == [TETO_DO_RANKING]
    assert ranqueados == em_ordem[:100][::-1] + em_ordem[100:]


def test_destaque_fora_dos_100_ranqueados_nao_passa_a_frente_deles() -> None:
    m = Mundo(*[pedido(texto_livre="vestido")] * 2)
    for i in range(1, 151):
        destaque = 3 if i > 110 else None
        m.com(job(f"j{i}"), objeto(f"o{i}", f"j{i}", 0, 1_000, destaque=destaque))
    enviados: list[str] = []

    class RankingEspiao:
        def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
            enviados.extend(r.job_id for r in registros)
            return registros

    ranqueados = todas_as_paginas(m.busca(ranking=RankingEspiao()))

    assert len(enviados) == TETO_DO_RANKING
    assert any(j in enviados for j in ("j111", "j150")) is False
    assert ranqueados[:100] == enviados


@pytest.mark.parametrize(
    "estrago",
    [
        {"conteudo": b"invalido"},
        {"conteudo": zlib.compress(b"nao e json")},
        {"conteudo": zlib.compress(b'{"videos": 3}')},
        {"dono": None},
    ],
)
def test_documento_da_lista_estragado_e_cursor_invalido(
    estrago: dict[str, Any],
) -> None:
    busca, cursor, _ = _cursor_valido()
    id, _, _ = cursor.partition(".")
    documento = busca._listas.documentos[id]  # type: ignore[attr-defined]
    documento.update(estrago)

    with pytest.raises(CursorInvalido):
        busca.buscar("vestido", cursor=cursor, dono="u1", limite=2)


def test_video_que_vai_para_a_lixeira_entre_as_paginas_some_da_seguinte() -> None:
    m = mundo_de_videos(4)
    busca = m.busca()
    primeira = busca.buscar("vestido", limite=2, dono="u1")
    seguintes = [
        v.job_id
        for v in busca.buscar(
            "vestido", limite=2, dono="u1", cursor=primeira._proximo_cursor
        ).videos
    ]
    lixo = EnvioParaLixeira(
        em=BASE, por_uid="adm", por_email="adm@redetv.com", motivo="duplicado"
    )
    j = m.jobs.obter(seguintes[0])
    assert j is not None
    m.jobs.salvar(j.model_copy(update={"lixeira": lixo}))

    segunda = busca.buscar(
        "vestido", limite=2, dono="u1", cursor=primeira._proximo_cursor
    )

    assert [v.job_id for v in segunda.videos] == seguintes[1:]


def _cursor_valido() -> tuple[Busca, str, list[datetime]]:
    agora = [BASE]
    m = mundo_de_videos(5)
    busca = m.busca(relogio=lambda: agora[0])
    cursor = busca.buscar("vestido", limite=2, dono="u1")._proximo_cursor
    assert cursor is not None
    return busca, cursor, agora


@pytest.mark.parametrize(
    "mudanca",
    [
        "outro-dono",
        "outra-consulta",
        "outro-filtro",
        "outra-ordem",
        "expirado",
        "sem-ponto",
        "posicao-nao-numero",
        "posicao-zero",
        "posicao-alem-do-fim",
        "posicao-unicode",
        "id-com-barra",
        "id-desconhecido",
    ],
)
def test_cursor_adulterado_de_outro_dono_ou_vencido_e_invalido(mudanca: str) -> None:
    busca, cursor, agora = _cursor_valido()
    id, _, _ = cursor.partition(".")
    pedido_: dict[str, Any] = {"cursor": cursor, "dono": "u1", "limite": 2}
    texto = "vestido"
    if mudanca == "outro-dono":
        pedido_["dono"] = "u2"
    elif mudanca == "outra-consulta":
        texto = "vermelho"
    elif mudanca == "outro-filtro":
        pedido_["ajustes"] = Ajustes(programa="TV Fama")
    elif mudanca == "outra-ordem":
        pedido_["ordem"] = "data"
    elif mudanca == "expirado":
        agora[0] = BASE + timedelta(minutes=15)
    else:
        pedido_["cursor"] = {
            "sem-ponto": id,
            "posicao-nao-numero": f"{id}.x",
            "posicao-zero": f"{id}.0",
            "posicao-alem-do-fim": f"{id}.5",
            "posicao-unicode": f"{id}.²",
            "id-com-barra": f"a/{id}.2",
            "id-desconhecido": f"{id}ff.2",
        }[mudanca]

    with pytest.raises(CursorInvalido):
        busca.buscar(texto, **pedido_)


def test_o_cursor_ainda_vale_um_pouco_antes_de_vencer() -> None:
    busca, cursor, agora = _cursor_valido()
    agora[0] = BASE + timedelta(minutes=14)

    assert busca.buscar("vestido", cursor=cursor, dono="u1", limite=2).videos


def test_a_lista_de_500_momentos_com_o_texto_maximo_cabe_no_documento() -> None:
    sorteio = random.Random(0)
    letras = "abcdefghijklmnopqrstuvwxyzáéíóãç     "

    def texto() -> str:
        return "".join(sorteio.choice(letras) for _ in range(2_000))

    lista = ListaDaBusca(
        dono="u1",
        impressao="0" * 64,
        criado_em=BASE,
        expira_em=BASE,
        entendida=Entendida(evidencias=[], programa=None, desde=None, ate=None),
        sem_aparicoes=[],
        plano_b=False,
        facetas=Facetas(),
        termos=["vestido"],
        videos=[
            VideoGuardado(
                job_id=f"{i:032x}",
                momentos=[
                    MomentoGuardado(
                        tipo="fala",
                        inicio_ms=i * 1_000,
                        fim_ms=i * 1_000 + 999,
                        motivo=f"Fala: '{texto()}'",
                        quadro=f"quadros/plano-{i}.jpg",
                    )
                ],
            )
            for i in range(TETO_DE_REGISTROS)
        ],
    )

    documento = lista.para_documento()

    assert len(documento["conteudo"]) < TETO_DA_LISTA_BYTES
    assert ListaDaBusca.do_documento(documento) == lista


def test_lista_grande_demais_perde_o_fim_e_segue_paginando(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.busca.TETO_DA_LISTA_BYTES", 330)
    m = mundo_de_videos(40)
    busca = m.busca()

    primeira = busca.buscar("vestido", limite=2, dono="u1")
    vistos = [v.job_id for v in primeira.videos]
    cursor = primeira._proximo_cursor
    while cursor:
        pagina = busca.buscar("vestido", limite=2, dono="u1", cursor=cursor)
        vistos += [v.job_id for v in pagina.videos]
        cursor = pagina._proximo_cursor

    assert 2 < len(vistos) < 40 and len(set(vistos)) == len(vistos)


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


def test_consulta_de_ate_300_caracteres_passa_e_de_301_responde_422() -> None:
    c, _ = cliente(["consulta"], pedido(texto_livre="a"))
    ok = c.get("/v1/busca", params={"q": "a" * 300}, headers=AUTORIZACAO)
    longa = c.get("/v1/busca", params={"q": "a" * 301}, headers=AUTORIZACAO)
    assert ok.status_code == 200
    assert longa.status_code == 422


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


def _por_destaque(
    destaque: int | None, id: str, inicio: int, **mudancas: Any
) -> Registro:
    return objeto(
        id,
        "j1",
        inicio,
        inicio + 1_000,
        **{
            "destaque": destaque,
            "texto": "carro azul, veículo, objeto de cena",
        }
        | mudancas,
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


def test_objeto_de_destaque_1_e_achado_mesmo_com_outra_categoria_na_consulta() -> None:
    # A consulta classificou "abajur" como móvel; o inventário o gravou como decoração.
    abajur = {"categoria": "movel", "tipo": "abajur", "cor_base": None, "pessoa": None}
    m = Mundo(pedido(objetos=[abajur]))
    m.com(
        job("j1"),
        _por_destaque(
            1,
            "a",
            0,
            categoria="decoracao",
            tipo_do_objeto="abajur",
            texto="abajur, decoração, objeto de cena",
        ),
    )
    [video] = m.busca().buscar("abajur").videos
    assert [x.inicio_ms for x in video.momentos] == [0]


def test_com_o_objeto_pedido_o_destaque_maior_vem_antes() -> None:
    cadeira = {
        "categoria": "movel",
        "tipo": "cadeira",
        "cor_base": None,
        "pessoa": None,
    }
    m = Mundo(pedido(objetos=[cadeira]))
    m.com(
        job("j1"),
        *(
            _por_destaque(
                d,
                id,
                inicio,
                categoria="movel",
                tipo_do_objeto="cadeira",
                texto="cadeira, móvel, objeto de cena",
            )
            for d, id, inicio in ((1, "baixo", 0), (2, "alto", 60_000))
        ),
    )
    [video] = m.busca().buscar("cadeira").videos
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
        objeto(
            "a",
            "j1",
            0,
            1_000,
            marca="Nike",
            dono=m.sabrina,
            data_de_exibicao=date(2024, 5, 1),
        ),
        objeto(
            "b",
            "j1",
            5_000,
            6_000,
            marca="Nike",
            dono=m.sabrina,
            data_de_exibicao=date(2024, 5, 1),
        ),
    )
    m.com(
        job("j2", programa="Leo Dias", data_exibicao=date(2024, 6, 2)),
        objeto(
            "c",
            "j2",
            0,
            1_000,
            marca="Adidas",
            programa="Leo Dias",
            data_de_exibicao=date(2024, 6, 2),
        ),
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
    assert [(v.valor, v.rotulo) for v in f.mes] == [
        ("2024-06", "06/2024"),
        ("2024-05", "05/2024"),
    ]
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


def test_faceta_filtra_no_indice_e_nao_so_entre_os_registros_do_teto() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    # Mais registros que o teto de cada cláusula; o da Adidas fica de fora sem o filtro.
    m.com(
        job("j1"),
        *(objeto(f"n{i}", "j1", i * 1_000, i * 1_000 + 500) for i in range(120)),
    )
    m.com(job("j2"), objeto("z", "j2", 0, 1_000, marca="Adidas"))

    r = buscar(m, "vestido", ajustes=Ajustes(marca="Adidas"))

    assert [v.job_id for v in r.videos] == ["j2"]
    assert all(c.filtros.marca == "Adidas" for c in m.indice.consultas)


def test_faceta_de_pessoa_casa_na_imagem_e_como_dona_do_objeto() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    plano = Registro(
        id="p",
        tipo="plano",
        job_id="j2",
        inicio_ms=0,
        fim_ms=1_000,
        pessoas=[m.sabrina],
        descricao="vestido no palco",
        texto="vestido no palco",
    )
    m.com(job("j1"), objeto("a", "j1", 0, 1_000, dono=m.sabrina))
    m.com(job("j2"), plano)
    m.com(job("j3"), objeto("b", "j3", 0, 1_000, dono="outra"))

    r = buscar(m, "vestido", ajustes=Ajustes(pessoa=m.sabrina))

    assert sorted(v.job_id for v in r.videos) == ["j1", "j2"]


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


def test_a_rota_devolve_facetas_com_e_sem_filtro() -> None:
    c, m = cliente(["consulta"], *[pedido(texto_livre="vestido")] * 3)
    m.com(
        job("j2", programa="Leo Dias"),
        objeto("b", "j2", 0, 1_000, marca="Adidas", programa="Leo Dias"),
    )

    sem = c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO)
    com = c.get(
        "/v1/busca", params={"q": "vestido", "marca": "Adidas"}, headers=AUTORIZACAO
    )
    vazia = c.get(
        "/v1/busca",
        params={"q": "vestido", "marca": "Nike", "tipo": "objeto", "pessoa": "p1"},
        headers=AUTORIZACAO,
    )

    assert contagens(sem.json()["facetas"]["programa"]) == {
        "TV Fama": 1,
        "Leo Dias": 1,
    }
    assert contagens(com.json()["facetas"]["programa"]) == {"Leo Dias": 1}
    assert contagens(com.json()["facetas"]["marca"]) == {"Adidas": 1}
    assert vazia.status_code == 200
    assert vazia.json()["videos"] == []
    assert (
        c.get(
            "/v1/busca", params={"q": "v", "tipo": "inventado"}, headers=AUTORIZACAO
        ).status_code
        == 422
    )


def plano(id: str, descricao: str = "plano") -> Registro:
    return Registro(
        id=id,
        tipo="plano",
        job_id="j1",
        inicio_ms=int(id[-1]) * 10_000,
        fim_ms=int(id[-1]) * 10_000 + 5_000,
        descricao=descricao,
        quadro=f"quadros/{id}.jpg",
    )


def mundo_de_planos(*respostas: str) -> Mundo:
    m = Mundo(*(respostas or (pedido(texto_livre="pista molhada"),) * 4))
    m.com(
        job("j1"),
        plano("j1:plano:1", "rua escura"),
        plano("j1:plano:2", "estúdio"),
    )
    return m


def _planos(m: Mundo, *descricoes: str) -> None:
    m.com(
        job("j1"),
        *(
            Registro(
                id=f"j1:plano:{i}",
                tipo="plano",
                job_id="j1",
                inicio_ms=i * 1_000,
                fim_ms=i * 1_000 + 500,
                descricao=d,
            )
            for i, d in enumerate(descricoes)
        ),
    )


FRASES = (
    "vestido amarelo",
    "Vestido Amarelo",
    "um vestido azul",
    "um carro amarelo",
    "amarelo e vestido",
    "calça vinho",
)


def _achados(resultado: Any) -> list[int]:
    return sorted(
        int(m.inicio_ms) // 1_000 for v in resultado.videos for m in v.momentos
    )


@pytest.mark.parametrize("modelo", [True, False])
def test_frase_entre_aspas_so_deixa_quem_tem_a_frase_inteira(modelo: bool) -> None:
    # Com o modelo, e no plano B (resposta inválida): o código lê as aspas.
    m = Mundo(pedido(texto_livre="vestido amarelo") if modelo else "isto nao e json")
    _planos(m, *FRASES)
    resultado = buscar(m, '"vestido amarelo"')
    assert _achados(resultado) == [0, 1]


def test_frase_e_resto_da_consulta_ficam_so_com_a_frase() -> None:
    m = Mundo("isto nao e json")
    _planos(m, *FRASES)
    resultado = buscar(m, '"vestido amarelo" calça')
    assert _achados(resultado) == [0, 1]


def test_sem_aspas_vale_qualquer_palavra() -> None:
    m = Mundo("isto nao e json")
    _planos(m, *FRASES)
    resultado = buscar(m, "vestido amarelo")
    assert _achados(resultado) == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("consulta", ['vestido "amarelo', 'vestido ""', '"'])
def test_aspas_soltas_ou_vazias_nao_quebram(consulta: str) -> None:
    m = Mundo("isto nao e json")
    _planos(m, *FRASES)
    buscar(m, consulta)


def test_a_frase_filtra_fala_texto_na_tela_e_objeto() -> None:
    m = Mundo("isto nao e json")
    tipos: list[Any] = ["fala", "texto_na_tela", "objeto"]
    m.com(
        job("j1"),
        *(
            Registro(
                id=f"j1:{t}:{i}",
                tipo=t,
                job_id="j1",
                inicio_ms=(len(tipos) * i + n) * 1_000,
                fim_ms=(len(tipos) * i + n) * 1_000 + 500,
                texto=frase,
            )
            for i, frase in enumerate(("Vestido amarelo!", "amarelo e vestido"))
            for n, t in enumerate(tipos)
        ),
    )
    assert _achados(buscar(m, '"vestido amarelo"')) == [0, 1, 2]


class IndicePorSignificado(IndiceEspia):
    """Como a busca por significado: devolve tudo, com ou sem as palavras."""

    def buscar(self, consulta: Consulta) -> list[Registro]:
        self.consultas.append(consulta)
        return IndiceEmMemoria.buscar(self, replace(consulta, texto=None))


def test_a_frase_tira_o_que_vem_so_da_busca_por_significado() -> None:
    m = Mundo("isto nao e json")
    m.indice = IndicePorSignificado()
    _planos(m, "vestido amarelo", "calça vinho", "camiseta verde limão")
    assert _achados(buscar(m, '"vestido amarelo"')) == [0]


def test_a_frase_nao_se_repete_quando_o_modelo_a_poe_no_texto_livre() -> None:
    m = Mundo(pedido(texto_livre="Vestido Amarelo"))
    _planos(m, *FRASES)
    buscar(m, '"vestido amarelo"')
    # A frase não entra duas vezes; cada palavra vai com o outro número dela (#405).
    assert {c.texto for c in m.indice.consultas if c.texto} == {
        "Vestido vestidos Amarelo amarelos"
    }


def test_a_frase_continua_filtrando_com_qualquer_chip() -> None:
    m = Mundo("isto nao e json")
    _planos(m, *FRASES)
    resultado = buscar(m, '"vestido amarelo"', ajustes=Ajustes(evidencias=("objeto",)))
    assert _achados(resultado) == [0, 1]


class ArmazenamentoQueConta(ArmazenamentoFalso):
    def __init__(self) -> None:
        super().__init__()
        self.assinaturas = 0
        self.simultaneas = 0
        self.mais_simultaneas = 0
        self._trava = threading.Lock()

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        with self._trava:
            self.assinaturas += 1
            self.simultaneas += 1
            self.mais_simultaneas = max(self.mais_simultaneas, self.simultaneas)
        time.sleep(0.005)  # a ida ao IAM
        try:
            return super().url_do_quadro(job_id, caminho, validade)
        finally:
            with self._trava:
                self.simultaneas -= 1


def mundo_de_cem_planos() -> tuple[Mundo, ArmazenamentoQueConta]:
    m = Mundo(pedido(texto_livre="rua"))
    armazenamento = ArmazenamentoQueConta()
    m.armazenamento = armazenamento
    m.com(
        job("j1", sistema="legado"),
        *[
            replace(
                plano("j1:plano:1", "rua escura"),
                id=f"j1:plano:{i}",
                inicio_ms=i * 10_000,
                fim_ms=i * 10_000 + 500,
                quadro=f"quadros/plano-{i}.jpg",
            )
            for i in range(100)
        ],
    )
    return m, armazenamento


def test_para_a_web_a_busca_de_cem_planos_nao_assina_nenhum_quadro() -> None:
    m, armazenamento = mundo_de_cem_planos()

    r = m.busca().buscar("rua", limite=50)

    momentos = [mo for v in r.videos for mo in v.momentos]
    assert len(momentos) == 100
    assert armazenamento.assinaturas == 0
    assert all(mo.quadro and mo.quadro_url is None for mo in momentos)


def test_para_chave_de_sistema_o_quadro_url_continua_vindo_assinado() -> None:
    m, armazenamento = mundo_de_cem_planos()

    r = m.busca().buscar("rua", sistema="legado")

    momentos = [mo for v in r.videos for mo in v.momentos]
    assert armazenamento.assinaturas == len(momentos) == 100
    assert all(
        mo.quadro and mo.quadro_url and mo.quadro in mo.quadro_url for mo in momentos
    )


def test_os_quadros_da_busca_saem_assinados_por_8_h() -> None:
    m, _ = mundo_de_cem_planos()

    r = m.busca().buscar("rua", sistema="legado")

    momentos = [mo for v in r.videos for mo in v.momentos]
    assert momentos
    assert all(str(mo.quadro_url).endswith("?validade=28800") for mo in momentos)
    # A URL vale 8 h, mas pode ter sido assinada até 1 h antes (#409): informa 7 h.
    assert r.quadros_expiram_em == BASE + timedelta(hours=7)


def test_a_chave_de_sistema_nao_assina_os_quadros_dos_videos_cortados_pelo_limite() -> (
    None
):
    m, armazenamento = mundo_de_cem_planos()
    m.com(
        job("j2", sistema="legado"),
        replace(
            plano("j1:plano:1", "rua escura"),
            id="j2:plano:0",
            job_id="j2",
            quadro="quadros/plano-0.jpg",
        ),
    )

    r = m.busca().buscar("rua", sistema="legado", limite=1)

    assert len(r.videos) == 1
    assert armazenamento.assinaturas == r.videos[0].n_momentos


def test_as_assinaturas_da_chave_de_sistema_vao_em_paralelo_ate_o_teto() -> None:
    m, armazenamento = mundo_de_cem_planos()

    m.busca().buscar("rua", sistema="legado")

    assert 1 < armazenamento.mais_simultaneas <= TETO_DE_ASSINATURAS


def test_busca_cancelada_para_antes_de_consultar_o_indice() -> None:
    m = mundo_de_planos()
    cancelado = threading.Event()
    cancelado.set()

    with pytest.raises(BuscaCancelada):
        m.busca().buscar("pista molhada", cancelado=cancelado)

    assert m.indice.consultas == []


def test_busca_cancelada_no_meio_das_assinaturas_para_de_assinar() -> None:
    m, armazenamento = mundo_de_cem_planos()
    cancelado = threading.Event()
    assinar = armazenamento.url_do_quadro

    def assina_e_desiste(job_id: str, caminho: str, validade: timedelta) -> str:
        # A rota passa do prazo na terceira assinatura.
        if armazenamento.assinaturas >= 2:
            cancelado.set()
        return assinar(job_id, caminho, validade)

    armazenamento.url_do_quadro = assina_e_desiste  # type: ignore[method-assign]

    with pytest.raises(BuscaCancelada):
        m.busca().buscar("rua", sistema="legado", cancelado=cancelado)

    # As que já tinham começado terminam; as que esperavam na fila não assinam.
    assert armazenamento.assinaturas < 3 + TETO_DE_ASSINATURAS


def test_o_openapi_marca_o_quadro_url_como_obsoleto() -> None:
    esquema = criar_app().openapi()["components"]["schemas"]["Momento"]

    quadro_url = esquema["properties"]["quadro_url"]
    assert quadro_url["deprecated"] is True
    assert "`quadro`" in quadro_url["description"]
    assert "/v1/jobs/{job_id}/quadros/{arquivo}" in quadro_url["description"]


# Singular e plural dão o mesmo resultado (#405).
PARES_DE_NUMERO = [
    ("microfone", "microfones", "microfone", "microfones"),
    ("cadeira", "cadeiras", "cadeira", "cadeiras"),
    ("vestido vermelho", "vestidos vermelhos", "vestido", "vestidos"),
]


@pytest.mark.parametrize("singular, plural, tipo, tipo_plural", PARES_DE_NUMERO)
@pytest.mark.parametrize("no_indice", ["singular", "plural"])
@pytest.mark.parametrize("pedida", ["singular", "plural"])
def test_objeto_pedido_no_singular_ou_no_plural_acha_o_mesmo_momento(
    singular: str,
    plural: str,
    tipo: str,
    tipo_plural: str,
    no_indice: str,
    pedida: str,
) -> None:
    na_consulta = tipo if pedida == "singular" else tipo_plural
    no_registro = tipo if no_indice == "singular" else tipo_plural
    consulta = singular if pedida == "singular" else plural
    m = Mundo(
        pedido(
            objetos=[{"categoria": "produto", "tipo": na_consulta}],
            evidencias=["objeto"],
        )
    )
    m.com(
        job("j1"),
        objeto(
            "j1:objeto:0",
            "j1",
            1_000,
            2_000,
            categoria="produto",
            tipo_do_objeto=no_registro,
            cor_base=[],
            cor=None,
            texto=no_registro,
        ),
    )
    assert [v.job_id for v in buscar(m, consulta).videos] == ["j1"]


@pytest.mark.parametrize(
    "pedida, no_texto",
    [
        ("promoção", "A promoções da semana"),
        ("promoções", "Veja a promoção da semana"),
        ("animais", "Cada animal come"),
        ("mulher", "As mulheres falaram"),
        ("homens", "O homem falou"),
    ],
)
def test_texto_livre_no_singular_ou_plural_acha_a_fala_e_destaca_as_duas_formas(
    pedida: str, no_texto: str
) -> None:
    m = Mundo(pedido(texto_livre=pedida))
    m.com(
        job("j1"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto=no_texto,
        ),
    )
    momento = buscar(m, pedida).videos[0].momentos[0]
    destacado = " ".join(momento.motivo[d.inicio : d.fim] for d in momento.destaques)
    palavra_do_texto = next(
        p for p in no_texto.split() if p.lower()[:4] == pedida.lower()[:4]
    )
    assert destacado == palavra_do_texto


def test_frase_exata_com_o_numero_trocado_ainda_vale() -> None:
    m = Mundo(pedido(frase_exata="promoção imperdível"))
    m.com(
        job("j1"),
        Registro(
            id="f1",
            tipo="fala",
            job_id="j1",
            inicio_ms=0,
            fim_ms=1_000,
            texto="Todas as promoções imperdíveis",
        ),
    )
    assert [v.job_id for v in buscar(m, '"promoção imperdível"').videos] == ["j1"]


def test_video_na_lixeira_do_indice_nao_ocupa_o_teto_de_registros() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    envio = EnvioParaLixeira(
        em=datetime(2026, 11, 2, tzinfo=UTC),
        por_uid="adm",
        por_email="adm@redetv.com",
        motivo="duplicado",
    )
    m.com(
        job("lixo", lixeira=envio),
        *[objeto(f"l{i}", "lixo", i, i + 1, na_lixeira=True) for i in range(600)],
    )
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))

    resultado = m.busca().buscar("vestido", filtros_do_servidor=filtros_do_servidor())

    assert [v.job_id for v in resultado.videos] == ["j1"]
    assert {c.filtros.na_lixeira for c in m.indice.consultas} == {False}


def test_o_filtro_do_indice_so_tira_inelegiveis_a_regra_segue_no_job() -> None:
    m = Mundo(pedido(texto_livre="vestido"))
    envio = EnvioParaLixeira(
        em=datetime(2026, 11, 2, tzinfo=UTC),
        por_uid="adm",
        por_email="adm@redetv.com",
        motivo="duplicado",
    )
    # O objeto ainda diz `na_lixeira=False` (o Job foi para a lixeira e o índice atrasou).
    m.com(job("j1", lixeira=envio), objeto("a", "j1", 0, 1_000, na_lixeira=False))
    m.com(job("j2"), objeto("b", "j2", 0, 1_000))

    resultado = m.busca().buscar("vestido", filtros_do_servidor=filtros_do_servidor())

    assert [v.job_id for v in resultado.videos] == ["j2"]


def test_chave_de_sistema_filtra_o_sistema_no_indice_e_o_resultado_nao_muda() -> None:
    m = Mundo(pedido(texto_livre="vestido"), pedido(texto_livre="vestido"))
    m.com(job("j1", sistema="outro"), objeto("a", "j1", 0, 1_000, sistema="outro"))
    m.com(job("j2", sistema="legado"), objeto("b", "j2", 0, 1_000, sistema="legado"))

    resultado = m.busca().buscar("vestido", sistema="outro")
    assert [v.job_id for v in resultado.videos] == ["j1"]
    assert {c.filtros.sistema for c in m.indice.consultas} == {"outro"}

    # A web (sem sistema) não filtra por ele e vê os dois.
    m.indice.consultas.clear()
    todos = m.busca().buscar("vestido")
    assert {v.job_id for v in todos.videos} == {"j1", "j2"}
    assert {c.filtros.sistema for c in m.indice.consultas} == {None}


def test_sem_nada_inelegivel_o_resultado_e_o_mesmo_com_e_sem_o_filtro() -> None:
    def rodar(filtros: Filtros | None) -> list[str]:
        m = Mundo(pedido(texto_livre="vestido"))
        for i in range(3):
            m.com(job(f"j{i}"), objeto(f"o{i}", f"j{i}", 0, 1_000))
        return [
            v.job_id
            for v in m.busca().buscar("vestido", filtros_do_servidor=filtros).videos
        ]

    assert rodar(filtros_do_servidor()) == rodar(Filtros())
