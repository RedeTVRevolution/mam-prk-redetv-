"""Indexação da Decupagem entregue no índice da busca (#118)."""

import inspect
import json
from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient

import api.jobs
from api.auth import Usuario
from api.copia_bigquery import CopiaDosMomentos
from api.correcoes import (
    RepositorioDeAprovacaoEmMemoria,
    RepositorioDeCorrecoesEmMemoria,
    versao_do_modelo,
)
from api.exemplos_da_busca import EXEMPLOS, SABRINA
from api.indexacao import reindexar, reindexar_jobs
from api.indice_da_busca import (
    Consulta,
    Filtros,
    IndiceEmMemoria,
    Registro,
    registros_da_decupagem,
)
from api.jobs import Indexacao, Job, RepositorioEmMemoria, ServicoIndisponivel
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_correcoes import BASE
from api.tests.test_jobs import ArmazenamentoFalso
from api.tipos_de_objeto import TiposDeObjetoEmMemoria

SABRINA_EXEMPLO = EXEMPLOS[0]
AUTORIZACAO = {"Authorization": "Bearer token-bom"}
CURADOR = {"Authorization": "Bearer token-curador"}
MODELO = json.loads(SABRINA_EXEMPLO.decupagem.model_dump_json())


class JobsQueNaoGravam(RepositorioEmMemoria):
    def transitar(self, job_id: str, de: Any, mudancas: dict[str, Any]) -> Job | None:
        if "indexacao" in mudancas:
            raise ConnectionError("Firestore fora do ar")
        return super().transitar(job_id, de, mudancas)


class DisparoFalso:
    """O Cloud Run: guarda o pedido; a reindexação roda quando o teste manda (`rodar_o_job`)."""

    def __init__(self, falha: bool = False) -> None:
        self.pedidos: list[str] = []
        self.falha = falha

    def iniciar(self, job_id: str) -> None:
        if self.falha:
            raise ServicoIndisponivel
        self.pedidos.append(job_id)


