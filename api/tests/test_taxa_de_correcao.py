"""A taxa de correção (#265): o cálculo, a rota e o comando."""

import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import taxa_de_correcao as taxa
from api.auth import Usuario
from api.correcoes import (
    CORRIGIVEIS,
    Ancora,
    Correcao,
    RepositorioDeCorrecoesEmMemoria,
    versao_do_modelo,
)
from api.itens_da_decupagem import ItensDaDecupagem
from api.jobs import Job, RepositorioEmMemoria, ServicoIndisponivel
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.revisao import Pulso, RepositorioDeRevisaoEmMemoria
from api.taxa_de_correcao import COLUNAS_DO_CSV, calcular, em_csv, main
from api.tests.test_auth import VerificadorFalso
from api.tests.test_passadas import AUTORIZACAO

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def _modelo(pessoas: int, pautas: int, pipeline: str | None = "v1") -> dict[str, Any]:
    return {
        "versao_pipeline": pipeline,
        "pessoas": [{"id": f"p{n}"} for n in range(pessoas)],
        "pautas": [{"id": f"t{n}"} for n in range(pautas)],
    }


class Decupagens:
    def __init__(self, dados: dict[str, dict[str, Any]]) -> None:
        self._dados = dados

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        if job_id not in self._dados:
            raise ServicoIndisponivel
        yield json.dumps(self._dados[job_id]).encode()


def _job(id: str, programa: str | None, estado: str = "concluido") -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        estado=estado,  # type: ignore[arg-type]
        criado_por="u1",
        programa=programa,
        criado_em=BASE,
        atualizado_em=BASE,
    )


def _c(
    id: str,
    job: str,
    modelo: dict[str, Any],
    tipo: str = "pessoa.renomear",
    dias: int = 0,
    **campos: Any,
) -> Correcao:
    item = "pauta" if tipo.startswith("pauta") else "pessoa"
    base: dict[str, Any] = {
        "id": id,
        "job_id": job,
        "autor_uid": "u",
        "autor_email": "u@x",
        "criada_em": BASE + timedelta(days=dias),
        "motivo": "m",
        "tipo": tipo,
        "item_id": "p0",
        "antes": "a",
        "depois": "b",
        "ancora": Ancora(
            versao=versao_do_modelo(json.dumps(modelo).encode()),
            tipo_do_item=item,  # type: ignore[arg-type]
            identidade="x",
            inicio_ms=0,
            fim_ms=1_000,
        ),
    }
    return Correcao(**{**base, **campos})


def _pulsar(revisao: RepositorioDeRevisaoEmMemoria, job: str, dias: int = 0) -> None:
    revisao.aplicar(
        Pulso(
            job_id=job,
            uid="u1",
            email="u1@x",
            quando=BASE + timedelta(days=dias),
            evento="inicio",
        ),
        300,
    )


def _mundo() -> tuple[
    RepositorioEmMemoria,
    Decupagens,
    RepositorioDeCorrecoesEmMemoria,
    RepositorioDeRevisaoEmMemoria,
]:
    """j1 e j2 do Jornal (10 pessoas e 5 pautas cada; j2 de outra versão do
    pipeline), j3 do Fama (4 pessoas, 2 pautas), j4 sem nenhuma revisão."""
    jobs = RepositorioEmMemoria()
    for id, programa in (("j1", "Jornal"), ("j2", "Jornal"), ("j3", "Fama")):
        jobs.salvar(_job(id, programa))
    jobs.salvar(_job("j4", "Jornal"))
    modelos = {
        "j1": _modelo(10, 5),
        "j2": _modelo(10, 5, "v2"),
        "j3": _modelo(4, 2),
        "j4": _modelo(100, 100),
    }
    correcoes = RepositorioDeCorrecoesEmMemoria()
    correcoes.acrescentar(_c("a", "j1", modelos["j1"]))
    correcoes.acrescentar(_c("b", "j1", modelos["j1"], item_id="p1"))
    correcoes.acrescentar(_c("c", "j1", modelos["j1"], "pauta.titulo"))
    correcoes.acrescentar(_c("d", "j2", modelos["j2"]))
    correcoes.acrescentar(_c("e", "j3", modelos["j3"], dias=10))
    return jobs, Decupagens(modelos), correcoes, RepositorioDeRevisaoEmMemoria()


