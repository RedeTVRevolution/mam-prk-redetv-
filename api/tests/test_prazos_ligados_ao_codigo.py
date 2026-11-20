"""Números de tempo e de memória que viviam em comentário, ligados ao código (#761, spec #638)."""

import re
from pathlib import Path

from api.cortes import TEMPO_LIMITE_S
from api.jobs import TAMANHO_MAXIMO_PADRAO_BYTES
from api.tests.test_workflow import FOLGA_DO_CONECTOR_S, MAIN, _timeout_do_job
from api.validador import (
    DURACAO_MAXIMA_S,
    FILTRO_DO_PROXY,
    TAXA_DO_AUDIO_HZ,
)

JOBS_TS = Path(__file__).parents[2] / "web" / "src" / "jobs.ts"
GIB = 1024**3
VALIDADOR = Path(__file__).parents[1] / "validador.py"
ALTURA_DO_PROXY_MEDIDO = 480
# Medido (#135) em 120 s de vídeo: o proxy 480p ficou em 51 MB = 5,75 GiB para 4 h.
PROXY_MEDIDO_GIB_PARA_4H = 5.75
DURACAO_DA_MEDIDA_S = 4 * 3600
BYTES_POR_AMOSTRA_PCM_S16LE_MONO = 2
FOLGA_DO_VOLUME_NA_MEMORIA_GIB = 1  # ffmpeg e Python, no mesmo contêiner


def _teto_da_tela_s() -> float:
    """O literal `TETO_DO_FINALIZANDO_MS` de `web/src/jobs.ts`, em segundos."""
    achado = re.search(
        r"^(?:export )?const TETO_DO_FINALIZANDO_MS = (.+)$",
        JOBS_TS.read_text(),
        re.MULTILINE,
    )
    assert achado is not None
    conta = achado.group(1).split("//")[0].replace("_", "")
    assert re.fullmatch(r"[\d\s*+()]+", conta.strip()), conta
    return eval(conta) / 1000


def _espera_de_gpu_s() -> int:
    """O maior padrão de `espera_gpu_minutos`, no módulo e na raiz da prod."""
    padroes = []
    for arquivo in (MAIN, MAIN.parents[2] / "ambientes/prod/main.tf"):
        bloco = (
            arquivo.read_text()
            .split('variable "espera_gpu_minutos" {')[1]
            .split("\n}")[0]
        )
        achado = re.search(r"default\s*=\s*(\d+)", bloco)
        assert achado is not None, arquivo
        padroes.append(int(achado.group(1)) * 60)
    return max(padroes)


def test_teto_do_finalizando_cobre_a_etapa_mais_longa_depois_do_concluido() -> None:
    """A etapa mais longa depois do `concluido` é o inventário de objetos: a espera de GPU, o
    Florence (`objetos_gpu`) e o inventário em CPU, cada passo com o prazo do conector. Fica
    fora a espera na fila FIFO de GPU (limite conhecido)."""
    main = MAIN.read_text()
    referencia = (
        _espera_de_gpu_s()
        + _timeout_do_job(main, "objetos_gpu")
        + FOLGA_DO_CONECTOR_S
        + _timeout_do_job(main, "inventario")
        + FOLGA_DO_CONECTOR_S
    )
    assert _teto_da_tela_s() > referencia


def _volume_e_memoria_do_job_de_validacao() -> tuple[int, int]:
    """O `size_limit` do volume em memória e o `memory` do contêiner, em GiB."""
    main = MAIN.read_text()
    job = main.split('resource "google_cloud_run_v2_job" "validacao" {')[1].split(
        "\nresource "
    )[0]
    volume = re.search(r'size_limit\s*=\s*"(\d+)Gi"', job)
    memoria = re.search(r'memory\s*=\s*"(\d+)Gi"', job)
    assert volume is not None and memoria is not None
    return int(volume.group(1)), int(memoria.group(1))


def test_volume_da_validacao_guarda_copia_proxy_e_audio_no_teto() -> None:
    volume_gib, memoria_gib = _volume_e_memoria_do_job_de_validacao()
    # A medição vale para o proxy de 480p e o áudio PCM s16le mono que o código gera.
    altura = re.search(r"round\((\d+)\*dar", FILTRO_DO_PROXY)
    assert altura is not None and int(altura.group(1)) == ALTURA_DO_PROXY_MEDIDO
    assert f"min({ALTURA_DO_PROXY_MEDIDO}" in FILTRO_DO_PROXY
    fonte = VALIDADOR.read_text()
    assert '"-ac", "1", "-ar", str(TAXA_DO_AUDIO_HZ)' in fonte
    assert '"-c:a", "pcm_s16le"' in fonte
    copia = TAMANHO_MAXIMO_PADRAO_BYTES / GIB
    proxy = PROXY_MEDIDO_GIB_PARA_4H * DURACAO_MAXIMA_S / DURACAO_DA_MEDIDA_S
    audio = TAXA_DO_AUDIO_HZ * BYTES_POR_AMOSTRA_PCM_S16LE_MONO * DURACAO_MAXIMA_S / GIB
    assert 0.4 < audio < 0.45  # cerca de 0,43 GiB para 4 h
    assert copia + proxy + audio <= volume_gib
    # O volume em memória conta na memória do contêiner.
    assert volume_gib + FOLGA_DO_VOLUME_NA_MEMORIA_GIB <= memoria_gib


def test_tempo_limite_do_ffmpeg_e_o_teto_de_um_passo_nao_do_job() -> None:
    """`TEMPO_LIMITE_S` vale para cada chamada ao ffmpeg (a da cópia limpa e a de proxy, áudio e
    cortes, que usam a mesma constante): é o teto de um passo. Nenhum passo passa do timeout do
    Job de validação; quando a soma dos passos o passa, quem vence é o timeout do Job."""
    timeout_do_job = _timeout_do_job(MAIN.read_text(), "validacao")
    assert TEMPO_LIMITE_S == 7200
    assert TEMPO_LIMITE_S <= timeout_do_job
    assert 2 * TEMPO_LIMITE_S > timeout_do_job
