"""O teste dos Jobs com GPU depois da publicação (#238), com um gcloud falso."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "testar-jobs-gpu.sh"

# O gcloud falso lê, por Job, uma resposta por execução em `<pasta>/<job>.respostas` (ok,
# sem_gpu, gpu_ausente, errado, errado_codigo, permissao ou generico_21) e anota o que recebeu em `<pasta>/chamadas`.
GCLOUD_FALSO = r"""#!/usr/bin/env bash
pasta=$FALSO
args=("$@")
for i in "${!args[@]}"; do
  case ${args[$i]} in
    execute) acao=execute; job=${args[$((i + 1))]} ;;
    update) acao=update; job=${args[$((i + 1))]} ;;
    list) acao=list ;;
    --job) job=${args[$((i + 1))]} ;;
  esac
done
echo "$acao $job ${args[*]}" >>"$pasta/chamadas"
if [[ $acao == update ]]; then exit 0; fi
# As condições da última execução, como o gcloud de verdade as dá (só para o caso real).
if [[ $acao == list ]]; then
  [[ $(cat "$pasta/$job.ultima" 2>/dev/null) == generico_21 ]] &&
    echo "Task $job-x-task0 failed with exit code: 21 and message: The container exited with an error.;Imported container image."
  exit 0
fi
echo "inicio $job" >>"$pasta/ordem"
/bin/sleep 0.4
resposta=$(head -n1 "$pasta/$job.respostas")
echo "$resposta" >"$pasta/$job.ultima"
tail -n +2 "$pasta/$job.respostas" >"$pasta/$job.resto" && mv "$pasta/$job.resto" "$pasta/$job.respostas"
echo "fim $job" >>"$pasta/ordem"
case $resposta in
  ok) exit 0 ;;
  sem_gpu) echo "ERROR: Quota exceeded for total allowable count of GPUs" >&2; exit 1 ;;
  gpu_ausente) echo "ERROR: Execution failed. Container called exit(20)." >&2; exit 1 ;;
  errado) echo "ERROR: Execution failed. Container called exit(21)." >&2; exit 1 ;;
  errado_codigo) echo "ERROR: Task failed with exit code 21." >&2; exit 1 ;;
  permissao) echo "ERROR: PERMISSION_DENIED: insufficient permissions" >&2; exit 1 ;;
  generico_21) echo "ERROR: (gcloud.run.jobs.execute) The execution failed. View details about this execution by running: gcloud run jobs executions describe x" >&2; exit 1 ;;