class IndiceQueConta(IndiceEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.gravacoes = 0

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        self.gravacoes += 1
        super().gravar(job_id, registros)


class IndiceQueFalha(IndiceEmMemoria):
    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        raise ConnectionError("índice fora do ar")


def _job(id: str = "j1", estado: str = "concluido") -> Job:
    return Job(
        id=id,
        nome="a.mp4",
        tamanho_bytes=10,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        programa="Exemplo",
        data_exibicao=date(2026, 10, 30),
        criado_em=BASE,
        atualizado_em=BASE,
    )


class Mundo:
    def __init__(
        self,
        indice: IndiceEmMemoria | None = None,
        copia: CopiaDosMomentos | None = None,
        modelo: dict[str, Any] = MODELO,
        disparo: DisparoFalso | None = None,
    ) -> None:
        self.disparo = disparo or DisparoFalso()
        self.indice = indice or IndiceEmMemoria()
        self.tipos = TiposDeObjetoEmMemoria()
        self.copia: Any = copia
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(_job())
        self.armazenamento = ArmazenamentoFalso()
        self.armazenamento.decupagens["j1"] = [json.dumps(modelo).encode()]
        self.correcoes = RepositorioDeCorrecoesEmMemoria()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("u1", ["editor"])
        papeis.salvar("u2", ["curador"])
        self.aprovacao = RepositorioDeAprovacaoEmMemoria()
        self.cliente = TestClient(
            criar_app(
                _Verificador(),
                self.jobs,
                self.armazenamento,
                papeis=papeis,
                correcoes=self.correcoes,
                aprovacao=self.aprovacao,
                indice=self.indice,
                tipos_de_objeto=self.tipos,
                copia=copia,
                disparo_da_indexacao=self.disparo,
                relogio=lambda: BASE,
            )
        )

    def reindexar(self) -> None:
        job = self.jobs.obter("j1")
        assert job
        reindexar(
            job,
            self.jobs,
            self.armazenamento,
            self.correcoes,
            self.indice,
            copia=self.copia,
            tipos_de_objeto=self.tipos,
        )

    def aprovar_revisao(self) -> Any:
        return self.cliente.post("/v1/jobs/j1/revisao/aprovar", headers=AUTORIZACAO)

    def rodar_o_job(self) -> None:
        """O que o `mam-indexacao` faz quando o disparo o inicia."""
        self.reindexar()

    def corrigir_a_fala(self, texto: str) -> Any:
        versao = versao_do_modelo(json.dumps(MODELO).encode())
        return self.cliente.post(
            "/v1/jobs/j1/correcoes",
            json={
                "tipo": "fala.texto",
                "item_id": "fal000",
                "valor": json.dumps({"texto": texto, "locutor": "Apresentadora"}),
                "motivo": "ouvi de novo",
                "versao": versao,
            },
            headers=AUTORIZACAO,
        )

    def textos_das_falas(self) -> list[str | None]:
        achados = self.indice.buscar(Consulta(filtros=Filtros(tipo="fala")))
        return [r.texto for r in achados]

    def indexacao(self) -> dict[str, Any]:
        corpo = self.cliente.get("/v1/jobs/j1", headers=AUTORIZACAO).json()
        indexacao: dict[str, Any] = corpo["indexacao"]
        return indexacao


class _Verificador:
    def verificar(self, token: str) -> Usuario:
        return {
            "token-bom": Usuario(uid="u1", email="ana@redetv.com.br"),
            "token-curador": Usuario(uid="u2", email="cura@redetv.com.br"),
        }[token]


def test_decupagem_de_dois_planos_uma_fala_um_gc_e_o_vestido_da_sabrina() -> None:
    registros = registros_da_decupagem(
        "j1", SABRINA_EXEMPLO.decupagem, "Exemplo", date(2026, 10, 30)
    )

    por_tipo = {
        t: [r for r in registros if r.tipo == t] for t in {r.tipo for r in registros}
    }
    assert {t: len(rs) for t, rs in por_tipo.items()} == {
        "plano": 2,
        "fala": 1,
        "texto_na_tela": 1,
        "objeto": 2,
    }
    [vestido] = [r for r in por_tipo["objeto"] if r.cor_base == ["vermelho"]]
    assert (vestido.categoria, vestido.tipo_do_objeto) == ("roupa", "vestido")
    assert vestido.dono == SABRINA
    assert por_tipo["texto_na_tela"][0].texto == "Noite de gala"
    assert por_tipo["fala"][0].texto == "Boa noite a todos"
    assert all(r.programa == "Exemplo" for r in registros)


def test_objeto_de_pessoa_sem_catalogo_id_fica_sem_dono() -> None:
    sem_catalogo = json.loads(SABRINA_EXEMPLO.decupagem.model_dump_json())
    for pessoa in sem_catalogo["pessoas"]:
        pessoa["catalogo_id"] = None
    decupagem = type(SABRINA_EXEMPLO.decupagem).model_validate(sem_catalogo)

    registros = registros_da_decupagem("j1", decupagem, None, None)

    assert [r.dono for r in registros if r.tipo == "objeto"] == [None, None]
    assert all(r.pessoas == [] for r in registros)


def test_vetores_so_nos_registros_de_plano() -> None:
    registros = registros_da_decupagem("j1", SABRINA_EXEMPLO.decupagem, None, None)

    assert all(r.descricao is None for r in registros if r.tipo != "plano")
    assert all(r.descricao for r in registros if r.tipo == "plano")
    assert all(
        r.quadro is None for r in registros if r.tipo in ("fala", "texto_na_tela")
    )


def test_reindexar_grava_o_video_e_marca_indexado() -> None:
    mundo = Mundo()

    mundo.reindexar()

    assert mundo.indice.total() == 6
    assert mundo.indexacao()["estado"] == "indexado"


def test_reindexar_grava_no_job_quem_do_catalogo_aparece_nele() -> None:
    modelo = json.loads(json.dumps(MODELO))
    modelo["pessoas"][0]["catalogo_id"] = "pessoa-1"
    mundo = Mundo(modelo=modelo)
    job = mundo.jobs.obter("j1")
    assert job and job.pessoas_do_catalogo == []

    mundo.reindexar()

    job = mundo.jobs.obter("j1")
    assert job and job.pessoas_do_catalogo == ["cat-outra", "pessoa-1"]


def test_reindexar_duas_vezes_deixa_o_mesmo_conjunto() -> None:
    mundo = Mundo()
    mundo.reindexar()
    antes = mundo.indice.buscar(Consulta(limite=100))

    mundo.reindexar()

    assert mundo.indice.buscar(Consulta(limite=100)) == antes
    assert mundo.indice.total() == 6


def test_falha_do_indice_marca_falhou_e_nao_muda_o_estado_do_job() -> None:
    mundo = Mundo(IndiceQueFalha())

    mundo.reindexar()

    job = mundo.jobs.obter("j1")
    assert job and job.estado == "concluido"
    assert job.indexacao and job.indexacao.estado == "falhou"
    assert mundo.indexacao()["estado"] == "falhou"


def test_job_que_nao_concluiu_nao_e_indexado() -> None:
    mundo = Mundo()
    mundo.jobs.salvar(_job("j2", "analisando"))

    assert reindexar_jobs(
        ["j2"], mundo.jobs, mundo.armazenamento, mundo.correcoes, mundo.indice
    ) == {"j2": "ignorado"}
    assert mundo.indice.total() == 0


def test_id_que_nao_existe_sai_como_inexistente() -> None:
    mundo = Mundo()

    assert reindexar_jobs(
        ["j1", "nao-existe"],
        mundo.jobs,
        mundo.armazenamento,
        mundo.correcoes,
        mundo.indice,
    ) == {"nao-existe": "inexistente", "j1": "indexado"}


def test_falha_ao_gravar_o_estado_nao_derruba_nem_impede_a_indexacao() -> None:
    mundo = Mundo()
    jobs = JobsQueNaoGravam()
    jobs.salvar(_job())

    assert (
        reindexar(_job(), jobs, mundo.armazenamento, mundo.correcoes, mundo.indice)
        is None
    )
    assert mundo.indice.total() == 6


def test_reindexar_todos_pega_so_os_concluidos() -> None:
    mundo = Mundo()
    mundo.jobs.salvar(_job("j2", "analisando"))

    resultado = reindexar_jobs(
        None, mundo.jobs, mundo.armazenamento, mundo.correcoes, mundo.indice
    )

    assert resultado == {"j1": "indexado"}


def test_correcao_responde_sem_reindexar_e_so_o_aprovar_revisao_atualiza_o_indice() -> (
    None
):
    indice = IndiceQueConta()
    mundo = Mundo(indice)
    mundo.reindexar()
    gravacoes = indice.gravacoes
    assert mundo.textos_das_falas() == ["Boa noite a todos"]

    resposta = mundo.corrigir_a_fala("Boa noite, Brasil")

    assert resposta.status_code == 201
    assert indice.gravacoes == gravacoes
    assert mundo.textos_das_falas() == ["Boa noite a todos"]
    assert mundo.disparo.pedidos == []

    aprovada = mundo.aprovar_revisao()
    assert aprovada.status_code == 202
    assert mundo.disparo.pedidos == ["j1"]
    assert mundo.indexacao()["estado"] == "pendente"
    mundo.rodar_o_job()
    assert mundo.textos_das_falas() == ["Boa noite, Brasil"]
    assert mundo.indice.total() == 6
    assert mundo.indexacao()["estado"] == "indexado"


def test_nenhuma_acao_da_revisao_grava_no_indice() -> None:
    indice = IndiceQueConta()
    mundo = Mundo(indice)
    mundo.reindexar()
    gravacoes = indice.gravacoes
    mundo.aprovacao.definir(frozenset({"fala.texto"}))

    cid = mundo.corrigir_a_fala("Boa noite, Brasil").json()["id"]
    aprovada = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=CURADOR
    )
    desfeita = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{cid}/desfazer",
        json={"motivo": "voltei atrás"},
        headers=AUTORIZACAO,
    )

    assert (aprovada.status_code, desfeita.status_code) == (201, 201)
    assert indice.gravacoes == gravacoes
    assert mundo.textos_das_falas() == ["Boa noite a todos"]


