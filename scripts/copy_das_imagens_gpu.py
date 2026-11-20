"""O `COPY` de `api/` de cada imagem com GPU, gerado do fecho de imports do ponto de entrada (#758).

Fica fora de `api/` para não entrar nas imagens. `python -m scripts.copy_das_imagens_gpu`
reescreve, no `Dockerfile`, o trecho entre os marcadores de cada imagem.
"""

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).parents[1]
API = RAIZ / "api"
DOCKERFILE = RAIZ / "Dockerfile"
ALVOS = {
    "transcricao-gpu": "transcricao_job",
    "ocr-gpu": "ocr_job",
    "objetos-gpu": "objetos_job",
}


def importados(modulo: str) -> set[str]:
    """Os módulos de `api/` que o arquivo importa, também os importados dentro de funções."""
    achados: set[str] = set()
    for no in ast.walk(ast.parse((API / f"{modulo}.py").read_text())):
        if isinstance(no, ast.Import):
            achados |= {
                a.name.split(".")[1] for a in no.names if a.name.startswith("api.")
            }
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            if no.module == "api":
                achados |= {a.name for a in no.names}
            elif no.module.startswith("api."):
                achados.add(no.module.split(".")[1])
        elif isinstance(no, ast.ImportFrom) and no.level == 1:
            achados |= (
                {no.module.split(".")[0]} if no.module else {a.name for a in no.names}
            )
    return achados


def fecho(entrada: str) -> set[str]:
    vistos: set[str] = set()
    pendentes = [entrada, "__init__"]
    while pendentes:
        modulo = pendentes.pop()
        if modulo not in vistos:
            vistos.add(modulo)
            pendentes += importados(modulo)
    return vistos


def arquivos_esperados(entrada: str) -> set[str]:
    modulos = fecho(entrada)
    # Os arquivos de dados de `api/` (não só `.toml`) que algum módulo do fecho cita pelo nome.
    textos = [(API / f"{m}.py").read_text() for m in modulos]
    dados = {
        f"api/{arquivo.name}"
        for arquivo in API.iterdir()
        if arquivo.is_file() and arquivo.suffix not in {".py", ".pyc"}
        if any(f'"{arquivo.name}"' in texto for texto in textos)
    }
    return {f"api/{m}.py" for m in modulos} | dados


def copy_gerado(entrada: str) -> str:
    """As linhas do `COPY`, em ordem alfabética."""
    arquivos = sorted(arquivos_esperados(entrada))
    return "COPY " + " \\\n     ".join(arquivos) + " api/\n"


def reescrever(dockerfile: str) -> str:
    for alvo, entrada in ALVOS.items():
        ini, fim = f"# >>> copy gerado: {alvo}\n", "# <<< copy gerado\n"
        assert dockerfile.count(ini) == 1, (
            f"Faltam os marcadores de {alvo} no Dockerfile."
        )
        de = dockerfile.index(ini)
        ate = dockerfile.index(fim, de) + len(fim)
        antigo = dockerfile[de + len(ini) : ate - len(fim)].replace("\\\n", " ")
        assert re.fullmatch(r"COPY [^\n]*\n", antigo), (
            f"O bloco de {alvo} tem de ser só o COPY: tire o resto dos marcadores."
        )
        dockerfile = (
            dockerfile[:de] + ini + copy_gerado(entrada) + fim + dockerfile[ate:]
        )
    return dockerfile


if __name__ == "__main__":
    DOCKERFILE.write_text(reescrever(DOCKERFILE.read_text()))
