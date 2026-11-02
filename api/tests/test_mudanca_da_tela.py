"""A leitura da tela só quando a imagem muda (#233): quadros fixos, sem modelo."""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from api import ocr_job
from api.jobs import Job, RepositorioEmMemoria
from api.leitura_da_tela import Caixa, LeiturasEmMemoria, LinhaLida
from api.mudanca_da_tela import LIMIAR_PADRAO, MudancaDaTela, limiar_do_ambiente

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
TAMANHO = (854, 480)


def _quadro(
    pasta: Path,
    nome: str,
    fundo: int = 90,
    tarja: bool = False,
    gc: bool = False,
    ruido: int = 0,
) -> Path:
    imagem = Image.new("RGB", TAMANHO, (fundo + ruido,) * 3)
    desenho = ImageDraw.Draw(imagem)
    # Um objeto que se mexe, no meio: não é texto.
    desenho.rectangle((300, 120, 500, 300), fill=(200, 60, 60))
    if tarja:
        # A tarja do terço de baixo: poucos por cento da imagem.
        desenho.rectangle((60, 400, 560, 440), fill=(255, 255, 255))
        desenho.rectangle((80, 408, 300, 432), fill=(0, 0, 0))
    if gc:
        desenho.rectangle((40, 30, 280, 60), fill=(255, 255, 0))
    caminho = pasta / f"{nome}.png"
    imagem.save(caminho)
    return caminho


def test_o_quadro_igual_ao_lido_nao_pede_leitura(tmp_path: Path) -> None:
    mudanca = MudancaDaTela(LIMIAR_PADRAO)

    assert mudanca.mudou(_quadro(tmp_path, "a")) is True  # o primeiro é sempre lido
    assert mudanca.mudou(_quadro(tmp_path, "b")) is False
    assert mudanca.mudou(_quadro(tmp_path, "c")) is False


def test_o_ruido_da_compressao_nao_pede_leitura(tmp_path: Path) -> None:
    mudanca = MudancaDaTela(LIMIAR_PADRAO)
    mudanca.mudou(_quadro(tmp_path, "a"))

    assert mudanca.mudou(_quadro(tmp_path, "b", ruido=1)) is False


def test_a_tarja_que_entra_e_lida_no_segundo_em_que_entra(tmp_path: Path) -> None:
    mudanca = MudancaDaTela(LIMIAR_PADRAO)
    mudanca.mudou(_quadro(tmp_path, "a"))

    assert mudanca.mudou(_quadro(tmp_path, "b", tarja=True)) is True
    # Com a tarja parada, o quadro seguinte repete a leitura.
    assert mudanca.mudou(_quadro(tmp_path, "c", tarja=True)) is False


def test_a_tela_preta_depois_do_texto_e_lida(tmp_path: Path) -> None:
    mudanca = MudancaDaTela(LIMIAR_PADRAO)
    mudanca.mudou(_quadro(tmp_path, "a", tarja=True))
    preto = tmp_path / "preto.png"
    Image.new("RGB", TAMANHO, (0, 0, 0)).save(preto)

    assert mudanca.mudou(preto) is True


def test_o_texto_que_sai_e_lido(tmp_path: Path) -> None:
    mudanca = MudancaDaTela(LIMIAR_PADRAO)
    mudanca.mudou(_quadro(tmp_path, "a", gc=True))

    assert mudanca.mudou(_quadro(tmp_path, "b")) is True


def test_a_comparacao_e_com_o_ultimo_lido_e_nao_com_o_anterior(tmp_path: Path) -> None:
    # Um fade lento: cada quadro difere pouco do anterior, mas o acumulado passa do limiar.
    mudanca = MudancaDaTela(LIMIAR_PADRAO)
    mudanca.mudou(_quadro(tmp_path, "f0", fundo=90))

    leituras = [
        mudanca.mudou(_quadro(tmp_path, f"f{i}", fundo=90 - 2 * i)) for i in range(1, 6)
    ]

    assert leituras == [False, True, False, True, False]