esac
"""

SLEEP_FALSO = '#!/usr/bin/env bash\necho "$1" >>"$FALSO/esperas"\n'

TRANSCRICAO = "mam-transcricao-gpu"
OCR = "mam-ocr-gpu"


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for nome, texto in (("gcloud", GCLOUD_FALSO), ("sleep", SLEEP_FALSO)):
        (bin_ / nome).write_text(texto)
        (bin_ / nome).chmod(0o755)
    return tmp_path


def _rodar(
    pasta: Path,
    argumentos: list[str],
    respostas: dict[str, list[str]],
    ambiente_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    ambiente_extra = ambiente_extra or {}
    for job, lista in respostas.items():
        (pasta / f"{job}.respostas").write_text("".join(f"{r}\n" for r in lista))
    ambiente = {
        **os.environ,
        "PATH": f"{pasta / 'bin'}:{os.environ['PATH']}",
        "FALSO": str(pasta),
        "GCP_PROJECT_ID": "projeto-x",
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "conta@x",
        "GPU_REGIAO": "regiao-gpu",
        "GPU_ESPERA_TOTAL_S": "15",
        "GPU_ESPERA_S": "5",
        "GPU_FATOR_DA_ESPERA": "2",
        "GPU_ESPERA_MAXIMA_S": "10",
        **ambiente_extra,
    }
    return subprocess.run(
        [str(SCRIPT), *argumentos],
        check=False,
        env=ambiente,
        capture_output=True,
        text=True,
    )


def _chamadas(pasta: Path, acao: str) -> list[str]:
    arquivo = pasta / "chamadas"
    linhas = arquivo.read_text().splitlines() if arquivo.exists() else []
    return [linha for linha in linhas if linha.startswith(f"{acao} ")]


def _texto(r: subprocess.CompletedProcess[str]) -> str:
    return r.stdout + r.stderr


def test_nenhuma_imagem_mudou_pula_o_teste_e_o_log_diz(pasta: Path) -> None:
    r = _rodar(
        pasta,
        [f"{TRANSCRICAO},img@a,img@a", f"{OCR},img@b,img@b"],
        {},
    )

    assert r.returncode == 0
    assert "Nenhuma imagem com GPU mudou nesta publicação" in r.stdout
    assert "pulado" in r.stdout
    assert _chamadas(pasta, "execute") == []


def test_so_o_job_que_mudou_e_testado(pasta: Path) -> None:
    r = _rodar(
        pasta,
        [f"{TRANSCRICAO},img@a,img@a", f"{OCR},img@b,img@c"],
        {OCR: ["ok"]},
    )

    assert r.returncode == 0
    (execucao,) = _chamadas(pasta, "execute")
    assert OCR in execucao
    assert "--region regiao-gpu" in execucao and "--wait" in execucao
    assert "--update-env-vars MODO_TESTE=1" in execucao
    assert "--task-timeout 15m" in execucao


def test_os_dois_mudaram_rodam_em_paralelo_e_o_log_diz_quanto_levou(
    pasta: Path,
) -> None:
    r = _rodar(
        pasta,
        [f"{TRANSCRICAO},img@a,img@d", f"{OCR},img@b,img@c"],
        {TRANSCRICAO: ["ok"], OCR: ["ok"]},
    )

    assert r.returncode == 0
    ordem = (pasta / "ordem").read_text().split("\n")[:-1]
    assert [linha.split()[0] for linha in ordem[:2]] == ["inicio", "inicio"]
    assert "O teste dos Jobs com GPU levou" in r.stdout
    assert _chamadas(pasta, "update") == []


def test_na_primeira_publicacao_todos_sao_testados(pasta: Path) -> None:
    r = _rodar(
        pasta,
        [f"{TRANSCRICAO},,img@d", f"{OCR},,img@c"],
        {TRANSCRICAO: ["ok"], OCR: ["ok"]},
    )

    assert r.returncode == 0
    assert len(_chamadas(pasta, "execute")) == 2


def test_resultado_errado_falha_diz_o_motivo_e_volta_a_imagem_anterior(
    pasta: Path,
) -> None:
    r = _rodar(
        pasta,
        [f"{TRANSCRICAO},img@a,img@d", f"{OCR},img@b,img@c"],
        {TRANSCRICAO: ["errado"], OCR: ["ok"]},
    )

    assert r.returncode == 1
    assert "resultado errado" in r.stderr and TRANSCRICAO in r.stderr
    assert "sem GPU" not in r.stderr and "a GPU não funcionou" not in r.stderr
    # Sem nova tentativa: só a falta de GPU ou de cota tenta de novo.
    assert len(_chamadas(pasta, "execute")) == 2
    voltas = _chamadas(pasta, "update")
    assert len(voltas) == 2
    assert any(TRANSCRICAO in v and "--image img@a" in v for v in voltas)
    assert any(OCR in v and "--image img@b" in v for v in voltas)


def test_gpu_ausente_na_instancia_falha_como_a_gpu_nao_funcionou(
    pasta: Path,
) -> None:
    r = _rodar(pasta, [f"{OCR},img@b,img@c"], {OCR: ["gpu_ausente"]})

    assert r.returncode == 1
    assert "a GPU não funcionou" in r.stderr
    assert "sem GPU" not in r.stderr and "resultado errado" not in r.stderr
    assert len(_chamadas(pasta, "execute")) == 1


def test_falta_de_gpu_tenta_de_novo_com_espera_crescente_e_passa(
    pasta: Path,
) -> None:
    r = _rodar(pasta, [f"{OCR},img@b,img@c"], {OCR: ["sem_gpu", "sem_gpu", "ok"]})

    assert r.returncode == 0
    assert len(_chamadas(pasta, "execute")) == 3
    assert (pasta / "esperas").read_text().split() == ["5", "10"]


def test_falta_de_gpu_nas_tentativas_falha_como_sem_gpu_e_volta_a_imagem(
    pasta: Path,
) -> None:
    r = _rodar(
        pasta,
        [f"{OCR},img@b,img@c"],
        {OCR: ["sem_gpu", "sem_gpu", "sem_gpu", "ok"]},
    )

    assert r.returncode == 1
    assert "sem GPU" in r.stderr and "3 tentativas" in r.stderr
    assert "a GPU não funcionou" not in r.stderr
    assert len(_chamadas(pasta, "execute")) == 3
    assert (pasta / "esperas").read_text().split() == ["5", "10"]
    (volta,) = _chamadas(pasta, "update")
    assert "--image img@b" in volta


def test_o_numero_de_tentativas_sai_da_espera_total_e_nenhuma_espera_passa_do_teto(
    pasta: Path,
) -> None:
    # Esperas 5, 10, 10, 10 (o teto é 10): somam 35, e a seguinte passaria dos 40.
    r = _rodar(
        pasta,
        [f"{OCR},img@b,img@c"],
        {OCR: ["sem_gpu"] * 9},
        {"GPU_ESPERA_TOTAL_S": "40"},
    )

    assert r.returncode == 1
    assert "5 tentativas" in r.stderr
    assert (pasta / "esperas").read_text().split() == ["5", "10", "10", "10"]


def test_uma_espera_total_menor_da_menos_tentativas(pasta: Path) -> None:
    r = _rodar(
        pasta,
        [f"{OCR},img@b,img@c"],
        {OCR: ["sem_gpu"] * 9},
        {"GPU_ESPERA_TOTAL_S": "7"},
    )

    assert r.returncode == 1
    assert "2 tentativas" in r.stderr
    assert (pasta / "esperas").read_text().split() == ["5"]


def test_espera_total_zero_tenta_uma_vez_so(pasta: Path) -> None:
    r = _rodar(
        pasta,
        [f"{OCR},img@b,img@c"],
        {OCR: ["sem_gpu"] * 3},
        {"GPU_ESPERA_TOTAL_S": "0"},
    )

    assert r.returncode == 1
    assert "1 tentativas" in r.stderr
    assert not (pasta / "esperas").exists()


def test_na_primeira_publicacao_a_falha_nao_tem_imagem_para_voltar(
    pasta: Path,
) -> None:
    r = _rodar(pasta, [f"{OCR},,img@c"], {OCR: ["errado"]})

    assert r.returncode == 1
    assert _chamadas(pasta, "update") == []
    assert "primeira publicação" in r.stderr


def test_um_job_a_mais_entra_so_com_mais_um_argumento(pasta: Path) -> None:
    florence = "mam-florence-gpu"

    r = _rodar(
        pasta,
        [f"{OCR},img@b,img@c", f"{florence},img@e,img@f"],
        {OCR: ["ok"], florence: ["ok"]},
    )

    assert r.returncode == 0
    assert len(_chamadas(pasta, "execute")) == 2


def test_resultado_errado_tambem_vem_como_exit_code(pasta: Path) -> None:
    r = _rodar(pasta, [f"{OCR},img@b,img@c"], {OCR: ["errado_codigo"]})

    assert r.returncode == 1
    assert "resultado errado" in r.stderr
    assert "a GPU não funcionou" not in r.stderr


def test_falta_de_permissao_nao_conta_como_falta_de_gpu(pasta: Path) -> None:
    r = _rodar(pasta, [f"{OCR},img@b,img@c"], {OCR: ["permissao", "ok"]})

    assert r.returncode == 1
    assert "a GPU não funcionou" in r.stderr and "sem GPU" not in r.stderr
    assert len(_chamadas(pasta, "execute")) == 1


def test_o_motivo_vem_da_execucao_quando_o_gcloud_so_diz_que_falhou(
    pasta: Path,
) -> None:
    # O `--wait` do gcloud de verdade só diz "The execution failed." (deploy de 2026-11-03).
    feito = _rodar(pasta, [f"{OCR},antiga,nova"], {OCR: ["generico_21"]})

    assert feito.returncode == 1
    assert "ERRO resultado errado" in feito.stderr
