"""A busca por imagem (#270, #443): a foto é entrada hostil e nunca é guardada; o modelo da
consulta dá o termo do objeto e a busca segue como se a pessoa o tivesse digitado."""

import io
import json
import logging
import tempfile
import time
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.auth import Usuario
from api.busca import Ajustes, BuscaPorImagemIndisponivel, ListasDaBuscaEmMemoria
from api.entendimento_da_consulta import MODELO_DA_CONSULTA
from api.eventos_de_uso import EventosEmMemoria
from api.gemini import ErroHttp
from api.main import criar_app
from api.rota_da_busca import LimitesDaImagem
from api.tests.test_auth import VerificadorFalso
from api.tests.test_busca import (
    AUTORIZACAO,
    Mundo,
    cliente,
    job,
    objeto,
    pedido,
)

ROTA = "/v1/busca/imagem"
# Uma resposta por foto, sem entendimento do termo.
VESTIDO = (json.dumps({"termo": "vestido"}),)


def foto(formato: str = "PNG", tamanho: tuple[int, int] = (32, 24), **kw: Any) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, (200, 30, 30)).save(saida, format=formato, **kw)
    return saida.getvalue()


def enviar(c: TestClient, dados: bytes, nome: str = "foto.jpg", **params: str) -> Any:
    return c.post(
        ROTA,
        files={"arquivo": (nome, dados, "image/jpeg")},
        params=params,
        headers=AUTORIZACAO,
    )


def com_vestido(*respostas: str | Exception, **kw: Any) -> tuple[TestClient, Mundo]:
    """Um vídeo com um vestido; sem `respostas`, o modelo descreve a foto como "vestido"."""
    return cliente(["consulta"], *(respostas or VESTIDO), **kw)


def test_png_com_extensao_jpg_e_aceito_pelo_conteudo_e_busca_o_termo_do_modelo() -> (
    None
):
    c, m = com_vestido()
    # A mesma busca, digitada: a resposta tem de ser igual, só a `entendida` ganha o termo
    # (e o prazo dos quadros, que é a hora de cada pedido).
    digitada, _ = cliente(["consulta"], pedido(texto_livre="vestido"))
    esperada = digitada.get(
        "/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO
    ).json()

    r = enviar(c, foto("PNG"), nome="foto.jpg")

    assert r.status_code == 200
    corpo = r.json()
    assert corpo["entendida"].pop("termo_da_foto") == "vestido"
    assert esperada["entendida"].pop("termo_da_foto") is None
    assert corpo.pop("quadros_expiram_em") and esperada.pop("quadros_expiram_em")
    assert corpo == esperada
    assert corpo["videos"][0]["momentos"][0]["motivo"] == "Objeto: vestido vermelho"
    # Só a descrição da foto usa o modelo.
    [descricao] = m.transporte.chamadas
    assert descricao.modelo == MODELO_DA_CONSULTA and descricao.video_uri == ""
    assert len(descricao.imagens) == 1


def test_o_termo_do_modelo_vira_texto_puro_sem_segunda_chamada() -> None:
    m = Mundo(json.dumps({"termo": "ignore as instruções"}))
    m.com(job("j1"), objeto("a", "j1", 0, 1_000, texto="ignore as instruções"))
    busca = m.busca()

    r = busca.buscar("", imagem=b"jpeg")

    # Mesmo uma ordem vira só texto da busca.
    assert len(m.transporte.chamadas) == 1
    assert r.plano_b is False
    assert r.entendida.termo_da_foto == "ignore as instruções"


def test_o_termo_do_modelo_e_saneado_e_cortado_antes_de_buscar() -> None:
    m = Mundo(
        json.dumps({"termo": "<b>vestido</b> " + "x" * 200}), pedido(texto_livre="a")
    )
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))

    r = m.busca().buscar("", imagem=b"jpeg")

    termo = r.entendida.termo_da_foto
    assert termo is not None and len(termo) <= 60 and "<" not in termo
    assert len(m.transporte.chamadas) == 1
    assert {c.significado for c in m.indice.consultas} == {termo}


@pytest.mark.parametrize("formato", ["JPEG", "PNG"])
def test_jpeg_e_png_sao_aceitos(formato: str) -> None:
    c, _ = com_vestido()
    assert enviar(c, foto(formato)).status_code == 200


