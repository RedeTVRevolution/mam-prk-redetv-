from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.correcoes import RepositorioDeCorrecoesEmMemoria
from api.indice_da_busca import IndiceEmMemoria
from api.jobs import EnvioParaLixeira, Job, RepositorioEmMemoria
from api.lixeira import ArquivosContados, ArquivosEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.purga import Purga, purgar_vencidas
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_lixeira import BASE, _correcao, _job

ADMIN = {"Authorization": "Bearer admin"}
EDITOR = {"Authorization": "Bearer editor"}
ROTA = "/v1/admin/lixeira/videos/j1/purgar"
AGORA = BASE + timedelta(days=40)


def _na_lixeira(id: str = "j1", em: datetime = BASE, **extra: Any) -> Job:
    return _job(
        id,
        lixeira=EnvioParaLixeira(
            em=em, por_uid="adm", por_email="ana@redetv.com", motivo="duplicado"
        ),
        **extra,
    )


class Mundo:
    def __init__(self, *jobs: Job, login_em: datetime | None = AGORA) -> None:
        self.jobs = RepositorioEmMemoria()
        for job in jobs or (_na_lixeira(),):
            self.jobs.salvar(job)
        self.agora = AGORA
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.correcoes = RepositorioDeCorrecoesEmMemoria()
        self.arquivos = ArquivosEmMemoria()
        self.indice = IndiceEmMemoria()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        papeis.salvar("ed", ["editor"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(
                            uid="adm", email="ana@redetv.com", login_em=login_em
                        ),
                        "editor": Usuario(
                            uid="ed", email="ed@redetv.com", login_em=login_em
                        ),
                    }
                ),
                self.jobs,
                ArmazenamentoFalso(),
                papeis=papeis,
                correcoes=self.correcoes,
                auditoria=self.auditoria,
                arquivos=self.arquivos,
                indice=self.indice,
                relogio=lambda: self.agora,
            )
        )
        for id in ("j1", "j2"):
            self.arquivos.por_job[id] = ArquivosContados(
                decupagem=1, copia_limpa=1, proxy=1, quadros=3
            )
        self.correcoes.acrescentar(_correcao("c1"))
        self.correcoes.acrescentar(_correcao("c2"))
        self.correcoes.acrescentar(_correcao("c3", job_id="j2"))

    def purgar(self, nome: str = "tv-fama.mp4", headers: Any = ADMIN) -> Any:
        return self.cliente.post(ROTA, json={"nome": nome}, headers=headers)

    def registros(self) -> list[Any]:
        return self.auditoria.consultar(FiltroDeAuditoria()).registros

    def purga(self) -> Purga:
        return Purga(
            self.jobs,
            self.correcoes,
            self.arquivos,
            self.indice,
            self.auditoria,
            lambda: self.agora,
        )


def test_depois_da_purga_nao_sobra_arquivo_correcao_nem_job_mas_a_auditoria_fica() -> (
    None
):
    mundo = Mundo()

    resposta = mundo.purgar()

    assert resposta.status_code == 200, resposta.text
    assert mundo.jobs.obter("j1") is None
    assert mundo.arquivos.contar("j1") == ArquivosContados()
    assert mundo.correcoes.listar("j1") == []
    # O que é de outro vídeo fica.
    assert mundo.arquivos.contar("j2").quadros == 3
    assert len(mundo.correcoes.listar("j2")) == 1
    [registro] = mundo.registros()
    assert (registro.acao, registro.alvo_id, registro.alvo_nome) == (
        "item.purgado",
        "j1",
        "tv-fama.mp4",
    )
    assert registro.email == "ana@redetv.com"
    assert registro.motivo == "duplicado"
    assert registro.detalhes["correcoes"] == 2
    assert registro.detalhes["decupagem"] == 1
    assert registro.detalhes["arquivos"] == {"copia_limpa": 1, "proxy": 1, "quadros": 3}
    assert registro.detalhes["conteudo_compartilhado"] is False


def test_a_purga_tira_os_momentos_do_indice() -> None:
    mundo = Mundo()
    apagados: list[str] = []
    mundo.indice.apagar = apagados.append  # type: ignore[method-assign, assignment]

    mundo.purgar()

    assert apagados == ["j1"]


