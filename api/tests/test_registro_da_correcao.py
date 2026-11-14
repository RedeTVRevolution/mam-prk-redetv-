"""O Registro da Correção (#614), pela interface do módulo e sem HTTP: a sequência gravar,
evento de uso, Catálogo do Job, em cada uma das cinco operações."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from api.catalogo import CatalogoEmMemoria
from api.correcoes import (
    Autoria,
    Correcao,
    CorrecaoInexistente,
    CorrecaoJaExiste,
    NaoDesfazivel,
    NaoNaFila,
    NaoPendente,
    NovaCorrecao,
    RepositorioDeCorrecoesEmMemoria,
    VersaoDesatualizada,
)
from api.eventos_de_uso import EventoDeUso, EventosEmMemoria
from api.jobs import Job, RepositorioEmMemoria
from api.marcas import CatalogoDeMarcasEmMemoria
from api.registro_da_correcao import RegistroDaCorrecao
from api.tests.test_correcoes import BYTES, MODELO, VERSAO, _novo, _pessoa
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
AUTORIA = Autoria("u1", "ana@redetv.com.br", BASE)
SEQUENCIA = ["gravou", "evento", "catalogo"]


class Mundo:
    """O Registro com os dublês em memória; `passos` anota a ordem do que foi feito."""

    def __init__(self) -> None:
        self.passos: list[str] = []
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(
            Job(
                id="j1",
                nome="a.mp4",
                tamanho_bytes=10,
                estado="concluido",
                criado_por="u1",
                criado_em=BASE,
                atualizado_em=BASE,
                programa="Jornal",
            )
        )
        self.armazenamento = ArmazenamentoFalso()
        self.armazenamento.decupagens["j1"] = [BYTES]
        self.correcoes = RepositorioDeCorrecoesEmMemoria()
        self.catalogo = CatalogoEmMemoria()
        self.eventos = EventosEmMemoria()
        self.ana = self.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
        self._anotar("gravou", self.correcoes, "acrescentar")
        self._anotar("evento", self.eventos, "publicar")
        self._anotar("catalogo", self.jobs, "trocar")
        self.registro = RegistroDaCorrecao(
            self.armazenamento,
            self.correcoes,
            self.catalogo,
            CatalogoDeMarcasEmMemoria(),
            self.jobs,
            self.eventos,
        )

    def _anotar(self, passo: str, objeto: Any, metodo: str) -> None:
        original = getattr(objeto, metodo)

        def anotando(*args: Any, **kwargs: Any) -> Any:
            self.passos.append(passo)
            return original(*args, **kwargs)

        setattr(objeto, metodo, anotando)

    @property
    def job(self) -> Job:
        job = self.jobs.obter("j1")
        assert job
        return job

    def comecar_de_novo(self) -> None:
        self.passos.clear()
        self.eventos.publicados.clear()

    def corrigir(self, exige_aprovacao: bool = False) -> Correcao:
        """Uma Correção gravada; o que veio antes dela não conta nos passos."""
        correcao, _ = self.registro.corrigir(
            self.job,
            NovaCorrecao(**_novo()),
            AUTORIA,
            exige_aprovacao=exige_aprovacao,
        )
        self.comecar_de_novo()
        return correcao

    def com_fila(self) -> Correcao:
        """Uma Correção que não casou depois do reprocessamento: está na fila."""
        correcao = self.corrigir()
        modelo = {**MODELO, "pessoas": [_pessoa("p1", "Carla Dias", 1000, 5000)]}
        self.armazenamento.decupagens["j1"] = [json.dumps(modelo).encode()]
        return correcao

    def disputar_o_id(self) -> None:
        """Outro pedido grava o mesmo registro entre a regra e a gravação."""

        def ja_existe(correcao: Correcao) -> None:
            raise CorrecaoJaExiste(correcao.id)

        self.correcoes.acrescentar = ja_existe  # type: ignore[method-assign]


def _evento(mundo: Mundo) -> EventoDeUso:
    (evento,) = mundo.eventos.publicados
    return evento


def test_corrigir_grava_registra_o_evento_e_atualiza_o_catalogo_do_job_nessa_ordem() -> (
    None
):
    mundo = Mundo()

    correcao, versao = mundo.registro.corrigir(
        mundo.job, NovaCorrecao(**_novo()), AUTORIA, exige_aprovacao=False
    )

    assert mundo.passos == SEQUENCIA
    assert versao == VERSAO
    assert mundo.correcoes.listar("j1") == [correcao]
    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]
    evento = _evento(mundo)
    assert (evento.tipo, evento.tipo_de_correcao) == ("correcao", "pessoa.renomear")
    assert (evento.quem_tipo, evento.quem_id) == ("usuario", "u1")
    assert (evento.job_id, evento.programa, evento.quando) == ("j1", "Jornal", BASE)


def test_corrigir_com_versao_desatualizada_nao_grava_nada() -> None:
    mundo = Mundo()

    with pytest.raises(VersaoDesatualizada):
        mundo.registro.corrigir(
            mundo.job,
            NovaCorrecao(**_novo(versao="outra")),
            AUTORIA,
            exige_aprovacao=False,
        )

    assert mundo.passos == []
    assert mundo.eventos.publicados == []


def test_corrigir_guarda_que_a_correcao_espera_aprovacao() -> None:
    assert Mundo().corrigir(exige_aprovacao=True).exige_aprovacao is True


def test_desfazer_grava_registra_o_evento_e_atualiza_o_catalogo_do_job() -> None:
    mundo = Mundo()
    alvo = mundo.corrigir()

    desfeita = mundo.registro.desfazer(mundo.job, alvo.id, "enganei-me", AUTORIA)

    assert mundo.passos == SEQUENCIA
    assert (desfeita.tipo, desfeita.desfaz) == ("desfazer", alvo.id)
    assert _evento(mundo).tipo_de_correcao == "desfazer"
    assert mundo.job.pessoas_do_catalogo == []


def test_reaplicar_grava_registra_o_evento_e_atualiza_o_catalogo_do_job() -> None:
    mundo = Mundo()
    alvo = mundo.com_fila()

    nova = mundo.registro.reaplicar(mundo.job, alvo.id, "p1", "revisei", AUTORIA)

    assert mundo.passos == SEQUENCIA
    assert (nova.reaplica, nova.item_id) == (alvo.id, "p1")
    assert _evento(mundo).tipo_de_correcao == "pessoa.renomear"


def test_descartar_grava_registra_o_evento_e_atualiza_o_catalogo_do_job() -> None:
    mundo = Mundo()
    alvo = mundo.com_fila()

    descarte = mundo.registro.descartar(mundo.job, alvo.id, "não vale", AUTORIA)

    assert mundo.passos == SEQUENCIA
    assert (descarte.tipo, descarte.descarta) == ("descartar", alvo.id)
    assert _evento(mundo).tipo_de_correcao == "descartar"


@pytest.mark.parametrize(("aprovada", "tipo"), [(True, "aprovar"), (False, "recusar")])
def test_decidir_grava_registra_o_evento_e_atualiza_o_catalogo_do_job(
    aprovada: bool, tipo: str
) -> None:
    mundo = Mundo()
    alvo = mundo.corrigir(exige_aprovacao=True)

    decisao = mundo.registro.decidir(mundo.job, alvo.id, aprovada, "ok", AUTORIA)

    assert mundo.passos == SEQUENCIA
    assert decisao.tipo == tipo
    assert _evento(mundo).tipo_de_correcao == tipo
    assert mundo.job.pessoas_do_catalogo == ([mundo.ana.id] if aprovada else [])


def test_decidir_nao_le_a_decupagem_antes_de_gravar() -> None:
    mundo = Mundo()
    alvo = mundo.corrigir(exige_aprovacao=True)
    lida_depois_de: list[str] = []
    abrir = mundo.armazenamento.abrir_decupagem

    def anotando(job_id: str) -> Any:
        lida_depois_de.append(mundo.passos[-1] if mundo.passos else "nada")
        return abrir(job_id)

    mundo.armazenamento.abrir_decupagem = anotando  # type: ignore[method-assign]

    mundo.registro.decidir(mundo.job, alvo.id, True, "", AUTORIA)

    # A única leitura é a do Catálogo do Job, depois da gravação e do evento.
    assert lida_depois_de == ["evento"]


def test_o_evento_usa_a_data_da_autoria() -> None:
    mundo = Mundo()
    depois = BASE + timedelta(hours=3)

    mundo.registro.corrigir(
        mundo.job,
        NovaCorrecao(**_novo()),
        Autoria("u1", "ana@redetv.com.br", depois),
        exige_aprovacao=False,
    )

    assert _evento(mundo).quando == depois


def test_a_falha_do_evento_nao_desfaz_a_gravacao_e_o_catalogo_segue() -> None:
    mundo = Mundo()

    def falha(evento: EventoDeUso) -> None:
        raise RuntimeError("Pub/Sub fora do ar")

    mundo.eventos.publicar = falha  # type: ignore[method-assign]

    correcao, _ = mundo.registro.corrigir(
        mundo.job, NovaCorrecao(**_novo()), AUTORIA, exige_aprovacao=False
    )

    assert mundo.correcoes.listar("j1") == [correcao]
    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_a_falha_do_catalogo_do_job_nao_desfaz_a_gravacao() -> None:
    mundo = Mundo()

    def falha(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Firestore fora do ar")

    mundo.jobs.trocar = falha  # type: ignore[method-assign]

    correcao, _ = mundo.registro.corrigir(
        mundo.job, NovaCorrecao(**_novo()), AUTORIA, exige_aprovacao=False
    )

    assert mundo.correcoes.listar("j1") == [correcao]
    assert len(mundo.eventos.publicados) == 1


def test_a_falha_ao_ler_a_decupagem_para_o_catalogo_nao_desfaz_a_gravacao() -> None:
    mundo = Mundo()
    abrir = mundo.armazenamento.abrir_decupagem
    leituras: list[str] = []

    def so_a_primeira_abre(job_id: str) -> Any:
        leituras.append(job_id)
        if len(leituras) > 1:
            raise OSError("Storage fora do ar")
        return abrir(job_id)

    mundo.armazenamento.abrir_decupagem = so_a_primeira_abre  # type: ignore[method-assign]

    correcao, _ = mundo.registro.corrigir(
        mundo.job, NovaCorrecao(**_novo()), AUTORIA, exige_aprovacao=False
    )

    assert len(leituras) == 2
    assert mundo.correcoes.listar("j1") == [correcao]
    assert len(mundo.eventos.publicados) == 1


def test_desfazer_que_ja_existe_vira_nao_desfazivel() -> None:
    mundo = Mundo()
    alvo = mundo.corrigir()
    mundo.disputar_o_id()

    with pytest.raises(NaoDesfazivel):
        mundo.registro.desfazer(mundo.job, alvo.id, "x", AUTORIA)

    assert mundo.eventos.publicados == []


@pytest.mark.parametrize("operacao", ["reaplicar", "descartar"])
def test_reaplicar_e_descartar_que_ja_existem_viram_nao_esta_na_fila(
    operacao: str,
) -> None:
    mundo = Mundo()
    alvo = mundo.com_fila()
    mundo.disputar_o_id()

    with pytest.raises(NaoNaFila):
        if operacao == "reaplicar":
            mundo.registro.reaplicar(mundo.job, alvo.id, "p1", "x", AUTORIA)
        else:
            mundo.registro.descartar(mundo.job, alvo.id, "x", AUTORIA)

    assert mundo.eventos.publicados == []


def test_decidir_que_ja_existe_vira_nao_esta_pendente() -> None:
    mundo = Mundo()
    alvo = mundo.corrigir(exige_aprovacao=True)
    mundo.disputar_o_id()

    with pytest.raises(NaoPendente):
        mundo.registro.decidir(mundo.job, alvo.id, True, "", AUTORIA)

    assert mundo.eventos.publicados == []


def test_correcao_inexistente_sobe_sem_gravar() -> None:
    mundo = Mundo()

    with pytest.raises(CorrecaoInexistente):
        mundo.registro.decidir(mundo.job, "zzz", True, "", AUTORIA)

    assert mundo.passos == []
