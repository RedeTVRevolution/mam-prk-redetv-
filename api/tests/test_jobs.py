import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import TokenInvalido, Usuario
from api.correcoes import versao_do_modelo
from api.idempotencia import RepositorioDeIdempotenciaEmMemoria
from api.jobs import (
    Estado,
    Job,
    RepositorioEmMemoria,
    ServicoIndisponivel,
    expirar_uploads,
)
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.programas_de_teste import cadastro_com_tv_fama

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
        self.comparacoes: dict[str, bytes] = {}
        self.quadros: dict[tuple[str, str], bytes] = {}
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

    def url_de_download(self, job_id: str, nome: str, validade: timedelta) -> str:
        return f"https://storage.exemplo/copia-limpa/{job_id}?nome={nome}&validade={int(validade.total_seconds())}"

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        return f"https://storage.exemplo/quadros/{job_id}/{caminho}?validade={int(validade.total_seconds())}"

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return self.quadros[(job_id, caminho)]

    def ler_comparacao(self, job_id: str) -> bytes | None:
        return self.comparacoes.get(job_id)

    def url_da_foto(self, objeto: str, validade: timedelta) -> str:
        return f"https://storage.exemplo/fotos/{objeto}?validade={int(validade.total_seconds())}"

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
        self.idempotencia = RepositorioDeIdempotenciaEmMemoria()
        self.repositorio = RepositorioEmMemoria()
        self.armazenamento = ArmazenamentoFalso()
        self.relogio = Relogio()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("u1", ["editor"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(),
                papeis=papeis,
                repositorio=self.repositorio,
                armazenamento=self.armazenamento,
                tamanho_maximo_bytes=tamanho_maximo,
                relogio=self.relogio,
                idempotencia=self.idempotencia,
                programas=cadastro_com_tv_fama()[0],
            )
        )

    def criar(self, **corpo: Any) -> Any:
        padrao = {
            "nome": "clipe.mp4",
            "tamanho_bytes": 1000,
            "tipo": "video/mp4",
            "data_exibicao": "2026-10-01",
        }
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


def test_criacao_grava_e_expoe_o_inicio_da_passada_com_a_data_de_criacao() -> None:
    ambiente = Ambiente()

    resposta = ambiente.criar()

    assert resposta.status_code == 202
    corpo = resposta.json()
    job = ambiente.repositorio.obter(corpo["id"])
    assert job is not None
    assert job.inicio_da_passada == job.criado_em == INICIO
    assert corpo["inicio_da_passada"] == corpo["criado_em"]
    for rota in (f"/v1/jobs/{job.id}", "/v1/jobs", f"/v1/jobs/andamento?ids={job.id}"):
        publico = ambiente.cliente.get(rota, headers=AUTORIZACAO).json()
        if isinstance(publico, list):
            [publico] = publico
        assert publico["inicio_da_passada"] == corpo["criado_em"]


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
        "data_exibicao",
        "indexacao",
        "copia_bigquery",
        "etapa_atual",
        "etapas",
        "reprocessamentos",
        "inicio_da_passada",
        "enviado_por",
        "estado",
        "codigo_falha",
        "duracao_s",
        "timecode_origem",
        "taxa_de_quadros",
        "capa_url",
        "criado_em",
        "atualizado_em",
    }


def test_get_job_traz_timecode_de_origem_e_taxa_de_quadros() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    job = ambiente.repositorio.obter(job_id)
    assert job is not None
    ambiente.repositorio.salvar(
        job.model_copy(
            update={"timecode_origem": "01:00:00;00", "taxa_de_quadros": 30000 / 1001}
        )
    )

    corpo = ambiente.cliente.get(f"/v1/jobs/{job_id}", headers=AUTORIZACAO).json()

    assert corpo["timecode_origem"] == "01:00:00;00"
    assert corpo["taxa_de_quadros"] == pytest.approx(29.97, abs=0.001)


def test_get_job_traz_os_cortes_de_camera() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")
    job = ambiente.repositorio.obter(job_id)
    assert job is not None
    ambiente.repositorio.salvar(job.model_copy(update={"cortes_ms": [1200, 5400]}))

    corpo = ambiente.cliente.get(f"/v1/jobs/{job_id}", headers=AUTORIZACAO).json()

    assert corpo["cortes_ms"] == [1200, 5400]


