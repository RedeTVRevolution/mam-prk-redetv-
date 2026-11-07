"""O cache curto do painel e dos relatórios (#453): a segunda chamada igual não vai ao
BigQuery, a página e a pessoa saem da soma já lida, a auditoria segue e o dado vence no TTL."""

import threading
from datetime import date
from typing import Any

import pytest

from api.auditoria import FiltroDeAuditoria
from api.cache_curto import CacheCurto
from api.custo_do_painel import CustoEmMemoria
from api.jobs import RepositorioEmMemoria
from api.qualidade_do_painel import QualidadeEmMemoria
from api.relatorio_de_marcas import ConsultaComCache as MarcasComCache
from api.relatorio_de_marcas import ConsultaEmMemoria as MarcasEmMemoria
from api.resumos_de_uso import ResumosEmMemoria
from api.tempo_de_tela import ConsultaComCache as TempoDeTelaComCache
from api.tempo_de_tela import ConsultaEmMemoria as TempoDeTelaEmMemoria
from api.tests import test_relatorio_de_marcas as marcas
from api.tests import test_tempo_de_tela as tempo_de_tela
from api.tests.test_passadas import AUTORIZACAO
from api.tests.test_rotas_do_painel import LINHAS, USO, Mundo

# --- o cache ----------------------------------------------------------------------------


def test_guarda_pela_chave_e_vence_no_prazo() -> None:
    agora = [0.0]
    cache = CacheCurto(validade=60, relogio=lambda: agora[0])
    chamadas: list[str] = []

    def calcular(valor: str) -> Any:
        def chamar() -> str:
            chamadas.append(valor)
            return valor

        return chamar

    assert cache.obter("a", calcular("a1")) == "a1"
    assert cache.obter("a", calcular("a2")) == "a1"
    assert cache.obter("b", calcular("b1")) == "b1"
    agora[0] = 59.0
    assert cache.obter("a", calcular("a3")) == "a1"
    agora[0] = 60.0
    assert cache.obter("a", calcular("a4")) == "a4"
    assert chamadas == ["a1", "b1", "a4"]


def test_erro_nao_fica_guardado() -> None:
    cache = CacheCurto()

    def falha() -> None:
        raise RuntimeError("fora")

    with pytest.raises(RuntimeError):
        cache.obter("a", falha)

    assert cache.obter("a", lambda: 1) == 1


def test_o_maximo_de_chaves_joga_fora_a_mais_antiga() -> None:
    cache = CacheCurto(maximo=2)
    for chave in "abc":
        cache.obter(chave, lambda c=chave: c)  # type: ignore[misc]

    refeitas: list[str] = []
    cache.obter("a", lambda: refeitas.append("a"))
    cache.obter("c", lambda: refeitas.append("c"))

    assert refeitas == ["a"]


def test_quem_chega_junto_espera_uma_so_consulta() -> None:
    cache = CacheCurto()
    chamadas: list[int] = []
    dentro = threading.Event()
    solta = threading.Event()

    def lenta() -> int:
        chamadas.append(1)
        dentro.set()
        assert solta.wait(5)
        return 7

    resultados: list[int] = []
    primeira = threading.Thread(
        target=lambda: resultados.append(cache.obter("a", lenta))
    )
    segunda = threading.Thread(
        target=lambda: resultados.append(cache.obter("a", lenta))
    )
    primeira.start()
    assert dentro.wait(5)
    segunda.start()
    solta.set()
    primeira.join(5)
    segunda.join(5)

    assert resultados == [7, 7]
    assert chamadas == [1]


# --- o painel ---------------------------------------------------------------------------


