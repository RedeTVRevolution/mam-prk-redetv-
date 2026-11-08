"""A posição na GPU é calculada na leitura, sem mudar o Job."""

from typing import Any

import pytest

from api.eventos_de_uso import EventosEmMemoria
from api.eventos_do_job import (
    PublicadorEmMemoria,
    RepositorioQuePublicaOFim,
    RepositorioQueRegistraOFim,
)
from api.jobs import RepositorioEmMemoria
from api.tests.test_rotas_do_painel import AGORA, CABECALHO, Mundo, _job_ha
from api.webhook import RepositorioDeWebhooksEmMemoria


class JobsComFila(RepositorioEmMemoria):
    def __init__(self, documento: dict[str, Any]) -> None:
        super().__init__()
        self.documento = documento

    def obter_fila_gpu(self) -> dict[str, Any]:
        return self.documento


def pedido(job_id: str, etapa: str = "transcricao", **campos: Any) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "etapa": etapa,
        "dono": "execucao",
        "chegada": AGORA.timestamp() - 600,
        "visto_em": AGORA.timestamp(),
        "timeout_gpu": 300,
        **campos,
    }


def test_detalhe_calcula_a_posicao_por_criacao_job_e_etapa_sem_gravar() -> None:
    repositorio = JobsComFila(
        {
            "espera": [
                pedido("b"),
                pedido("a"),
                pedido("a", "leitura_da_tela"),
                pedido("antigo", chegada=AGORA.timestamp() - 1200),
            ],
            "ocupadas": [pedido("ocupante", desde=AGORA.timestamp())],
        }
    )
    for id_ in ("a", "b", "antigo", "ocupante", "fora"):
        repositorio.salvar(_job_ha(id_, "analisando", 5))
    com_eventos = RepositorioQueRegistraOFim(
        RepositorioQuePublicaOFim(
            repositorio, RepositorioDeWebhooksEmMemoria(), PublicadorEmMemoria()
        ),
        EventosEmMemoria(),
    )
    mundo = Mundo(["diretoria"], jobs=com_eventos, relogio=lambda: AGORA)

    for id_, posicao in (
        ("antigo", 1),
        ("a", 2),
        ("b", 4),
        ("ocupante", None),
        ("fora", None),
    ):
        resposta = mundo.cliente.get(f"/v1/jobs/{id_}", headers=CABECALHO)
        assert resposta.status_code == 200
        assert resposta.json().get("posicao_na_fila_gpu") == posicao
    assert repositorio.obter("a") == _job_ha("a", "analisando", 5)


@pytest.mark.parametrize(
    "estado,etapa,sem_pulso_s,conta",
    [
        ("analisando", "transcricao", 180, True),
        ("analisando", "transcricao", 181, False),
        ("concluido", "inventario_de_objetos", 180, True),
        ("concluido", "inventario_de_objetos", 181, False),
        ("concluido", "transcricao", 0, False),
        ("concluido", "leitura_da_tela", 0, False),
        ("falhou", "inventario_de_objetos", 0, False),
        ("cancelado", "inventario_de_objetos", 0, False),
        ("validando", "transcricao", 0, False),
        ("aguardando_upload", "transcricao", 0, False),
        (None, "transcricao", 0, False),
    ],
)
def test_pedido_abandonado_nao_ocupa_posicao_e_florence_concluido_conta(
    estado: Any, etapa: str, sem_pulso_s: int, conta: bool
) -> None:
    repositorio = JobsComFila(
        {
            "espera": [
                pedido("a", etapa, visto_em=AGORA.timestamp() - sem_pulso_s),
                pedido("b"),
            ],
            "ocupadas": [
                pedido("expirado", desde=AGORA.timestamp() - 301),
                pedido("apagado", desde=AGORA.timestamp()),
                pedido("terminado", desde=AGORA.timestamp()),
                pedido("florence", "inventario_de_objetos", desde=AGORA.timestamp()),
            ],
        }
    )
    if estado is not None:
        repositorio.salvar(_job_ha("a", estado, 10))
    repositorio.salvar(_job_ha("b", "analisando", 10))
    repositorio.salvar(_job_ha("expirado", "analisando", 10))
    repositorio.salvar(_job_ha("terminado", "concluido", 10))
    repositorio.salvar(_job_ha("florence", "concluido", 10))
    mundo = Mundo(["diretoria"], jobs=repositorio, relogio=lambda: AGORA)

    resposta = mundo.cliente.get("/v1/jobs/b", headers=CABECALHO)

    assert resposta.status_code == 200
    assert resposta.json()["posicao_na_fila_gpu"] == (2 if conta else 1)

    fila = mundo.get("/fila")
    assert fila.status_code == 200
    assert fila.json()["esperando_gpu"] == {
        "quantidade": 2 if conta else 1,
        "idade_do_mais_antigo_s": 600,
    }


def test_painel_conta_pedidos_e_idade_desde_a_criacao_sem_os_abandonados() -> None:
    repositorio = JobsComFila(
        {
            "espera": [
                pedido("a", chegada=AGORA.timestamp() - 1200),
                pedido("a", "leitura_da_tela"),
                pedido("b"),
                pedido("abandonado", chegada=0, visto_em=0),
            ]
        }
    )
    for id_ in ("a", "b", "abandonado"):
        repositorio.salvar(_job_ha(id_, "analisando", 5))
    mundo = Mundo(["diretoria"], jobs=repositorio, relogio=lambda: AGORA)

    resposta = mundo.get("/fila", desde="2000-01-01", programa="outro")

    assert resposta.status_code == 200
    assert resposta.json()["esperando_gpu"] == {
        "quantidade": 3,
        "idade_do_mais_antigo_s": 1200,
    }
    repositorio.documento = {}
    assert mundo.get("/fila").json()["esperando_gpu"] == {
        "quantidade": 0,
        "idade_do_mais_antigo_s": 0,
    }
