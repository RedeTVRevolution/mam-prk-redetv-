"""Adaptadores do Model Armor e da Ranking e a montagem pelo ambiente, sem rede."""

import json
from typing import Any

import pytest
import requests

from api.busca_na_nuvem import (
    MODELO_DA_RANKING,
    TEMPO_DA_RANKING_S,
    RankingReal,
    adaptadores_da_busca,
    aquecer_na_partida,
    tocar_o_host,
)
from api.gemini import MODO_STANDARD, Chamada, ErroHttp, TransporteVertex
from api.indice_da_busca import Registro
from api.tests.test_gemini import RespostaFalsa, RespostaSemJson, SessaoFalsa


def test_configuracao_antiga_do_armor_nao_abre_sessao_sem_projeto() -> None:
    def sem_sessao() -> Any:
        raise AssertionError("não devia abrir sessão")

    adaptadores = adaptadores_da_busca(
        {"MODEL_ARMOR_MODELO": "m", "MODEL_ARMOR_REGIAO": "r"}, sem_sessao
    )
    assert adaptadores.transporte_da_consulta is None


def test_modelo_da_foto_independe_do_armor() -> None:
    adaptadores = adaptadores_da_busca(
        {"GCP_PROJECT_ID": "proj"}, lambda: SessaoFalsa()
    )
    assert isinstance(adaptadores.transporte_da_consulta, TransporteVertex)


def test_configuracao_antiga_do_armor_nao_envia_pedido() -> None:
    sessao = SessaoFalsa()
    adaptadores_da_busca(AMBIENTE, lambda: sessao)
    assert sessao.pedidos == []


@pytest.mark.parametrize(
    "ambiente", [{"MODEL_ARMOR_MODELO": "m"}, {"MODEL_ARMOR_REGIAO": "r"}]
)
def test_armor_parcial_nao_desliga_descricao_da_foto(ambiente: dict[str, str]) -> None:
    adaptadores = adaptadores_da_busca(
        {"GCP_PROJECT_ID": "proj", **ambiente}, lambda: SessaoFalsa()
    )
    assert isinstance(adaptadores.transporte_da_consulta, TransporteVertex)


def test_modelo_da_foto_sem_ranking() -> None:
    adaptadores = adaptadores_da_busca(
        {"GCP_PROJECT_ID": "proj"}, lambda: SessaoFalsa()
    )
    assert adaptadores.ranking is None


def test_sessao_e_compartilhada_pela_foto_e_ranking() -> None:
    sessoes: list[SessaoFalsa] = []

    def abrir() -> SessaoFalsa:
        sessao = SessaoFalsa()
        sessoes.append(sessao)
        return sessao

    adaptadores_da_busca(AMBIENTE, abrir)
    assert len(sessoes) == 1


@pytest.mark.parametrize(
    "falha, status", [(requests.Timeout("lento"), 503), (RespostaSemJson(200), 502)]
)
def test_falha_http_do_ranking_sobe(falha: Any, status: int) -> None:
    ranking, _ = _ranking(falha)
    with pytest.raises(ErroHttp) as erro:
        ranking.reordenar("q", [_r("a", "texto")])
    assert erro.value.status == status


def _r(id: str, texto: str | None = None, descricao: str | None = None) -> Registro:
    return Registro(
        id=id,
        tipo="fala",
        job_id="j",
        inicio_ms=0,
        fim_ms=1,
        texto=texto,
        descricao=descricao,
    )


def _ranking(*respostas: Any) -> tuple[RankingReal, SessaoFalsa]:
    sessao = SessaoFalsa(*respostas)
    return RankingReal("proj", "config-z", sessao), sessao


def _ordem(*ids: str) -> RespostaFalsa:
    return RespostaFalsa(200, {"records": [{"id": i, "score": 0.5} for i in ids]})


def test_ranking_monta_o_pedido_com_o_texto_de_cada_registro() -> None:
    ranking, sessao = _ranking(_ordem("a", "b"))

    ranking.reordenar(
        "bolsa vermelha", [_r("a", texto="oi"), _r("b", descricao="plano")]
    )

    pedido = sessao.pedidos[0]
    assert pedido["url"] == (
        "https://discoveryengine.googleapis.com/v1/projects/proj/locations/global"
        "/rankingConfigs/config-z:rank"
    )
    assert pedido["json"]["query"] == "bolsa vermelha"
    assert pedido["json"]["records"] == [
        {"id": "a", "content": "oi"},
        {"id": "b", "content": "plano"},
    ]


def test_ranking_devolve_os_registros_na_ordem_da_api() -> None:
    ranking, _ = _ranking(_ordem("c", "a", "b"))
    a, b, c = _r("a", "1"), _r("b", "2"), _r("c", "3")

    assert ranking.reordenar("q", [a, b, c]) == [c, a, b]


def test_ranking_mantem_no_fim_o_que_a_api_nao_devolveu_e_o_que_nao_tem_texto() -> None:
    ranking, sessao = _ranking(_ordem("b", "desconhecido"))
    a, b, vazio = _r("a", "1"), _r("b", "2"), _r("v")

    assert ranking.reordenar("q", [a, vazio, b]) == [b, a, vazio]
    assert [r["id"] for r in sessao.pedidos[0]["json"]["records"]] == ["a", "b"]


