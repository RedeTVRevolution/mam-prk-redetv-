"""#720: gravar, decidir ou desfazer uma Correção só relê a Decupagem do Storage quando a
Correção pode mudar o conjunto de `catalogo_id`. As leituras são contadas num dublê."""

import json
from datetime import timedelta
from typing import Any

from api.correcoes import TIPOS, Autoria, NovaCorrecao, versao_do_modelo
from api.registro_da_correcao import pode_mudar_os_ids
from api.tests.test_correcoes import MODELO, _pessoa
from api.tests.test_registro_da_correcao import AUTORIA, BASE, Mundo

PESSOAS = [
    {**_pessoa("p1", "Ana Souza", 1000, 5000), "citada_na_fala": []},
    {**_pessoa("p2", "Beto Lima", 7000, 9000), "citada_na_fala": []},
]
BYTES = json.dumps({**MODELO, "pessoas": PESSOAS}).encode()
VERSAO = versao_do_modelo(BYTES)


class MundoContado(Mundo):
    def __init__(self) -> None:
        super().__init__()
        self.armazenamento.decupagens["j1"] = [BYTES]
        self.beto = self.catalogo.acrescentar("Beto Lima Neto", "repórter", [])
        self.leituras = 0
        self._minutos = 0
        abrir = self.armazenamento.abrir_decupagem

        def contando(job_id: str) -> Any:
            self.leituras += 1
            return abrir(job_id)

        self.armazenamento.abrir_decupagem = contando  # type: ignore[method-assign]

    @property
    def autoria(self) -> Autoria:
        """Cada registro um minuto depois do outro: a ordem das Correções vem da data."""
        self._minutos += 1
        return Autoria(
            AUTORIA.uid, AUTORIA.email, BASE + timedelta(minutes=self._minutos)
        )

    def novo(self, tipo: Any, item_id: str, valor: str, **campos: Any) -> NovaCorrecao:
        return NovaCorrecao(
            tipo=tipo, item_id=item_id, valor=valor, motivo="m", versao=VERSAO, **campos
        )

    def registrar(self, novo: NovaCorrecao, aprovacao: bool = False) -> Any:
        correcao, _ = self.registro.corrigir(
            self.job, novo, self.autoria, exige_aprovacao=aprovacao
        )
        return correcao

    def renomear_ana(self) -> Any:
        return self.registrar(self.novo("pessoa.renomear", "p1", "Ana Souza Lima"))

    def tempos_e_nao_e(self) -> Any:
        """A aparição da Ana vai para 10–14 s e o `nao_e` a casa ali e esvazia a pessoa."""
        ocorrencia = {"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000}
        tempos = self.registrar(
            self.novo(
                "item.tempos",
                "p1",
                "10000-14000",
                tipo_do_item="pessoa",
                ocorrencia=ocorrencia,
            )
        )
        nao_e = self.registrar(
            self.novo(
                "pessoa.nao_e",
                "p1",
                "Não identificado",
                ocorrencia={**ocorrencia, "inicio_ms": 10000, "fim_ms": 14000},
            )
        )
        return tempos, nao_e


def test_desfazer_um_tipo_neutro_devolve_o_id_que_o_nao_e_tirou() -> None:
    mundo = MundoContado()
    mundo.renomear_ana()
    tempos, _ = mundo.tempos_e_nao_e()
    assert mundo.job.pessoas_do_catalogo == []

    mundo.registro.desfazer(mundo.job, tempos.id, "enganei-me", mundo.autoria)

    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_nao_e_que_esvazia_seguido_de_aparicao_do_mesmo_nome_mantem_a_pessoa() -> None:
    mundo = MundoContado()
    mundo.renomear_ana()
    ocorrencia = {"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000}
    mundo.registrar(
        mundo.novo("pessoa.nao_e", "p1", "Não identificado", ocorrencia=ocorrencia)
    )
    assert mundo.job.pessoas_do_catalogo == []

    mundo.registrar(
        mundo.novo(
            "pessoa.acrescentar_aparicao",
            "p1",
            json.dumps({"inicio_ms": 20000, "fim_ms": 22000, "evidencia": "rosto"}),
        )
    )

    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_corrigir_le_a_decupagem_uma_vez_com_ou_sem_mudar_o_conjunto() -> None:
    mundo = MundoContado()

    mundo.registrar(mundo.novo("pauta.titulo", "pau01", "Outro título"))
    assert mundo.leituras == 1

    mundo.renomear_ana()
    assert mundo.leituras == 2
    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_decidir_de_tipo_neutro_nao_le_a_decupagem() -> None:
    mundo = MundoContado()
    alvo = mundo.registrar(mundo.novo("pauta.titulo", "pau01", "Outro"), True)
    mundo.leituras = 0

    mundo.registro.decidir(mundo.job, alvo.id, True, "", mundo.autoria)

    assert mundo.leituras == 0


def test_decidir_de_tipo_que_pode_mudar_le_uma_vez_depois_de_gravar() -> None:
    mundo = MundoContado()
    alvo = mundo.registrar(mundo.novo("pessoa.renomear", "p1", "Ana Souza Lima"), True)
    mundo.leituras = 0

    mundo.registro.decidir(mundo.job, alvo.id, True, "", mundo.autoria)

    assert mundo.leituras == 1
    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_desfazer_de_tipo_neutro_le_uma_vez_e_o_que_muda_o_conjunto_atualiza() -> None:
    mundo = MundoContado()
    titulo = mundo.registrar(mundo.novo("pauta.titulo", "pau01", "Outro"))
    renomeada = mundo.renomear_ana()
    mundo.leituras = 0

    mundo.registro.desfazer(mundo.job, titulo.id, "x", mundo.autoria)
    assert mundo.leituras == 1
    mundo.registro.desfazer(mundo.job, renomeada.id, "x", mundo.autoria)

    assert mundo.job.pessoas_do_catalogo == []


def test_dois_registros_que_mudam_o_conjunto_e_o_segundo_entra_antes_do_recalculo() -> (
    None
):
    mundo = MundoContado()
    publicar = mundo.eventos.publicar
    entrou: list[Any] = []

    def segundo_no_meio(evento: Any) -> None:
        publicar(evento)
        if not entrou:  # outro pedido grava entre a gravação e o recálculo do primeiro
            entrou.append(
                mundo.registrar(mundo.novo("pessoa.renomear", "p2", "Beto Lima Neto"))
            )

    mundo.eventos.publicar = segundo_no_meio  # type: ignore[method-assign]

    mundo.renomear_ana()

    assert sorted(mundo.job.pessoas_do_catalogo) == sorted(
        [mundo.ana.id, mundo.beto.id]
    )


def test_pode_mudar_os_ids_declara_todo_tipo_que_mexe_em_pessoa_ou_comercial() -> None:
    for tipo, entrada in TIPOS.items():
        if pode_mudar_os_ids(tipo):
            continue
        assert entrada.aplicar_na_pessoa is None, tipo
        assert entrada.catalogo_de is None, tipo
        assert not entrada.pode_esvaziar, tipo
        assert entrada.tipo_do_item not in (None, "pessoa", "comercial"), tipo
    # Os de hoje que podem, direta ou indiretamente (o `item.tempos` leva a aparição
    # para onde um `nao_e` deixa de casar).
    for tipo in (
        "pessoa.renomear",
        "comercial.marca",
        "pessoa.nao_e",
        "pessoa.acrescentar_aparicao",
        "item.tempos",
    ):
        assert pode_mudar_os_ids(tipo), tipo
    assert not pode_mudar_os_ids("pauta.titulo")
    assert pode_mudar_os_ids("tipo.que.nao.existe")


def test_pedido_concorrente_de_tipo_que_pode_mudar_recalcula_mesmo_sem_mudar_na_comparacao() -> (
    None
):
    mundo = MundoContado()
    mundo.renomear_ana()
    acrescentar = mundo.correcoes.acrescentar
    entrou: list[Any] = []

    def com_o_nao_e_no_meio(correcao: Any) -> None:
        if not entrou:
            entrou.append(True)  # o `nao_e` do outro pedido entra antes dos tempos
            ocorrencia = {"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000}
            mundo.registrar(
                mundo.novo(
                    "pessoa.nao_e", "p1", "Não identificado", ocorrencia=ocorrencia
                )
            )
        acrescentar(correcao)

    mundo.correcoes.acrescentar = com_o_nao_e_no_meio  # type: ignore[method-assign]

    # Com a lista que o pedido leu (sem o `nao_e`) os tempos não mudam o conjunto; com as
    # duas gravadas (tempos antes), o `nao_e` já não casa e a Ana fica.
    mundo.registrar(
        mundo.novo(
            "item.tempos",
            "p1",
            "10000-14000",
            tipo_do_item="pessoa",
            ocorrencia={"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000},
        )
    )

    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def _job_com(mundo: MundoContado, ids: list[str]) -> None:
    mundo.jobs.trocar("j1", lambda j: {"pessoas_do_catalogo": ids})


def _reprocessar_sem_a_ana(mundo: MundoContado) -> None:
    """Outro modelo, em que a Correção do `renomear` já não casa: ela vai para a fila."""
    modelo = {**MODELO, "pessoas": [_pessoa("p1", "Carla Dias", 1000, 5000)]}
    mundo.armazenamento.decupagens["j1"] = [json.dumps(modelo).encode()]


# As seis operações com um tipo que muda o conjunto (`pessoa.renomear`): o Catálogo do Job
# fica certo mesmo partindo de um valor velho.


def test_seis_operacoes_corrigir() -> None:
    mundo = MundoContado()
    mundo.renomear_ana()
    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_seis_operacoes_desfazer() -> None:
    mundo = MundoContado()
    alvo = mundo.renomear_ana()
    mundo.registro.desfazer(mundo.job, alvo.id, "x", mundo.autoria)
    assert mundo.job.pessoas_do_catalogo == []


def test_seis_operacoes_reaplicar() -> None:
    mundo = MundoContado()
    alvo = mundo.renomear_ana()
    _reprocessar_sem_a_ana(mundo)
    _job_com(mundo, [])

    mundo.registro.reaplicar(mundo.job, alvo.id, "p1", "x", mundo.autoria)

    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_seis_operacoes_descartar() -> None:
    mundo = MundoContado()
    alvo = mundo.renomear_ana()
    _reprocessar_sem_a_ana(mundo)
    _job_com(mundo, [mundo.ana.id])

    mundo.registro.descartar(mundo.job, alvo.id, "x", mundo.autoria)

    assert mundo.job.pessoas_do_catalogo == []


def test_seis_operacoes_aprovar() -> None:
    mundo = MundoContado()
    alvo = mundo.registrar(mundo.novo("pessoa.renomear", "p1", "Ana Souza Lima"), True)
    mundo.registro.decidir(mundo.job, alvo.id, True, "", mundo.autoria)
    assert mundo.job.pessoas_do_catalogo == [mundo.ana.id]


def test_seis_operacoes_recusar() -> None:
    mundo = MundoContado()
    alvo = mundo.registrar(mundo.novo("pessoa.renomear", "p1", "Ana Souza Lima"), True)
    _job_com(mundo, [mundo.ana.id])
    mundo.registro.decidir(mundo.job, alvo.id, False, "não", mundo.autoria)
    assert mundo.job.pessoas_do_catalogo == []
