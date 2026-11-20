"""`api.criar_colecao_da_busca` (#757): a conta que impersona e o que cria, sem nuvem."""

from dataclasses import replace
from functools import partial
from typing import Any

import pytest

from api import agent_retrieval, criar_colecao_da_busca
from api.agent_retrieval import ConfigDaBusca, JaExiste, esquema_da_colecao

AMBIENTE = {
    "GCP_PROJECT_ID": "proj-x",
    "BUSCA_REGIAO": "reg-y",
    "BUSCA_COLECAO": "col-z",
    "BUSCA_COLECAO_DE_TEXTO": "col-texto",
    "BUSCA_INDICE_DESCRICAO": "ind-d",
    "BUSCA_DIMENSAO": "256",
    "BUSCA_INDICES_LIGADOS": "true",
}
CONFIG = ConfigDaBusca.do_ambiente(AMBIENTE)
CONTA = "mam-terraform@proj-x.iam.gserviceaccount.com"


class NuvemFalsa:
    """Coleções e índices em memória; só o que a ferramenta chama."""

    def __init__(self, colecoes: dict[str, dict[str, Any]] | None = None) -> None:
        self.colecoes = colecoes or {}
        self.indices: list[str] = []
        self.chamadas: list[tuple[str, str]] = []

    def __call__(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> dict[str, Any]:
        self.chamadas.append((metodo, caminho))
        nome = caminho.split("?")[0].rsplit("/", 1)[-1]
        if metodo == "POST" and "/indexes" in caminho:
            indice = caminho.split("indexId=")[1]
            if indice in self.indices:
                raise JaExiste(caminho)
            self.indices.append(indice)
        elif metodo == "POST":
            nome = caminho.split("collectionId=")[1]
            if nome in self.colecoes:
                raise JaExiste(caminho)
            assert corpo is not None
            self.colecoes[nome] = corpo
        elif metodo == "PATCH":
            assert corpo is not None
            self.colecoes[nome] = corpo
        elif metodo == "GET" and "/indexes/" in caminho:
            return {}
        elif metodo == "GET":
            return self.colecoes[nome]
        return {"name": "op", "done": True}


@pytest.fixture
def rodar(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _rodar(nuvem: NuvemFalsa, *argv: str, **extra: str) -> list[dict[str, Any]]:
        pedidos: list[dict[str, Any]] = []

        def transporte(**kwargs: Any) -> NuvemFalsa:
            pedidos.append(kwargs)
            return nuvem

        monkeypatch.setattr(criar_colecao_da_busca, "transporte_http", transporte)
        for nome, valor in {**AMBIENTE, **extra}.items():
            monkeypatch.setenv(nome, valor)
        criar_colecao_da_busca.main(list(argv))
        return pedidos

    return _rodar


def test_impersona_a_conta_pedida(rodar: Any) -> None:
    pedidos = rodar(NuvemFalsa(), "--personificar", CONTA)
    assert pedidos == [{"personificar": CONTA}]


def test_sem_o_argumento_ignora_a_variavel_do_arquivo_de_ambiente(
    rodar: Any,
) -> None:
    # O alvo manual do Makefile carrega o .env, que traz a conta do dev: segue como hoje.
    pedidos = rodar(NuvemFalsa(), GOOGLE_IMPERSONATE_SERVICE_ACCOUNT="dev@x")
    assert pedidos == [{}]


def test_o_transporte_entrega_a_conta_a_sessao_autenticada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pedidos: list[dict[str, Any]] = []

    def sessao(**kwargs: Any) -> Any:
        pedidos.append(kwargs)
        return object()

    monkeypatch.setattr(agent_retrieval, "sessao_autenticada", sessao)
    monkeypatch.setattr(agent_retrieval, "com_pool", lambda s, _n: s)
    agent_retrieval.transporte_http(personificar=CONTA)
    assert pedidos == [{"personificar": CONTA}]


def test_ambiente_vazio_cria_as_colecoes_e_o_indice(
    rodar: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    nuvem = NuvemFalsa()
    rodar(nuvem)
    assert set(nuvem.colecoes) == {"col-z", "col-texto"}
    assert nuvem.indices == ["ind-d"]
    assert "Coleções e índice da busca prontos." in capsys.readouterr().out


def test_colecao_existente_sem_um_campo_ganha_o_campo_sem_ser_recriada(
    rodar: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    completo = esquema_da_colecao(CONFIG)
    texto = esquema_da_colecao(replace(CONFIG, colecao="col-texto"))
    propriedades = dict(completo["dataSchema"]["properties"])
    falta = list(propriedades)[-1]
    del propriedades[falta]
    incompleto = {"dataSchema": {"type": "object", "properties": propriedades}}
    nuvem = NuvemFalsa({"col-z": incompleto, "col-texto": texto})
    rodar(nuvem)
    patches = [c for m, c in nuvem.chamadas if m == "PATCH"]
    assert patches == [f"{CONFIG.caminho_da_colecao}?updateMask=dataSchema"]
    assert falta in nuvem.colecoes["col-z"]["dataSchema"]["properties"]
    saida = capsys.readouterr().out
    assert falta in saida and "make reindexar" in saida


def test_esquema_incompativel_para_com_a_causa(rodar: Any) -> None:
    completo = esquema_da_colecao(CONFIG)
    propriedades = {
        **completo["dataSchema"]["properties"],
        "campo_velho": {"type": "string"},
    }
    sobra = {"dataSchema": {"type": "object", "properties": propriedades}}
    with pytest.raises(SystemExit) as erro:
        rodar(NuvemFalsa({"col-z": sobra}))
    assert "campo_velho" in str(erro.value)


def test_o_aviso_de_reindexar_sai_logo_apos_o_patch_mesmo_se_o_indice_falha(
    rodar: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    completo = esquema_da_colecao(CONFIG)
    texto = esquema_da_colecao(replace(CONFIG, colecao="col-texto"))
    propriedades = dict(completo["dataSchema"]["properties"])
    falta = list(propriedades)[-1]
    del propriedades[falta]
    incompleto = {"dataSchema": {"type": "object", "properties": propriedades}}

    class IndiceFalha(NuvemFalsa):
        def __call__(self, metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
            if metodo == "POST" and "/indexes" in caminho:
                raise RuntimeError("429 cota")
            return super().__call__(metodo, caminho, corpo)

    with pytest.raises(RuntimeError):
        rodar(IndiceFalha({"col-z": incompleto, "col-texto": texto}))
    saida = capsys.readouterr().out
    assert falta in saida and "make reindexar" in saida


class SemPapelAinda(NuvemFalsa):
    """O papel recém-concedido pelo apply ainda não propagou nas `falhas` primeiras chamadas."""

    def __init__(self, falhas: int) -> None:
        super().__init__()
        self.falhas = falhas

    def __call__(self, metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        if self.falhas:
            self.falhas -= 1
            raise RuntimeError(f"{metodo} {caminho}: HTTP 403: IAM_PERMISSION_DENIED")
        return super().__call__(metodo, caminho, corpo)


@pytest.fixture
def esperas(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    feitas: list[float] = []
    monkeypatch.setattr(criar_colecao_da_busca, "sleep", feitas.append)
    return feitas


def test_no_deploy_espera_o_papel_novo_propagar(
    rodar: Any, esperas: list[float]
) -> None:
    nuvem = SemPapelAinda(falhas=2)
    rodar(nuvem, "--personificar", CONTA)
    assert set(nuvem.colecoes) == {"col-z", "col-texto"}
    assert len(esperas) == 2


def test_no_deploy_desiste_depois_do_teto_da_propagacao(
    rodar: Any, esperas: list[float]
) -> None:
    with pytest.raises(RuntimeError, match="HTTP 403"):
        rodar(SemPapelAinda(falhas=1000), "--personificar", CONTA)
    # O IAM leva até 7 min para propagar um papel novo.
    assert 7 * 60 <= sum(esperas) <= 10 * 60


def test_fora_do_deploy_o_403_falha_na_hora(rodar: Any, esperas: list[float]) -> None:
    with pytest.raises(RuntimeError, match="HTTP 403"):
        rodar(SemPapelAinda(falhas=1))
    assert esperas == []


def test_outro_erro_nao_espera(rodar: Any, esperas: list[float]) -> None:
    class Quebrada(NuvemFalsa):
        def __call__(self, metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
            raise RuntimeError("HTTP 400: esquema recusado")

    with pytest.raises(RuntimeError, match="HTTP 400"):
        rodar(Quebrada(), "--personificar", CONTA)
    assert esperas == []


def test_o_403_na_operacao_aceita_repete_so_a_consulta_e_o_aviso_sai(
    rodar: Any,
    esperas: list[float],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """O PATCH é aceito e a primeira consulta da operação recebe 403: repetir a criação
    inteira acharia o campo já no esquema e perderia o aviso de reindexação."""
    completo = esquema_da_colecao(CONFIG)
    texto = esquema_da_colecao(replace(CONFIG, colecao="col-texto"))
    propriedades = dict(completo["dataSchema"]["properties"])
    falta = list(propriedades)[-1]
    del propriedades[falta]
    incompleto = {"dataSchema": {"type": "object", "properties": propriedades}}

    class OperacaoSemPapel(NuvemFalsa):
        negadas = 1

        def __call__(self, metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
            if caminho == "op-patch":
                if self.negadas:
                    self.negadas -= 1
                    raise RuntimeError("GET op-patch: HTTP 403: IAM_PERMISSION_DENIED")
                return {"name": "op-patch", "done": True}
            resposta = super().__call__(metodo, caminho, corpo)
            return (
                {"name": "op-patch", "done": False} if metodo == "PATCH" else resposta
            )

    monkeypatch.setattr(
        criar_colecao_da_busca,
        "criar_colecao",
        partial(agent_retrieval.criar_colecao, dormir=lambda _s: None),
    )
    rodar(
        OperacaoSemPapel({"col-z": incompleto, "col-texto": texto}),
        "--personificar",
        CONTA,
    )
    assert len(esperas) == 1
    assert "make reindexar" in capsys.readouterr().out
