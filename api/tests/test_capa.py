"""Quadro de capa do vídeo no Acervo (#162): o do primeiro plano com pessoa na imagem."""

from datetime import UTC, datetime
from pathlib import Path

from api.decupagem import Decupagem
from api.jobs import Job, RepositorioEmMemoria
from api.quadros_chave import capa_da_decupagem, executar
from api.tests.test_quadros_chave import QuadrosFalso, _video


def _decupagem(
    planos: list[tuple[int, int, str | None]], aparicoes: list[tuple[int, int]]
) -> Decupagem:
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.3",
            "video": {"sha256": "a" * 64, "duracao_ms": 6_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": [
                {
                    "id": "pes01",
                    "nome": "Fulana",
                    "na_imagem": [
                        {"inicio_ms": i, "fim_ms": f, "evidencia": "rosto"}
                        for i, f in aparicoes
                    ],
                    "citada_na_fala": [],
                    "citada_no_texto": [],
                }
            ],
            "planos": [
                {
                    "id": f"pla{n}",
                    "inicio_ms": i,
                    "fim_ms": f,
                    "ambiente": "estúdio",
                    "plano_limpo": True,
                    "quadro": q,
                }
                for n, (i, f, q) in enumerate(planos)
            ],
            "comerciais": [],
            "transcricao": [],
        }
    )


PLANOS: list[tuple[int, int, str | None]] = [
    (0, 2_000, "quadros/plano-0.jpg"),
    (2_000, 4_000, "quadros/plano-1.jpg"),
    (4_000, 6_000, "quadros/plano-2.jpg"),
]


def test_a_capa_e_o_quadro_do_primeiro_plano_com_pessoa_na_imagem() -> None:
    decupagem = _decupagem(PLANOS, [(4_500, 5_000), (2_200, 2_500)])

    assert capa_da_decupagem(decupagem) == "quadros/plano-1.jpg"


def test_sem_pessoa_na_imagem_a_capa_e_a_do_primeiro_plano() -> None:
    assert capa_da_decupagem(_decupagem(PLANOS, [])) == "quadros/plano-0.jpg"


def test_plano_sem_quadro_nao_vira_capa() -> None:
    planos = [(0, 2_000, None), *PLANOS[1:]]

    assert capa_da_decupagem(_decupagem(planos, [(500, 900)])) == "quadros/plano-1.jpg"
    assert capa_da_decupagem(_decupagem(planos, [])) == "quadros/plano-1.jpg"


def test_sem_planos_nao_ha_capa() -> None:
    assert capa_da_decupagem(_decupagem([], [(0, 1_000)])) is None


def test_o_job_guarda_o_caminho_da_capa(tmp_path: Path) -> None:
    repositorio = RepositorioEmMemoria()
    agora = datetime(2026, 10, 31, tzinfo=UTC)
    repositorio.salvar(
        Job(
            id="j1", nome="a.mp4", tamanho_bytes=1, estado="concluido",
            criado_por="u", criado_em=agora, atualizado_em=agora,
        )
    )  # fmt: skip
    sem_quadros = _decupagem([(i, f, None) for i, f, _ in PLANOS], [(2_200, 2_500)])
    armazenamento = QuadrosFalso(_video(tmp_path / "v.mp4"), sem_quadros)
    (tmp_path / "saida").mkdir()

    executar("j1", repositorio, armazenamento, tmp_path / "saida")

    job = repositorio.obter("j1")
    assert job is not None
    assert job.capa == "quadros/plano-1.jpg"


def test_reprocessar_sem_planos_tira_a_capa_antiga(tmp_path: Path) -> None:
    repositorio = RepositorioEmMemoria()
    agora = datetime(2026, 10, 31, tzinfo=UTC)
    repositorio.salvar(
        Job(
            id="j1", nome="a.mp4", tamanho_bytes=1, estado="concluido",
            criado_por="u", capa="quadros/plano-9.jpg",
            criado_em=agora, atualizado_em=agora,
        )
    )  # fmt: skip
    armazenamento = QuadrosFalso(_video(tmp_path / "v.mp4"), _decupagem([], []))
    (tmp_path / "saida").mkdir()

    executar("j1", repositorio, armazenamento, tmp_path / "saida")

    job = repositorio.obter("j1")
    assert job is not None
    assert job.capa is None
