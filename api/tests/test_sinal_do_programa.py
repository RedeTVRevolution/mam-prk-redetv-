"""O sinal por programa (#287): eventos por hora de vídeo contra o histórico do programa."""

import json
from datetime import UTC, date, datetime
from typing import Any

from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaEmMemoria,
    LinhaDoMomento,
    PessoaDoMomento,
)
from api.indexacao import reindexar
from api.sinal_do_programa import (
    ConfigDoSinal,
    HistoricoBigQuery,
    HistoricoEmMemoria,
    SinalDoPrograma,
    eventos_por_hora,
    registro_do_desvio,
)
from api.tests.test_indexacao import Mundo

HORA_MS = 3_600_000
BASE = datetime(2026, 11, 1, tzinfo=UTC)


def _linhas(
    job_id: str,
    comerciais: int,
    *,
    programa: str | None = "Exemplo",
    dia: int = 1,
    duracao_ms: int | None = HORA_MS,
) -> list[LinhaDoMomento]:
    base: dict[str, Any] = {
        "job_id": job_id,
        "programa": programa,
        "data_de_exibicao": date(2026, 10, dia),
        "gravado_em": BASE,
        "duracao_do_video_ms": duracao_ms,
    }
    dona = [PessoaDoMomento("p1", "Ana")]
    return [
        LinhaDoMomento(tipo="fala", inicio_ms=0, fim_ms=10, **base),
        LinhaDoMomento(tipo="aparicao", inicio_ms=0, fim_ms=10, pessoas=dona, **base),
        LinhaDoMomento(tipo="mencao_na_fala", inicio_ms=0, fim_ms=1, **base),
        LinhaDoMomento(tipo="mencao_no_texto", inicio_ms=0, fim_ms=1, **base),
        LinhaDoMomento(tipo="pauta", inicio_ms=0, fim_ms=10, **base),
        *[
            LinhaDoMomento(tipo="comercial", inicio_ms=i, fim_ms=i + 1, **base)
            for i in range(comerciais)
        ],
    ]


def _historico(comerciais: list[int]) -> HistoricoEmMemoria:
    copia = CopiaEmMemoria()
    for i, n in enumerate(comerciais):
        copia.gravar(f"h{i}", _linhas(f"h{i}", n, dia=i + 1))
    return HistoricoEmMemoria(copia)


def _sinal(
    historico: HistoricoEmMemoria, *, n: int = 5, k: float = 2
) -> tuple[SinalDoPrograma, list[dict[str, Any]]]:
    saidas: list[dict[str, Any]] = []
    return (
        SinalDoPrograma(
            historico,
            ConfigDoSinal(videos=n, desvios=k),
            lambda x: saidas.append(json.loads(x)),
        ),
        saidas,
    )