def _taxa(
    linhas: list[Any], programa: str, tipo: str, versao: str | None = "v1"
) -> Any:
    [linha] = [
        x
        for x in linhas
        if (x.programa, x.versao_pipeline, x.tipo) == (programa, versao, tipo)
    ]
    return linha


def test_taxa_por_tipo_e_por_programa_sobre_os_itens_das_decupagens_revisadas() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()

    linhas = calcular(jobs, decupagens, correcoes, revisao)

    renomear = _taxa(linhas, "Jornal", "pessoa.renomear")
    assert (renomear.correcoes, renomear.itens, renomear.taxa_de_correcao) == (
        2,
        10,
        0.2,
    )
    titulo = _taxa(linhas, "Jornal", "pauta.titulo")
    assert (titulo.correcoes, titulo.itens, titulo.taxa_de_correcao) == (1, 5, 0.2)
    fama = _taxa(linhas, "Fama", "pessoa.renomear")
    assert (fama.correcoes, fama.itens, fama.taxa_de_correcao) == (1, 4, 0.25)
    # tipo sem correção aparece com taxa 0; j4, sem correção nem revisão, não conta
    sem = _taxa(linhas, "Jornal", "pessoa.nao_e")
    assert (sem.correcoes, sem.itens, sem.taxa_de_correcao) == (0, 10, 0.0)


def test_separa_por_versao_do_pipeline() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()

    linhas = calcular(jobs, decupagens, correcoes, revisao)

    v2 = _taxa(linhas, "Jornal", "pessoa.renomear", "v2")
    assert (v2.correcoes, v2.itens) == (1, 10)


def test_decupagem_revisada_sem_correcao_entra_no_denominador() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()
    _pulsar(revisao, "j4")

    linhas = calcular(jobs, decupagens, correcoes, revisao)

    renomear = _taxa(linhas, "Jornal", "pessoa.renomear")
    assert (renomear.correcoes, renomear.itens) == (2, 110)


def test_so_o_periodo_pedido_conta() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()

    primeiros = calcular(
        jobs, decupagens, correcoes, revisao, ate=BASE + timedelta(days=5)
    )
    ultimos = calcular(
        jobs, decupagens, correcoes, revisao, desde=BASE + timedelta(days=5)
    )

    assert {x.programa for x in primeiros} == {"Jornal"}
    assert {x.programa for x in ultimos} == {"Fama"}
    assert _taxa(ultimos, "Fama", "pessoa.renomear").correcoes == 1


def test_filtra_por_programa() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()

    linhas = calcular(jobs, decupagens, correcoes, revisao, programa="Fama")

    assert {x.programa for x in linhas} == {"Fama"}


def test_correcao_desfeita_recusada_ou_de_outro_json_nao_conta() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()
    modelo = _modelo(10, 5)
    correcoes.acrescentar(_c("f", "j1", modelo, "pessoa.nao_e"))
    correcoes.acrescentar(
        _c("g", "j1", modelo, "desfazer", desfaz="f", antes="", depois="")
    )
    correcoes.acrescentar(
        _c("h", "j1", modelo, "pessoa.fontes_do_nome", exige_aprovacao=True)
    )
    antiga = _c("i", "j1", modelo, "pessoa.nao_e")
    antiga.ancora = antiga.ancora.model_copy(update={"versao": "outro"})
    correcoes.acrescentar(antiga)

    linhas = calcular(jobs, decupagens, correcoes, revisao)

    for tipo in ("pessoa.nao_e", "pessoa.fontes_do_nome"):
        assert _taxa(linhas, "Jornal", tipo).correcoes == 0