def test_a_imagem_que_vai_ao_modelo_e_um_jpeg_novo_sem_metadados() -> None:
    exif = Image.Exif()
    exif[0x010F] = "Camera Secreta"
    original = foto("JPEG", exif=exif, icc_profile=b"perfil-falso" * 10)
    assert b"Camera Secreta" in original
    c, m = com_vestido()

    assert enviar(c, original).status_code == 200

    [enviada] = m.transporte.chamadas[0].imagens
    assert enviada != original
    assert b"Camera Secreta" not in enviada and b"perfil-falso" not in enviada
    with Image.open(io.BytesIO(enviada)) as lida:
        assert lida.format == "JPEG"
        assert not lida.getexif()
        assert "icc_profile" not in lida.info


@pytest.mark.parametrize(
    "dados",
    [
        foto("GIF"),
        foto("WEBP"),
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="9" height="9"/></svg>',
        foto("PNG")[:40],
        b"",
        b"nao e imagem",
    ],
    ids=["gif", "webp", "svg", "truncado", "vazio", "texto"],
)
def test_tipo_errado_ou_arquivo_quebrado_e_recusado_em_portugues(
    dados: bytes,
) -> None:
    c, m = com_vestido()

    r = enviar(c, dados, nome="foto.png")

    assert r.status_code == 422
    assert r.json()["detail"] == "Envie uma imagem JPEG ou PNG válida"
    assert m.transporte.chamadas == []


def test_imagem_acima_do_limite_de_bytes_e_recusada() -> None:
    c, m = com_vestido(limites_da_imagem=LimitesDaImagem(max_bytes=100))
    r = enviar(c, foto("PNG", (64, 64), compress_level=0))
    assert r.status_code == 422
    assert r.json()["detail"] == "A imagem passa do tamanho máximo"
    assert m.transporte.chamadas == []


def test_imagem_acima_do_limite_de_pixels_e_recusada() -> None:
    c, m = com_vestido(limites_da_imagem=LimitesDaImagem(max_pixels=100))
    r = enviar(c, foto("PNG", (20, 20)))
    assert r.status_code == 422
    assert r.json()["detail"] == "A imagem passa do tamanho máximo em pixels"
    assert m.transporte.chamadas == []


def test_os_filtros_de_programa_e_periodo_valem() -> None:
    c, m = com_vestido(*VESTIDO * 3)

    r = enviar(c, foto(), programa="Leo Dias")
    assert r.status_code == 200 and r.json()["videos"] == []
    assert {x.filtros.programa for x in m.indice.consultas} == {"Leo Dias"}

    r = enviar(c, foto(), desde="2025-01-01", ate="2025-01-02")
    assert {x.filtros.exibido_desde for x in m.indice.consultas[1:]} == {
        date(2025, 1, 1)
    }

    r = enviar(c, foto(), desde="2025-02-01", ate="2025-01-02")
    assert r.status_code == 422
    assert r.json()["detail"] == "O início do período passa do fim"


def test_sem_periodo_e_ignorado_e_nao_vira_filtro_do_evento() -> None:
    eventos = EventosEmMemoria()
    c, _ = com_vestido(*VESTIDO * 2, eventos=eventos)
    base = enviar(c, foto(), programa="Leo Dias")
    com = enviar(c, foto(), programa="Leo Dias", sem_periodo="true")

    def corpo(r: Any) -> dict[str, Any]:
        return {k: v for k, v in r.json().items() if k != "quadros_expiram_em"}

    assert com.status_code == 200 and corpo(com) == corpo(base)
    assert all(f.nome != "sem_periodo" for e in eventos.publicados for f in e.filtros)


def test_sem_decupagem_ver_responde_403_e_sem_login_401() -> None:
    c, m = cliente([], *VESTIDO)
    assert enviar(c, foto()).status_code == 403
    r = c.post(ROTA, files={"arquivo": ("a.png", foto(), "image/png")})
    assert r.status_code == 401
    assert m.transporte.chamadas == []


def test_sem_modelo_da_consulta_responde_503() -> None:
    m = Mundo()
    m.com(job("j1"), objeto("a", "j1", 0, 1_000))
    app = criar_app(
        VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
        m.jobs,
        m.armazenamento,
        indice=m.indice,
    )
    r = enviar(TestClient(app), foto())
    assert r.status_code == 503
    assert r.json()["detail"] == "A busca por imagem não está disponível agora"


