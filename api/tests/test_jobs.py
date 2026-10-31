import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from api.auth import TokenInvalido, Usuario
from api.correcoes import versao_do_modelo
from api.jobs import (
    Estado,
    Job,
    RepositorioEmMemoria,
    ServicoIndisponivel,
    expirar_uploads,
)
from api.main import criar_app

AUTORIZACAO = {"Authorization": "Bearer token-bom"}
INICIO = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class VerificadorFalso:
    def verificar(self, token: str) -> Usuario:
        if token != "token-bom":
            raise TokenInvalido
        return Usuario(uid="u1", email="ana@redetv.com.br")


class ArmazenamentoFalso:
    """Storage simulado: devolve uma URL assinada fixa por Job e anota o que pediram."""

    def __init__(self) -> None:
        self.pedidos: list[dict[str, Any]] = []
        self.cancelados: list[str] = []
        self.decupagens: dict[str, list[bytes]] = {}
        self.decupagens_indisponiveis = False

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        self.pedidos.append(
            {"job_id": job_id, "tamanho_bytes": tamanho_bytes, "tipo": tipo}
        )
        return f"https://storage.exemplo/quarentena/{job_id}?assinatura=x"

    def cancelar_upload(self, job_id: str) -> None:
        self.cancelados.append(job_id)

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        return f"https://storage.exemplo/proxy/{job_id}?validade={int(validade.total_seconds())}"

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        # Gerador, como seria o adaptador real: a falha só aparece no primeiro pedaço.
        if self.decupagens_indisponiveis:
            raise ServicoIndisponivel
        yield from self.decupagens[job_id]


class Relogio:
    def __init__(self) -> None:
        self.agora = INICIO

    def __call__(self) -> datetime:
        return self.agora


class Ambiente:
    def __init__(self, tamanho_maximo: int = 4 * 1024**3) -> None:
        self.repositorio = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.relogio = Relogio()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(),
                repositorio=self.repositorio,
                armazenamento=self.armazenamento,
                tamanho_maximo_bytes=tamanho_maximo,
                relogio=self.relogio,
            )
        )

    def criar(self, **corpo: Any) -> Any:
        padrao = {"nome": "clipe.mp4", "tamanho_bytes": 1000, "tipo": "video/mp4"}
        return self.cliente.post(
            "/v1/jobs", json={**padrao, **corpo}, headers=AUTORIZACAO
        )


def test_criar_job_devolve_202_com_url_assinada_e_job_aguardando_upload() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar()

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["estado"] == "aguardando_upload"
    assert (
        corpo["url_de_upload"]
        == f"https://storage.exemplo/quarentena/{corpo['id']}?assinatura=x"
    )
    assert ambiente.armazenamento.pedidos == [
        {"job_id": corpo["id"], "tamanho_bytes": 1000, "tipo": "video/mp4"}
    ]
    guardado = ambiente.cliente.get(
        f"/v1/jobs/{corpo['id']}", headers=AUTORIZACAO
    ).json()
    assert guardado["nome"] == "clipe.mp4"
    assert guardado["estado"] == "aguardando_upload"


def test_tipo_diferente_de_mp4_recebe_415_e_nada_e_criado() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar(tipo="video/quicktime")

    assert resposta.status_code == 415
    assert ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json() == []
    assert ambiente.armazenamento.pedidos == []


def test_tipo_errado_recebe_415_mesmo_com_nome_ou_tamanho_invalidos() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar(nome="clipe.mov", tipo="video/quicktime", tamanho_bytes=0)

    assert resposta.status_code == 415
    assert ambiente.armazenamento.pedidos == []


def test_tamanho_acima_do_maximo_configurado_recebe_422() -> None:
    ambiente = Ambiente(tamanho_maximo=5000)

    assert ambiente.criar(tamanho_bytes=5000).status_code == 202
    assert ambiente.criar(tamanho_bytes=5001).status_code == 422


def test_tamanho_zero_negativo_ou_nao_inteiro_recebe_422() -> None:
    ambiente = Ambiente()

    for tamanho in (0, -1, "1000", 10.5, None):
        assert ambiente.criar(tamanho_bytes=tamanho).status_code == 422


def test_nome_vazio_ou_longo_recebe_422() -> None:
    ambiente = Ambiente()

    assert ambiente.criar(nome="").status_code == 422
    assert ambiente.criar(nome="a" * 252 + ".mp4").status_code == 422


def test_nome_com_caminho_ou_sem_extensao_mp4_recebe_422() -> None:
    ambiente = Ambiente()

    for nome in (
        "../clipe.mp4",
        "a/b.mp4",
        "a\\b.mp4",
        "clipe.mov",
        "clipe",
        "a\x00b.mp4",
    ):
        assert ambiente.criar(nome=nome).status_code == 422, nome


