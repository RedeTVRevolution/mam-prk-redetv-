"""Passada de comparação (#247): comando e rotas, sem nuvem."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import NotFound

from api.auth import Usuario
from api.comparar_objetos import FaltaNoAmbiente, Preco
from api.decupagem import Decupagem
from api.gemini import Chamada
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.passadas import (
    ETAPA_DE_CUSTO,
    JobNaoConcluido,
    Passada,
    PassadasEmMemoria,
    PassadasStorage,
    rodar_passada,
)
from api.tests.test_auth import VerificadorFalso
from api.tests.test_gemini import BOA
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
PRECO = Preco(1.0, 4.0)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}


class TransporteContado:
    def __init__(self) -> None:
        self.tokens_de_entrada = 0
        self.tokens_de_saida = 0
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        self.tokens_de_entrada += 1000
        self.tokens_de_saida += 200
        return BOA


class Relogio:
    def __init__(self) -> None:
        self.agora = 0.0

    def __call__(self) -> float:
        self.agora += 2.0
        return self.agora


def _job(estado: str = "concluido") -> Job:
    return Job(
        id="j1",
        nome="a.mp4",
        tamanho_bytes=10,
        sha256="a" * 64,
        duracao_s=60.0,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        criado_em=BASE,
        atualizado_em=BASE,
    )


def _rodar(
    estado: str = "concluido",
    modelo: str = "gemini-3.8-flash",
    preco: Preco = PRECO,
    armazem: PassadasEmMemoria | None = None,
) -> tuple[Passada, PassadasEmMemoria, TransporteContado]:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job(estado))
    armazem = armazem or PassadasEmMemoria()
    transporte = TransporteContado()
    passada = rodar_passada(
        "j1",
        modelo,
        preco,
        repositorio=repositorio,
        armazem=armazem,
        transporte=transporte,
        relogio=Relogio(),
        agora=lambda: BASE,
        dormir=lambda _s: None,
    )
    return passada, armazem, transporte


def test_grava_a_passada_com_modelo_data_custo_e_tempo_de_cada_etapa() -> None:
    passada, armazem, _ = _rodar()

    assert armazem.ler_passada("j1", passada.id) == passada
    assert (passada.job_id, passada.modelo, passada.criada_em) == (
        "j1",
        "gemini-3.8-flash",
        BASE,
    )
    assert passada.custo.tokens_de_entrada == 1000
    assert passada.custo.tokens_de_saida == 200
    # 1000 tokens a US$ 1 e 200 a US$ 4, por milhão.
    assert passada.custo.usd == pytest.approx(0.0018)
    assert [e.nome for e in passada.etapas] == ["janelas", "identificacao"]
    assert all(e.segundos > 0 for e in passada.etapas)
    assert passada.decupagem.video.duracao_ms == 60_000


def test_a_chamada_usa_o_modelo_pedido_e_o_rotulo_de_custo_proprio() -> None:
    _, _, transporte = _rodar()

    (chamada,) = transporte.chamadas
    assert chamada.modelo == "gemini-3.8-flash"
    assert chamada.rotulos == {"job_id": "j1", "etapa": ETAPA_DE_CUSTO}


class _Blob:
    def __init__(self, cliente: "_StorageFalso", bucket: str, nome: str) -> None:
        self._cliente, self._chave = cliente, (bucket, nome)

    def download_as_bytes(self) -> bytes:
        if self._chave not in self._cliente.objetos:
            raise NotFound(self._chave[1])  # type: ignore[no-untyped-call]
        return self._cliente.objetos[self._chave]

    def upload_from_string(self, conteudo: str, content_type: str) -> None:
        self._cliente.objetos[self._chave] = conteudo.encode()
        self._cliente.gravados.append(self._chave)


class _Bucket:
    def __init__(self, cliente: "_StorageFalso", nome: str) -> None:
        self._cliente, self._nome = cliente, nome

    def blob(self, nome: str) -> _Blob:
        return _Blob(self._cliente, self._nome, nome)


class _StorageFalso:
    def __init__(self, objetos: dict[tuple[str, str], bytes]) -> None:
        self.objetos = objetos
        self.gravados: list[tuple[str, str]] = []

    def bucket(self, nome: str) -> _Bucket:
        return _Bucket(self, nome)

    def list_blobs(self, bucket: str, prefix: str) -> list[_Blob]:
        return [
            _Blob(self, b, n)
            for b, n in sorted(self.objetos)
            if b == bucket and n.startswith(prefix)
        ]


def test_a_decupagem_do_job_nao_muda() -> None:
    decupagem_do_job = ("decupagens", "j1.json")
    storage = _StorageFalso({decupagem_do_job: b'{"intacta": true}'})
    armazem = PassadasStorage(cast(Any, storage), "aceitos", "decupagens")
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job())
    transporte = TransporteContado()

    passada = rodar_passada(
        "j1",
        "gemini-3.8-flash",
        PRECO,
        repositorio=repositorio,
        armazem=armazem,
        transporte=transporte,
        agora=lambda: BASE,
        dormir=lambda _s: None,
    )

    assert storage.objetos[decupagem_do_job] == b'{"intacta": true}'
    assert storage.gravados == [("decupagens", f"j1/passadas/{passada.id}.json")]
    assert transporte.chamadas[0].video_uri == "gs://aceitos/j1/proxy.mp4"
    assert armazem.ler_passada("j1", passada.id) == passada
    assert [r.id for r in armazem.listar_passadas("j1")] == [passada.id]
    assert armazem.ler_passada("j1", "outra") is None


def test_todas_as_janelas_usam_o_modelo_pedido_sem_escalonamento() -> None:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(_job().model_copy(update={"duracao_s": 720.0}))
    transporte = TransporteContado()

    passada = rodar_passada(
        "j1",
        "gemini-3.8-flash",
        PRECO,
        repositorio=repositorio,
        armazem=PassadasEmMemoria(),
        transporte=transporte,
        relogio=Relogio(),
        agora=lambda: BASE,
        dormir=lambda _s: None,
    )

    # 12 min: três janelas, uma chamada cada (nada de escalonamento).
    assert len(transporte.chamadas) == 3
    assert {c.modelo for c in transporte.chamadas} == {"gemini-3.8-flash"}
    assert all(c.rotulos["etapa"] == ETAPA_DE_CUSTO for c in transporte.chamadas)
    assert passada.custo.tokens_de_entrada == 3000
    assert [e.nome for e in passada.etapas] == [
        "janelas",
        "consolidacao",
        "identificacao",
    ]


def test_modelo_com_barra_nao_roda() -> None:
    with pytest.raises(ValueError, match="sem barra"):
        _rodar(modelo="publishers/google/models/gemini-3.8-flash")


def test_job_que_nao_esta_concluido_nao_roda_passada() -> None:
    with pytest.raises(JobNaoConcluido):
        _rodar(estado="analisando")


def test_duas_passadas_ficam_lado_a_lado() -> None:
    armazem = PassadasEmMemoria()
    primeira, _, _ = _rodar(armazem=armazem)
    segunda, _, _ = _rodar(modelo="gemini-3.5-flash-lite", armazem=armazem)

    assert primeira.id != segunda.id
    assert {p.id for p in armazem.listar_passadas("j1")} == {primeira.id, segunda.id}


def test_modelo_sem_preco_no_ambiente_e_erro() -> None:
    from api.passadas import preco_do_modelo

    assert preco_do_modelo("m", "m=1:4") == Preco(1.0, 4.0)
    with pytest.raises(FaltaNoAmbiente, match="m"):
        preco_do_modelo("m", "outro=1:4")


def test_a_passada_nao_chega_ao_indice_ao_acervo_nem_ao_webhook() -> None:
    # A passada só conhece o repositório (leitura), o transporte e o seu armazém:
    # nada de índice, webhook ou correções entra nos parâmetros.
    import inspect

    nomes = set(inspect.signature(rodar_passada).parameters)
    assert nomes.isdisjoint({"indice", "webhook", "correcoes", "disparo"})
    passada, armazem, _ = _rodar()
    cliente = _cliente(armazem)

    # Não é um Job: não recebe correções nem aparece na lista do Acervo.
    corrige = cliente.post(
        f"/v1/jobs/{passada.id}/correcoes", json={}, headers=AUTORIZACAO
    )
    assert corrige.status_code in (403, 404, 422)
    ids = [j["id"] for j in cliente.get("/v1/jobs", headers=AUTORIZACAO).json()]
    assert ids == ["j1"]


def _cliente(armazem: PassadasEmMemoria, papeis: list[Papel] | None = None) -> Any:
    repo_papeis = RepositorioDePapeisEmMemoria()
    if papeis is not None:
        repo_papeis.salvar("u1", papeis)
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job())
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            jobs,
            ArmazenamentoFalso(),
            papeis=repo_papeis,
            passadas=armazem,
        )
    )


def test_rota_lista_as_passadas_sem_a_decupagem() -> None:
    passada, armazem, _ = _rodar()

    resposta = _cliente(armazem).get("/v1/jobs/j1/passadas", headers=AUTORIZACAO)

    assert resposta.status_code == 200
    (item,) = resposta.json()
    assert item["id"] == passada.id and item["modelo"] == "gemini-3.8-flash"
    assert item["custo"]["usd"] == pytest.approx(0.0018)
    assert "decupagem" not in item


def test_rota_devolve_uma_passada_com_a_decupagem() -> None:
    passada, armazem, _ = _rodar()

    resposta = _cliente(armazem).get(
        f"/v1/jobs/j1/passadas/{passada.id}", headers=AUTORIZACAO
    )

    assert resposta.status_code == 200
    Decupagem.model_validate(resposta.json()["decupagem"])


def test_passada_que_nao_existe_e_404() -> None:
    cliente = _cliente(PassadasEmMemoria())

    resposta = cliente.get("/v1/jobs/j1/passadas/nao-existe", headers=AUTORIZACAO)

    assert resposta.status_code == 404


def test_job_que_nao_existe_e_404() -> None:
    cliente = _cliente(PassadasEmMemoria())

    assert cliente.get("/v1/jobs/x/passadas", headers=AUTORIZACAO).status_code == 404


def test_sem_decupagem_ver_e_403() -> None:
    passada, armazem, _ = _rodar()
    cliente = _cliente(armazem, papeis=[])

    assert cliente.get("/v1/jobs/j1/passadas", headers=AUTORIZACAO).status_code == 403
    rota = f"/v1/jobs/j1/passadas/{passada.id}"
    assert cliente.get(rota, headers=AUTORIZACAO).status_code == 403
