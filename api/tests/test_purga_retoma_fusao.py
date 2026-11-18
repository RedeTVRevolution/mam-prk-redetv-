"""A varredura diária (`api.purga.main`) retoma as fusões de pessoas pendentes (#722),
contra os emuladores do Firestore e do Storage."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.auditoria import FiltroDeAuditoria
from api.bancos import auditoria_do_firestore
from api.catalogo import FusaoDaPessoa
from api.nuvem import CatalogoFirestore, RepositorioFirestore
from api.purga import main
from api.tests.test_lixeira import _job

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("FIRESTORE_EMULATOR_HOST")
        and os.environ.get("STORAGE_EMULATOR_HOST")
    ),
    reason="sem emuladores do Firestore e do Storage",
)


def _fusao(destino_id: str, fase: str) -> FusaoDaPessoa:
    return FusaoDaPessoa(
        destino_id=destino_id,
        em=datetime(2026, 11, 1, tzinfo=UTC),
        por_uid="u",
        por_email="u@redetv.com",
        motivo="duplicada",
        fase=fase,  # type: ignore[arg-type]
        registro_id=uuid.uuid4().hex,
        registro_detalhes={"destino_nome": "Destino"},
    )


def test_a_varredura_conclui_as_duas_fases_e_a_segunda_nao_faz_nada() -> None:
    projeto = f"teste-{uuid.uuid4().hex[:12]}"
    ambiente = {
        "GCP_PROJECT_ID": projeto,
        "BUCKET_QUARENTENA": "q",
        "BUCKET_ACEITOS": "a",
        "BUCKET_DECUPAGENS": "d",
        "BUCKET_REFERENCIAS": f"ref-{uuid.uuid4().hex[:12]}",
        # Só configuração: nenhum vídeo é purgado, então o BigQuery não é chamado.
        "BIGQUERY_DATASET": "d",
        "BIGQUERY_TABELA": "t",
        "BIGQUERY_REGIAO": "r",
        "BIGQUERY_TABELA_DE_JOBS": "j",
        "BIGQUERY_TABELA_DE_EVENTOS": "e",
        "BIGQUERY_TABELA_DE_REVISAO": "v",
    }
    ClienteStorage(project=projeto).create_bucket(ambiente["BUCKET_REFERENCIAS"])
    cliente = firestore.Client(project=projeto)
    catalogo = CatalogoFirestore(cliente)
    jobs = RepositorioFirestore(cliente)
    destino = catalogo.acrescentar("Destino", "", [])
    aguardando = catalogo.acrescentar("Origem 1", "", [])
    limpando = catalogo.acrescentar("Origem 2", "", [])
    catalogo.definir_fusao(aguardando.id, _fusao(destino.id, "aguardando_auditoria"))
    catalogo.definir_fusao(limpando.id, _fusao(destino.id, "limpando"))
    jobs.salvar(_job("j1", pessoas_do_catalogo=[aguardando.id]))
    jobs.salvar(_job("j2", pessoas_do_catalogo=[limpando.id]))
    assert aguardando.id not in [p.id for p in catalogo.todas()]  # invisível a `todas`

    assert main(ambiente) == 0

    assert catalogo.fusoes_pendentes() == []
    for id in ("j1", "j2"):
        job = jobs.obter(id)
        assert job and job.pessoas_do_catalogo == [destino.id]
    auditoria = auditoria_do_firestore(projeto, ambiente)
    registros = auditoria.consultar(FiltroDeAuditoria()).registros
    assert [r.alvo_id for r in registros] == [
        aguardando.id
    ]  # "limpando" já tinha o seu

    assert main(ambiente) == 0
    assert len(auditoria.consultar(FiltroDeAuditoria()).registros) == 1