def test_correcao_aprovada_conta_e_pendente_nao() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()
    modelo = _modelo(10, 5)
    correcoes.acrescentar(_c("f", "j1", modelo, "pessoa.nao_e", exige_aprovacao=True))
    correcoes.acrescentar(
        _c("g", "j1", modelo, "pessoa.fontes_do_nome", exige_aprovacao=True)
    )
    correcoes.acrescentar(
        _c("h", "j1", modelo, "aprovar", aprova="f", antes="", depois="")
    )

    linhas = calcular(jobs, decupagens, correcoes, revisao)

    assert _taxa(linhas, "Jornal", "pessoa.nao_e").correcoes == 1
    assert _taxa(linhas, "Jornal", "pessoa.fontes_do_nome").correcoes == 0


def test_aprovada_conta_no_periodo_da_aprovacao() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()
    modelo = _modelo(10, 5)
    # criada antes do período e aprovada nele; criada nele e aprovada depois
    correcoes.acrescentar(
        _c("f", "j1", modelo, "pessoa.nao_e", dias=-10, exige_aprovacao=True)
    )
    correcoes.acrescentar(
        _c("g", "j1", modelo, "aprovar", aprova="f", antes="", depois="")
    )
    correcoes.acrescentar(
        _c("h", "j1", modelo, "pessoa.nao_e", dias=1, exige_aprovacao=True)
    )
    correcoes.acrescentar(
        _c("i", "j1", modelo, "aprovar", dias=20, aprova="h", antes="", depois="")
    )

    linhas = calcular(
        jobs,
        decupagens,
        correcoes,
        revisao,
        desde=BASE - timedelta(days=1),
        ate=BASE + timedelta(days=5),
    )

    assert _taxa(linhas, "Jornal", "pessoa.nao_e").correcoes == 1


def test_aprovacao_no_periodo_torna_a_decupagem_revisada() -> None:
    jobs, decupagens, correcoes, revisao = _mundo()
    modelo = _modelo(100, 100)
    correcoes.acrescentar(
        _c("f", "j4", modelo, "pessoa.nao_e", dias=-10, exige_aprovacao=True)
    )
    correcoes.acrescentar(
        _c("g", "j4", modelo, "aprovar", aprova="f", antes="", depois="")
    )

    linhas = calcular(
        jobs, decupagens, correcoes, revisao, desde=BASE - timedelta(days=1)
    )

    nao_e = _taxa(linhas, "Jornal", "pessoa.nao_e")
    assert (nao_e.correcoes, nao_e.itens) == (1, 110)


def test_decupagem_fora_do_formato_fica_de_fora_sem_somar_pela_metade() -> None:
    jobs, _decupagens, correcoes, revisao = _mundo()
    decupagens = Decupagens(
        {
            "j1": [1, 2],  # type: ignore[dict-item]
            "j2": {**_modelo(10, 5, "v2"), "pautas": [{"id": "t0"}, "lixo"]},
            "j3": {**_modelo(4, 2), "versao_pipeline": 7},
        }
    )

    linhas = calcular(jobs, decupagens, correcoes, revisao)

    assert {(x.programa, x.versao_pipeline) for x in linhas} == {
        ("Jornal", "v2"),
        ("Fama", None),
    }
    assert _taxa(linhas, "Jornal", "pauta.titulo", "v2").itens == 1


def test_job_sem_decupagem_legivel_fica_de_fora() -> None:
    jobs, _decupagens, correcoes, revisao = _mundo()

    linhas = calcular(jobs, Decupagens({}), correcoes, revisao)

    assert linhas == []


def test_csv_tem_as_colunas_e_taxa_vazia_sem_itens() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("j1", None))
    modelo = _modelo(0, 0, None)
    correcoes = RepositorioDeCorrecoesEmMemoria()
    correcoes.acrescentar(_c("a", "j1", modelo))

    linhas = calcular(
        jobs, Decupagens({"j1": modelo}), correcoes, RepositorioDeRevisaoEmMemoria()
    )
    lidas = list(csv.DictReader(io.StringIO(em_csv(linhas))))

    assert tuple(lidas[0]) == COLUNAS_DO_CSV
    renomear = next(x for x in lidas if x["tipo"] == "pessoa.renomear")
    assert renomear == {
        "programa": "",
        "versao_pipeline": "",
        "tipo": "pessoa.renomear",
        "correcoes": "1",
        "itens": "0",
        "taxa_de_correcao": "",
    }