class ResumosQueContam(ResumosEmMemoria):
    def __init__(self) -> None:
        super().__init__(LINHAS, ["Hoje", "Fofocalizando"], USO)
        self.consultas = 0

    def acessos(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().acessos(*a, **k)

    def uso_por_quem(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().uso_por_quem(*a, **k)

    def uso_por_programa(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().uso_por_programa(*a, **k)

    def correcoes(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().correcoes(*a, **k)

    def chamadas(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().chamadas(*a, **k)

    def programas(self) -> list[str]:
        self.consultas += 1
        return super().programas()

    def usuarios(self) -> list[str]:
        self.consultas += 1
        return super().usuarios()


class QualidadeQueConta(QualidadeEmMemoria):
    def __init__(self, resumos: ResumosQueContam) -> None:
        super().__init__([], [])
        self.resumos = resumos

    def taxa_de_correcao(self, *a: Any, **k: Any) -> Any:
        self.resumos.consultas += 1
        return super().taxa_de_correcao(*a, **k)

    def tempo_de_revisao(self, *a: Any, **k: Any) -> Any:
        self.resumos.consultas += 1
        return super().tempo_de_revisao(*a, **k)


@pytest.mark.parametrize(
    "rota", ["/acessos", "/videos", "/buscas", "/revisao", "/api", "/filtros"]
)
@pytest.mark.parametrize("params", [{}, {"formato": "csv"}])
def test_segunda_chamada_igual_nao_consulta_de_novo(
    rota: str, params: dict[str, str]
) -> None:
    resumos = ResumosQueContam()
    mundo = Mundo(
        ["diretoria"],
        resumos=resumos,
        qualidade=QualidadeQueConta(resumos),
        cache_do_painel=CacheCurto(),
    )

    primeira = mundo.get(rota, **params)
    consultas = resumos.consultas
    segunda = mundo.get(rota, **params)

    assert primeira.status_code == 200
    assert consultas > 0
    assert resumos.consultas == consultas
    assert segunda.text == primeira.text


def test_o_json_e_o_csv_do_mesmo_filtro_dividem_a_consulta() -> None:
    resumos = ResumosQueContam()
    mundo = Mundo(["diretoria"], resumos=resumos, cache_do_painel=CacheCurto())

    mundo.get("/buscas")
    consultas = resumos.consultas
    mundo.get("/buscas", formato="csv")

    assert resumos.consultas == consultas


class CustoQueConta(CustoEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.consultas = 0

    def custos(self, desde: date | None) -> Any:
        self.consultas += 1
        return super().custos(desde)


def test_segunda_chamada_igual_do_custo_nao_consulta_de_novo() -> None:
    faturamento = CustoQueConta()
    mundo = Mundo(
        ["diretoria"],
        faturamento=faturamento,
        jobs=RepositorioEmMemoria(),
        cache_do_painel=CacheCurto(),
    )

    respostas = [
        mundo.get("/custo"),
        mundo.get("/custo"),
        mundo.get("/custo", formato="csv"),
    ]

    assert [r.status_code for r in respostas] == [200, 200, 200]
    assert faturamento.consultas == 1


def test_filtro_diferente_consulta_de_novo() -> None:
    resumos = ResumosQueContam()
    mundo = Mundo(["diretoria"], resumos=resumos, cache_do_painel=CacheCurto())

    mundo.get("/acessos", desde="2026-11-01")
    mundo.get("/acessos", desde="2026-11-02")

    assert resumos.consultas == 2


def test_a_auditoria_registra_cada_abertura_mesmo_vinda_do_cache() -> None:
    resumos = ResumosQueContam()
    mundo = Mundo(["diretoria"], resumos=resumos, cache_do_painel=CacheCurto())

    for _ in range(3):
        mundo.get("/acessos")
    mundo.get("/acessos", formato="csv")
    mundo.get("/acessos", formato="csv")

    assert resumos.consultas == 1
    # A abertura repetida na janela já era uma só; cada exportação grava a sua.
    registros = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert sorted(r.acao for r in registros) == [
        "painel.aberto",
        "painel.exportado",
        "painel.exportado",
    ]


def test_o_dado_novo_aparece_depois_do_prazo() -> None:
    agora = [0.0]
    resumos = ResumosQueContam()
    mundo = Mundo(
        ["diretoria"],
        resumos=resumos,
        cache_do_painel=CacheCurto(validade=120, relogio=lambda: agora[0]),
    )

    mundo.get("/buscas")
    agora[0] = 119.0
    mundo.get("/buscas")
    assert resumos.consultas == 1
    agora[0] = 121.0
    mundo.get("/buscas")

    assert resumos.consultas == 2


def test_sem_cache_cada_chamada_consulta() -> None:
    resumos = ResumosQueContam()
    mundo = Mundo(["diretoria"], resumos=resumos)

    mundo.get("/acessos")
    mundo.get("/acessos")

    assert resumos.consultas == 2


# --- os relatórios ----------------------------------------------------------------------


class MomentosQueContam(TempoDeTelaEmMemoria):
    def __init__(self, copia: Any) -> None:
        super().__init__(copia)
        self.consultas = 0

    def somas(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().somas(*a, **k)

    def ranking(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().ranking(*a, **k)

    def videos_da_pessoa(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().videos_da_pessoa(*a, **k)


def test_trocar_de_pagina_no_tempo_de_tela_nao_consulta_de_novo() -> None:
    fonte = MomentosQueContam(tempo_de_tela._varias_pessoas())
    cliente = tempo_de_tela._cliente(consulta=TempoDeTelaComCache(fonte, CacheCurto()))
    rota = tempo_de_tela.ROTA
    puro = tempo_de_tela._cliente(
        consulta=TempoDeTelaEmMemoria(tempo_de_tela._varias_pessoas())
    )

    primeira = cliente.get(rota, params={"limite": 3}, headers=AUTORIZACAO)
    consultas = fonte.consultas
    segunda = cliente.get(
        rota,
        params={"limite": 3, "cursor": primeira.headers["X-Proximo-Cursor"]},
        headers=AUTORIZACAO,
    )
    videos = cliente.get(
        f"{rota}/videos", params={"pessoa_id": "c1"}, headers=AUTORIZACAO
    )
    csv_ = cliente.get(rota, params={"formato": "csv"}, headers=AUTORIZACAO)
    inteiro = cliente.get(rota, headers=AUTORIZACAO)

    assert consultas == 1  # uma só leitura das somas
    assert fonte.consultas == 1
    # O resultado é o mesmo do relatório sem cache.
    casos: list[tuple[dict[str, Any], Any]] = [
        ({"limite": 3}, primeira),
        (
            {"limite": 3, "cursor": primeira.headers["X-Proximo-Cursor"]},
            segunda,
        ),
        ({"formato": "csv"}, csv_),
        ({}, inteiro),
    ]
    for params, resposta in casos:
        esperado = puro.get(rota, params=params, headers=AUTORIZACAO)
        assert resposta.text == esperado.text
        assert resposta.headers.get("X-Proximo-Cursor") == esperado.headers.get(
            "X-Proximo-Cursor"
        )
    esperados = puro.get(
        f"{rota}/videos", params={"pessoa_id": "c1"}, headers=AUTORIZACAO
    )
    assert videos.json() == esperados.json()


def test_filtro_diferente_do_tempo_de_tela_consulta_de_novo() -> None:
    fonte = MomentosQueContam(tempo_de_tela._varias_pessoas())
    consulta = TempoDeTelaComCache(fonte, CacheCurto())

    consulta.ranking(None, None, None, 0, 5)
    consulta.ranking(None, date(2026, 1, 1), None, 0, 5)
    consulta.ranking(None, None, None, 5, 5)

    assert fonte.consultas == 2


class InsercoesQueContam(MarcasEmMemoria):
    def __init__(self, copia: Any) -> None:
        super().__init__(copia)
        self.consultas = 0

    def somas(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().somas(*a, **k)

    def ranking(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().ranking(*a, **k)

    def lista_da_marca(self, *a: Any, **k: Any) -> Any:
        self.consultas += 1
        return super().lista_da_marca(*a, **k)


def test_trocar_de_pagina_nas_marcas_nao_consulta_de_novo() -> None:
    fonte = InsercoesQueContam(marcas._copia())
    cliente = marcas._cliente(consulta=MarcasComCache(fonte, CacheCurto()))
    rota = marcas.ROTA
    puro = marcas._cliente(consulta=MarcasEmMemoria(marcas._copia()))

    primeira = cliente.get(rota, params={"limite": 1}, headers=AUTORIZACAO)
    segunda = cliente.get(
        rota,
        params={"limite": 1, "cursor": primeira.headers["X-Proximo-Cursor"]},
        headers=AUTORIZACAO,
    )
    lista = cliente.get(
        f"{rota}/insercoes", params={"marca": "Ambev"}, headers=AUTORIZACAO
    )
    csv_ = cliente.get(rota, params={"formato": "csv"}, headers=AUTORIZACAO)

    assert fonte.consultas == 1
    casos: list[tuple[dict[str, Any], Any]] = [
        ({"limite": 1}, primeira),
        ({"limite": 1, "cursor": primeira.headers["X-Proximo-Cursor"]}, segunda),
        ({"formato": "csv"}, csv_),
    ]
    for params, resposta in casos:
        esperado = puro.get(rota, params=params, headers=AUTORIZACAO)
        assert resposta.text == esperado.text
    esperada = puro.get(
        f"{rota}/insercoes", params={"marca": "Ambev"}, headers=AUTORIZACAO
    )
    assert lista.json() == esperada.json()