@pytest.mark.parametrize(
    "falha",
    [
        ErroHttp(503),
        "isto não é json",
        json.dumps({"outro": "campo"}),
        json.dumps({"termo": "   "}),
    ],
    ids=["modelo-fora", "fora-do-json", "fora-do-esquema", "termo-vazio"],
)
def test_modelo_fora_ou_sem_objeto_na_foto_responde_503_sem_plano_b(
    falha: str | Exception,
) -> None:
    c, m = com_vestido(falha)

    r = enviar(c, foto())

    assert r.status_code == 503
    assert r.json()["detail"] == "A busca por imagem não está disponível agora"
    # Nenhum plano B: nem o entendimento nem o índice foram chamados.
    assert len(m.transporte.chamadas) == 1 and m.indice.consultas == []


def test_a_busca_por_foto_levanta_indisponivel_sem_termo() -> None:
    m = Mundo(ErroHttp(503))
    with pytest.raises(BuscaPorImagemIndisponivel):
        m.busca().buscar("", imagem=b"jpeg", ajustes=Ajustes())


def test_arquivo_ausente_responde_422() -> None:
    c, m = com_vestido()
    assert c.post(ROTA, headers=AUTORIZACAO).status_code == 422
    assert m.transporte.chamadas == []


def test_nada_e_gravado_nem_logado(caplog: pytest.LogCaptureFixture) -> None:
    c, m = com_vestido()
    dados = foto("PNG", (48, 48))

    def estado() -> tuple[Any, ...]:
        a = m.armazenamento
        return (
            dict(a.quadros),
            dict(a.decupagens),
            list(a.pedidos),
            dict(m.jobs._jobs),
            m.indice.total(),
        )

    antes = estado()
    with caplog.at_level(logging.DEBUG):
        assert enviar(c, dados, nome="segredo-da-pauta.png").status_code == 200
        assert enviar(c, b"lixo", nome="segredo-da-pauta.png").status_code == 422

    assert estado() == antes
    assert "segredo-da-pauta" not in caplog.text
    assert dados[:16].hex() not in caplog.text


def test_a_busca_por_imagem_conta_no_limite_de_consultas() -> None:
    c, _ = com_vestido(maximo_por_minuto=1)
    assert enviar(c, foto()).status_code == 200
    assert enviar(c, foto()).status_code == 429


def test_com_o_limite_esgotado_bytes_que_nao_sao_imagem_recebem_429_nao_422() -> None:
    c, _ = com_vestido(maximo_por_minuto=1)
    assert enviar(c, foto()).status_code == 200
    r = enviar(c, b"nao sou imagem")
    assert r.status_code == 429
    assert r.json()["detail"] == "Consultas demais; tente em um minuto"


def test_cursor_invalido_na_foto_responde_422() -> None:
    c, _ = com_vestido()
    r = enviar(c, foto(), cursor="nao-existe")
    assert r.status_code == 422
    assert r.json()["detail"] == "Cursor inválido"


def test_foto_que_passa_do_prazo_responde_504_com_a_mensagem_da_busca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.rota_da_busca.TEMPO_DA_CONSULTA_S", 0.0)
    from api.indice_da_busca import Consulta, IndiceEmMemoria, Registro

    class Lento(IndiceEmMemoria):
        def buscar(self, consulta: Consulta) -> list[Registro]:
            time.sleep(0.5)
            return []

    c, _ = com_vestido(tempo_maximo_s=0.05, indice=Lento())
    r = enviar(c, foto())
    assert r.status_code == 504
    assert r.json()["detail"] == "A busca demorou demais"


def test_jpeg_de_celular_que_abre_como_mpo_e_aceito() -> None:
    quadros = [Image.new("RGB", (32, 24), cor) for cor in ((200, 30, 30), (0, 0, 0))]
    saida = io.BytesIO()
    quadros[0].save(saida, format="MPO", save_all=True, append_images=quadros[1:])
    with Image.open(io.BytesIO(saida.getvalue())) as lida:
        assert lida.format == "MPO"
    c, m = com_vestido()

    assert enviar(c, saida.getvalue()).status_code == 200
    [enviada] = m.transporte.chamadas[0].imagens
    with Image.open(io.BytesIO(enviada)) as lida:
        assert lida.format == "JPEG"


def test_corpo_declarado_acima_do_teto_e_recusado_sem_ler_o_arquivo() -> None:
    c, m = com_vestido(limites_da_imagem=LimitesDaImagem(max_bytes=100))

    r = enviar(c, b"\0" * 10_000)

    assert r.status_code == 422
    assert r.json()["detail"] == "A imagem passa do tamanho máximo"
    assert m.transporte.chamadas == []