def test_aprovar_revisao_que_nao_dispara_volta_o_estado_e_da_503() -> None:
    mundo = Mundo(disparo=DisparoFalso(falha=True))
    mundo.reindexar()

    resposta = mundo.aprovar_revisao()

    assert resposta.status_code == 503
    assert mundo.indexacao()["estado"] == "indexado"


def test_aprovar_revisao_volta_o_estado_mesmo_com_erro_inesperado_do_disparo() -> None:
    class DisparoQueQuebra(DisparoFalso):
        def iniciar(self, job_id: str) -> None:
            raise RuntimeError("sem credencial")

    mundo = Mundo(disparo=DisparoQueQuebra())
    mundo.reindexar()
    cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)

    resposta = cliente.post("/v1/jobs/j1/revisao/aprovar", headers=AUTORIZACAO)

    assert resposta.status_code == 500
    assert mundo.indexacao()["estado"] == "indexado"


def test_nenhuma_rota_dos_jobs_reindexa_dentro_do_pedido() -> None:
    # As rotas da revisão (corrigir, aceitar sugestão, desfazer, aprovar ou recusar,
    # descartar e reaplicar da fila) só gravam Correções: a reindexação é do Job
    # `mam-indexacao`, que o "Aprovar Revisão" dispara (#328).
    assert "reindexar" not in inspect.signature(api.jobs.criar_rotas).parameters
    assert "reindexar" not in inspect.getsource(api.jobs)


