import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.correcoes import (
    Ancora,
    Correcao,
    RepositorioDeCorrecoesEmMemoria,
)
from api.jobs import Job, RepositorioEmMemoria
from api.lixeira import ArquivosContados, ArquivosEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.relatorios import poe_o_nome_dos_videos
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
ADMIN = {"Authorization": "Bearer admin"}
EDITOR = {"Authorization": "Bearer editor"}
LIXEIRA = "/v1/admin/lixeira"
ROTA_DO_VIDEO = f"{LIXEIRA}/videos/j1"


def _job(id: str = "j1", estado: str = "concluido", **extra: Any) -> Job:
    campos: dict[str, Any] = {
        "id": id,
        "nome": "tv-fama.mp4",
        "tamanho_bytes": 10,
        "sha256": "a" * 64,
        "estado": estado,
        "criado_por": "sistema:Playout",
        "sistema": "Playout",
        "criado_em": BASE,
        "atualizado_em": BASE,
    }
    campos.update(extra)
    return Job(**campos)


def _correcao(id: str, job_id: str = "j1") -> Correcao:
    return Correcao(
        id=id,
        job_id=job_id,
        autor_uid="ed",
        autor_email="ed@redetv.com",
        criada_em=BASE,
        motivo="erro de grafia",
        tipo="pessoa.renomear",
        antes="Ana",
        depois="Anna",
        ancora=Ancora(
            versao="v", tipo_do_item="pessoa", identidade="p1", inicio_ms=0, fim_ms=1
        ),
    )


class Mundo:
    def __init__(self, *jobs: Job) -> None:
        self.jobs = RepositorioEmMemoria()
        for job in jobs or (_job(),):
            self.jobs.salvar(job)
        self.agora = BASE
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.correcoes = RepositorioDeCorrecoesEmMemoria()
        self.arquivos = ArquivosEmMemoria()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        papeis.salvar("ed", ["editor"])
        chaves = RepositorioDeChavesEmMemoria()
        self.chave = {
            "X-API-Key": emitir_chave(
                "Playout", frozenset({"criar", "ler", "cancelar"}), MAC, chaves, BASE
            ).chave
        }
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(uid="adm", email="Ana@redetv.com"),
                        "editor": Usuario(uid="ed", email="ed@redetv.com"),
                    }
                ),
                self.jobs,
                ArmazenamentoFalso(),
                chaves=VerificadorDeChaveDeApi(chaves, MAC),
                papeis=papeis,
                correcoes=self.correcoes,
                auditoria=self.auditoria,
                arquivos=self.arquivos,
                relogio=lambda: self.agora,
            )
        )

    def enviar(self, id: str = "j1", motivo: str | None = "duplicado") -> Any:
        corpo = {} if motivo is None else {"motivo": motivo}
        return self.cliente.post(f"{LIXEIRA}/videos/{id}", json=corpo, headers=ADMIN)

    def registros(self) -> list[Any]:
        return self.auditoria.consultar(FiltroDeAuditoria()).registros


def test_video_na_lixeira_some_para_editor_e_sistema_mas_o_administrador_le() -> None:
    mundo = Mundo()
    assert mundo.enviar().status_code == 201

    assert mundo.cliente.get("/v1/jobs", headers=EDITOR).json() == []
    assert mundo.cliente.get("/v1/jobs", headers=mundo.chave).json() == []
    for rota in ("", "/decupagem", "/reproducao", "/correcoes", "/fila", "/sugestoes"):
        for quem in (EDITOR, mundo.chave):
            assert (
                mundo.cliente.get(f"/v1/jobs/j1{rota}", headers=quem).status_code == 404
            ), rota
    assert mundo.cliente.get("/v1/jobs/j1", headers=ADMIN).status_code == 200


def test_restaurado_tudo_volta() -> None:
    mundo = Mundo()
    mundo.enviar()

    resposta = mundo.cliente.post(f"{ROTA_DO_VIDEO}/restaurar", headers=ADMIN)

    assert resposta.status_code == 200
    assert [j["id"] for j in mundo.cliente.get("/v1/jobs", headers=EDITOR).json()] == [
        "j1"
    ]
    assert mundo.cliente.get("/v1/jobs/j1", headers=mundo.chave).status_code == 200
    assert mundo.cliente.get(LIXEIRA, headers=ADMIN).json() == []


def test_o_job_guarda_quando_quem_e_por_que_e_a_lista_mostra_os_dias_ate_a_purga() -> (
    None
):
    mundo = Mundo()
    mundo.enviar(motivo="  duplicado ")
    mundo.agora = BASE + timedelta(days=4, hours=1)

    [item] = mundo.cliente.get(LIXEIRA, headers=ADMIN).json()

    assert item == {
        "tipo": "video",
        "id": "j1",
        "nome": "tv-fama.mp4",
        "enviado_por": "ana@redetv.com",
        "enviado_em": "2026-11-02T12:00:00Z",
        "motivo": "duplicado",
        "dias_ate_a_purga": 26,
    }


