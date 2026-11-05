import json
import os
import subprocess
from pathlib import Path

WIZARD = Path(__file__).resolve().parents[2] / "scripts" / "wizard-gcp-dev.sh"

GCLOUD_FALSO = """#!/usr/bin/env bash
# Guarda as políticas num arquivo; recusa a forma que $RECUSA pedir.
echo "$*" >> "$FAKE_DIR/chamadas.txt"
estado="$FAKE_DIR/politicas.txt"; touch "$estado"
case "$*" in
  *"policies create"*)
    arquivo=$(sed -n 's/.*--policy-from-file=\\([^ ]*\\).*/\\1/p' <<<"$*")
    forma=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['displayName'][-1])" "$arquivo")
    if [[ "$RECUSA" == *"$forma"* ]]; then echo "ERROR: invalid argument" >&2; exit 1; fi
    cp "$arquivo" "$FAKE_DIR/gravada-$forma.json"
    echo "projects/p/alertPolicies/$forma-$RANDOM" | tee -a "$estado"
    ;;
  *"policies describe"*) cat "$FAKE_DIR"/gravada-*.json ;;
  *"policies list"*)
    if [[ -n "${LISTA_FALHA:-}" ]]; then echo "ERROR: permission denied" >&2; exit 1; fi
    cat "$estado"
    ;;
  *"policies delete"*)
    nome=$(sed -n 's/.*policies delete \\([^ ]*\\).*/\\1/p' <<<"$*")
    grep -vxF "$nome" "$estado" > "$estado.novo" || true; mv "$estado.novo" "$estado"
    ;;
esac
"""

TERRAFORM_FALSO = """#!/usr/bin/env bash
if [[ -n "${SEM_SAIDAS:-}" ]]; then echo "Error: Output not found" >&2; exit 1; fi
case "$*" in
  *metrica_de_falhas_por_etapa*) printf 'mam_falhas_por_etapa' ;;
  *janela_dos_alertas_s*) printf '86400s' ;;
  *limite_de_falhas_por_etapa*) printf '3' ;;
esac
"""


def _bloco() -> str:
    texto = WIZARD.read_text()
    inicio = texto.index("# ENSAIO_FALHAS_INICIO")
    fim = texto.index("# ENSAIO_FALHAS_FIM")
    return texto[inicio:fim]


def _biblioteca() -> str:
    texto = WIZARD.read_text()
    return texto[: texto.index("run_wizard() {")]


def _rodar(
    tmp_path: Path,
    recusa: str,
    bloco: str | None = None,
    entrada: str = "y\n\n",
    **extra: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for nome, corpo in (("gcloud", GCLOUD_FALSO), ("terraform", TERRAFORM_FALSO)):
        (bin_dir / nome).write_text(corpo)
        (bin_dir / nome).chmod(0o755)
    fake = tmp_path / "fake"
    fake.mkdir()
    script = tmp_path / "ensaio.sh"
    script.write_text(
        _biblioteca()
        + "P=meu-projeto\nSKIPPED=()\nTOTAL_STAGES=1\n"
        + (bloco or _bloco())
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "RECUSA": recusa,
        **extra,
    }
    r = subprocess.run(
        ["bash", str(script)],
        check=False,
        input=entrada,
        text=True,
        capture_output=True,
        env=env,
    )
    return r, fake


def _chamadas(fake: Path) -> list[str]:
    return (fake / "chamadas.txt").read_text().splitlines()


def test_forma_a_aceita_cria_desabilitada_sem_canal_e_apaga(tmp_path: Path) -> None:
    r, fake = _rodar(tmp_path, recusa="")
    assert r.returncode == 0, r.stderr
    politica = json.loads((fake / "gravada-a.json").read_text())
    assert politica["displayName"] == "mam-ensaio-falhas-por-etapa-a"
    assert politica["enabled"] is False
    assert politica["notificationChannels"] == []
    cond = politica["conditions"][0]["conditionThreshold"]
    assert "one_of(" in cond["filter"]
    assert "logging.googleapis.com/user/mam_falhas_por_etapa" in cond["filter"]
    assert cond["thresholdValue"] == 3
    assert cond["aggregations"][0]["groupByFields"] == ["metric.label.etapa"]
    assert not (fake / "gravada-b.json").exists()
    assert (fake / "politicas.txt").read_text() == ""
    assert any("policies delete" in c for c in _chamadas(fake))
    assert "a API aceitou a forma (a)" in r.stdout
    assert "meu-projeto" in " ".join(_chamadas(fake))


def test_forma_a_recusada_tenta_a_b_em_prometheus(tmp_path: Path) -> None:
    r, fake = _rodar(tmp_path, recusa="a")
    assert r.returncode == 0, r.stderr
    assert "recusou a forma (a)" in r.stdout
    assert "invalid argument" in r.stdout
    politica = json.loads((fake / "gravada-b.json").read_text())
    assert politica["displayName"] == "mam-ensaio-falhas-por-etapa-b"
    assert politica["enabled"] is False
    assert politica["notificationChannels"] == []
    query = politica["conditions"][0]["conditionPrometheusQueryLanguage"]["query"]
    assert query.startswith("sum by (etapa)")
    assert "mam_falhas_por_etapa" in query
    assert (fake / "politicas.txt").read_text() == ""
    assert "a API aceitou a forma (b)" in r.stdout


def test_as_duas_recusadas_nao_deixa_nada_e_avisa(tmp_path: Path) -> None:
    r, fake = _rodar(tmp_path, recusa="ab")
    assert r.returncode == 0, r.stderr
    assert "recusou as duas formas" in r.stdout
    assert (fake / "politicas.txt").read_text() == ""


def test_trap_apaga_o_que_criou_se_o_script_morre_no_meio(tmp_path: Path) -> None:
    # `false` derruba o bloco (set -e) depois da criação: só o trap ainda apaga.
    bloco = _bloco().replace("ENSAIO_GRAVADA=$(", "false; ENSAIO_GRAVADA=$(", 1)
    assert bloco != _bloco()
    r, fake = _rodar(tmp_path, recusa="", bloco=bloco)
    assert r.returncode != 0
    assert any("policies create" in c for c in _chamadas(fake))
    assert (fake / "politicas.txt").read_text() == ""


def test_nomes_da_nuvem_vem_das_saidas_do_terraform() -> None:
    bloco = _bloco()
    assert "mam_falhas_por_etapa" not in bloco
    assert "output -raw metrica_de_falhas_por_etapa" in bloco


def test_sem_as_saidas_do_terraform_pula_a_etapa_sem_derrubar_o_wizard(
    tmp_path: Path,
) -> None:
    r, fake = _rodar(tmp_path, recusa="", SEM_SAIDAS="1")
    assert r.returncode == 0, r.stderr
    assert "ainda não tem a métrica" in r.stdout
    assert not (fake / "chamadas.txt").exists()


def test_recusar_o_ensaio_pula_a_etapa_sem_derrubar_o_wizard(tmp_path: Path) -> None:
    r, fake = _rodar(tmp_path, recusa="", entrada="n\n\n")
    assert r.returncode == 0, r.stderr
    assert "Nada foi criado" in r.stdout
    assert not (fake / "chamadas.txt").exists()


def test_listagem_que_falha_nao_diz_que_nada_sobrou(tmp_path: Path) -> None:
    r, _ = _rodar(tmp_path, recusa="", LISTA_FALHA="1")
    assert r.returncode == 0, r.stderr
    assert "nenhuma política" not in r.stdout
    assert "Não consegui listar" in r.stdout