def test_campo_desconhecido_recebe_422() -> None:
    assert Ambiente().criar(estado="concluido").status_code == 422


def test_get_jobs_lista_do_mais_recente_para_o_mais_antigo() -> None:
    ambiente = Ambiente()
    for nome in ("a.mp4", "b.mp4", "c.mp4"):
        ambiente.criar(nome=nome)
        ambiente.relogio.agora += timedelta(minutes=1)

    lista = ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()

    assert [j["nome"] for j in lista] == ["c.mp4", "b.mp4", "a.mp4"]
    assert set(lista[0]) == {
        "id",
        "nome",
        "programa",
        "estado",
        "codigo_falha",
        "duracao_s",
        "criado_em",
        "atualizado_em",
    }


def test_get_job_inexistente_recebe_404() -> None:
    resposta = Ambiente().cliente.get("/v1/jobs/nao-existe", headers=AUTORIZACAO)

    assert resposta.status_code == 404


def test_jobs_sem_token_recebe_401() -> None:
    assert Ambiente().cliente.get("/v1/jobs").status_code == 401


def test_sem_adaptadores_reais_a_api_responde_503() -> None:
    cliente = TestClient(criar_app(VerificadorFalso()))

    assert cliente.get("/v1/jobs", headers=AUTORIZACAO).status_code == 503


def test_job_sem_upload_em_24h_vira_falhou_com_upload_expirado() -> None:
    ambiente = Ambiente()
    antigo = ambiente.criar(nome="antigo.mp4").json()["id"]
    ambiente.relogio.agora += timedelta(hours=23, minutes=59)
    recente = ambiente.criar(nome="recente.mp4").json()["id"]
    ambiente.relogio.agora = INICIO + timedelta(hours=24)

    expirados = expirar_uploads(
        ambiente.repositorio, ambiente.armazenamento, ambiente.relogio()
    )

    assert expirados == [antigo]
    assert ambiente.armazenamento.cancelados == [antigo]
    job = ambiente.cliente.get(f"/v1/jobs/{antigo}", headers=AUTORIZACAO).json()
    assert (job["estado"], job["codigo_falha"]) == ("falhou", "upload_expirado")
    assert ambiente.cliente.get(f"/v1/jobs/{recente}", headers=AUTORIZACAO).json()[
        "estado"
    ] == ("aguardando_upload")


def test_expiracao_nao_mexe_em_job_que_ja_passou_do_upload() -> None:
    ambiente = Ambiente()
    job_id = ambiente.criar().json()["id"]
    job = ambiente.repositorio.obter(job_id)
    assert isinstance(job, Job)
    ambiente.repositorio.salvar(job.model_copy(update={"estado": "validando"}))
    ambiente.relogio.agora += timedelta(days=3)

    assert (
        expirar_uploads(
            ambiente.repositorio, ambiente.armazenamento, ambiente.relogio()
        )
        == []
    )


def _job_com_estado(ambiente: Ambiente, estado: Estado) -> str:
    job = Job(
        id="j1",
        nome="clipe.mp4",
        tamanho_bytes=10,
        estado=estado,
        codigo_falha="analise_falhou" if estado == "falhou" else None,
        criado_por="u1",
        criado_em=INICIO,
        atualizado_em=INICIO,
    )
    ambiente.repositorio.salvar(job)
    return job.id


def test_reproducao_devolve_link_assinado_e_quando_expira() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")

    resposta = ambiente.cliente.get(
        f"/v1/jobs/{job_id}/reproducao", headers=AUTORIZACAO
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "url": "https://storage.exemplo/proxy/j1?validade=600",
        "expira_em": "2026-10-29T12:10:00Z",
    }


def test_reproducao_e_decupagem_dao_409_antes_de_concluido_e_404_sem_job() -> None:
    ambiente = Ambiente()
    estados: list[Estado] = [
        "aguardando_upload",
        "validando",
        "analisando",
        "falhou",
        "cancelado",
    ]
    for estado in estados:
        job_id = _job_com_estado(ambiente, estado)
        for rota in ("reproducao", "decupagem"):
            resposta = ambiente.cliente.get(
                f"/v1/jobs/{job_id}/{rota}", headers=AUTORIZACAO
            )
            assert resposta.status_code == 409, (estado, rota)
    for rota in ("reproducao", "decupagem"):
        resposta = ambiente.cliente.get(
            f"/v1/jobs/nao-existe/{rota}", headers=AUTORIZACAO
        )
        assert resposta.status_code == 404