def test_impacto_conta_decupagem_correcoes_arquivos_e_outros_jobs_com_o_mesmo_conteudo() -> (
    None
):
    mundo = Mundo(
        _job(),
        _job(
            "j2",
            nome="copia.mp4",
            sistema=None,
            criado_por="ed",
            criado_por_email="ed@redetv.com",
        ),
        _job("j3", sha256="b" * 64),
    )
    mundo.arquivos.por_job["j1"] = ArquivosContados(
        decupagem=1, copia_limpa=1, proxy=1, quadros=12
    )
    mundo.correcoes.acrescentar(_correcao("c1"))
    mundo.correcoes.acrescentar(_correcao("c2"))
    mundo.correcoes.acrescentar(_correcao("c3", job_id="j3"))

    resposta = mundo.cliente.get(f"{ROTA_DO_VIDEO}/impacto", headers=ADMIN)

    assert resposta.status_code == 200
    assert resposta.json() == {
        "decupagem": 1,
        "correcoes": 2,
        "arquivos": {"copia_limpa": 1, "proxy": 1, "quadros": 12},
        "outros_jobs": [
            {"id": "j2", "nome": "copia.mp4", "enviado_por": "ed@redetv.com"}
        ],
    }


def test_sem_motivo_422_job_andando_409_sem_permissao_403_e_job_inexistente_404() -> (
    None
):
    mundo = Mundo(_job(), _job("j2", estado="analisando"))

    assert mundo.enviar(motivo=None).status_code == 422
    assert mundo.enviar(motivo="   ").status_code == 422
    assert mundo.enviar("j2").status_code == 409
    assert mundo.enviar("nada").status_code == 404
    for quem in (EDITOR, mundo.chave):
        respostas = [
            mundo.cliente.get(LIXEIRA, headers=quem),
            mundo.cliente.get(f"{ROTA_DO_VIDEO}/impacto", headers=quem),
            mundo.cliente.post(ROTA_DO_VIDEO, json={"motivo": "x"}, headers=quem),
            mundo.cliente.post(f"{ROTA_DO_VIDEO}/restaurar", headers=quem),
        ]
        assert [r.status_code for r in respostas] == [403] * 4
    assert mundo.jobs.obter("j1").lixeira is None  # type: ignore[union-attr]


def test_so_manda_para_a_lixeira_job_concluido_falhou_ou_cancelado() -> None:
    estados = ["concluido", "falhou", "cancelado"]
    mundo = Mundo(*(_job(f"j-{e}", estado=e) for e in estados))
    for e in estados:
        assert mundo.enviar(f"j-{e}").status_code == 201


def test_enviar_de_novo_ou_restaurar_o_que_nao_esta_na_lixeira_da_409() -> None:
    mundo = Mundo()

    assert (
        mundo.cliente.post(f"{ROTA_DO_VIDEO}/restaurar", headers=ADMIN).status_code
        == 409
    )
    mundo.enviar()
    assert mundo.enviar().status_code == 409


def test_envio_e_restauracao_vao_para_a_auditoria_com_motivo_e_impacto() -> None:
    mundo = Mundo()
    mundo.arquivos.por_job["j1"] = ArquivosContados(quadros=3)
    mundo.enviar(motivo="duplicado")
    mundo.cliente.post(f"{ROTA_DO_VIDEO}/restaurar", headers=ADMIN)

    por_acao = {
        r.acao: r for r in mundo.registros()
    }  # o relógio fixo empata o `quando`
    assert set(por_acao) == {"item.para_lixeira", "item.restaurado"}
    enviado, restaurado = por_acao["item.para_lixeira"], por_acao["item.restaurado"]
    for registro in (enviado, restaurado):
        assert (registro.alvo_tipo, registro.alvo_id, registro.alvo_nome) == (
            "video",
            "j1",
            "tv-fama.mp4",
        )
        assert registro.email == "ana@redetv.com"
    assert enviado.motivo == "duplicado"
    assert enviado.detalhes["arquivos"]["quadros"] == 3
    assert "correcoes" in enviado.detalhes


def test_auditoria_que_falha_desfaz_o_envio_e_a_restauracao() -> None:
    mundo = Mundo()

    def falhar(_registro: Any) -> None:
        raise RuntimeError("auditoria fora do ar")

    original = mundo.auditoria.acrescentar
    mundo.auditoria.acrescentar = falhar  # type: ignore[assignment]
    cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)
    assert (
        cliente.post(ROTA_DO_VIDEO, json={"motivo": "x"}, headers=ADMIN).status_code
        == 500
    )
    assert mundo.jobs.obter("j1").lixeira is None  # type: ignore[union-attr]

    mundo.auditoria.acrescentar = original  # type: ignore[method-assign]
    mundo.enviar()
    mundo.auditoria.acrescentar = falhar  # type: ignore[assignment]
    resposta = cliente.post(f"{ROTA_DO_VIDEO}/restaurar", headers=ADMIN)
    assert resposta.status_code == 500
    assert mundo.jobs.obter("j1").lixeira is not None  # type: ignore[union-attr]


def test_toda_rota_de_job_em_v1_chama_o_parametro_de_job_id() -> None:
    # A trava `sem_job_na_lixeira` só enxerga `{job_id}`: um Job com outro nome escaparia.
    fora_do_job = {"uid", "chave_id", "id_do_video"}
    app = Mundo().cliente.app
    assert isinstance(app, FastAPI)
    for caminho in app.openapi()["paths"]:
        parametros = set(re.findall(r"{(\w+)}", caminho))
        if parametros and "job_id" not in parametros:
            assert parametros <= fora_do_job, caminho


def test_relatorio_nao_mostra_o_nome_do_video_na_lixeira() -> None:
    mundo = Mundo(_job(), _job("j2", nome="outro.mp4"))
    mundo.enviar()
    itens = [
        SimpleNamespace(job_id="j1", nome=None),
        SimpleNamespace(job_id="j2", nome=None),
    ]

    poe_o_nome_dos_videos(itens, mundo.jobs)

    assert [i.nome for i in itens] == [None, "outro.mp4"]