def test_a_foto_fica_em_memoria_e_nunca_vai_para_arquivo_temporario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Acima de 1 MB o multipart comum passaria a foto para um arquivo em disco.
    criados: list[int] = []
    original: Any = tempfile.SpooledTemporaryFile

    def espiao(max_size: int = 0, **kw: Any) -> Any:
        criados.append(max_size)
        return original(max_size=max_size, **kw)

    monkeypatch.setattr("starlette.formparsers.SpooledTemporaryFile", espiao)
    c, _ = com_vestido()
    grande = foto("PNG", (1024, 1024), compress_level=0)
    assert len(grande) > 1024 * 1024

    assert enviar(c, grande).status_code == 200
    assert criados and all(m > len(grande) for m in criados)


def test_sem_o_campo_arquivo_ou_com_corpo_que_nao_e_multipart_responde_422() -> None:
    c, _ = com_vestido()
    r = c.post(
        ROTA, files={"outro": ("a.png", foto(), "image/png")}, headers=AUTORIZACAO
    )
    assert r.status_code == 422
    r = c.post(ROTA, json={"arquivo": "x"}, headers=AUTORIZACAO)
    assert r.status_code == 422


def test_a_mesma_foto_pagina_pelo_cursor_sem_chamar_o_modelo_de_novo() -> None:
    c, m = com_vestido()
    m.com(job("j2"), replace(objeto("b", "j2", 0, 1_000), job_id="j2"))
    dados = foto("PNG")

    r1 = enviar(c, dados, limite="1")
    r2 = enviar(c, dados, limite="1", cursor=r1.headers["X-Proximo-Cursor"])

    assert r2.status_code == 200, r2.text
    ids = [r.json()["videos"][0]["job_id"] for r in (r1, r2)]
    assert sorted(ids) == ["j1", "j2"]
    assert "X-Proximo-Cursor" not in r2.headers
    # A 2ª página sai da lista guardada, e o termo da foto vai junto na `entendida`.
    assert len(m.transporte.chamadas) == 1
    assert r2.json()["entendida"]["termo_da_foto"] == "vestido"