def test_get_job_sem_timecode_traz_null() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "analisando")

    corpo = ambiente.cliente.get(f"/v1/jobs/{job_id}", headers=AUTORIZACAO).json()

    assert corpo["timecode_origem"] is None
    assert corpo["taxa_de_quadros"] is None
    assert corpo["cortes_ms"] is None


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


def test_reproducao_continua_com_link_de_10_min() -> None:
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


def test_quadro_devolve_link_assinado_do_jpeg_valido_por_8_h() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")

    resposta = ambiente.cliente.get(
        f"/v1/jobs/{job_id}/quadros/plano-0.jpg", headers=AUTORIZACAO
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "url": "https://storage.exemplo/quadros/j1/quadros/plano-0.jpg?validade=28800",
        "expira_em": "2026-10-29T19:00:00Z",
    }


def test_quadro_recusa_nome_que_nao_e_de_um_quadro_e_job_que_nao_concluiu() -> None:
    ambiente = Ambiente()
    job_id = _job_com_estado(ambiente, "concluido")
    for nome in ("..%2Fj2%2Fproxy.mp4", "plano-0.png", ".jpg", "a%2Fb.jpg"):
        resposta = ambiente.cliente.get(
            f"/v1/jobs/{job_id}/quadros/{nome}", headers=AUTORIZACAO
        )
        assert resposta.status_code in (404, 422), nome
    em_analise = _job_com_estado(ambiente, "analisando")
    resposta = ambiente.cliente.get(
        f"/v1/jobs/{em_analise}/quadros/plano-0.jpg", headers=AUTORIZACAO
    )
    assert resposta.status_code == 409


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


def test_data_de_exibicao_fica_no_job_e_volta_no_get_e_na_lista() -> None:
    ambiente = Ambiente()

    criado = ambiente.criar(data_exibicao="1999-12-31")

    assert criado.status_code == 202
    assert criado.json()["data_exibicao"] == "1999-12-31"
    job_id = criado.json()["id"]
    lido = ambiente.cliente.get(f"/v1/jobs/{job_id}", headers=AUTORIZACAO).json()
    assert lido["data_exibicao"] == "1999-12-31"
    lista = ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()
    assert lista[0]["data_exibicao"] == "1999-12-31"
    job = ambiente.repositorio.obter(job_id)
    assert job is not None and job.data_exibicao == date(1999, 12, 31)


def test_sem_data_de_exibicao_da_422_e_nao_cria_o_job() -> None:
    ambiente = Ambiente()
    corpo = {"nome": "clipe.mp4", "tamanho_bytes": 1000, "tipo": "video/mp4"}

    resposta = ambiente.cliente.post("/v1/jobs", json=corpo, headers=AUTORIZACAO)

    assert resposta.status_code == 422
    assert "data_exibicao" in resposta.text
    assert ambiente.armazenamento.pedidos == []
    assert ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json() == []


def test_data_de_exibicao_nula_da_422() -> None:
    assert Ambiente().criar(data_exibicao=None).status_code == 422


def test_data_de_exibicao_de_hoje_e_aceita_e_a_de_amanha_da_422() -> None:
    ambiente = Ambiente()

    assert ambiente.criar(data_exibicao="2026-10-29").status_code == 202
    assert ambiente.criar(data_exibicao="2026-10-30").status_code == 422


def test_data_de_exibicao_futura_conta_pelo_dia_de_brasilia() -> None:
    ambiente = Ambiente()
    # 01h30 em UTC do dia 30 ainda é 22h30 do dia 29 em Brasília.
    ambiente.relogio.agora = datetime(2026, 10, 30, 1, 30, tzinfo=UTC)

    assert ambiente.criar(data_exibicao="2026-10-30").status_code == 422
    assert ambiente.criar(data_exibicao="2026-10-29").status_code == 202


@pytest.mark.parametrize(
    "valor",
    ["31/12/1999", "1999-13-40", "ontem", 20261029, "", "1999-12-31T00:00:00"],
)
def test_data_de_exibicao_mal_formada_da_422(valor: Any) -> None:
    assert Ambiente().criar(data_exibicao=valor).status_code == 422


def test_job_guardado_sem_data_de_exibicao_continua_sendo_lido() -> None:
    registro = {
        "id": "antigo",
        "nome": "a.mp4",
        "tamanho_bytes": 1,
        "estado": "concluido",
        "criado_por": "u",
        "criado_em": INICIO,
        "atualizado_em": INICIO,
    }

    assert Job.model_validate(registro).data_exibicao is None


