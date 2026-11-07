"""Texto como dado na API (#461, #474): tamanho, caracteres de controle e ids."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import BASE, NOVO_JOB
from api.tests.test_jobs import ArmazenamentoFalso
from api.texto_como_dado import id_seguro, tem_controle

CURADOR = {"Authorization": "Bearer curador"}
# O que cada tipo de texto recusa: NUL, escape, DEL e controle C1.
CONTROLES = ["\x00", "\x1b", "\x7f", "\x85"]


class RepositorioQueAnota(RepositorioEmMemoria):
    """Anota cada id que chegou ao repositório (o Firestore, na produção)."""

    def __init__(self) -> None:
        super().__init__()
        self.consultados: list[str] = []

    def obter(self, job_id: str) -> Job | None:
        self.consultados.append(job_id)
        return super().obter(job_id)


class Mundo:
    def __init__(self) -> None:
        self.jobs = RepositorioQueAnota()
        self.armazenamento = ArmazenamentoFalso()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("cur", ["curador", "administrador"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {"curador": Usuario(uid="cur", email="cur@redetv.com")}
                ),
                self.jobs,
                self.armazenamento,
                papeis=papeis,
                relogio=lambda: BASE,
            )
        )

    def post(self, caminho: str, corpo: dict[str, Any]) -> Any:
        return self.cliente.post(caminho, json=corpo, headers=CURADOR)


def _esquemas_de_entrada() -> list[tuple[str, dict[str, Any]]]:
    """Cada texto que o app lê do pedido (corpo e consulta), com o caminho no esquema."""
    esquema = criar_app().openapi()
    componentes = esquema["components"]["schemas"]
    achados: list[tuple[str, dict[str, Any]]] = []

    def andar(no: dict[str, Any], onde: str, vistos: frozenset[str]) -> None:
        if "$ref" in no:
            nome = no["$ref"].rsplit("/", 1)[-1]
            if nome not in vistos:
                andar(componentes[nome], onde, vistos | {nome})
            return
        for chave in ("anyOf", "oneOf", "allOf"):
            for sub in no.get(chave, []):
                andar(sub, onde, vistos)
        if no.get("type") == "string" and not {"enum", "const", "format"} & no.keys():
            achados.append((onde, no))
        for nome, sub in no.get("properties", {}).items():
            andar(sub, f"{onde}.{nome}", vistos)
        if isinstance(no.get("additionalProperties"), dict):
            andar(no["additionalProperties"], f"{onde}.*", vistos)
        if "items" in no:
            andar(no["items"], f"{onde}[]", vistos)

    for caminho, metodos in esquema["paths"].items():
        for metodo, operacao in metodos.items():
            onde = f"{metodo.upper()} {caminho}"
            for parametro in operacao.get("parameters", []):
                if parametro["in"] in ("query", "header"):
                    andar(
                        parametro["schema"], f"{onde} ?{parametro['name']}", frozenset()
                    )
            for conteudo in operacao.get("requestBody", {}).get("content", {}).values():
                andar(conteudo["schema"], f"{onde} corpo", frozenset())
    return achados


def test_todo_texto_do_pedido_tem_tamanho_maximo_e_recusa_controle() -> None:
    achados = _esquemas_de_entrada()
    assert len(achados) > 50  # o levantamento enxerga o app inteiro

    sem_limite = [onde for onde, no in achados if "maxLength" not in no]
    sem_controle = [onde for onde, no in achados if "pattern" not in no]

    assert sem_limite == [], "\n".join(sem_limite)
    assert sem_controle == [], sem_controle


@pytest.mark.parametrize("controle", CONTROLES)
def test_nome_com_caractere_de_controle_volta_422(controle: str) -> None:
    mundo = Mundo()

    resposta = mundo.post(
        "/v1/catalogo/pessoas", {"nome": f"A{controle}na", "papel": "apresentadora"}
    )

    assert resposta.status_code == 422


def test_nome_com_quebra_de_linha_volta_422_e_a_observacao_aceita() -> None:
    mundo = Mundo()

    nome = mundo.post(
        "/v1/catalogo/pessoas", {"nome": "Ana\nLima", "papel": "apresentadora"}
    )
    motivo = mundo.post(
        "/v1/admin/lixeira/pessoas/p1", {"motivo": "primeira linha\nsegunda linha"}
    )

    assert nome.status_code == 422
    assert motivo.status_code != 422  # 404: a pessoa não existe; o texto passou


def test_motivo_com_controle_volta_422() -> None:
    mundo = Mundo()

    resposta = mundo.post("/v1/admin/lixeira/pessoas/p1", {"motivo": "x\x00y"})

    assert resposta.status_code == 422


def test_campo_acima_do_maximo_volta_422() -> None:
    mundo = Mundo()

    pessoa = mundo.post(
        "/v1/catalogo/pessoas", {"nome": "A" * 10_000, "papel": "apresentadora"}
    )
    motivo = mundo.post("/v1/admin/lixeira/pessoas/p1", {"motivo": "m" * 100_000})
    programa = mundo.post("/v1/jobs", {**NOVO_JOB, "programa": "P" * 10_000})

    assert [pessoa.status_code, motivo.status_code, programa.status_code] == [422] * 3


def test_consulta_com_controle_ou_gigante_volta_422() -> None:
    mundo = Mundo()

    controle = mundo.cliente.get("/v1/busca", params={"q": "a\x00b"}, headers=CURADOR)
    gigante = mundo.cliente.get("/v1/jobs", params={"q": "q" * 20_000}, headers=CURADOR)

    assert controle.status_code == 422
    assert gigante.status_code == 422


@pytest.mark.parametrize(
    "id_ruim", ["a..b", "a%00b", "a%0ab", "a%1bb", "a%5Cb", "a%7Fb", "x" * 300]
)
def test_id_no_caminho_e_recusado_antes_do_repositorio(id_ruim: str) -> None:
    mundo = Mundo()

    leitura = mundo.cliente.get(f"/v1/jobs/{id_ruim}", headers=CURADOR)
    remocao = mundo.cliente.delete(f"/v1/jobs/{id_ruim}", headers=CURADOR)

    assert leitura.status_code in (404, 422)
    assert remocao.status_code in (404, 422)
    assert mundo.jobs.consultados == []


def test_id_com_barra_nao_chega_ao_repositorio() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get("/v1/jobs/a%2Fb", headers=CURADOR)

    assert resposta.status_code in (404, 422)
    assert mundo.jobs.consultados == []


def test_id_normal_segue_para_o_repositorio() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get("/v1/jobs/j-1_a", headers=CURADOR)

    assert resposta.status_code == 404
    assert set(mundo.jobs.consultados) == {"j-1_a"}


@pytest.mark.parametrize(
    "valor",
    ["", ".", "..", "a/b", "a\\b", "a..b", "a\x00b", "a\nb", "a\x7fb", "x" * 201],
)
def test_id_seguro_recusa(valor: str) -> None:
    assert not id_seguro(valor)


@pytest.mark.parametrize("valor", ["abc123", "j-1_a", "Ab:cd", "a.b", "sabrina-sato"])
def test_id_seguro_aceita(valor: str) -> None:
    assert id_seguro(valor)


def test_controle_so_aceita_quebra_quando_pedida() -> None:
    assert tem_controle("a\nb")
    assert not tem_controle("a\nb", permite_quebra=True)
    assert not tem_controle("a\tb\r\nc", permite_quebra=True)
    assert tem_controle("a\x00b", permite_quebra=True)
    assert not tem_controle("Ação — 日本")