def test_conta_os_eventos_por_hora_de_video() -> None:
    linhas = _linhas("j", 6, duracao_ms=HORA_MS // 2)
    assert eventos_por_hora(linhas) == {
        "aparicoes": 2.0,
        "mencoes": 4.0,
        "pautas": 2.0,
        "comerciais": 12.0,
    }


def test_sem_duracao_nao_ha_taxa() -> None:
    assert eventos_por_hora(_linhas("j", 1, duracao_ms=None)) is None


def test_dentro_do_normal_nao_loga() -> None:
    sinal, saidas = _sinal(_historico([4, 6, 5, 4, 6]))
    sinal.avaliar("j", "Exemplo", _linhas("j", 5, dia=20))
    assert saidas == []


def test_fora_dos_desvios_loga_programa_tipo_e_valor() -> None:
    sinal, saidas = _sinal(_historico([4, 6, 5, 4, 6]))
    sinal.avaliar("j", "Exemplo", _linhas("j", 30, dia=20))
    assert len(saidas) == 1
    assert saidas[0]["evento"] == "desvio_de_programa"
    assert saidas[0]["programa"] == "Exemplo"
    assert saidas[0]["tipo"] == "comerciais"
    assert saidas[0]["valor"] == 30.0
    assert saidas[0]["media"] == 5.0
    assert saidas[0]["job_id"] == "j"
    assert saidas[0]["severity"] == "WARNING"


def test_fora_para_baixo_tambem_loga() -> None:
    sinal, saidas = _sinal(_historico([20, 22, 21, 20, 22]))
    sinal.avaliar("j", "Exemplo", _linhas("j", 0, dia=20))
    assert [s["tipo"] for s in saidas] == ["comerciais"]


def test_programa_com_poucos_videos_nao_alerta() -> None:
    sinal, saidas = _sinal(_historico([4, 6, 5, 4]), n=5)
    sinal.avaliar("j", "Exemplo", _linhas("j", 300, dia=20))
    assert saidas == []


def test_o_proprio_video_nao_entra_no_historico() -> None:
    historico = _historico([4, 6, 5, 4, 6])
    historico.copia.gravar("j", _linhas("j", 30, dia=20))
    sinal, saidas = _sinal(historico)
    sinal.avaliar("j", "Exemplo", _linhas("j", 30, dia=20))
    assert len(saidas) == 1


def test_so_os_ultimos_n_videos_do_mesmo_programa() -> None:
    copia = CopiaEmMemoria()
    for i, n in enumerate([100, 100, 4, 6, 5, 4, 6]):
        copia.gravar(f"h{i}", _linhas(f"h{i}", n, dia=i + 1))
    copia.gravar("outro", _linhas("outro", 100, programa="Outro", dia=25))
    sinal, saidas = _sinal(HistoricoEmMemoria(copia))
    sinal.avaliar("j", "Exemplo", _linhas("j", 30, dia=20))
    assert saidas[0]["media"] == 5.0


def test_sem_programa_nao_avalia() -> None:
    sinal, saidas = _sinal(_historico([4, 6, 5, 4, 6]))
    sinal.avaliar("j", None, _linhas("j", 30, programa=None))
    assert saidas == []


def test_historico_sem_variacao_nao_alerta() -> None:
    sinal, saidas = _sinal(_historico([5, 5, 5, 5, 5]))
    sinal.avaliar("j", "Exemplo", _linhas("j", 30, dia=20))
    assert saidas == []


def test_registro_do_desvio_e_uma_linha_json() -> None:
    from api.sinal_do_programa import Desvio

    linha = registro_do_desvio("j", "P", Desvio("pautas", 9.0, 3.0, 1.0, 5), 2)
    dados = json.loads(linha)
    assert dados["tipo"] == "pautas" and dados["limite_de_desvios"] == 2
    assert "\n" not in linha


def test_a_consulta_do_bigquery_traz_media_e_desvio_do_programa() -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        # videos, depois media e desvio de aparicoes, mencoes, pautas, comerciais
        valores = ["5", "1", "0.5", "2", "0", "1", "0", "5", "1.5"]
        return {"jobComplete": True, "rows": [{"f": [{"v": v} for v in valores]}]}

    historico = HistoricoBigQuery(ConfigDoBigQuery("p", "d", "t", "r"), transporte)
    ref = historico.do_programa("Exemplo", "j", 5)
    assert ref["comerciais"].videos == 5
    assert (ref["comerciais"].media, ref["comerciais"].desvio) == (5.0, 1.5)
    assert ref["mencoes"].desvio == 0.0
    corpo = pedidos[0]
    assert "STDDEV_SAMP" in corpo["query"] and "LIMIT @n" in corpo["query"]
    nomes = {p["name"]: p["parameterValue"]["value"] for p in corpo["queryParameters"]}
    assert nomes == {"programa": "Exemplo", "job_id": "j", "n": "5"}


def test_bigquery_sem_nenhum_video_devolve_referencia_vazia() -> None:
    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobComplete": True,
            "rows": [{"f": [{"v": "0"}] + [{"v": None}] * 8}],
        }

    ref = HistoricoBigQuery(
        ConfigDoBigQuery("p", "d", "t", "r"), transporte
    ).do_programa("E", "j", 5)
    assert all(r.videos == 0 for r in ref.values())


class _HistoricoQueFalha:
    def do_programa(self, programa: str, job_id: str, videos: int) -> Any:
        raise ConnectionError("BigQuery fora do ar")


def _reindexar_com(mundo: Mundo, sinal: SinalDoPrograma) -> None:
    job = mundo.jobs.obter("j1")
    assert job
    reindexar(
        job,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.indice,
        copia=mundo.copia,
        sinal=sinal,
    )


def test_a_indexacao_avalia_o_video_depois_de_copiar() -> None:
    copia = CopiaEmMemoria()
    historico = _historico([4, 6, 5, 4, 6])
    for j, linhas in historico.copia.por_job.items():
        copia.gravar(j, [x for x in linhas])
    sinal, saidas = _sinal(HistoricoEmMemoria(copia), n=5, k=0.0001)
    mundo = Mundo(copia=copia)
    _reindexar_com(mundo, sinal)
    assert saidas
    assert all(s["job_id"] == "j1" and s["programa"] == "Exemplo" for s in saidas)


def test_falha_do_sinal_nao_derruba_a_indexacao() -> None:
    mundo = Mundo(copia=CopiaEmMemoria())
    sinal = SinalDoPrograma(
        _HistoricoQueFalha(),
        ConfigDoSinal(5, 3),
        lambda _: None,
    )
    _reindexar_com(mundo, sinal)
    job = mundo.jobs.obter("j1")
    assert job and job.indexacao and job.indexacao.estado == "indexado"
    assert job.copia_bigquery and job.copia_bigquery.estado == "copiado"