def test_data_de_exibicao_vai_ao_armazenamento_como_texto() -> None:
    # O Firestore não guarda `date`; o Job a entrega como texto ISO e a lê de volta.
    job = Job(
        id="j", nome="a.mp4", tamanho_bytes=1, estado="concluido", criado_por="u",
        data_exibicao=date(1999, 12, 31), criado_em=INICIO, atualizado_em=INICIO,
    )  # fmt: skip

    registro = job.model_dump()

    assert registro["data_exibicao"] == "1999-12-31"
    assert Job.model_validate(registro) == job


def _job_com_capa(ambiente: Ambiente, job_id: str, capa: str | None) -> None:
    ambiente.repositorio.salvar(
        Job(
            id=job_id,
            nome=f"{job_id}.mp4",
            tamanho_bytes=10,
            estado="concluido",
            criado_por="u1",
            capa=capa,
            criado_em=ambiente.relogio(),
            atualizado_em=ambiente.relogio(),
        )
    )


def test_listagem_traz_a_capa_assinada_por_8_h_e_job_sem_capa_traz_null() -> None:
    ambiente = Ambiente()
    _job_com_capa(ambiente, "com", "quadros/plano-1.jpg")
    _job_com_capa(ambiente, "sem", None)

    lista = ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()

    urls = {j["id"]: j["capa_url"] for j in lista}
    assert urls == {
        "com": "https://storage.exemplo/quadros/com/quadros/plano-1.jpg?validade=28800",
        "sem": None,
    }


def test_listagem_com_capa_falsa_nao_assina_e_traz_os_mesmos_jobs() -> None:
    ambiente = Ambiente()
    _job_com_capa(ambiente, "com", "quadros/plano-1.jpg")
    _job_com_capa(ambiente, "sem", None)

    com_capa = ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()
    resposta = ambiente.cliente.get("/v1/jobs?capa=false", headers=AUTORIZACAO)

    sem_capa = resposta.json()
    assert all("capa_url" not in j for j in sem_capa)
    assert [j["id"] for j in sem_capa] == [j["id"] for j in com_capa]
    assert [
        {k: v for k, v in j.items() if k != "capa_url"} for j in com_capa
    ] == sem_capa


def test_detalhe_traz_a_capa_assinada_e_job_sem_capa_traz_null() -> None:
    ambiente = Ambiente()
    _job_com_capa(ambiente, "com", "quadros/plano-1.jpg")
    _job_com_capa(ambiente, "sem", None)

    com = ambiente.cliente.get("/v1/jobs/com", headers=AUTORIZACAO).json()
    sem = ambiente.cliente.get("/v1/jobs/sem", headers=AUTORIZACAO).json()

    assert com["capa_url"] == (
        "https://storage.exemplo/quadros/com/quadros/plano-1.jpg?validade=28800"
    )
    assert sem["capa_url"] is None


def test_lista_e_detalhe_sem_decupagem_ver_dao_403_sem_assinar_a_capa() -> None:
    repositorio = RepositorioEmMemoria()
    armazenamento = ArmazenamentoFalso()
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("u1", [])
    cliente = TestClient(
        criar_app(VerificadorFalso(), repositorio, armazenamento, papeis=papeis)
    )
    repositorio.salvar(
        Job(
            id="com", nome="com.mp4", tamanho_bytes=10, estado="concluido",
            criado_por="u1", capa="quadros/plano-1.jpg",
            criado_em=INICIO, atualizado_em=INICIO,
        )
    )  # fmt: skip

    for caminho in ("/v1/jobs", "/v1/jobs/com"):
        resposta = cliente.get(caminho, headers=AUTORIZACAO)

        assert resposta.status_code == 403
        assert "capa_url" not in resposta.text


def test_etapa_tem_dispositivo_e_tentativas_na_gpu_so_quando_o_workflow_grava() -> None:
    from datetime import UTC, datetime

    from api.jobs import Etapa, EtapaPublica

    agora = datetime(2026, 11, 2, tzinfo=UTC)

    assert Etapa(inicio=agora).dispositivo is None
    assert Etapa(inicio=agora).tentativas_gpu is None
    etapa = EtapaPublica(
        nome="transcricao", inicio=agora, dispositivo="cpu", tentativas_gpu=6
    )
    assert etapa.dispositivo == "cpu" and etapa.tentativas_gpu == 6