ROTA = "/v1/qualidade/taxa-de-correcao"
OUTRA = {"Authorization": "Bearer token-outra"}


def _cliente(papeis: dict[str, list[Papel]]) -> TestClient:
    jobs, decupagens, correcoes, revisao = _mundo()
    repo_papeis = RepositorioDePapeisEmMemoria()
    for uid, lista in papeis.items():
        repo_papeis.salvar(uid, lista)
    return TestClient(
        criar_app(
            VerificadorFalso(
                {
                    "token-bom": Usuario(uid="u1", email="a@redetv.com.br"),
                    "token-outra": Usuario(uid="u2", email="b@redetv.com.br"),
                }
            ),
            jobs,
            armazenamento=decupagens,  # type: ignore[arg-type]
            papeis=repo_papeis,
            correcoes=correcoes,
            revisao=revisao,
        )
    )


def test_rota_devolve_as_linhas_do_periodo_e_do_programa() -> None:
    cliente = _cliente({"u1": ["curador"]})

    corpo = cliente.get(
        ROTA,
        params={"desde": "2026-11-02", "ate": "2026-11-02", "programa": "Jornal"},
        headers=AUTORIZACAO,
    ).json()

    assert corpo["desde"] == "2026-11-02"
    assert {x["programa"] for x in corpo["linhas"]} == {"Jornal"}
    [renomear] = [
        x
        for x in corpo["linhas"]
        if x["tipo"] == "pessoa.renomear" and x["versao_pipeline"] == "v1"
    ]
    assert renomear == {
        "programa": "Jornal",
        "versao_pipeline": "v1",
        "tipo": "pessoa.renomear",
        "correcoes": 2,
        "itens": 10,
        "taxa_de_correcao": 0.2,
    }


def test_o_dia_de_ate_entra_inteiro() -> None:
    cliente = _cliente({"u1": ["curador"]})

    corpo = cliente.get(ROTA, params={"ate": "2026-11-02"}, headers=AUTORIZACAO).json()

    assert {x["programa"] for x in corpo["linhas"]} == {"Jornal"}


def test_quem_ve_e_curador_ou_auditor() -> None:
    cliente = _cliente({"u1": ["editor"], "u2": ["administrador"]})

    assert cliente.get(ROTA, headers=AUTORIZACAO).status_code == 403
    assert cliente.get(ROTA, headers=OUTRA).status_code == 200
    assert cliente.get(ROTA).status_code == 401


def test_periodo_invertido_e_422() -> None:
    cliente = _cliente({"u1": ["curador"]})

    resposta = cliente.get(
        ROTA, params={"desde": "2026-11-03", "ate": "2026-11-02"}, headers=AUTORIZACAO
    )

    assert resposta.status_code == 422


def test_sem_projeto_o_comando_avisa_e_sai_com_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([], {}) == 2
    assert "GCP_PROJECT_ID" in capsys.readouterr().err


def test_data_invalida_ou_invertida_avisa_e_sai_com_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ambiente = {"GCP_PROJECT_ID": "p", "BUCKET_ACEITOS": "a", "BUCKET_DECUPAGENS": "d"}

    assert main(["ontem"], ambiente) == 2
    assert main(["2026-11-03", "2026-11-02"], ambiente) == 2
    assert "ontem" in capsys.readouterr().err