def test_decupagem_chega_em_gzip_e_inteira() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")
    documento = {"versao_esquema": "1.2", "pessoas": ["Ana"] * 200}
    texto = json.dumps(documento).encode()
    ambiente.armazenamento.decupagens[job_id] = [texto[:50], texto[50:]]

    resposta = ambiente.cliente.get(
        f"/v1/jobs/{job_id}/decupagem",
        headers={**AUTORIZACAO, "Accept-Encoding": "gzip"},
    )

    assert resposta.status_code == 200
    assert resposta.headers["content-encoding"] == "gzip"
    assert resposta.headers["content-type"] == "application/json"
    entregue = resposta.json()  # o cliente já descomprimiu
    assert entregue.pop("versao_decupagem") == versao_do_modelo(texto)
    assert entregue == documento


def test_decupagem_sem_gzip_no_pedido_vem_em_texto_puro() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")
    ambiente.armazenamento.decupagens[job_id] = [b'{"a": 1}']

    resposta = ambiente.cliente.get(
        f"/v1/jobs/{job_id}/decupagem",
        headers={**AUTORIZACAO, "Accept-Encoding": "identity"},
    )

    assert "content-encoding" not in resposta.headers
    assert resposta.json() == {
        "a": 1,
        "versao_decupagem": versao_do_modelo(b'{"a": 1}'),
    }


def test_reproducao_e_decupagem_exigem_token() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")
    for rota in ("reproducao", "decupagem"):
        assert ambiente.cliente.get(f"/v1/jobs/{job_id}/{rota}").status_code == 401


def test_decupagem_com_gzip_recusado_vem_em_texto_puro() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")
    ambiente.armazenamento.decupagens[job_id] = [b'{"a": 1}']

    resposta = ambiente.cliente.get(
        f"/v1/jobs/{job_id}/decupagem",
        headers={**AUTORIZACAO, "Accept-Encoding": "gzip;q=0, identity"},
    )

    assert "content-encoding" not in resposta.headers
    assert resposta.json() == {
        "a": 1,
        "versao_decupagem": versao_do_modelo(b'{"a": 1}'),
    }


def test_decupagem_indisponivel_da_503_antes_de_comecar_o_stream() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")
    ambiente.armazenamento.decupagens_indisponiveis = True

    resposta = ambiente.cliente.get(f"/v1/jobs/{job_id}/decupagem", headers=AUTORIZACAO)

    assert resposta.status_code == 503


def _cancelar(ambiente: Ambiente, job_id: str) -> Any:
    return ambiente.cliente.delete(f"/v1/jobs/{job_id}", headers=AUTORIZACAO)


def test_delete_cancela_job_em_andamento_e_responde_202_com_o_job() -> None:
    ambiente = Ambiente()
    estados: list[Estado] = ["aguardando_upload", "validando", "analisando"]
    for estado in estados:
        job_id = _job_com_estado(ambiente, estado)
        ambiente.relogio.agora += timedelta(minutes=1)

        resposta = _cancelar(ambiente, job_id)

        assert resposta.status_code == 202, estado
        assert resposta.json()["estado"] == "cancelado"
        assert resposta.json()["atualizado_em"] == "2026-10-29T12:01:00Z"
        job = ambiente.repositorio.obter(job_id)
        assert job is not None and job.estado == "cancelado"
        ambiente.relogio.agora = INICIO


def test_delete_repetido_em_job_cancelado_responde_202_sem_mudar_nada() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "cancelado")

    resposta = _cancelar(ambiente, job_id)

    assert resposta.status_code == 202
    assert resposta.json()["estado"] == "cancelado"
    job = ambiente.repositorio.obter(job_id)
    assert job is not None and job.atualizado_em == INICIO


def test_delete_em_concluido_ou_falhou_recebe_409_e_nao_muda_o_job() -> None:
    ambiente = Ambiente()
    for estado in ("concluido", "falhou"):
        job_id = _job_com_estado(ambiente, estado)

        assert _cancelar(ambiente, job_id).status_code == 409
        job = ambiente.repositorio.obter(job_id)
        assert job is not None and job.estado == estado


def test_delete_de_job_inexistente_recebe_404() -> None:
    assert _cancelar(Ambiente(), "nao-existe").status_code == 404


def test_delete_exige_token() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")

    assert ambiente.cliente.delete(f"/v1/jobs/{job_id}").status_code == 401