def _criar_com_chave(ambiente: Ambiente, chave: str, **corpo: Any) -> Any:
    padrao = {
        "nome": "clipe.mp4",
        "tamanho_bytes": 1000,
        "tipo": "video/mp4",
        "data_exibicao": "2026-10-01",
    }
    return ambiente.cliente.post(
        "/v1/jobs",
        json={**padrao, **corpo},
        headers={**AUTORIZACAO, "Idempotency-Key": chave},
    )


def test_idempotency_key_repetida_devolve_200_com_o_mesmo_job_e_sem_novo_job() -> None:
    ambiente = Ambiente()

    primeira = _criar_com_chave(ambiente, "k1")
    repeticao = _criar_com_chave(ambiente, "k1")

    assert primeira.status_code == 202
    assert repeticao.status_code == 200
    assert repeticao.json()["id"] == primeira.json()["id"]
    assert len(ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json()) == 1


def test_idempotency_key_com_outro_corpo_recebe_409_e_chaves_diferentes_criam_jobs() -> (
    None
):
    ambiente = Ambiente()
    primeira = _criar_com_chave(ambiente, "k1")

    assert _criar_com_chave(ambiente, "k1", tamanho_bytes=2000).status_code == 409
    outra = _criar_com_chave(ambiente, "k2")

    assert outra.status_code == 202
    assert outra.json()["id"] != primeira.json()["id"]


def test_idempotency_key_repetida_de_job_na_lixeira_recebe_410() -> None:
    from api.catalogo import EnvioParaLixeira

    ambiente = Ambiente()
    primeira = _criar_com_chave(ambiente, "k1")
    job = ambiente.repositorio.obter(primeira.json()["id"])
    assert job is not None
    ambiente.repositorio.salvar(
        job.model_copy(
            update={
                "lixeira": EnvioParaLixeira(
                    em=datetime(2026, 11, 4, tzinfo=UTC),
                    por_uid="u1",
                    por_email="a@b.c",
                    motivo="teste",
                )
            }
        )
    )

    repeticao = _criar_com_chave(ambiente, "k1")

    assert repeticao.status_code == 410
    assert repeticao.json()["detail"] == "Este Job foi apagado"


def test_idempotency_key_repetida_de_job_purgado_recebe_410_e_nao_cria_job() -> None:
    ambiente = Ambiente()
    primeira = _criar_com_chave(ambiente, "k1")
    ambiente.repositorio.remover(primeira.json()["id"])

    repeticao = _criar_com_chave(ambiente, "k1")

    assert repeticao.status_code == 410
    assert ambiente.repositorio.obter(primeira.json()["id"]) is None
    assert ambiente.repositorio.listar() == []


def test_idempotency_key_invalida_recebe_422() -> None:
    ambiente = Ambiente()

    assert _criar_com_chave(ambiente, "x" * 256).status_code == 422
    assert _criar_com_chave(ambiente, "chave\tcom tab").status_code == 422
    assert ambiente.cliente.get("/v1/jobs", headers=AUTORIZACAO).json() == []


def test_repeticao_que_grava_o_job_que_faltou_usa_a_hora_de_agora() -> None:
    # O processo caiu entre reservar e gravar: a repetição, horas depois, grava o Job.
    # Com a hora da reserva, o prazo do upload já estaria quase vencido ao dar a URL.
    ambiente = Ambiente()
    primeira = _criar_com_chave(ambiente, "k1").json()
    del ambiente.repositorio._jobs[primeira["id"]]
    # Sem a marca de Job gravado: a queda foi antes de gravar.
    (id_,) = ambiente.idempotencia._reservas
    reserva = ambiente.idempotencia._reservas[id_]
    ambiente.idempotencia._reservas[id_] = reserva.model_copy(
        update={"job_gravado": False}
    )
    ambiente.relogio.agora = INICIO + timedelta(hours=30)

    repeticao = _criar_com_chave(ambiente, "k1")

    assert repeticao.status_code == 200
    assert repeticao.json()["id"] == primeira["id"]
    assert repeticao.json()["url_de_upload"] is not None
    guardado = ambiente.repositorio.obter(primeira["id"])
    assert guardado is not None and guardado.criado_em == INICIO + timedelta(hours=30)