def test_comando_imprime_o_csv_do_periodo_e_do_programa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, decupagens, correcoes, revisao = _mundo()
    monkeypatch.setattr(taxa, "cliente_do_firestore", lambda projeto: None)
    monkeypatch.setattr(taxa, "ClienteStorage", lambda project: None)
    monkeypatch.setattr(taxa, "RepositorioFirestore", lambda banco: jobs)
    monkeypatch.setattr(taxa, "DecupagensStorage", lambda *_: decupagens)
    monkeypatch.setattr(
        taxa, "RepositorioDeCorrecoesFirestore", lambda banco: correcoes
    )
    monkeypatch.setattr(taxa, "RepositorioDeRevisaoFirestore", lambda banco: revisao)
    ambiente = {"GCP_PROJECT_ID": "p", "BUCKET_ACEITOS": "a", "BUCKET_DECUPAGENS": "d"}
    impresso: list[str] = []

    assert main(["2026-11-02", "2026-11-02", "Jornal"], ambiente, impresso.append) == 0

    [texto] = impresso
    lidas = list(csv.DictReader(io.StringIO(texto)))
    assert {x["programa"] for x in lidas} == {"Jornal"}
    assert {
        "programa": "Jornal",
        "versao_pipeline": "v1",
        "tipo": "pessoa.renomear",
        "correcoes": "2",
        "itens": "10",
        "taxa_de_correcao": "0.2",
    } in lidas


def _taxa_com_contagem_sem(*tipos: str) -> list[Any]:
    jobs, decupagens, correcoes, revisao = _mundo()
    _pulsar(revisao, "j1")
    pronta = taxa._itens_da_decupagem(decupagens, "j1")
    gravada = ItensDaDecupagem(
        versao_do_modelo=pronta.versao_do_modelo,
        versao_pipeline=pronta.versao_pipeline,
        itens={t: n for t, n in pronta.itens.items() if t not in tipos},
    )
    por_job = taxa.calcular_com_itens(jobs, lambda _job_id: gravada, correcoes, revisao)
    return [linha for job_id, linha in por_job if job_id == "j1"]


def test_tipo_novo_com_irmao_mantem_o_video_na_taxa() -> None:
    linhas = _taxa_com_contagem_sem("pessoa.renomear")

    assert _taxa(linhas, "Jornal", "pessoa.renomear").itens == 10
    assert _taxa(linhas, "Jornal", "pessoa.renomear").correcoes == 2


def test_tipo_novo_sem_irmao_tira_o_video_da_taxa() -> None:
    tipos_da_pauta = [t for t in CORRIGIVEIS if t.startswith("pauta.")]

    assert _taxa_com_contagem_sem(*tipos_da_pauta) == []


_PAUTA = {"id": "t0", "titulo": "x", "inicio_ms": 0, "fim_ms": 1_000}


def _regravada(pauta_depois: dict[str, Any], desfeita: bool = False) -> list[Any]:
    """j1 com uma pauta corrigida sobre o JSON antigo; a decupagem foi regravada
    com mais uma pessoa (outro sha256) e a pauta como `pauta_depois`."""
    antes = {"versao_pipeline": "v1", "pessoas": [], "pautas": [_PAUTA]}
    depois = {**antes, "pessoas": [{"nome": "Ana"}], "pautas": [pauta_depois]}
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("j1", "Jornal"))
    correcoes = RepositorioDeCorrecoesEmMemoria()
    correcoes.acrescentar(_c("a", "j1", antes, "pauta.titulo"))
    if desfeita:
        correcoes.acrescentar(
            _c("b", "j1", antes, "desfazer", desfaz="a", antes="", depois="")
        )
    revisao = RepositorioDeRevisaoEmMemoria()
    _pulsar(revisao, "j1")
    return calcular(jobs, Decupagens({"j1": depois}), correcoes, revisao)


def test_correcao_reconciliada_com_a_versao_atual_conta() -> None:
    linhas = _regravada(_PAUTA)

    assert _taxa(linhas, "Jornal", "pauta.titulo").correcoes == 1


def test_correcao_que_nao_casa_com_a_versao_atual_nao_conta() -> None:
    linhas = _regravada({**_PAUTA, "inicio_ms": 5_000, "fim_ms": 6_000})

    assert _taxa(linhas, "Jornal", "pauta.titulo").correcoes == 0


def test_correcao_desfeita_apos_regravar_nao_conta() -> None:
    linhas = _regravada(_PAUTA, desfeita=True)

    assert _taxa(linhas, "Jornal", "pauta.titulo").correcoes == 0