def test_aprovar_revisao_pede_permissao_de_editar() -> None:
    mundo = Mundo()
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("u1", ["consulta"])
    cliente = TestClient(
        criar_app(
            _Verificador(),
            mundo.jobs,
            mundo.armazenamento,
            papeis=papeis,
            disparo_da_indexacao=mundo.disparo,
        )
    )

    resposta = cliente.post("/v1/jobs/j1/revisao/aprovar", headers=AUTORIZACAO)

    assert resposta.status_code == 403
    assert mundo.disparo.pedidos == []


def _na_busca(mundo: Mundo) -> list[str]:
    historico = mundo.cliente.get("/v1/jobs/j1/correcoes", headers=AUTORIZACAO).json()
    return [item["na_busca"] for item in historico]


def test_correcao_gravada_so_aparece_na_busca_depois_de_aprovar_a_revisao() -> None:
    mundo = Mundo()
    mundo.reindexar()
    mundo.corrigir_a_fala("Boa noite, Brasil")

    mundo.aprovar_revisao()
    assert _na_busca(mundo) == ["indexando"]
    mundo.rodar_o_job()

    assert _na_busca(mundo) == ["na_busca"]


def test_correcao_mostra_indexando_enquanto_a_indexacao_roda() -> None:
    mundo = Mundo()
    mundo.corrigir_a_fala("Boa noite, Brasil")
    mundo.jobs.transitar(
        "j1", "concluido", {"indexacao": Indexacao(estado="pendente", em=BASE)}
    )

    assert _na_busca(mundo) == ["indexando"]


def test_correcao_fica_so_salva_se_a_indexacao_falhou() -> None:
    mundo = Mundo(IndiceQueFalha())
    mundo.corrigir_a_fala("Boa noite, Brasil")
    mundo.aprovar_revisao()
    mundo.rodar_o_job()

    assert _na_busca(mundo) == ["salva"]


def test_correcao_gravada_depois_da_rodada_nao_esta_na_busca() -> None:
    mundo = Mundo()
    mundo.corrigir_a_fala("Boa noite, Brasil")
    antes = BASE - timedelta(hours=1)
    mundo.jobs.transitar(
        "j1",
        "concluido",
        {"indexacao": Indexacao(estado="indexado", em=antes, desde=antes)},
    )

    assert _na_busca(mundo) == ["salva"]


def test_correcao_pendente_de_aprovacao_so_entra_na_busca_depois_de_aprovada() -> None:
    mundo = Mundo()
    mundo.reindexar()
    mundo.aprovacao.definir(frozenset({"fala.texto"}))
    cid = mundo.corrigir_a_fala("Boa noite, Brasil").json()["id"]
    mundo.aprovar_revisao()
    mundo.rodar_o_job()
    assert _na_busca(mundo) == ["salva"]

    mundo.cliente.post(f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=CURADOR)
    mundo.aprovar_revisao()
    mundo.rodar_o_job()

    assert "na_busca" in _na_busca(mundo)


