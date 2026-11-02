"""A avaliação diária por rubrica (#255): amostra, rubricas, juiz da Vertex e regra de queda."""

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from api.avaliacao import (
    REQUISITOS,
    Avaliacao,
    AvaliacaoFalhou,
    AvaliadorVertex,
    Nota,
    amostrar,
    detectar_quedas,
    em_pontos,
    ler_rubricas,
    registro_da_queda,
)
from api.jobs import Job

DIA = date(2026, 11, 2)
AGORA = datetime(2026, 11, 2, 12, tzinfo=UTC)


def job(id: str, programa: str | None) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=1,
        estado="concluido",
        criado_por="u",
        programa=programa,
        criado_em=AGORA,
        atualizado_em=AGORA,
    )


def avaliacao(dia: date, job_id: str, **notas: float) -> Avaliacao:
    return Avaliacao(
        dia=dia,
        job_id=job_id,
        programa=None,
        versao_pipeline="v",
        notas={r: Nota(nota=n) for r, n in notas.items()},
        caracteres=10,
        avaliado_em=AGORA,
    )


def test_as_rubricas_do_repositorio_cobrem_os_cinco_requisitos() -> None:
    rubricas = ler_rubricas()
    assert set(rubricas) == set(REQUISITOS)
    assert all(r.criterios and r.campos for r in rubricas.values())


def test_amostra_reproduzivel_com_ao_menos_um_por_programa() -> None:
    jobs = [job(f"a{i}", "A") for i in range(20)] + [job("b0", "B"), job("n0", None)]
    primeira = amostrar(jobs, DIA, 0.1, "s")
    assert [j.id for j in primeira] == [j.id for j in amostrar(jobs, DIA, 0.1, "s")]
    assert [j.programa for j in primeira].count("A") == 2
    assert {j.programa for j in primeira} == {"A", "B", None}


def test_amostra_muda_com_o_dia_e_com_a_semente() -> None:
    jobs = [job(f"a{i}", "A") for i in range(50)]
    ids = {j.id for j in amostrar(jobs, DIA, 0.1, "s")}
    assert ids != {j.id for j in amostrar(jobs, date(2026, 11, 3), 0.1, "s")}
    assert ids != {j.id for j in amostrar(jobs, DIA, 0.1, "outra")}


def test_fracao_fora_de_0_a_1_e_recusada() -> None:
    with pytest.raises(ValueError):
        amostrar([], DIA, 1.5, "s")


def test_queda_abaixo_do_limiar() -> None:
    quedas = detectar_quedas(
        [avaliacao(DIA, "a", pautas=50, broll=90)], [], limiar=60, queda_maxima=10
    )
    assert [(q.requisito, q.motivo) for q in quedas] == [("pautas", "abaixo_do_limiar")]


def test_queda_de_mais_que_x_pontos_da_media_dos_dias_anteriores() -> None:
    antes = [
        avaliacao(date(2026, 10, 30), "x", pautas=90),
        avaliacao(date(2026, 10, 31), "y", pautas=80),
    ]
    hoje = [avaliacao(DIA, "a", pautas=70)]
    (queda,) = detectar_quedas(hoje, antes, limiar=60, queda_maxima=10)
    assert (queda.motivo, queda.media_anterior) == ("queda_na_semana", 85)
    assert detectar_quedas(hoje, antes, limiar=60, queda_maxima=15) == []


def test_sem_historico_so_vale_o_limiar_e_requisito_sem_nota_nao_alerta() -> None:
    assert detectar_quedas([avaliacao(DIA, "a", pautas=80)], [], 60, 10) == []
    assert (
        detectar_quedas([], [avaliacao(date(2026, 10, 31), "x", pautas=90)], 60, 10)
        == []
    )


def test_registro_da_queda_e_json_estruturado_para_o_alerta() -> None:
    (queda,) = detectar_quedas([avaliacao(DIA, "a", pautas=50)], [], 60, 10)
    linha = json.loads(registro_da_queda(queda, DIA, {"videos": 3}))
    assert linha["evento"] == "queda_de_qualidade"
    assert linha["severity"] == "WARNING"
    assert (linha["requisito"], linha["dia"], linha["videos"]) == (
        "pautas",
        "2026-11-02",
        3,
    )


def test_nota_do_juiz_vira_0_a_100() -> None:
    assert [em_pontos(n) for n in (1, 3, 5, 9, 0)] == [0, 50, 100, 100, 0]


class SessaoFalsa:
    def __init__(self, status: int = 200, corpo: dict[str, Any] | None = None) -> None:
        self.status, self.corpo = status, corpo or {}
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> Any:
        self.chamadas.append((url, kwargs["json"]))
        sessao = self

        class Resposta:
            status_code = sessao.status

            def json(self) -> dict[str, Any]:
                return sessao.corpo

        return Resposta()


def test_avaliador_da_vertex_monta_o_pedido_e_le_a_nota() -> None:
    sessao = SessaoFalsa(
        corpo={"pointwiseMetricResult": {"score": 4, "explanation": "bom"}}
    )
    rubrica = ler_rubricas()["pautas"]
    nota = AvaliadorVertex("proj", "regiao", "juiz", sessao).avaliar(rubrica, "{}")
    assert nota == Nota(nota=75, explicacao="bom")
    url, corpo = sessao.chamadas[0]
    assert url.endswith("/locations/regiao:evaluateInstances")
    assert corpo["autoraterConfig"]["autoraterModel"].endswith("/models/juiz")
    modelo = corpo["pointwiseMetricInput"]["metricSpec"]["metricPromptTemplate"]
    assert "'pautas'" in modelo and "{conteudo}" in modelo


@pytest.mark.parametrize(
    "sessao",
    [
        SessaoFalsa(status=503),
        SessaoFalsa(corpo={"pointwiseMetricResult": {}}),
        SessaoFalsa(corpo={}),
        SessaoFalsa(corpo={"pointwiseMetricResult": {"score": "ruim"}}),
        SessaoFalsa(corpo={"pointwiseMetricResult": {"score": "nan"}}),
    ],
)
def test_avaliador_da_vertex_falha_sem_nota(sessao: SessaoFalsa) -> None:
    with pytest.raises(AvaliacaoFalhou):
        AvaliadorVertex("p", "r", "j", sessao).avaliar(ler_rubricas()["pautas"], "{}")