def test_leitura_do_indice_que_estoura_o_prazo_do_transporte_responde_504(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O `ReadTimeout` do `batchSearch` (15 s) vira 504, não 500 (#560).
    import requests

    from api.agent_retrieval import AgentRetrieval, transporte_http
    from api.tests.test_agent_retrieval import SEM_INDICES

    class Sessao:
        def __init__(self, _: object) -> None: ...

        def mount(self, *_: object) -> None: ...

        def request(self, *_: object, **__: object) -> None:
            raise requests.exceptions.ReadTimeout("batchSearch")

    monkeypatch.setattr("google.auth.default", lambda scopes: (None, None))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Sessao)
    indice: Any = AgentRetrieval(SEM_INDICES, transporte_http())
    c, _ = com_vestido(indice=indice)

    assert enviar(c, foto("JPEG")).status_code == 504


def test_os_limites_padrao_da_imagem_vem_do_valor_unico_de_imagens_hostis() -> None:
    from api import imagens_hostis

    assert LimitesDaImagem() == LimitesDaImagem(
        max_bytes=imagens_hostis.LIMITE_DE_BYTES_DO_ORIGINAL,
        max_pixels=imagens_hostis.LIMITE_DE_PIXELS_DO_ORIGINAL,
    )
    assert (LimitesDaImagem.max_bytes, LimitesDaImagem.max_pixels) == (
        5_000_000,
        25_000_000,
    )


# --- token da foto (#802) -----------------------------------------------------------

TOKEN = "X-Token-Da-Foto"


def com_token(c: TestClient, token: str, **params: str) -> Any:
    # Um campo de texto do multipart (sem nome de arquivo), como o `FormData` da tela manda.
    return c.post(
        ROTA, files={"token": (None, token)}, params=params, headers=AUTORIZACAO
    )


def mundo_de_dois_programas(
    *respostas: str | Exception, **kw: Any
) -> tuple[TestClient, Mundo]:
    """j1 (TV Fama, 2024) e j2 (Leo Dias, 2025), os dois com um vestido."""
    c, m = com_vestido(*respostas, **kw)
    m.com(job("j1"), objeto("a", "j1", 0, 1_000, data_de_exibicao=date(2024, 5, 1)))
    m.com(
        job("j2", programa="Leo Dias", data_exibicao=date(2025, 3, 1)),
        objeto(
            "b", "j2", 0, 1_000, programa="Leo Dias", data_de_exibicao=date(2025, 3, 1)
        ),
    )
    return c, m


def ids(r: Any) -> list[str]:
    return [v["job_id"] for v in r.json()["videos"]]


def sem_o_prazo(corpo: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in corpo.items() if k != "quadros_expiram_em"}


def test_a_troca_de_programa_e_de_ano_pelo_token_nao_chama_o_modelo() -> None:
    c, m = mundo_de_dois_programas()
    dados = foto("PNG")
    primeira = enviar(c, dados)
    token = primeira.headers[TOKEN]
    assert sorted(ids(primeira)) == ["j1", "j2"]
    chamadas = len(m.transporte.chamadas)

    for filtros in (
        {"programa": "Leo Dias"},
        {"programa": "TV Fama"},
        {"desde": "2025-01-01", "ate": "2025-12-31"},
        {"desde": "2024-01-01", "ate": "2024-12-31"},
    ):
        pelo_token = com_token(c, token, **filtros)
        assert pelo_token.status_code == 200, pelo_token.text
        assert len(ids(pelo_token)) == 1
        assert pelo_token.json()["entendida"]["termo_da_foto"] == "vestido"
        assert TOKEN not in pelo_token.headers
        # A mesma troca pela foto devolve o mesmo (o modelo responde "vestido" de novo).
        m.transporte.respostas.extend(VESTIDO)
        pela_foto = enviar(c, dados, **filtros)
        assert sem_o_prazo(pelo_token.json()) == sem_o_prazo(pela_foto.json())
        chamadas += 1

    # Só as quatro conferências pela foto chamaram o modelo; as trocas pelo token, não.
    assert len(m.transporte.chamadas) == chamadas


def com_listas(*respostas: str | Exception, **kw: Any) -> tuple[TestClient, Mundo, Any]:
    listas = ListasDaBuscaEmMemoria()
    c, m = mundo_de_dois_programas(*respostas, listas_da_busca=listas, **kw)
    return c, m, listas


def test_a_pagina_seguinte_pelo_token_traz_os_mesmos_videos_que_pela_foto() -> None:
    c, m, _ = com_listas()
    dados = foto("PNG")
    primeira = enviar(c, dados, limite="1")
    token, cursor = primeira.headers[TOKEN], primeira.headers["X-Proximo-Cursor"]

    pelo_token = com_token(c, token, limite="1", cursor=cursor)
    pela_foto = enviar(c, dados, limite="1", cursor=cursor)

    assert pelo_token.status_code == 200, pelo_token.text
    assert sem_o_prazo(pelo_token.json()) == sem_o_prazo(pela_foto.json())
    assert sorted(ids(primeira) + ids(pelo_token)) == ["j1", "j2"]
    assert len(m.transporte.chamadas) == 1


def test_o_cursor_da_1a_pagina_feita_pelo_token_vale_na_pagina_2() -> None:
    c, m, _ = com_listas()
    token = enviar(c, foto("PNG"), limite="2").headers[TOKEN]
    # Um programa só: a lista nova tem um vídeo por vez.
    m.com(job("j3"), objeto("c", "j3", 0, 1_000))

    primeira = com_token(c, token, limite="1", programa="TV Fama")
    segunda = com_token(
        c,
        token,
        limite="1",
        programa="TV Fama",
        cursor=primeira.headers["X-Proximo-Cursor"],
    )

    assert segunda.status_code == 200, segunda.text
    assert sorted(ids(primeira) + ids(segunda)) == ["j1", "j3"]
    assert len(m.transporte.chamadas) == 1


def test_a_troca_pelo_token_e_busca_nova_por_imagem_e_a_pagina_nao() -> None:
    eventos = EventosEmMemoria()
    c, _, _ = com_listas(eventos=eventos)
    primeira = enviar(c, foto("PNG"), limite="1")
    token, cursor = primeira.headers[TOKEN], primeira.headers["X-Proximo-Cursor"]
    assert len(eventos.publicados) == 1

    com_token(c, token, programa="Leo Dias")
    assert len(eventos.publicados) == 2
    nova = eventos.publicados[-1]
    assert nova.tamanho_da_consulta is None
    assert nova.programa == "Leo Dias"
    assert {(f.nome, f.valor) for f in nova.filtros} == {("modo", "imagem")}

    com_token(c, token, limite="1", cursor=cursor)
    assert len(eventos.publicados) == 2


@pytest.mark.parametrize(
    "falha", ["inexistente", "vencido", "de-outro-dono", "de-lista", "formato"]
)
def test_token_que_nao_vale_responde_422_do_token(falha: str) -> None:
    c, _, listas = com_listas()
    primeira = enviar(c, foto("PNG"), limite="1")
    token = primeira.headers[TOKEN]
    if falha == "inexistente":
        token = "0" * 20
    elif falha == "vencido":
        listas.documentos[token]["expira_em"] = datetime(2000, 1, 1, tzinfo=UTC)
    elif falha == "de-outro-dono":
        listas.documentos[token]["dono"] = "u2"
    elif falha == "de-lista":
        token = primeira.headers["X-Proximo-Cursor"].partition(".")[0]
    else:
        token = "a/b"

    r = com_token(c, token)

    assert r.status_code == 422
    assert r.json()["detail"] == "Token da foto inválido"


def test_token_vencido_com_a_lista_do_cursor_valida_da_o_422_do_token() -> None:
    c, _, listas = com_listas()
    primeira = enviar(c, foto("PNG"), limite="1")
    token, cursor = primeira.headers[TOKEN], primeira.headers["X-Proximo-Cursor"]
    listas.documentos[token]["expira_em"] = datetime.now(UTC) - timedelta(seconds=1)

    r = com_token(c, token, limite="1", cursor=cursor)

    assert r.status_code == 422
    assert r.json()["detail"] == "Token da foto inválido"


def test_token_valido_com_cursor_recusado_da_cursor_invalido() -> None:
    c, _, _ = com_listas()
    token = enviar(c, foto("PNG")).headers[TOKEN]

    r = com_token(c, token, cursor="0" * 20 + ".1")

    assert r.status_code == 422
    assert r.json()["detail"] == "Cursor inválido"


def test_o_id_de_um_token_usado_como_cursor_da_cursor_invalido() -> None:
    c, _, _ = com_listas()
    token = enviar(c, foto("PNG"), limite="1").headers[TOKEN]

    for cursor in (token, f"{token}.1"):
        r = enviar(c, foto("PNG"), limite="1", cursor=cursor)
        assert r.status_code == 422
        assert r.json()["detail"] == "Cursor inválido"


@pytest.mark.parametrize("campos", ["os-dois", "nenhum"])
def test_arquivo_e_token_juntos_ou_nenhum_dos_dois_dao_422(campos: str) -> None:
    c, m, _ = com_listas()
    token = enviar(c, foto("PNG")).headers[TOKEN]
    arquivos: dict[str, Any] = {"arquivo": ("a.png", foto("PNG"), "image/png")}
    if campos == "os-dois":
        arquivos["token"] = (None, token)
    else:
        arquivos = {"outro": (None, "x")}
    chamadas = len(m.transporte.chamadas)

    r = c.post(ROTA, files=arquivos, headers=AUTORIZACAO)

    assert r.status_code == 422
    assert len(m.transporte.chamadas) == chamadas


def test_acima_da_cota_o_token_responde_429_sem_ler_o_firestore() -> None:
    class Contada(ListasDaBuscaEmMemoria):
        leituras = 0

        def ler(self, id: str) -> Any:
            self.leituras += 1
            return super().ler(id)

    listas = Contada()
    c, _ = mundo_de_dois_programas(listas_da_busca=listas, maximo_por_minuto=1)
    token = enviar(c, foto("PNG")).headers[TOKEN]

    r = com_token(c, token)

    assert r.status_code == 429
    assert listas.leituras == 0


def test_com_o_token_a_foto_nao_e_recodificada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _, _ = com_listas()
    token = enviar(c, foto("PNG")).headers[TOKEN]

    def proibida(*_: Any, **__: Any) -> Any:
        raise AssertionError("recodificou")

    monkeypatch.setattr("api.rota_da_busca.recodificar", proibida)

    assert com_token(c, token, programa="Leo Dias").status_code == 200


def test_o_documento_do_token_so_tem_dono_termo_hash_criacao_e_vencimento() -> None:
    c, _, listas = com_listas()
    dados = foto("PNG", (48, 48))

    token = enviar(c, dados).headers[TOKEN]

    [documento] = listas.documentos.values()
    assert set(documento) == {"dono", "termo", "hash", "criado_em", "expira_em"}
    assert documento["dono"] == "u1" and documento["termo"] == "vestido"
    assert len(documento["hash"]) == 64
    assert documento["expira_em"] - documento["criado_em"] == timedelta(minutes=15)
    assert token in listas.documentos
    assert dados not in [v for v in documento.values() if isinstance(v, bytes)]
