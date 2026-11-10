"""Job em CPU do inventário de objetos (#244): lê, converte e grava na Decupagem."""

import io
import json
from typing import Any

import pytest
from google.api_core.exceptions import NotFound
from PIL import Image

from api import inventario_job
from api.decupagem import Decupagem
from api.florence import ObjetoDetectado, ObjetosDaDecupagem, QuadroDetectado
from api.gemini import AnaliseFalhou
from api.inventario_job import ConfigDoInventario, config_do_ambiente, executar
from api.leitura_da_tela import Caixa
from api.nuvem import ObjetosStorage
from api.tests.test_gemini import TransporteFalso
from api.tests.test_inventario import decupagem as decupagem_com_planos


class Armazem:
    def __init__(self) -> None:
        self.decupagens: dict[str, Decupagem] = {}
        self.resultados: dict[tuple[str, str | None], ObjetosDaDecupagem] = {}
        self.quadros: dict[str, bytes] = {}
        self.gravadas: list[tuple[str, str]] = []

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return self.decupagens.get(job_id)

    def ler_resultado(
        self, job_id: str, destino: str | None = None
    ) -> ObjetosDaDecupagem | None:
        return self.resultados.get((job_id, destino))

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return self.quadros[caminho]

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self.gravadas.append((job_id, conteudo))


def _bruto() -> ObjetosDaDecupagem:
    return ObjetosDaDecupagem(
        modelo="m",
        quadros=[
            QuadroDetectado(
                plano=0,
                caminho="q/a.jpg",
                largura=10,
                altura=10,
                objetos=[
                    ObjetoDetectado(
                        rotulo="chair",
                        caixa=Caixa(x=0.3, y=0.3, largura=0.4, altura=0.4),
                    )
                ],
                regioes=[],
            )
        ],
    )


def _armazem() -> Armazem:
    a = Armazem()
    a.decupagens["j1"] = decupagem_com_planos(["q/a.jpg"])
    a.resultados[("j1", None)] = _bruto()
    a.quadros["q/a.jpg"] = b"jpeg"
    return a


def _florence(destino: str | None = None) -> ConfigDoInventario:
    return ConfigDoInventario(
        motor="florence", modelo="gemini-x", destino_do_bruto=destino
    )


CONVERTIDO = json.dumps(
    {
        "planos": [
            {
                "plano": 0,
                "objetos": [
                    {
                        "nome": "cadeira",
                        "categoria": "movel",
                        "cor": None,
                        "marca": None,
                        "deteccoes": ["p0q0o0"],
                    }
                ],
            }
        ]
    }
)
VISTO = json.dumps(
    {
        "planos": [
            {
                "plano": 0,
                "objetos": [
                    {
                        "nome": "cadeira",
                        "categoria": "movel",
                        "cor": "marrom",
                        "marca": None,
                        "caixas": [
                            {
                                "quadro": 0,
                                "x": 0.3,
                                "y": 0.3,
                                "largura": 0.4,
                                "altura": 0.4,
                            }
                        ],
                    }
                ],
            }
        ]
    }
)


def test_motor_florence_grava_a_decupagem_com_o_inventario_em_portugues() -> None:
    armazem = _armazem()
    transporte = TransporteFalso(CONVERTIDO)

    executar("j1", armazem, transporte, _florence())

    ((job, conteudo),) = armazem.gravadas
    gravada = Decupagem.model_validate_json(conteudo)
    assert job == "j1"
    assert gravada.planos[0].inventario[0].nome == "cadeira"
    assert gravada.inventario_gerado_por is not None
    assert gravada.inventario_gerado_por.model_dump() == {
        "motor": "florence",
        "modelo": "gemini-x",
    }
    assert transporte.chamadas[0].imagens == ()
    assert "chair" not in conteudo


def test_o_resto_da_decupagem_nao_muda() -> None:
    armazem = _armazem()
    antes = armazem.decupagens["j1"]

    executar("j1", armazem, TransporteFalso(CONVERTIDO), _florence())

    gravada = Decupagem.model_validate_json(armazem.gravadas[0][1])
    assert gravada.model_copy(update={"planos": [], "inventario_gerado_por": None}) == (
        antes.model_copy(update={"planos": []})
    )


def test_o_destino_alternativo_do_bruto_e_lido_quando_configurado() -> None:
    armazem = _armazem()
    armazem.resultados = {("j1", "alt.json"): _bruto()}

    executar("j1", armazem, TransporteFalso(CONVERTIDO), _florence("alt.json"))

    assert len(armazem.gravadas) == 1


def test_motor_gemini_manda_os_quadros_e_nao_le_o_bruto() -> None:
    armazem = _armazem()
    armazem.resultados = {}
    transporte = TransporteFalso(VISTO)

    executar(
        "j1",
        armazem,
        transporte,
        ConfigDoInventario(motor="gemini", modelo="gemini-3.8-flash"),
    )

    assert transporte.chamadas[0].imagens == (b"jpeg",)
    assert transporte.chamadas[0].modelo == "gemini-3.8-flash"
    gravada = Decupagem.model_validate_json(armazem.gravadas[0][1])
    assert gravada.planos[0].inventario[0].cor == "marrom"
    assert gravada.inventario_gerado_por is not None
    assert gravada.inventario_gerado_por.motor == "gemini"