def test_expiracao_ignora_job_cancelado() -> None:
    ambiente = Ambiente()
    job_id = ambiente.criar().json()["id"]
    assert _cancelar(ambiente, job_id).status_code == 202
    ambiente.relogio.agora += timedelta(days=3)

    assert (
        expirar_uploads(
            ambiente.repositorio, ambiente.armazenamento, ambiente.relogio()
        )
        == []
    )
    job = ambiente.repositorio.obter(job_id)
    assert job is not None and job.estado == "cancelado"
    assert ambiente.armazenamento.cancelados == []


def _consultar(ambiente: Ambiente, job_id: str, **cabecalhos: str) -> Any:
    return ambiente.cliente.get(
        f"/v1/jobs/{job_id}", headers={**AUTORIZACAO, **cabecalhos}
    )


def test_status_devolve_etag_e_cache_control_privado() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")

    resposta = _consultar(ambiente, job_id)

    assert resposta.status_code == 200
    assert resposta.headers["ETag"].startswith('"')
    assert resposta.headers["Cache-Control"] == "private, no-cache"
    assert resposta.json()["estado"] == "analisando"


def test_if_none_match_igual_ao_atual_responde_304_sem_corpo() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    etag = _consultar(ambiente, job_id).headers["ETag"]

    resposta = _consultar(ambiente, job_id, **{"If-None-Match": etag})

    assert resposta.status_code == 304
    assert resposta.content == b""
    assert resposta.headers["ETag"] == etag
    assert resposta.headers["Cache-Control"] == "private, no-cache"


def test_mudanca_de_estado_muda_o_etag_e_o_mesmo_if_none_match_da_200() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    antigo = _consultar(ambiente, job_id).headers["ETag"]
    ambiente.relogio.agora += timedelta(minutes=1)
    job = ambiente.repositorio.obter(job_id)
    assert job is not None
    ambiente.repositorio.salvar(
        job.model_copy(
            update={"estado": "concluido", "atualizado_em": ambiente.relogio()}
        )
    )

    resposta = _consultar(ambiente, job_id, **{"If-None-Match": antigo})

    assert resposta.status_code == 200
    assert resposta.headers["ETag"] != antigo
    assert resposta.json()["estado"] == "concluido"


def test_etag_muda_com_codigo_de_falha_ou_duracao_ou_atualizado_em() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    job = ambiente.repositorio.obter(job_id)
    assert job is not None
    etags = set()
    mudancas: list[dict[str, Any]] = [
        {},
        {"codigo_falha": "analise_falhou"},
        {"duracao_s": 30.0},
        {"atualizado_em": INICIO + timedelta(seconds=1)},
    ]
    for mudanca in mudancas:
        ambiente.repositorio.salvar(job.model_copy(update=mudanca))
        etags.add(_consultar(ambiente, job_id).headers["ETag"])

    assert len(etags) == 4


def test_if_none_match_aceita_lista_de_etags_e_etag_fraca() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    etag = _consultar(ambiente, job_id).headers["ETag"]

    em_lista = _consultar(ambiente, job_id, **{"If-None-Match": f'"outro", {etag}'})
    fraca = _consultar(ambiente, job_id, **{"If-None-Match": f"W/{etag}"})
    outro = _consultar(ambiente, job_id, **{"If-None-Match": '"outro"'})
    todos = _consultar(ambiente, job_id, **{"If-None-Match": "*"})

    assert em_lista.status_code == 304
    assert fraca.status_code == 304
    assert outro.status_code == 200
    assert todos.status_code == 304


def test_status_com_etag_exige_autenticacao_e_404_segue_404() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    etag = _consultar(ambiente, job_id).headers["ETag"]

    sem_chave = ambiente.cliente.get(
        f"/v1/jobs/{job_id}", headers={"If-None-Match": etag}
    )

    assert sem_chave.status_code == 401
    assert (
        _consultar(ambiente, "nao-existe", **{"If-None-Match": etag}).status_code == 404
    )


def test_programa_com_perfil_fica_no_job_e_aparece_na_api() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar(programa="TV Fama")

    assert resposta.status_code == 202
    assert resposta.json()["programa"] == "TV Fama"
    job = ambiente.repositorio.obter(resposta.json()["id"])
    assert job is not None and job.programa == "TV Fama"


def test_programa_sem_perfil_da_422() -> None:
    assert Ambiente().criar(programa="Programa Inventado").status_code == 422


def test_get_programas_lista_os_perfis() -> None:
    resposta = Ambiente().cliente.get("/v1/programas", headers=AUTORIZACAO)

    assert resposta.status_code == 200
    assert resposta.json() == ["TV Fama"]


def test_get_programas_exige_login() -> None:
    assert Ambiente().cliente.get("/v1/programas").status_code == 401
