"""O Job da avaliação diária (#255), com o juiz, o Firestore e o Storage falsos."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from api.avaliacao import REQUISITOS, AvaliacaoFalhou, Nota, Rubrica, ler_rubricas
from api.avaliacao_job import AvaliacoesEmMemoria, concluidos_no_dia, executar, main
from api.decupagem import Decupagem
from api.jobs import Job, RepositorioEmMemoria

DIA = date(2026, 11, 2)
HORA = datetime(2026, 11, 2, 12, tzinfo=UTC)


def _job(
    id: str, programa: str, quando: datetime = HORA, estado: str = "concluido"
) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=1,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u",
        programa=programa,
        criado_em=quando,
        atualizado_em=quando,
    )


DECUPAGEM = Decupagem.model_validate(
    {
        "versao_esquema": "1.3",
        "video": {"sha256": "a" * 64, "duracao_ms": 6_000},
        "programa": {"resumo": "r", "blocos": []},
        "pautas": [],
        "pessoas": [],
        "planos": [],
        "comerciais": [],
        "transcricao": [],
        "versao_pipeline": "2026.11.1",
    }
)


class Decupagens:
    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return None if job_id == "sem" else DECUPAGEM


class Juiz:
    def __init__(self, nota: float = 80, falha_em: str | None = None) -> None:
        self.nota = nota
        self.falha_em = falha_em
        self.requisitos: list[str] = []

    def avaliar(self, rubrica: Rubrica, conteudo: str) -> Nota:
        self.requisitos.append(rubrica.requisito)
        if rubrica.requisito == self.falha_em:
            raise AvaliacaoFalhou("fora do ar")
        return Nota(nota=self.nota)


def _rodar(
    jobs: list[Job],
    juiz: Juiz,
    avaliacoes: AvaliacoesEmMemoria | None = None,
    **opcoes: Any,
) -> tuple[dict[str, Any], AvaliacoesEmMemoria, list[dict[str, Any]]]:
    repositorio = RepositorioEmMemoria()
    for j in jobs:
        repositorio.salvar(j)
    linhas: list[str] = []
    avaliacoes = avaliacoes or AvaliacoesEmMemoria()
    resumo = executar(
        DIA,
        repositorio,
        Decupagens(),
        juiz,
        avaliacoes,
        ler_rubricas(),
        registrar=linhas.append,
        **opcoes,
    )
    return resumo, avaliacoes, [json.loads(linha) for linha in linhas]


def test_so_os_concluidos_do_dia_entram() -> None:
    repositorio = RepositorioEmMemoria()
    ontem = HORA - timedelta(days=1)
    for j in (
        _job("hoje", "A"),
        _job("ontem", "A", ontem),
        _job("falho", "A", estado="falhou"),
    ):
        repositorio.salvar(j)
    assert [j.id for j in concluidos_no_dia(repositorio, DIA)] == ["hoje"]


def test_grava_nota_por_video_requisito_e_versao_do_pipeline() -> None:
    resumo, avaliacoes, _ = _rodar([_job("a", "A"), _job("b", "B")], Juiz(80))
    gravadas = avaliacoes.do_dia(DIA)
    assert {a.job_id for a in gravadas} == {"a", "b"}
    for a in gravadas:
        assert set(a.notas) == set(REQUISITOS)
        assert a.versao_pipeline == "2026.11.1"
    assert resumo["avaliados"] == 2


def test_falha_do_juiz_num_requisito_deixa_so_ele_de_fora() -> None:
    _, avaliacoes, linhas = _rodar([_job("a", "A")], Juiz(falha_em="broll"))
    (a,) = avaliacoes.do_dia(DIA)
    assert "broll" not in a.notas and len(a.notas) == 4
    assert any(linha.get("evento") == "avaliacao_falhou" for linha in linhas)


def test_rodar_de_novo_no_dia_nao_reavalia() -> None:
    juiz = Juiz()
    _, avaliacoes, _ = _rodar([_job("a", "A")], juiz)
    visto = len(juiz.requisitos)
    _rodar([_job("a", "A")], juiz, avaliacoes)
    assert len(juiz.requisitos) == visto


def test_video_sem_decupagem_e_pulado_com_aviso() -> None:
    resumo, _, linhas = _rodar([_job("sem", "A")], Juiz())
    assert resumo["avaliados"] == 0
    assert any("sem Decupagem" in linha.get("detalhe", "") for linha in linhas)


def test_queda_vira_log_estruturado_e_custo_sai_no_resumo() -> None:
    resumo, _, linhas = _rodar(
        [_job("a", "A")], Juiz(40), limiar=60, preco_por_mil_caracteres=0.5
    )
    quedas = [linha for linha in linhas if linha.get("evento") == "queda_de_qualidade"]
    assert {q["requisito"] for q in quedas} == set(REQUISITOS)
    assert resumo["custo_por_video_usd"] == resumo["custo_estimado_usd"] > 0


def test_queda_em_relacao_a_semana_anterior() -> None:
    avaliacoes = AvaliacoesEmMemoria()
    _rodar(
        [_job("x", "A", HORA - timedelta(days=2))], Juiz(100), avaliacoes
    )  # outro dia: só estoque
    # historico gravado à mão em um dia anterior
    from api.avaliacao import Avaliacao

    avaliacoes.gravar(
        Avaliacao(
            dia=DIA - timedelta(days=1),
            job_id="h",
            programa="A",
            versao_pipeline="v",
            notas={r: Nota(nota=100) for r in REQUISITOS},
            caracteres=1,
            avaliado_em=HORA,
        )
    )
    _, _, linhas = _rodar(
        [_job("a", "A")], Juiz(80), avaliacoes, limiar=50, queda_maxima=10
    )
    quedas = [linha for linha in linhas if linha.get("evento") == "queda_de_qualidade"]
    assert {q["motivo"] for q in quedas} == {"queda_na_semana"}


def test_main_sem_ambiente_sai_com_erro_de_uso(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main({}) == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err