def test_com_outro_job_na_mesma_chave_de_conteudo_so_o_job_e_removido() -> None:
    mundo = Mundo(_na_lixeira(), _job("j2"))
    apagados: list[str] = []
    mundo.indice.apagar = apagados.append  # type: ignore[method-assign, assignment]

    resposta = mundo.purgar()

    assert resposta.status_code == 200
    assert mundo.jobs.obter("j1") is None
    assert mundo.jobs.obter("j2") is not None
    assert mundo.arquivos.contar("j1") == ArquivosContados(
        decupagem=1, copia_limpa=1, proxy=1, quadros=3
    )
    assert apagados == []
    assert mundo.registros()[0].detalhes["conteudo_compartilhado"] is True


def test_nome_errado_da_422_e_nada_e_apagado() -> None:
    mundo = Mundo()

    assert mundo.purgar("outro.mp4").status_code == 422
    assert mundo.purgar("").status_code == 422
    assert mundo.jobs.obter("j1") is not None
    assert mundo.registros() == []


def test_login_antigo_ou_sem_horario_da_403_login_recente_exigido() -> None:
    antigo = Mundo(login_em=AGORA - timedelta(minutes=6))
    sem_horario = Mundo(login_em=None)
    recente = Mundo(login_em=AGORA - timedelta(minutes=4))

    for mundo in (antigo, sem_horario):
        resposta = mundo.purgar()
        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "login_recente_exigido"
        assert mundo.jobs.obter("j1") is not None
    assert recente.purgar().status_code == 200


def test_so_o_administrador_purga_e_so_o_que_esta_na_lixeira() -> None:
    mundo = Mundo(_na_lixeira(), _job("j3"))

    assert mundo.purgar(headers=EDITOR).status_code == 403
    assert mundo.jobs.obter("j1") is not None
    fora = mundo.cliente.post(
        "/v1/admin/lixeira/videos/j3/purgar",
        json={"nome": "tv-fama.mp4"},
        headers=ADMIN,
    )
    assert fora.status_code == 409
    inexistente = mundo.cliente.post(
        "/v1/admin/lixeira/videos/x/purgar", json={"nome": "a"}, headers=ADMIN
    )
    assert inexistente.status_code == 404


def test_auditoria_que_falha_nao_apaga_nada() -> None:
    mundo = Mundo()

    def falhar(_registro: Any) -> None:
        raise ConnectionError("fora do ar")

    mundo.auditoria.acrescentar = falhar  # type: ignore[method-assign, assignment]
    cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)

    resposta = cliente.post(ROTA, json={"nome": "tv-fama.mp4"}, headers=ADMIN)

    assert resposta.status_code == 500
    assert mundo.jobs.obter("j1") is not None
    assert len(mundo.correcoes.listar("j1")) == 2


def test_purga_automatica_pega_o_item_com_30_dias_e_deixa_o_de_29() -> None:
    mundo = Mundo(
        _na_lixeira("j1", em=AGORA - timedelta(days=30)),
        _na_lixeira("j2", em=AGORA - timedelta(days=29, hours=23)),
        _job("j3"),
    )

    purgados = purgar_vencidas(mundo.jobs, mundo.purga(), AGORA)

    assert purgados == ["j1"]
    assert mundo.jobs.obter("j1") is None
    assert mundo.jobs.obter("j2") is not None
    assert mundo.jobs.obter("j3") is not None
    [registro] = mundo.registros()
    assert registro.sistema == "Purga automática"
    assert registro.uid is None
    assert registro.alvo_id == "j1"


def test_a_purga_automatica_segue_quando_uma_falha() -> None:
    mundo = Mundo(
        _na_lixeira("j1", em=AGORA - timedelta(days=31)),
        _na_lixeira("j2", em=AGORA - timedelta(days=31)),
    )
    original = mundo.arquivos.apagar

    def apagar(job_id: str) -> None:
        if job_id == "j1":
            raise ConnectionError("Storage fora do ar")
        original(job_id)

    mundo.arquivos.apagar = apagar  # type: ignore[method-assign]

    purgados = purgar_vencidas(mundo.jobs, mundo.purga(), AGORA)

    assert purgados == ["j2"]
    assert mundo.jobs.obter("j1") is not None
