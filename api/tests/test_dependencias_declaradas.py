import tomllib
from pathlib import Path

PYPROJECT = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())


def test_as_dependencias_importadas_estao_declaradas_e_nao_ha_grupo_ocr() -> None:
    declaradas = {
        d.split("[")[0].split(">")[0].split("=")[0]
        for d in PYPROJECT["project"]["dependencies"]
    }
    assert {"requests", "google-auth", "google-api-core"} <= declaradas
    assert "ocr" not in PYPROJECT["dependency-groups"]
    assert all(
        {"group": "ocr"} not in par for par in PYPROJECT["tool"]["uv"]["conflicts"]
    )
