"""Lógica do scripts/wizard-migracao-us-east4.sh (#538): listas de endereços, pares de recursos
antigo → novo e comparação das contagens. O wizard em si mexe na nuvem e não roda aqui."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
WIZARD = RAIZ / "scripts" / "wizard-migracao-us-east4.sh"
ENDERECOS_REAIS = RAIZ / "infra" / "migracao-us-east4" / "enderecos-recriados.txt"


def _biblioteca() -> str:
    texto = WIZARD.read_text()
    return texto[: texto.index("run_wizard() {")]


def _bash(
    tmp_path: Path, corpo: str, entrada: str = "", fake_gcloud: str | None = None
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "t.sh"
    script.write_text(_biblioteca() + "\n" + corpo)
    env = dict(os.environ)
    if fake_gcloud is not None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "gcloud").write_text(fake_gcloud)
        (bin_dir / "gcloud").chmod(0o755)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(script)],
        input=entrada,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_o_script_passa_no_bash_n() -> None:
    r = subprocess.run(
        ["bash", "-n", str(WIZARD)], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="sem shellcheck")
def test_o_script_passa_no_shellcheck() -> None:
    r = subprocess.run(
        ["shellcheck", str(WIZARD)], capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stdout


def test_enderecos_do_arquivo_tira_comentario_e_linha_vazia(tmp_path: Path) -> None:
    arq = tmp_path / "lista.txt"
    arq.write_text("# cabeçalho\n\nmodule.mam.a.x\n  module.mam.b.y  # fim\n")
    r = _bash(tmp_path, f'enderecos_do_arquivo "{arq}"')
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["module.mam.a.x", "module.mam.b.y"]


def test_enderecos_do_arquivo_recusa_ausente_e_vazio(tmp_path: Path) -> None:
    r = _bash(tmp_path, f'enderecos_do_arquivo "{tmp_path / "nao-existe"}"')
    assert r.returncode == 1
    vazio = tmp_path / "vazio.txt"
    vazio.write_text("# só comentário\n")
    r = _bash(tmp_path, f'enderecos_do_arquivo "{vazio}"')
    assert r.returncode == 1
    assert "nenhum endereço" in r.stderr


def test_a_lista_real_do_537_tem_enderecos_de_modulo(tmp_path: Path) -> None:
    r = _bash(tmp_path, f'enderecos_do_arquivo "{ENDERECOS_REAIS}"')
    assert r.returncode == 0, r.stderr
    linhas = r.stdout.splitlines()
    assert len(linhas) > 20
    assert all(linha.startswith("module.mam.") for linha in linhas)


def test_enderecos_no_estado_pula_o_que_nao_esta_no_estado(tmp_path: Path) -> None:
    estado = tmp_path / "estado.txt"
    estado.write_text(
        'module.mam.google_firestore_index.acervo["criado_em-1"]\n'
        'module.mam.google_firestore_index.acervo["criado_em-2"]\n'
        'module.mam.google_storage_bucket.mam["aceitos"]\n'
        "module.mam.google_storage_bucket.mam_gpu\n"
    )
    entrada = (
        "module.mam.google_firestore_index.acervo\n"
        "module.mam.google_storage_bucket.mam\n"
        "module.mam.google_compute_url_map.web\n"
        "module.mam.google_storage_bucket.m\n"
    )
    r = _bash(tmp_path, f'enderecos_no_estado "{estado}"', entrada)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "module.mam.google_firestore_index.acervo",
        "module.mam.google_storage_bucket.mam",
    ]


def test_pares_de_buckets_ligam_pelo_papel(tmp_path: Path) -> None:
    novos = json.dumps(
        {
            "quarentena": "p-novo-quarentena",
            "clipes-ouro": "p-novo-clipes-ouro",
            "aceitos": "p-novo-aceitos",
        }
    )
    r = _bash(
        tmp_path,
        f"pares_por_papel '{novos}' p-aceitos p-clipes-ouro p-quarentena p-fontes",
    )
    assert r.returncode == 0, r.stderr
    assert sorted(r.stdout.splitlines()) == [
        "aceitos p-aceitos p-novo-aceitos",
        "clipes-ouro p-clipes-ouro p-novo-clipes-ouro",
        "quarentena p-quarentena p-novo-quarentena",
    ]


def test_pares_aceitam_chave_em_maiuscula_e_dataset_com_underscore(
    tmp_path: Path,
) -> None:
    novos = json.dumps({"BUCKET_CLIPES_OURO": "n-clipes-ouro"})
    r = _bash(tmp_path, f"pares_por_papel '{novos}' p-clipes-ouro")
    assert r.stdout.strip() == "clipes-ouro p-clipes-ouro n-clipes-ouro"
    datasets = json.dumps({"faturamento": "fat_novo", "decupagens": "dec_novo"})
    r = _bash(tmp_path, f"pares_por_papel '{datasets}' faturamento mam_decupagens")
    assert sorted(r.stdout.splitlines()) == [
        "decupagens mam_decupagens dec_novo",
        "faturamento faturamento fat_novo",
    ]


def test_pares_param_se_falta_ou_sobra_recurso_antigo(tmp_path: Path) -> None:
    novos = json.dumps({"aceitos": "p-novo-aceitos", "decupagens": "p-novo-decupagens"})
    falta = _bash(tmp_path, f"pares_por_papel '{novos}' p-aceitos")
    assert falta.returncode == 1
    assert "decupagens" in falta.stderr
    dois = _bash(
        tmp_path, f"pares_por_papel '{novos}' p-aceitos x-aceitos p-decupagens"
    )
    assert dois.returncode == 1
    assert "Mais de um" in dois.stderr
    vazio = _bash(tmp_path, "pares_por_papel '{}' p-aceitos")
    assert vazio.returncode == 1


def test_banco_principal_antigo_e_o_que_nao_e_de_seguranca(tmp_path: Path) -> None:
    r = _bash(
        tmp_path, "banco_principal_antigo mam-seguranca", "(default)\nmam-seguranca\n"
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "(default)"
    tres = _bash(tmp_path, "banco_principal_antigo s", "a\nb\ns\n")
    assert tres.returncode == 1
    nenhum = _bash(tmp_path, "banco_principal_antigo s", "s\n")
    assert nenhum.returncode == 1


def _comparar(
    tmp_path: Path, antigas: str, novas: str
) -> subprocess.CompletedProcess[str]:
    a, n = tmp_path / "a.txt", tmp_path / "n.txt"
    a.write_text(antigas)
    n.write_text(novas)
    return _bash(tmp_path, f'comparar_contagens "{a}" "{n}"')


def test_contagens_iguais_passam(tmp_path: Path) -> None:
    r = _comparar(
        tmp_path,
        "bucket:aceitos 3 100\nprincipal:jobs 7\n",
        "principal:jobs 7\nbucket:aceitos 3 100\n",
    )
    assert r.returncode == 0, r.stdout
    assert r.stdout.count("ok ") == 2


def test_contagem_diferente_para_e_mostra_os_dois_valores(tmp_path: Path) -> None:
    r = _comparar(
        tmp_path,
        "bucket:aceitos 3 100\nprincipal:jobs 7\n",
        "bucket:aceitos 3 99\nprincipal:jobs 7\n",
    )
    assert r.returncode == 1
    assert "DIFERE  bucket:aceitos: antigo 3 100 | novo 3 99" in r.stdout
    assert "ok      principal:jobs: 7" in r.stdout


def test_contagem_que_so_existe_de_um_lado_para(tmp_path: Path) -> None:
    r = _comparar(tmp_path, "a 1\nb 2\n", "a 1\nc 3\n")
    assert r.returncode == 1
    assert "FALTA   b: só no antigo (2)" in r.stdout
    assert "FALTA   c: só no novo (3)" in r.stdout


def test_antigas_vazias_nao_viram_as_novas(tmp_path: Path) -> None:
    r = _comparar(tmp_path, "", "a 1\n")
    assert r.returncode == 1
    assert "FALTA   a: só no novo (1)" in r.stdout


def test_contagem_que_so_cresce_passa_se_cresceu_e_para_se_caiu(tmp_path: Path) -> None:
    a, n = tmp_path / "a.txt", tmp_path / "n.txt"
    a.write_text("seguranca:auditoria 328\n")
    comparar = (
        f'CONTAGENS_QUE_SO_CRESCEM=seguranca:auditoria comparar_contagens "{a}" "{n}"'
    )
    n.write_text("seguranca:auditoria 330\n")
    cresceu = _bash(tmp_path, comparar)
    assert cresceu.returncode == 0, cresceu.stdout
    assert "(só cresce)" in cresceu.stdout
    n.write_text("seguranca:auditoria 320\n")
    caiu = _bash(tmp_path, comparar)
    assert caiu.returncode == 1
    assert "DIFERE  seguranca:auditoria: antigo 328 | novo 320" in caiu.stdout


def test_contagens_que_cairam(tmp_path: Path) -> None:
    antes, depois = tmp_path / "antes.txt", tmp_path / "depois.txt"
    antes.write_text("fat.t1 10\nfat.t2 5\nfat.t3 2\n")
    depois.write_text("fat.t1 14\nfat.t2 4\n")
    r = _bash(tmp_path, f'contagens_que_cairam "{antes}" "{depois}"')
    assert r.returncode == 1
    assert "fat.t2: eram 5, agora 4" in r.stdout
    assert "fat.t3: eram 2, agora (sumiu)" in r.stdout
    assert "fat.t1" not in r.stdout
    depois.write_text("fat.t1 10\nfat.t2 5\nfat.t3 9\n")
    assert _bash(tmp_path, f'contagens_que_cairam "{antes}" "{depois}"').returncode == 0


GCLOUD_COM_OBJETOS = """#!/usr/bin/env bash
echo "     10  2026-11-01T00:00:00Z  gs://b/a"
echo "TOTAL: 2 objects, 4096 bytes (4KiB)"
"""
GCLOUD_SEM_OBJETOS = """#!/usr/bin/env bash
echo "ERROR: (gcloud.storage.ls) One or more URLs matched no objects." >&2
exit 1
"""
GCLOUD_SEM_PERMISSAO = """#!/usr/bin/env bash
echo "ERROR: 403 permission denied" >&2
exit 1
"""


def test_contagem_do_bucket(tmp_path: Path) -> None:
    r = _bash(tmp_path, "contagem_do_bucket b", fake_gcloud=GCLOUD_COM_OBJETOS)
    assert r.stdout.strip() == "2 4096"


def test_bucket_vazio_e_zero(tmp_path: Path) -> None:
    r = _bash(tmp_path, "contagem_do_bucket b", fake_gcloud=GCLOUD_SEM_OBJETOS)
    assert r.returncode == 0
    assert r.stdout.strip() == "0 0"


def test_erro_de_permissao_na_contagem_para(tmp_path: Path) -> None:
    r = _bash(tmp_path, "contagem_do_bucket b", fake_gcloud=GCLOUD_SEM_PERMISSAO)
    assert r.returncode == 1
    assert "permission denied" in r.stderr


def test_condicoes_do_banco_pega_o_titulo_antigo_e_ignora_o_banco_novo(
    tmp_path: Path,
) -> None:
    # Na nuvem as condições de SP têm o título so-o-banco-default; o Terraform novo usa
    # so-o-banco-principal. O filtro é pela expressão, e a remoção leva o título real.
    def cond(titulo: str, banco: str) -> dict[str, str]:
        return {
            "title": titulo,
            "expression": f'resource.name == "projects/p/databases/{banco}"',
        }

    politica = {
        "bindings": [
            {
                "role": "roles/datastore.user",
                "members": ["sa:a", "sa:b"],
                "condition": cond("so-o-banco-default", "(default)"),
            },
            {
                "role": "roles/datastore.user",
                "members": ["sa:a"],
                "condition": cond("so-o-banco-principal", "mam"),
            },
            {"role": "roles/viewer", "members": ["sa:a"]},
        ]
    }
    r = _bash(tmp_path, "condicoes_do_banco p '(default)'", json.dumps(politica))
    assert r.returncode == 0, r.stderr
    exp = 'resource.name == "projects/p/databases/(default)"'
    assert r.stdout.splitlines() == [
        f"sa:a|roles/datastore.user|so-o-banco-default|{exp}",
        f"sa:b|roles/datastore.user|so-o-banco-default|{exp}",
    ]


def test_o_aviso_de_passo_que_falhou_sai_em_stderr(tmp_path: Path) -> None:
    linha = next(
        x.strip()
        for x in WIZARD.read_text().splitlines()
        if x.strip().startswith("trap ")
    )
    r = _bash(
        tmp_path, f"set -E\n{linha}\nfalso() {{ return 1; }}\nfalso || true\nfalso\n"
    )
    assert r.returncode == 1
    assert "O passo falhou" not in r.stdout
    assert "O passo falhou" in r.stderr
