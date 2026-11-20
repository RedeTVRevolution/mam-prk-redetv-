"""O ponto único que lê os outputs do Terraform (#756), sem nuvem: um `terraform` simulado no PATH."""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[2]
SCRIPT = RAIZ / "scripts" / "ler-ambiente.sh"
MAKEFILE = (RAIZ / "Makefile").read_text()
DEPLOY = (RAIZ / "scripts" / "deploy-dev.sh").read_text()

SEGREDO = "chave-que-nunca-sai-no-log"
SAIDAS = {
    "bucket_aceitos": "aceitos-x",
    "bucket_decupagens": "decupagens-x",
    "banco_firestore": "banco-x",
    "banco_de_seguranca": "seguranca-x",
    "busca_regiao": "us-east4",
    "busca_colecao": "momentos",
    "busca_colecao_de_texto": "texto",
    "busca_colecao_de_medida": "medida",
    "busca_indice_descricao": "indice",
    "busca_indices_ligados": False,
    "busca_dimensao": 256,
    "busca_cota_de_escrita": 6000,
    "identity_api_key": SEGREDO,
    "limpeza_de_imagens": {"pacotes_do_cache": ["cache"]},
    "url": "https://mam.example",
}


def _saidas(**mudancas: object) -> dict[str, object]:
    return {**SAIDAS, **mudancas}


def _terraform_simulado(
    pasta: Path, saidas: dict[str, object] | None, falha: bool = False
) -> dict[str, str]:
    """Um `terraform` no PATH que imprime os outputs em JSON e registra a pasta e as chamadas."""
    json_dos_outputs = {
        nome: {"value": valor, "sensitive": nome == "identity_api_key", "type": "x"}
        for nome, valor in (saidas or {}).items()
    }
    (pasta / "saida.json").write_text(json.dumps(json_dos_outputs))
    terraform = pasta / "terraform"
    terraform.write_text(
        f"""#!/usr/bin/env bash
echo "$*" >> {shlex.quote(str(pasta / "chamadas"))}
{"echo 'Error: backend' >&2; exit 1" if falha else f"cat {shlex.quote(str(pasta / 'saida.json'))}"}
"""
    )
    terraform.chmod(0o755)
    ambiente = {
        k: v for k, v in os.environ.items() if not k.startswith(("BUSCA_", "BUCKET_"))
    }
    for nome in (
        "FIRESTORE_BANCO",
        "FIRESTORE_BANCO_DE_SEGURANCA",
        "GCP_PROJECT_ID",
        "PASTA_DO_AMBIENTE",
    ):
        ambiente.pop(nome, None)
    ambiente["PATH"] = f"{pasta}:{ambiente['PATH']}"
    return ambiente