def test_ranking_manda_no_maximo_200_registros_e_o_resto_fica_no_fim() -> None:
    ranking, sessao = _ranking(_ordem("r1", "r0"))
    registros = [_r(f"r{i}", "t") for i in range(250)]

    ordem = ranking.reordenar("q", registros)

    assert len(sessao.pedidos[0]["json"]["records"]) == 200
    assert [r.id for r in ordem[:3]] == ["r1", "r0", "r2"]
    assert [r.id for r in ordem[-50:]] == [f"r{i}" for i in range(200, 250)]


def test_ranking_sem_nenhum_texto_nao_chama_a_api() -> None:
    ranking, sessao = _ranking()
    registros = [_r("v")]

    assert ranking.reordenar("q", registros) == registros
    assert sessao.pedidos == []


def test_ranking_erro_http_vira_excecao() -> None:
    ranking, _ = _ranking(RespostaFalsa(429))
    with pytest.raises(ErroHttp) as e:
        ranking.reordenar("q", [_r("a", "1")])
    assert e.value.status == 429


AMBIENTE = {
    "GCP_PROJECT_ID": "proj",
    "MODEL_ARMOR_MODELO": "modelo-y",
    "MODEL_ARMOR_REGIAO": "reg-x",
    "RANKING_CONFIG": "config-z",
}


def test_com_as_variaveis_a_busca_recebe_foto_e_ranking() -> None:
    adaptadores = adaptadores_da_busca(AMBIENTE, lambda: SessaoFalsa())

    assert isinstance(adaptadores.transporte_da_consulta, TransporteVertex)
    assert isinstance(adaptadores.ranking, RankingReal)


def test_sem_as_variaveis_ficam_os_substitutos_de_hoje() -> None:
    def sem_sessao() -> Any:
        raise AssertionError("não devia abrir sessão")

    adaptadores = adaptadores_da_busca({}, sem_sessao)
    assert adaptadores.transporte_da_consulta is None
    assert adaptadores.ranking is None


def test_foto_e_ranking_nao_dependem_da_configuracao_do_armor() -> None:
    so_ranking = adaptadores_da_busca(
        {"GCP_PROJECT_ID": "proj", "RANKING_CONFIG": "c"}, lambda: SessaoFalsa()
    )
    assert so_ranking.ranking is not None
    assert so_ranking.transporte_da_consulta is not None

    meio = adaptadores_da_busca(
        {"GCP_PROJECT_ID": "proj", "MODEL_ARMOR_MODELO": "m"}, lambda: SessaoFalsa()
    )
    assert meio.transporte_da_consulta is not None


def test_a_consulta_registra_o_uso_do_modelo_com_a_etapa_busca(
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpo = {
        "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 3,
            "thoughtsTokenCount": 2,
        },
    }
    adaptadores = adaptadores_da_busca(
        AMBIENTE, lambda: SessaoFalsa(RespostaFalsa(200, corpo))
    )
    assert adaptadores.transporte_da_consulta is not None
    chamada = Chamada(
        modelo="m", instrucao="i", video_uri="", esquema={}, rotulos={}, texto="oi"
    )

    adaptadores.transporte_da_consulta.gerar(chamada)

    registro = json.loads(capsys.readouterr().out)
    assert registro["evento"] == "uso_do_modelo"
    assert registro["etapa"] == "busca"
    assert registro["tokens_de_raciocinio"] == 2


def test_a_consulta_vai_em_standard_sem_os_cabecalhos_do_flex() -> None:
    sessao = SessaoFalsa(
        RespostaFalsa(200, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
    )
    chamada = Chamada(
        modelo="m",
        instrucao="i",
        video_uri="",
        esquema={},
        rotulos={},
        texto="<consulta>x</consulta>",
        timeout_s=10,
        modo=MODO_STANDARD,
    )

    TransporteVertex("proj", sessao).gerar(chamada)

    assert sessao.pedidos[0]["headers"] == {}


def test_ranking_usa_o_prazo_de_1_s_e_o_modelo_fixado() -> None:
    ranking, sessao = _ranking(_ordem("a"))
    ranking.reordenar("q", [_r("a", texto="oi")])
    assert TEMPO_DA_RANKING_S == 1.0
    assert sessao.pedidos[0]["timeout"] == 1.0
    assert sessao.pedidos[0]["json"]["model"] == "semantic-ranker-default-005"
    assert MODELO_DA_RANKING == "semantic-ranker-default-005"


class SessaoDeGet:
    def __init__(self) -> None:
        self.urls: list[tuple[str, float]] = []

    def get(self, url: str, timeout: float) -> None:
        self.urls.append((url, timeout))


def test_tocar_o_host_faz_um_get_barato() -> None:
    sessao = SessaoDeGet()
    tocar_o_host(sessao, "discoveryengine.googleapis.com")
    assert sessao.urls == [("https://discoveryengine.googleapis.com/", 5)]


def test_aquecer_na_partida_roda_em_segundo_plano_e_so_loga_a_falha(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feitas: list[str] = []

    def falha() -> None:
        raise RuntimeError("sem rede")

    aquecer_na_partida([falha, lambda: feitas.append("b")]).join(timeout=2)
    assert feitas == ["b"]
    assert "aquecimento da conexão falhou" in caplog.text


def test_o_aquecimento_da_ranking_so_existe_com_a_configuracao() -> None:
    sessao = SessaoDeGet()
    com = adaptadores_da_busca(AMBIENTE, lambda: sessao)  # type: ignore[arg-type,return-value]
    assert com.aquecer is not None
    com.aquecer()
    assert [u for u, _ in sessao.urls] == ["https://discoveryengine.googleapis.com/"]
    sem = adaptadores_da_busca({"GCP_PROJECT_ID": "proj"}, lambda: SessaoFalsa())
    assert sem.aquecer is None