def test_a_imagem_que_se_mexe_em_outra_parte_nao_pede_leitura(tmp_path: Path) -> None:
    # Um plano com movimento: o objeto do meio muda de cor um pouco, a tarja fica.
    mudanca = MudancaDaTela(LIMIAR_PADRAO)
    primeiro = _quadro(tmp_path, "a", tarja=True)
    mudanca.mudou(primeiro)
    with Image.open(primeiro) as imagem:
        movido = imagem.copy()
    ImageDraw.Draw(movido).rectangle((330, 140, 350, 160), fill=(60, 60, 200))
    movido.save(tmp_path / "b.png")

    assert mudanca.mudou(tmp_path / "b.png") is False


def test_limiar_zero_le_todo_quadro(tmp_path: Path) -> None:
    mudanca = MudancaDaTela(0)

    assert [mudanca.mudou(_quadro(tmp_path, f"q{i}")) for i in range(3)] == [True] * 3


def test_o_limiar_vem_da_configuracao() -> None:
    assert limiar_do_ambiente({}) == LIMIAR_PADRAO
    assert limiar_do_ambiente({"LIMIAR_DE_MUDANCA": " "}) == LIMIAR_PADRAO
    assert limiar_do_ambiente({"LIMIAR_DE_MUDANCA": "5.5"}) == 5.5
    assert limiar_do_ambiente({"LIMIAR_DE_MUDANCA": "0"}) == 0
    with pytest.raises(ValueError, match="LIMIAR_DE_MUDANCA"):
        limiar_do_ambiente({"LIMIAR_DE_MUDANCA": "-1"})


class LeitorContador:
    def __init__(self) -> None:
        self.lidos: list[str] = []

    def ler(self, quadro: Path) -> list[LinhaLida]:
        self.lidos.append(quadro.name)
        return [
            LinhaLida(
                texto=f"lido {quadro.stem}",
                confianca=0.9,
                caixa=Caixa(x=0.1, y=0.8, largura=0.5, altura=0.1),
            )
        ]


def _repositorio() -> RepositorioEmMemoria:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(
        Job(
            id="j1",
            nome="j1.mp4",
            tamanho_bytes=1,
            estado="analisando",
            criado_por="uid-1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    return repositorio


def _trechos(
    pasta: Path, quadros: dict[int, list[Path]]
) -> Iterator[tuple[int, list[Path]]]:
    yield from quadros.items()


def test_o_job_repete_a_leitura_dos_quadros_iguais_e_mantem_um_quadro_por_segundo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Dois trechos: a referência do quadro lido atravessa a divisa entre eles.
    pasta = tmp_path / "q"
    pasta.mkdir()
    trechos = {
        0: [
            _quadro(pasta, "s0"),
            _quadro(pasta, "s1"),
            _quadro(pasta, "s2", tarja=True),
        ],
        3: [
            _quadro(pasta, "s3", tarja=True),
            _quadro(pasta, "s4"),
        ],
    }
    monkeypatch.setattr(
        ocr_job, "quadros_por_trecho", lambda *_: _trechos(pasta, trechos)
    )
    repositorio = _repositorio()
    armazenamento = LeiturasEmMemoria({"j1": b"proxy"})
    leitor = LeitorContador()

    with caplog.at_level(logging.INFO, logger="api.ocr_job"):
        ocr_job.executar(
            "j1", repositorio, armazenamento, leitor, tmp_path, limiar_de_mudanca=3
        )

    assert leitor.lidos == ["s0.png", "s2.png", "s4.png"]
    leitura = armazenamento.ler_leitura("j1")
    assert leitura is not None
    assert [(q.segundo, [x.texto for x in q.linhas]) for q in leitura.quadros] == [
        (0, ["lido s0"]),
        (1, ["lido s0"]),
        (2, ["lido s2"]),
        (3, ["lido s2"]),
        (4, ["lido s4"]),
    ]
    assert "3 quadros lidos e 2 pulados" in caplog.text


def test_o_job_sem_limiar_le_todo_quadro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pasta = tmp_path / "q"
    pasta.mkdir()
    trechos = {0: [_quadro(pasta, f"s{i}") for i in range(3)]}
    monkeypatch.setattr(
        ocr_job, "quadros_por_trecho", lambda *_: _trechos(pasta, trechos)
    )
    repositorio = _repositorio()
    leitor = LeitorContador()

    ocr_job.executar(
        "j1", repositorio, LeiturasEmMemoria({"j1": b"proxy"}), leitor, tmp_path
    )

    assert len(leitor.lidos) == 3
