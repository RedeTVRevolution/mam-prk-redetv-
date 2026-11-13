"""A indexação e a cópia no BigQuery leem pela leitura corrigida (#586, spec #582).

Pessoa e marca na lixeira do catálogo (ou purgadas) mantêm o `catalogo_id` no índice, no
BigQuery e no Catálogo do Job: o que muda é só quem monta a leitura.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from api.catalogo import CatalogoEmMemoria, EnvioParaLixeira, PessoaDoCatalogo
from api.copia_bigquery import CopiaEmMemoria
from api.copiar_para_bigquery import copiar, copiar_jobs
from api.indexacao import reindexar, reindexar_jobs
from api.indice_da_busca import Consulta
from api.marcas import CatalogoDeMarcasEmMemoria, MarcaDoCatalogo
from api.tests.test_indexacao import MODELO, Mundo

LIXEIRA = EnvioParaLixeira(
    em=datetime(2026, 11, 1), por_uid="u2", por_email="c@x", motivo="duplicada"
)
SABRINA = "cat-sabrina-sato"


def _modelo_com_marca() -> dict[str, Any]:
    modelo: dict[str, Any] = json.loads(json.dumps(MODELO))
    modelo["comerciais"] = [
        {
            "marca": "Marca X",
            "catalogo_id": "marca-x",
            "tipo": "intervalo",
            "inicio_ms": 0,
            "fim_ms": 1000,
            "evidencias": ["logo"],
        }
    ]
    return modelo


class PessoasContadas(CatalogoEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lotes = 0
        self.individuais = 0

    def obter(self, id: str) -> PessoaDoCatalogo | None:
        self.individuais += 1
        return super().obter(id)

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        self.lotes += 1
        return super().obter_varios(ids)


def _catalogos() -> tuple[PessoasContadas, CatalogoDeMarcasEmMemoria]:
    pessoas = PessoasContadas()
    pessoas._pessoas[SABRINA] = PessoaDoCatalogo(
        id=SABRINA, nome="Sabrina Sato", papel="apresentadora", lixeira=LIXEIRA
    )
    marcas = CatalogoDeMarcasEmMemoria()
    marcas._marcas["marca-x"] = MarcaDoCatalogo(
        id="marca-x", nome="Marca X", lixeira=LIXEIRA
    )
    return pessoas, marcas


def _ids_no_indice(mundo: Mundo) -> set[str]:
    achados = mundo.indice.buscar(Consulta(limite=100))
    return {p for r in achados for p in (getattr(r, "pessoas", None) or [])}


def _ids_no_bigquery(mundo: Mundo) -> set[str]:
    return {p.id for x in mundo.copia.por_job["j1"] for p in x.pessoas}


def _reindexar(mundo: Mundo, pessoas: Any, marcas: Any) -> None:
    job = mundo.jobs.obter("j1")
    assert job
    reindexar(
        job,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.indice,
        copia=mundo.copia,
        tipos_de_objeto=mundo.tipos,
        pessoas=pessoas,
        marcas=marcas,
    )


def test_pessoa_e_marca_na_lixeira_mantem_os_vinculos_no_indice_no_bigquery_e_no_job() -> (
    None
):
    pessoas, marcas = _catalogos()
    mundo = Mundo(copia=CopiaEmMemoria(), modelo=_modelo_com_marca())

    _reindexar(mundo, pessoas, marcas)

    job = mundo.jobs.obter("j1")
    assert job and job.indexacao and job.indexacao.estado == "indexado"
    assert SABRINA in job.pessoas_do_catalogo
    assert job.marcas_do_catalogo == ["marca-x"]
    assert SABRINA in _ids_no_indice(mundo)
    assert SABRINA in _ids_no_bigquery(mundo)


def test_a_indexacao_le_o_catalogo_em_lote() -> None:
    pessoas, marcas = _catalogos()
    mundo = Mundo(modelo=_modelo_com_marca())

    _reindexar(mundo, pessoas, marcas)

    assert pessoas.lotes == 1
    assert pessoas.individuais == 0


def test_a_copia_usa_a_leitura_corrigida_com_os_catalogos_em_lote() -> None:
    pessoas, marcas = _catalogos()
    mundo = Mundo(copia=CopiaEmMemoria(), modelo=_modelo_com_marca())
    job = mundo.jobs.obter("j1")
    assert job

    copiar(
        job,
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.copia,
        pessoas=pessoas,
        marcas=marcas,
        indice=mundo.indice,
    )

    assert SABRINA in _ids_no_bigquery(mundo)
    assert pessoas.lotes >= 1
    assert pessoas.individuais == 0


def test_copiar_jobs_e_reindexar_jobs_aceitam_os_catalogos() -> None:
    pessoas, marcas = _catalogos()
    mundo = Mundo(copia=CopiaEmMemoria(), modelo=_modelo_com_marca())

    assert copiar_jobs(
        ["j1"],
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.copia,
        pessoas=pessoas,
        marcas=marcas,
        indice=mundo.indice,
    ) == {"j1": "copiado"}
    assert reindexar_jobs(
        ["j1"],
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.indice,
        copia=mundo.copia,
        pessoas=pessoas,
        marcas=marcas,
    ) == {"j1": "indexado"}