def _modelo_com_sandalia_e_scarpin() -> dict[str, Any]:
    modelo: dict[str, Any] = json.loads(json.dumps(MODELO))
    for objeto, tipo in zip(modelo["objetos"], ["sandália", "scarpin"], strict=True):
        objeto["tipo"] = tipo
    return modelo


def test_reindexar_registra_os_tipos_dos_objetos() -> None:
    mundo = Mundo(modelo=_modelo_com_sandalia_e_scarpin())

    mundo.reindexar()

    assert mundo.tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 1}]
    assert mundo.tipos.buscar("SCAR") == [{"tipo": "scarpin", "ocorrencias": 1}]


def test_reindexar_duas_vezes_nao_dobra_a_contagem_dos_tipos() -> None:
    mundo = Mundo(modelo=_modelo_com_sandalia_e_scarpin())

    mundo.reindexar()
    mundo.reindexar()

    assert mundo.tipos.buscar("sa") == [{"tipo": "sandália", "ocorrencias": 1}]


def test_tipos_que_falham_nao_derrubam_a_indexacao() -> None:
    class Quebrado(TiposDeObjetoEmMemoria):
        def registrar(self, job_id: str, contagens: Any) -> None:
            raise ConnectionError("Firestore fora do ar")

    mundo = Mundo()
    mundo.tipos = Quebrado()

    mundo.reindexar()

    assert mundo.indice.total() == 6
    assert mundo.indexacao()["estado"] == "indexado"


def test_a_rota_devolve_os_tipos_gravados_pelo_reindexar() -> None:
    mundo = Mundo(modelo=_modelo_com_sandalia_e_scarpin())
    mundo.reindexar()

    def buscar(q: str) -> Any:
        return mundo.cliente.get(
            "/v1/objetos/tipos", params={"q": q}, headers=AUTORIZACAO
        )

    assert buscar("sa").json() == [{"tipo": "sandália", "ocorrencias": 1}]
    assert buscar("SCAR").json() == [{"tipo": "scarpin", "ocorrencias": 1}]


def test_os_tipos_acompanham_acrescentar_e_atributos() -> None:
    mundo = Mundo()
    versao = versao_do_modelo(json.dumps(MODELO).encode())

    def corrigir(tipo: str, valor: dict[str, Any], item_id: str = "") -> Any:
        return mundo.cliente.post(
            "/v1/jobs/j1/correcoes",
            json={
                "tipo": tipo,
                "item_id": item_id,
                "valor": json.dumps(valor),
                "motivo": "ouvi de novo",
                "versao": versao,
            },
            headers=AUTORIZACAO,
        )

    def buscar(q: str) -> list[tuple[str, int]]:
        r = mundo.cliente.get("/v1/objetos/tipos", params={"q": q}, headers=AUTORIZACAO)
        return [(t["tipo"], t["ocorrencias"]) for t in r.json()]

    mundo.reindexar()
    assert buscar("sa") == []
    [(_, vestidos)] = buscar("vest")

    novo = {
        "categoria": "calcado",
        "tipo": "sandália",
        "cor_base": ["vermelho"],
        "inicio_ms": 0,
        "fim_ms": 4000,
    }
    assert corrigir("objeto.acrescentar", novo).status_code == 201
    assert mundo.aprovar_revisao().status_code == 202
    mundo.rodar_o_job()
    assert buscar("SA") == [("sandália", 1)]

    atributos = {"tipo": "scarpin", "cor_base": MODELO["objetos"][0]["cor_base"]}
    assert corrigir("objeto.atributos", atributos, "obj01").status_code == 201
    assert mundo.aprovar_revisao().status_code == 202
    mundo.rodar_o_job()
    assert buscar("scar") == [("scarpin", 1)]
    assert buscar("vest") == [("vestido", vestidos - 1)]
