"""O workflow do CI (#290), lido como texto: sem PyYAML no projeto."""

import re
from pathlib import Path

CI = (Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml").read_text()


def _jobs() -> list[str]:
    bloco = CI[CI.index("\njobs:\n") :]
    return re.findall(r"^  ([a-z-]+):$", bloco, re.MULTILINE)


def test_nenhuma_chave_de_topo_se_repete() -> None:
    # O GitHub recusa o workflow inteiro com chave duplicada; o parse do PyYAML não.
    chaves = re.findall(r"^([a-z_-]+):", CI, re.MULTILINE)
    assert len(chaves) == len(set(chaves)), chaves


def test_nenhum_job_se_repete() -> None:
    jobs = _jobs()
    assert len(jobs) == len(set(jobs)), jobs


def test_o_publicar_espera_todos_os_outros_jobs() -> None:
    necessarios = re.search(r"^    needs: \[(.*)\]$", CI, re.MULTILINE)
    assert necessarios
    esperados = {j.strip() for j in necessarios.group(1).split(",")}
    assert esperados == set(_jobs()) - {"publicar"}