def test_o_job_grava_o_grupo_dos_planos_recorrentes_pelos_quadros_chave() -> None:
    imagem = io.BytesIO()
    Image.new("RGB", (32, 32), "gray").save(imagem, "PNG")
    armazem = Armazem()
    armazem.decupagens["j1"] = decupagem_com_planos(["q/a.jpg"], ["q/b.jpg"])
    armazem.quadros = {"q/a.jpg": imagem.getvalue(), "q/b.jpg": imagem.getvalue()}

    executar(
        "j1",
        armazem,
        TransporteFalso(json.dumps({"planos": []})),
        ConfigDoInventario(motor="gemini", modelo="gemini-x"),
    )

    gravada = Decupagem.model_validate_json(armazem.gravadas[0][1])
    assert [p.plano_recorrente for p in gravada.planos] == ["rec01", "rec01"]


def test_sem_a_decupagem_falha_com_mensagem_clara() -> None:
    armazem = _armazem()
    armazem.decupagens = {}

    with pytest.raises(RuntimeError, match="Decupagem"):
        executar("j1", armazem, TransporteFalso(), _florence())


def test_sem_o_resultado_do_florence_falha_e_nao_grava() -> None:
    armazem = _armazem()
    armazem.resultados = {}

    with pytest.raises(RuntimeError, match="Florence"):
        executar("j1", armazem, TransporteFalso(), _florence())

    assert armazem.gravadas == []


def test_falha_da_conversao_sobe_e_nao_grava() -> None:
    armazem = _armazem()

    with pytest.raises(AnaliseFalhou):
        executar(
            "j1",
            armazem,
            TransporteFalso(*(["lixo"] * 10)),
            _florence(),
            dormir=lambda s: None,
        )

    assert armazem.gravadas == []


def test_config_do_ambiente_padrao_e_florence_com_o_flash_lite() -> None:
    config = config_do_ambiente({"MODELO_OBJETOS": "gemini-flash-lite-x"})

    assert config == ConfigDoInventario(
        motor="florence", modelo="gemini-flash-lite-x", destino_do_bruto=None
    )


def test_config_do_ambiente_le_o_motor_e_o_destino() -> None:
    config = config_do_ambiente(
        {
            "MOTOR_OBJETOS": "gemini",
            "MODELO_OBJETOS": "m",
            "DESTINO_DO_RESULTADO": "a.json",
        }
    )

    assert (config.motor, config.modelo, config.destino_do_bruto) == (
        "gemini",
        "m",
        "a.json",
    )


def test_motor_desconhecido_e_erro() -> None:
    with pytest.raises(ValueError, match="motor"):
        config_do_ambiente({"MOTOR_OBJETOS": "gpt", "MODELO_OBJETOS": "m"})


def test_modelo_obrigatorio() -> None:
    with pytest.raises(KeyError):
        config_do_ambiente({})


class _Blob:
    def __init__(self, guardado: dict[str, Any], nome: str) -> None:
        self.guardado, self.nome = guardado, nome

    def upload_from_string(self, conteudo: str, content_type: str) -> None:
        self.guardado[self.nome] = (conteudo, content_type)

    def download_as_bytes(self) -> bytes:
        if self.nome not in self.guardado:
            raise NotFound("não há")  # type: ignore[no-untyped-call]
        conteudo = self.guardado[self.nome]
        return conteudo[0].encode() if isinstance(conteudo, tuple) else bytes(conteudo)


class _Bucket:
    def __init__(self, nome: str, guardado: dict[str, Any]) -> None:
        self.nome, self.guardado = nome, guardado

    def blob(self, nome: str) -> _Blob:
        return _Blob(self.guardado, f"{self.nome}/{nome}")


class _Cliente:
    def __init__(self) -> None:
        self.guardado: dict[str, Any] = {}

    def bucket(self, nome: str) -> _Bucket:
        return _Bucket(nome, self.guardado)


def test_o_storage_le_o_resultado_e_regrava_a_decupagem_no_bucket_das_decupagens() -> (
    None
):
    cliente = _Cliente()
    armazenamento = ObjetosStorage(cliente, "decupagens-x")
    bruto = _bruto()
    assert armazenamento.ler_resultado("j1") is None
    cliente.guardado["decupagens-x/j1/objetos/florence.json"] = (
        bruto.model_dump_json(),
        "application/json",
    )
    cliente.guardado["decupagens-x/alt.json"] = (
        bruto.model_dump_json(),
        "application/json",
    )

    assert armazenamento.ler_resultado("j1") == bruto
    assert armazenamento.ler_resultado("j1", "alt.json") == bruto
    armazenamento.gravar_decupagem("j1", "{}")
    assert cliente.guardado["decupagens-x/j1.json"] == ("{}", "application/json")


def test_main_exige_o_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    for variavel in ("GCP_PROJECT_ID", "JOB_ID", "BUCKET_DECUPAGENS", "MODELO_OBJETOS"):
        monkeypatch.delenv(variavel, raising=False)

    with pytest.raises(KeyError):
        inventario_job.main()