def _rodar(
    tmp_path: Path,
    *args: str,
    saidas: dict[str, object] | None = None,
    falha: bool = False,
    ambiente: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _terraform_simulado(tmp_path, SAIDAS if saidas is None else saidas, falha)
    env.update(ambiente or {})
    return subprocess.run(
        [str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def _chamadas(tmp_path: Path) -> list[str]:
    arquivo = tmp_path / "chamadas"
    return arquivo.read_text().splitlines() if arquivo.exists() else []


def _exportado(feito: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """As atribuições que o chamador receberia com `eval`, lidas por um shell de verdade."""
    script = f"eval {shlex.quote(feito.stdout)}; env"
    lido = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.environ["PATH"]},
    ).stdout
    return dict(l.split("=", 1) for l in lido.splitlines() if "=" in l)


def test_exporta_so_as_variaveis_pedidas_com_uma_unica_leitura(tmp_path: Path) -> None:
    feito = _rodar(tmp_path, "BUCKET_ACEITOS", "FIRESTORE_BANCO", "BUSCA_DIMENSAO")

    assert feito.returncode == 0, feito.stderr
    env = _exportado(feito)
    assert env["BUCKET_ACEITOS"] == "aceitos-x"
    assert env["FIRESTORE_BANCO"] == "banco-x"
    assert env["BUSCA_DIMENSAO"] == "256"
    assert "BUCKET_DECUPAGENS" not in env
    assert _chamadas(tmp_path) == ["-chdir=infra output -json"]


def test_o_que_ja_vem_no_ambiente_fica_e_sem_nada_a_ler_nao_chama_o_terraform(
    tmp_path: Path,
) -> None:
    feito = _rodar(
        tmp_path,
        "BUCKET_ACEITOS",
        "BUCKET_DECUPAGENS",
        ambiente={"BUCKET_ACEITOS": "da-pessoa"},
    )
    env = _exportado(feito)
    assert "BUCKET_ACEITOS" not in feito.stdout
    assert env["BUCKET_DECUPAGENS"] == "decupagens-x"

    tudo = _rodar(
        tmp_path,
        "BUCKET_ACEITOS",
        ambiente={"BUCKET_ACEITOS": "da-pessoa"},
    )
    assert tudo.returncode == 0 and tudo.stdout == ""
    assert len(_chamadas(tmp_path)) == 1  # só a da primeira execução


def test_o_nome_do_banco_de_seguranca_e_o_do_banco_principal_vem_dos_outputs_certos(
    tmp_path: Path,
) -> None:
    env = _exportado(
        _rodar(tmp_path, "FIRESTORE_BANCO_DE_SEGURANCA", "FIRESTORE_BANCO")
    )

    assert env["FIRESTORE_BANCO_DE_SEGURANCA"] == "seguranca-x"
    assert env["FIRESTORE_BANCO"] == "banco-x"


def test_para_com_erro_se_a_leitura_falha(tmp_path: Path) -> None:
    feito = _rodar(tmp_path, "BUCKET_ACEITOS", falha=True)

    assert feito.returncode != 0
    assert feito.stdout == ""
    assert "Não consegui ler os outputs" in feito.stderr


def test_para_com_erro_se_falta_saida_obrigatoria_mas_nao_a_cota_de_escrita(
    tmp_path: Path,
) -> None:
    sem = {
        k: v
        for k, v in SAIDAS.items()
        if k not in ("bucket_aceitos", "busca_cota_de_escrita")
    }

    faltou = _rodar(tmp_path, "BUCKET_ACEITOS", saidas=sem)
    assert faltou.returncode != 0 and "bucket_aceitos" in faltou.stderr

    cota = _rodar(tmp_path, "BUSCA_COTA_DE_ESCRITA", saidas=sem)
    assert cota.returncode == 0
    assert _exportado(cota)["BUSCA_COTA_DE_ESCRITA"] == ""


def test_false_do_indice_e_preservado_e_ausente_vira_texto_invalido(
    tmp_path: Path,
) -> None:
    falso = _exportado(_rodar(tmp_path, "BUSCA_INDICES_LIGADOS"))
    assert falso["BUSCA_INDICES_LIGADOS"] == "false"

    verdadeiro = _rodar(
        tmp_path, "BUSCA_INDICES_LIGADOS", saidas=_saidas(busca_indices_ligados=True)
    )
    assert _exportado(verdadeiro)["BUSCA_INDICES_LIGADOS"] == "true"

    sem = {k: v for k, v in SAIDAS.items() if k != "busca_indices_ligados"}
    ausente = _rodar(tmp_path, "BUSCA_INDICES_LIGADOS", saidas=sem)
    assert _exportado(ausente)["BUSCA_INDICES_LIGADOS"] == "terraform_output_falhou"


def test_le_a_pasta_da_prod_quando_pedida_e_exige_o_projeto_do_ambiente(
    tmp_path: Path,
) -> None:
    sem_projeto = _rodar(
        tmp_path,
        "BUCKET_ACEITOS",
        ambiente={"PASTA_DO_AMBIENTE": "infra/ambientes/prod"},
    )
    assert sem_projeto.returncode != 0 and "GCP_PROJECT_ID" in sem_projeto.stderr
    assert _chamadas(tmp_path) == []

    feito = _rodar(
        tmp_path,
        "BUCKET_ACEITOS",
        ambiente={
            "PASTA_DO_AMBIENTE": "infra/ambientes/prod",
            "GCP_PROJECT_ID": "projeto-da-prod",
        },
    )
    assert feito.returncode == 0, feito.stderr
    assert _chamadas(tmp_path) == ["-chdir=infra/ambientes/prod output -json"]


def test_nunca_imprime_o_json_inteiro_nem_o_output_sensitive(tmp_path: Path) -> None:
    feito = _rodar(tmp_path, "BUCKET_ACEITOS", falha=False)
    assert SEGREDO not in feito.stdout + feito.stderr
    assert "sensitive" not in feito.stdout + feito.stderr

    # No deploy o segredo sai só quando pedido, e o resto do JSON não aparece.
    pedido = _rodar(tmp_path, "--deploy", "IDENTITY_API_KEY=identity_api_key")
    assert pedido.stdout == f"IDENTITY_API_KEY='{SEGREDO}'\n"
    assert "bucket_aceitos" not in pedido.stdout + pedido.stderr


def test_no_deploy_o_terraform_vale_sobre_o_ambiente_e_nada_vira_export(
    tmp_path: Path,
) -> None:
    feito = _rodar(
        tmp_path,
        "--deploy",
        "BUSCA_REGIAO=busca_regiao",
        "BUSCA_INDICES_LIGADOS=busca_indices_ligados",
        ambiente={"BUSCA_REGIAO": "do-ambiente", "BUSCA_INDICES_LIGADOS": "true"},
    )

    assert feito.stdout.splitlines() == [
        "BUSCA_REGIAO='us-east4'",
        "BUSCA_INDICES_LIGADOS='false'",
    ]


def test_no_deploy_saida_obrigatoria_ausente_ou_vazia_para_e_a_opcional_nao(
    tmp_path: Path,
) -> None:
    sem_url = {k: v for k, v in SAIDAS.items() if k != "url"}
    ausente = _rodar(tmp_path, "--deploy", "URL=url", saidas=sem_url)
    assert ausente.returncode != 0 and "url" in ausente.stderr

    vazia = _rodar(tmp_path, "--deploy", "URL=url", saidas=_saidas(url=""))
    assert vazia.returncode != 0

    nula = _rodar(tmp_path, "--deploy", "URL=url", saidas=_saidas(url=None))
    assert nula.returncode != 0

    opcional = _rodar(
        tmp_path, "--deploy", "CERTIFICADO=certificado_do_balanceador:opcional"
    )
    assert opcional.returncode == 0 and opcional.stdout == "CERTIFICADO=''\n"


def test_o_objeto_vira_json_compacto_para_o_jq_do_deploy(tmp_path: Path) -> None:
    feito = _rodar(tmp_path, "--deploy", "LIMPEZA=limpeza_de_imagens")
    valor = shlex.split(feito.stdout)[0].split("=", 1)[1]

    assert json.loads(valor) == {"pacotes_do_cache": ["cache"]}


def test_primeira_publicacao_web_e_jobs_ausentes_na_primeira_leitura_e_presentes_na_segunda(
    tmp_path: Path,
) -> None:
    leituras = re.findall(
        r"^ler_ambiente (.*?)\n(?!  )", DEPLOY, re.MULTILINE | re.DOTALL
    )
    primeira, segunda = leituras
    estado_novo = {
        k: v for k, v in SAIDAS.items() if k not in ("url", "job_de_ocr_gpu")
    } | {
        "repositorio": "r",
        "repositorio_gpu": "rg",
        "conta_build": "c",
        "bucket_fontes": "b",
    }
    completo = estado_novo | {
        "url": "https://mam.example",
        "regiao_gpu": "us-east4",
        **{f"job_de_{n}_gpu": f"mam-{n}" for n in ("transcricao", "ocr", "objetos")},
        **{f"gpu_espera_{n}": 1 for n in ("total_s", "s", "maxima_s")},
        "gpu_fator_da_espera": 2,
    }

    antes = _rodar(
        tmp_path,
        "--deploy",
        *shlex.split(primeira.replace("\\\n", " ")),
        saidas=estado_novo,
    )
    depois = _rodar(
        tmp_path,
        "--deploy",
        *shlex.split(segunda.replace("\\\n", " ")),
        saidas=completo,
    )

    assert antes.returncode == 0, antes.stderr
    assert "JOB_OCR_GPU=''" in antes.stdout
    assert depois.returncode == 0, depois.stderr
    assert "JOB_OCR_GPU='mam-ocr'" in depois.stdout
    assert "URL='https://mam.example'" in depois.stdout
    # A segunda leitura exige o que a primeira dispensa.
    assert "URL=url" not in primeira and "URL=url" in segunda
    assert ":opcional" in primeira


def test_nenhum_alvo_do_makefile_le_o_terraform_por_output_raw() -> None:
    assert "terraform -chdir=infra output" not in MAKEFILE
    assert "output -raw" not in MAKEFILE


def test_os_alvos_do_makefile_param_com_erro_se_a_leitura_falha() -> None:
    # O `&&` encadeia o eval: um script que falha não deixa o comando rodar.
    assert re.search(
        r'^LER_AMBIENTE = ambiente=\$\$\(scripts/ler-ambiente\.sh \$\(1\)\) && eval "\$\$ambiente" &&$',
        MAKEFILE,
        re.MULTILINE,
    )
    # Sem o projeto do arquivo de ambiente quando a pasta não é a do dev.
    assert 'PASTA_DO_AMBIENTE:-infra}" = infra' in MAKEFILE


def test_o_makefile_entrega_a_cada_alvo_so_o_que_ele_lia() -> None:
    esperado = {
        "emitir-chave": {"FIRESTORE_BANCO_DE_SEGURANCA"},
        "registrar-webhook": {"FIRESTORE_BANCO", "WEBHOOK_SEGREDOS"},
        "listar-chaves": {"FIRESTORE_BANCO_DE_SEGURANCA"},
        "revogar-chave": {"FIRESTORE_BANCO_DE_SEGURANCA"},
        "atribuir-papeis": {"FIRESTORE_BANCO_DE_SEGURANCA"},
        "corrigir-estado": {
            "BUCKET_ACEITOS",
            "BUCKET_DECUPAGENS",
            "FIRESTORE_BANCO_DE_SEGURANCA",
        },
        "carregar-marcas": {"BUCKET_ACEITOS", "BUCKET_DECUPAGENS"},
        "cache-dos-quadros": {"BUCKET_DECUPAGENS"},
        "comparar-objetos": {"BUCKET_DECUPAGENS", "REGIAO_GPU", "JOB_DE_OBJETOS_GPU"},
        "sondar-busca": {"BUSCA_DISTANCIA_MAXIMA", "BUSCA_PALAVRAS_MINIMAS"},
        "reindexar": {"BUCKET_ACEITOS", "BUCKET_DECUPAGENS"},
        "preencher-taxa-diaria": {
            "BUCKET_ACEITOS",
            "BUCKET_DECUPAGENS",
            "BIGQUERY_DATASET",
            "BIGQUERY_TABELA_DA_TAXA",
            "BIGQUERY_REGIAO",
        },
    }
    for alvo, variaveis in esperado.items():
        receita = MAKEFILE[MAKEFILE.index(f"\n{alvo}:") + 1 :].split("\n\n")[0]
        pedidas = set(
            " ".join(
                re.findall(
                    r"\$\(call (?:LER_AMBIENTE|AMBIENTE_DA_BUSCA),([^)]*)\)", receita
                )
            ).split()
        )
        pedidas -= {
            v
            for v in pedidas
            if v.startswith("BUSCA_") and alvo not in ("sondar-busca",)
        }
        assert pedidas == variaveis, alvo


def test_o_pacote_de_cache_do_deploy_vem_de_limpeza_de_imagens() -> None:
    assert '"$REPOSITORIO/cache"' not in DEPLOY and '/cache"' not in DEPLOY
    assert "jq -er '.pacotes_do_cache[0]'" in DEPLOY
    assert 'CACHE="$REPOSITORIO/$PACOTE_DO_CACHE"' in DEPLOY
    assert 'CACHE_GPU="$REPOSITORIO_GPU/$PACOTE_DO_CACHE"' in DEPLOY


def test_o_deploy_nao_le_mais_output_por_output() -> None:
    assert "tf output" not in DEPLOY
    assert DEPLOY.count("\nler_ambiente ") == 2


@pytest.mark.parametrize("arquivo", ["scripts/ler-ambiente.sh"])
def test_o_script_e_executavel(arquivo: str) -> None:
    assert os.access(RAIZ / arquivo, os.X_OK)


def test_o_deploy_le_sempre_a_pasta_infra_mesmo_com_a_da_prod_no_ambiente(
    tmp_path: Path,
) -> None:
    inicio = DEPLOY.index("ler_ambiente() {")
    funcao = DEPLOY[inicio : DEPLOY.index("\n}\n", inicio) + 3]
    env = _terraform_simulado(tmp_path, SAIDAS)
    env.update(
        PASTA_DO_AMBIENTE="infra/ambientes/prod", GCP_PROJECT_ID="projeto-da-prod"
    )
    script = f'set -euo pipefail\n{funcao}\nler_ambiente URL=url\necho "$URL"\n'

    feito = subprocess.run(
        ["bash", "-c", script],
        cwd=RAIZ,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert feito.returncode == 0, feito.stderr
    assert _chamadas(tmp_path) == ["-chdir=infra output -json"]


@pytest.mark.parametrize(
    "valor",
    ["d'Artagnan", 'aspas "duplas"', "$HOME `id`", "com espaço", "linha1\nlinha2", "'"],
)
def test_o_valor_com_caracteres_de_shell_volta_igual_depois_do_eval(
    tmp_path: Path, valor: str
) -> None:
    feito = _rodar(tmp_path, "BUCKET_ACEITOS", saidas=_saidas(bucket_aceitos=valor))

    assert feito.returncode == 0, feito.stderr
    assert (
        subprocess.run(
            [
                "bash",
                "-c",
                f'eval {shlex.quote(feito.stdout)}; printf %s "$BUCKET_ACEITOS"',
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == valor
    )


def test_valor_composto_e_recusado_salvo_na_saida_estruturada(tmp_path: Path) -> None:
    for composto in (["a"], {"a": 1}):
        feito = _rodar(tmp_path, "--deploy", "URL=url", saidas=_saidas(url=composto))
        assert feito.returncode != 0 and "composto" in feito.stderr
        local = _rodar(
            tmp_path, "BUCKET_ACEITOS", saidas=_saidas(bucket_aceitos=composto)
        )
        assert local.returncode != 0

    estruturada = _rodar(tmp_path, "--deploy", "LIMPEZA=limpeza_de_imagens")
    assert estruturada.returncode == 0


def test_o_alvo_da_busca_recebe_a_colecao_de_texto_do_ponto_unico(
    tmp_path: Path,
) -> None:
    # O alvo usa a macro AMBIENTE_DA_BUSCA; roda-se o fragmento dele (sem o carregamento do arquivo
    # de ambiente e com um comando que imprime a variável no lugar do Python) com o terraform simulado.
    comando = subprocess.run(
        ["make", "-n", "criar-colecao-da-busca"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    fim = 'eval "$ambiente" &&'
    fragmento = comando[comando.index("ambiente=$(") :]
    fragmento = fragmento[: fragmento.index(fim) + len(fim)]
    assert "BUSCA_COLECAO_DE_TEXTO" in fragmento
    env = _terraform_simulado(tmp_path, SAIDAS)

    feito = subprocess.run(
        ["bash", "-c", f"{fragmento} printenv BUSCA_COLECAO_DE_TEXTO"],
        cwd=RAIZ,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert feito.stdout == "texto\n", feito.stderr
