"""O aceite dos esquemas contra o Vertex (#617): a lógica, com transporte falso."""

import ast
from pathlib import Path

import pytest
import requests
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from api import aceite_dos_esquemas as aceite
from api.aceite_dos_esquemas import aceitar, codigo_de_saida
from api.decupagem import esquema_do_modelo
from api.entendimento_da_consulta import _TermoDaFoto, esquema_do_termo_da_foto
from api.gemini import MODO_STANDARD, Chamada, ErroHttp
from api.inventario import RespostaConvertida, RespostaVista, esquema_obrigatorio
from api.modelo_forte import esquema_da_resposta


class Transporte:
    def __init__(self, *respostas: str | Exception) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_manda_os_cinco_esquemas_do_codigo_com_texto_so() -> None:
    t = Transporte(*["{}"] * 5)

    resultados = aceitar(t)

    assert [c.esquema for c in t.chamadas] == [
        esquema_do_modelo(),
        esquema_obrigatorio(RespostaConvertida),
        esquema_obrigatorio(RespostaVista),
        esquema_da_resposta(),
        esquema_do_termo_da_foto(),
    ]
    assert all(c.video_uri == "" and not c.imagens for c in t.chamadas)
    assert [r.nome for r in resultados] == [
        "analise",
        "inventario_convertido",
        "inventario_visto",
        "identificacao",
        "busca_por_foto",
    ]
    assert [r.veredito for r in resultados] == ["aceito"] * 5
    assert codigo_de_saida(resultados) == 0


def test_400_e_erro_de_esquema_e_falha_mesmo_com_os_outros_passando() -> None:
    t = Transporte("{}", ErroHttp(400, "INVALID_ARGUMENT", "x"), "{}", "{}", "{}")

    resultados = aceitar(t)

    assert [r.veredito for r in resultados] == [
        "aceito",
        "recusado",
        "aceito",
        "aceito",
        "aceito",
    ]
    assert "INVALID_ARGUMENT" in resultados[1].detalhe
    assert codigo_de_saida(resultados) == 1


def test_429_e_5xx_sao_passageiros_e_nao_derrubam_o_deploy() -> None:
    t = Transporte(ErroHttp(429), ErroHttp(503), "{}", "{}", "{}")

    resultados = aceitar(t)

    assert [r.veredito for r in resultados] == [
        "passageiro",
        "passageiro",
        "aceito",
        "aceito",
        "aceito",
    ]
    assert codigo_de_saida(resultados) == 0


def test_outro_erro_nao_prova_nada_e_falha_com_codigo_proprio() -> None:
    resultados = aceitar(Transporte(ErroHttp(403), "{}", "{}", "{}", "{}"))

    assert resultados[0].veredito == "sem_prova"
    assert codigo_de_saida(resultados) == 2


def test_recusa_vale_mais_que_falta_de_prova() -> None:
    resultados = aceitar(Transporte(ErroHttp(403), ErroHttp(400), "{}", "{}", "{}"))

    assert codigo_de_saida(resultados) == 1


def test_chamadas_em_standard_e_com_prazo_curto_para_nao_segurar_o_deploy() -> None:
    t = Transporte(*["{}"] * 5)

    aceitar(t)

    assert all(c.modo == MODO_STANDARD and c.timeout_s == 60 for c in t.chamadas)


@pytest.mark.parametrize("erro", [RefreshError, DefaultCredentialsError])
def test_falha_de_autenticacao_na_sessao_da_saida_2(
    monkeypatch: pytest.MonkeyPatch, erro: type[Exception]
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")

    def sessao(**_: object) -> None:
        raise erro("falhou")

    monkeypatch.setattr(aceite, "sessao_autenticada", sessao)
    assert aceite.main() == 2


@pytest.mark.parametrize("erro", [RefreshError, requests.exceptions.Timeout])
def test_falha_de_autenticacao_ou_rede_no_meio_da_chamada_da_saida_2(
    monkeypatch: pytest.MonkeyPatch, erro: type[Exception]
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setattr(aceite, "sessao_autenticada", lambda **_: object())

    class Falho:
        def __init__(self, *_: object, **__: object) -> None: ...

        def gerar(self, chamada: Chamada) -> str:
            raise erro("falhou")

    monkeypatch.setattr(aceite, "TransporteVertex", Falho)
    assert aceite.main() == 2


def test_outra_excecao_vira_sem_prova_e_as_demais_seguem() -> None:
    t = Transporte(
        "{}",
        requests.exceptions.ConnectionError("token"),
        ValueError("json"),
        "{}",
        "{}",
    )

    resultados = aceitar(t)

    assert [r.veredito for r in resultados] == [
        "aceito",
        "sem_prova",
        "sem_prova",
        "aceito",
        "aceito",
    ]
    assert "token" in resultados[1].detalhe
    assert codigo_de_saida(resultados) == 2


def test_400_colhido_nao_se_perde_com_outra_excecao_depois(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setattr(aceite, "sessao_autenticada", lambda **_: object())
    t = Transporte(
        ErroHttp(400, "INVALID_ARGUMENT", "x"),
        requests.exceptions.Timeout("rede"),
        "{}",
        "{}",
        "{}",
    )
    monkeypatch.setattr(aceite, "TransporteVertex", lambda *_, **__: t)

    assert aceite.main() == 1


def test_esquema_do_termo_da_foto_e_o_de_hoje() -> None:
    assert esquema_do_termo_da_foto() == _TermoDaFoto.model_json_schema()


# --- guarda: todo esquema mandado ao Gemini entra no aceite ---

_PRODUTORES = {
    "esquema_do_modelo",
    "esquema_obrigatorio",
    "esquema_da_resposta",
    "esquema_do_termo_da_foto",
}
_API = Path(aceite.__file__).parent


def _chamadas_de_esquema(fonte: str) -> set[str]:
    """Cada chamada a produtor de esquema fora da definição do próprio produtor."""
    arvore = ast.parse(fonte)
    dentro: set[int] = set()
    for f in ast.walk(arvore):
        if isinstance(f, ast.FunctionDef) and f.name in _PRODUTORES:
            dentro |= {id(n) for n in ast.walk(f)}
    achadas = set()
    for n in ast.walk(arvore):
        if not isinstance(n, ast.Call) or id(n) in dentro:
            continue
        nome = (
            n.func.id
            if isinstance(n.func, ast.Name)
            else n.func.attr
            if isinstance(n.func, ast.Attribute)
            else ""
        )
        if nome in _PRODUTORES or nome == "model_json_schema":
            achadas.add(ast.unparse(n))
    return achadas


def _faltam_no_aceite(fontes: dict[str, str]) -> set[str]:
    no_aceite = _chamadas_de_esquema(fontes["aceite_dos_esquemas"])
    achadas = set()
    for modulo, fonte in fontes.items():
        if modulo != "aceite_dos_esquemas":
            achadas |= _chamadas_de_esquema(fonte)
    return achadas - no_aceite


def _fontes_de_producao() -> dict[str, str]:
    return {p.stem: p.read_text() for p in _API.glob("*.py")}


def test_todo_esquema_mandado_ao_gemini_esta_no_aceite() -> None:
    faltam = _faltam_no_aceite(_fontes_de_producao())
    assert not faltam, f"acrescente o esquema ao aceite: {sorted(faltam)}"


def test_guarda_pega_esquema_novo_em_modulo_ja_registrado() -> None:
    fontes = _fontes_de_producao()
    fontes["inventario"] += "\n_novo = esquema_obrigatorio(RespostaNova)\n"

    assert _faltam_no_aceite(fontes) == {"esquema_obrigatorio(RespostaNova)"}
