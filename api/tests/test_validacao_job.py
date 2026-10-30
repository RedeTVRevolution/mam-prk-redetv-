"""Ponto de entrada do Job de validação, contra os emuladores do Firestore e do Storage.

Sem `FIRESTORE_EMULATOR_HOST` / `STORAGE_EMULATOR_HOST`, os testes são pulados;
no CI os emuladores sobem antes do pytest.
"""

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.storage import Bucket
from google.cloud.storage import Client as ClienteStorage

from api.jobs import Job
from api.nuvem import RepositorioFirestore
from api.validacao_job import executar

EMULADOR_FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
EMULADOR_STORAGE = os.environ.get("STORAGE_EMULATOR_HOST")
BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

pytestmark = [
    pytest.mark.skipif(
        not (EMULADOR_FIRESTORE and EMULADOR_STORAGE), reason="sem emuladores"
    ),
    # Sem ffmpeg na máquina (o CI), os testes rodam na imagem do Job: make testar-na-imagem.
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg"),
]


@dataclass
class Ambiente:
    repositorio: RepositorioFirestore
    quarentena: Bucket
    aceitos: Bucket
    montagem: Path
    saida: Path

    def enviar(
        self, job_id: str, conteudo: bytes, estado: str = "aguardando_upload"
    ) -> None:
        """Põe o original na quarentena e no volume montado, e registra o Job."""
        self.quarentena.blob(job_id).upload_from_string(conteudo)
        (self.montagem / job_id).write_bytes(conteudo)
        self.repositorio.salvar(
            Job(
                id=job_id,
                nome=f"{job_id}.mp4",
                tamanho_bytes=len(conteudo),
                estado=estado,  # type: ignore[arg-type]
                criado_por="uid-1",
                criado_em=BASE,
                atualizado_em=BASE,
            )
        )

    def executar(self, job_id: str) -> None:
        executar(
            job_id,
            self.repositorio,
            self.quarentena,
            self.aceitos,
            self.montagem,
            self.saida,
        )

    def job(self, job_id: str) -> Job:
        job = self.repositorio.obter(job_id)
        assert job is not None
        return job


@pytest.fixture
def ambiente(tmp_path: Path) -> Ambiente:
    sufixo = uuid.uuid4().hex[:8]
    cliente = ClienteStorage(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
        client_options={"api_endpoint": EMULADOR_STORAGE},
    )
    montagem, saida = tmp_path / "quarentena", tmp_path / "saida"
    montagem.mkdir()
    saida.mkdir()
    return Ambiente(
        repositorio=RepositorioFirestore(
            firestore.Client(
                project="teste",
                credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
            ),
            colecao=f"jobs-{sufixo}",
        ),
        quarentena=cliente.create_bucket(f"teste-quarentena-{sufixo}"),
        aceitos=cliente.create_bucket(f"teste-aceitos-{sufixo}"),
        montagem=montagem,
        saida=saida,
    )


def _mp4(destino: Path, duracao: float = 2) -> bytes:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={duracao}",
            "-f", "lavfi", "-i", f"sine=duration={duracao}",
            "-c:v", "libx264", "-c:a", "aac", str(destino),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return destino.read_bytes()


def test_aceito_envia_copia_limpa_e_proxy_apaga_o_original_e_segue_para_analise(
    ambiente: Ambiente, tmp_path: Path
) -> None:
    ambiente.enviar("j1", _mp4(tmp_path / "v.mp4"))

    ambiente.executar("j1")

    assert ambiente.aceitos.blob("j1/copia_limpa.mp4").exists()
    assert ambiente.aceitos.blob("j1/proxy.mp4").exists()
    assert not ambiente.quarentena.blob("j1").exists()
    job = ambiente.job("j1")
    assert job.estado == "analisando"
    assert job.codigo_falha is None
    assert job.sha256 is not None and len(job.sha256) == 64
    assert job.duracao_s == pytest.approx(2, abs=0.2)


def test_recusado_grava_falhou_com_o_codigo_e_apaga_o_original(
    ambiente: Ambiente,
) -> None:
    ambiente.enviar("j2", b"isto nao e um mp4, mas tem mais de doze bytes")

    ambiente.executar("j2")

    job = ambiente.job("j2")
    assert (job.estado, job.codigo_falha) == ("falhou", "formato_invalido")
    assert not ambiente.quarentena.blob("j2").exists()
    assert not ambiente.aceitos.blob("j2/copia_limpa.mp4").exists()


def test_job_inexistente_nao_faz_nada(ambiente: Ambiente) -> None:
    ambiente.quarentena.blob("fantasma").upload_from_string(b"x")

    ambiente.executar("fantasma")

    assert ambiente.repositorio.obter("fantasma") is None
    assert ambiente.quarentena.blob("fantasma").exists()


@pytest.mark.parametrize(
    "estado", ["validando", "analisando", "concluido", "falhou", "cancelado"]
)
def test_job_fora_de_aguardando_upload_nao_muda(
    ambiente: Ambiente, tmp_path: Path, estado: str
) -> None:
    ambiente.enviar("j3", _mp4(tmp_path / "v.mp4"), estado=estado)
    antes = ambiente.job("j3")

    ambiente.executar("j3")

    assert ambiente.job("j3") == antes
    assert ambiente.quarentena.blob("j3").exists()
    assert not ambiente.aceitos.blob("j3/proxy.mp4").exists()


def _cancelar_ao_validar(ambiente: Ambiente) -> None:
    """O cancelamento chega logo depois de o worker marcar `validando`."""
    repositorio = ambiente.repositorio
    salvar = repositorio.salvar

    def salvar_e_cancelar(job: Job) -> None:
        salvar(job)
        if job.estado == "validando":
            salvar(job.model_copy(update={"estado": "cancelado"}))

    repositorio.salvar = salvar_e_cancelar  # type: ignore[method-assign]


def test_cancelado_durante_a_validacao_continua_cancelado(
    ambiente: Ambiente, tmp_path: Path
) -> None:
    ambiente.enviar("j4", _mp4(tmp_path / "v.mp4"))
    _cancelar_ao_validar(ambiente)

    ambiente.executar("j4")

    assert ambiente.job("j4").estado == "cancelado"


def test_cancelado_durante_a_validacao_nao_vira_falhou_se_o_arquivo_for_recusado(
    ambiente: Ambiente,
) -> None:
    ambiente.enviar("j5", b"isto nao e um mp4, mas tem mais de doze bytes")
    _cancelar_ao_validar(ambiente)

    ambiente.executar("j5")

    job = ambiente.job("j5")
    assert (job.estado, job.codigo_falha) == ("cancelado", None)
