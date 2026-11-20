"""Cada imagem com GPU leva só os módulos de `api/` que o ponto de entrada importa (#388)."""

import re
from pathlib import Path

import pytest

from scripts.copy_das_imagens_gpu import (
    ALVOS,
    arquivos_esperados,
    copy_gerado,
    fecho,
    reescrever,
)

RAIZ = Path(__file__).parents[2]


def _alvo(nome: str) -> str:
    dockerfile = (RAIZ / "Dockerfile").read_text()
    return dockerfile[dockerfile.index(f"AS {nome}\n") :].split("\nFROM ")[0]


def _copiados(alvo: str) -> set[str]:
    texto = alvo.replace("\\\n", " ")
    arquivos: set[str] = set()
    for linha in re.findall(r"^COPY (api/\S.*) api/$", texto, flags=re.MULTILINE):
        arquivos |= set(linha.split())
    return arquivos


@pytest.mark.parametrize(("alvo", "entrada"), ALVOS.items())
def test_imagens_gpu_copiam_so_o_que_importam(alvo: str, entrada: str) -> None:
    copiados = _copiados(_alvo(alvo))
    esperados = arquivos_esperados(entrada)

    assert "COPY api/ api/" not in _alvo(alvo)
    assert esperados - copiados == set(), (
        f"O alvo {alvo} do Dockerfile não copia o que {entrada} importa: acrescente ao COPY de api/."
    )
    assert copiados - esperados == set(), (
        f"O alvo {alvo} copia o que {entrada} não importa: tire do COPY, ou a imagem muda à toa."
    )


def test_painel_nao_entra_em_nenhuma_imagem_com_gpu() -> None:
    for alvo, entrada in ALVOS.items():
        assert not {
            "api/painel.py",
            "api/resumos_de_uso.py",
            "api/main.py",
        } & _copiados(_alvo(alvo)), alvo
        assert "painel" not in fecho(entrada)


def test_a_lista_do_dockerfile_e_a_gerada() -> None:
    for alvo, entrada in ALVOS.items():
        assert f"# >>> copy gerado: {alvo}\n{copy_gerado(entrada)}# <<<" in _alvo(
            alvo
        ), f"Rode `make gerar-copy-das-imagens-gpu`: o COPY de {alvo} não é o gerado."


def test_o_gerador_reescreve_igual_ao_arquivo_e_e_idempotente() -> None:
    dockerfile = (RAIZ / "Dockerfile").read_text()
    uma_vez = reescrever(dockerfile)
    assert uma_vez == dockerfile
    assert reescrever(uma_vez) == uma_vez
    assert reescrever(uma_vez.replace("api/whisper.py", "api/x.py", 1)) == uma_vez


def test_o_gerador_recusa_bloco_com_outra_instrucao() -> None:
    dockerfile = (RAIZ / "Dockerfile").read_text()
    fim = "# <<< copy gerado\n"
    ruim = dockerfile.replace(fim, "RUN compileall -q api\n" + fim, 1)
    with pytest.raises(AssertionError, match="COPY"):
        reescrever(ruim)
