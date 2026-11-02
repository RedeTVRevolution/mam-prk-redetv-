"""`make comparar-objetos` (#244): compara os motores do inventário de objetos num Job.

Com as credenciais da pessoa, dispara o Job do Florence-2 na GPU com o destino alternativo
do resultado (a Decupagem não muda), e roda no computador dela a conversão do Florence-2 e
cada modelo do Gemini olhando os quadros-chave. Por motor, guarda numa pasta local o
inventário, os tokens, o tempo e o custo. Roda só com credenciais e fica fora do CI.

    python -m api.comparar_objetos JOB_ID PASTA

Vem do ambiente (o Makefile lê os nomes do Terraform): `GCP_PROJECT_ID`,
`BUCKET_DECUPAGENS`, `REGIAO_GPU`, `JOB_DE_OBJETOS_GPU`, `MODELOS_DA_COMPARACAO` (modelos
do Gemini separados por vírgula, o primeiro também converte o texto do Florence-2),
`PRECOS_DOS_MODELOS` (`modelo=entrada:saida`, US$ por milhão de tokens, separados por
vírgula) e, opcional, `PRECO_DA_GPU_POR_HORA` (US$ 1,05 na L4, #237).
"""

import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud.storage import Client as ClienteStorage

from api.decupagem import Decupagem
from api.florence import ObjetosDaDecupagem
from api.gemini import SessaoHttp, Transporte, TransporteVertex
from api.inventario import Inventarios, converter_do_florence, olhar_com_gemini
from api.nuvem import ObjetosStorage

PRECO_DA_GPU_POR_HORA = 1.05
ESPERA_DO_JOB_S = 30.0


class FaltaNoAmbiente(Exception):
    pass


@dataclass(frozen=True)
class Preco:
    entrada: float  # US$ por milhão de tokens
    saida: float


@dataclass(frozen=True)
class Medida:
    motor: str
    modelo: str
    tokens_de_entrada: int
    tokens_de_saida: int
    segundos: float
    segundos_na_gpu: float
    custo_usd: float


class Armazem(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def ler_resultado(
        self, job_id: str, destino: str | None = None
    ) -> ObjetosDaDecupagem | None: ...

    def ler_quadro(self, job_id: str, caminho: str) -> bytes: ...


class Disparador(Protocol):
    def rodar(self, job_id: str, destino: str) -> None:
        """Roda o Job do Florence-2 até o fim; levanta se ele falhar."""
        ...


def destino_do_florence(job_id: str) -> str:
    return f"{job_id}/objetos/comparacao-florence.json"


def precos_do_ambiente(texto: str) -> dict[str, Preco]:
    precos: dict[str, Preco] = {}
    for item in filter(None, (p.strip() for p in texto.split(","))):
        modelo, _, valores = item.partition("=")
        entrada, _, saida = valores.partition(":")
        try:
            precos[modelo] = Preco(float(entrada), float(saida))
        except ValueError as e:
            raise FaltaNoAmbiente(
                f"preço inválido em PRECOS_DOS_MODELOS: {item!r}"
            ) from e
    return precos


def _tokens(transporte: Transporte) -> tuple[int, int]:
    return (
        getattr(transporte, "tokens_de_entrada", 0),
        getattr(transporte, "tokens_de_saida", 0),
    )


def _medir(
    motor: str,
    modelo: str,
    transporte: Transporte,
    preco: Preco,
    relogio: Callable[[], float],
    segundos_na_gpu: float,
    preco_da_gpu: float,
    gerar: Callable[[], Inventarios],
) -> tuple[Inventarios, Medida]:
    entrada_antes, saida_antes = _tokens(transporte)
    inicio = relogio()
    inventarios = gerar()
    segundos = relogio() - inicio
    entrada, saida = _tokens(transporte)
    entrada -= entrada_antes
    saida -= saida_antes
    custo = (
        entrada * preco.entrada / 1e6
        + saida * preco.saida / 1e6
        + segundos_na_gpu / 3600 * preco_da_gpu
    )
    return inventarios, Medida(
        motor=motor,
        modelo=modelo,
        tokens_de_entrada=entrada,
        tokens_de_saida=saida,
        segundos=round(segundos, 2),
        segundos_na_gpu=round(segundos_na_gpu, 2),
        custo_usd=round(custo, 6),
    )


def _guardar(pasta: Path, nome: str, inventarios: Inventarios, medida: Medida) -> None:
    destino = pasta / nome
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "inventario.json").write_text(
        json.dumps(
            {
                str(i): [o.model_dump(mode="json") for o in os_]
                for i, os_ in inventarios.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (destino / "medida.json").write_text(
        json.dumps(asdict(medida), ensure_ascii=False, indent=2)
    )


def comparar(
    job_id: str,
    pasta: Path,
    *,
    armazem: Armazem,
    disparador: Disparador,
    transporte: Transporte,
    modelos: list[str],
    precos: Mapping[str, Preco],
    preco_da_gpu: float = PRECO_DA_GPU_POR_HORA,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> list[Medida]:
    """Nunca grava na Decupagem: só lê dela, do resultado alternativo e dos quadros."""
    if not modelos:
        raise FaltaNoAmbiente("MODELOS_DA_COMPARACAO está vazia")
    faltam = [m for m in modelos if m not in precos]
    if faltam:
        raise FaltaNoAmbiente(
            f"sem preço em PRECOS_DOS_MODELOS para {', '.join(faltam)}"
        )
    decupagem = armazem.ler_decupagem(job_id)
    if decupagem is None:
        raise RuntimeError(f"Não há Decupagem do Job {job_id}.")
    destino = destino_do_florence(job_id)
    inicio = relogio()
    disparador.rodar(job_id, destino)
    segundos_na_gpu = relogio() - inicio
    bruto = armazem.ler_resultado(job_id, destino)
    if bruto is None:
        raise RuntimeError("O Job do Florence-2 não gravou o resultado alternativo.")

    medidas: list[Medida] = []
    conversor = modelos[0]
    inventarios, medida = _medir(
        "florence",
        conversor,
        transporte,
        precos[conversor],
        relogio,
        segundos_na_gpu,
        preco_da_gpu,
        lambda: converter_do_florence(
            decupagem,
            bruto,
            transporte=transporte,
            modelo=conversor,
            job_id=job_id,
            dormir=dormir,
        ),
    )
    _guardar(pasta, "florence", inventarios, medida)
    medidas.append(medida)
    for modelo in modelos:
        inventarios, medida = _medir(
            "gemini",
            modelo,
            transporte,
            precos[modelo],
            relogio,
            0.0,
            preco_da_gpu,
            lambda modelo=modelo: olhar_com_gemini(  # type: ignore[misc]
                decupagem,
                transporte=transporte,
                modelo=modelo,
                job_id=job_id,
                quadro_de=lambda caminho: armazem.ler_quadro(job_id, caminho),
                dormir=dormir,
            ),
        )
        _guardar(pasta, f"gemini-{modelo}", inventarios, medida)
        medidas.append(medida)
    return medidas


class SessaoDoCloudRun(Protocol):
    def post(self, url: str, **kwargs: Any) -> Any: ...

    def get(self, url: str, **kwargs: Any) -> Any: ...


class DisparadorDoCloudRun:
    """Roda o Job com GPU pela API REST do Cloud Run, com `DESTINO_DO_RESULTADO`."""

    def __init__(
        self,
        projeto: str,
        regiao: str,
        job: str,
        sessao: SessaoDoCloudRun,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base = "https://run.googleapis.com/v2"
        self._job = f"projects/{projeto}/locations/{regiao}/jobs/{job}"
        self._sessao = sessao
        self._dormir = dormir

    def rodar(self, job_id: str, destino: str) -> None:
        corpo = {
            "overrides": {
                "containerOverrides": [
                    {
                        "env": [
                            {"name": "JOB_ID", "value": job_id},
                            {"name": "DESTINO_DO_RESULTADO", "value": destino},
                        ]
                    }
                ]
            }
        }
        resposta = self._sessao.post(f"{self._base}/{self._job}:run", json=corpo)
        resposta.raise_for_status()
        operacao: dict[str, Any] = resposta.json()
        while not operacao.get("done"):
            self._dormir(ESPERA_DO_JOB_S)
            resposta = self._sessao.get(f"{self._base}/{operacao['name']}")
            resposta.raise_for_status()
            operacao = resposta.json()
        if "error" in operacao:
            raise RuntimeError(
                f"O Job do Florence-2 falhou: {operacao['error'].get('message', '')}"
            )


def _exigir(ambiente: Mapping[str, str], nome: str) -> str:
    if not ambiente.get(nome):
        raise FaltaNoAmbiente(f"{nome} não está no ambiente")
    return ambiente[nome]


def main(argumentos: list[str], ambiente: Mapping[str, str] = os.environ) -> int:
    if len(argumentos) != 2:
        print("uso: python -m api.comparar_objetos JOB_ID PASTA", file=sys.stderr)
        return 2
    job_id, pasta = argumentos
    try:
        projeto = _exigir(ambiente, "GCP_PROJECT_ID")
        bucket = _exigir(ambiente, "BUCKET_DECUPAGENS")
        regiao = _exigir(ambiente, "REGIAO_GPU")
        job = _exigir(ambiente, "JOB_DE_OBJETOS_GPU")
        modelos = [
            m.strip() for m in _exigir(ambiente, "MODELOS_DA_COMPARACAO").split(",")
        ]
        precos = precos_do_ambiente(_exigir(ambiente, "PRECOS_DOS_MODELOS"))
        preco_da_gpu = float(
            ambiente.get("PRECO_DA_GPU_POR_HORA") or PRECO_DA_GPU_POR_HORA
        )
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao: Any = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]
    try:
        medidas = comparar(
            job_id,
            Path(pasta),
            armazem=ObjetosStorage(ClienteStorage(project=projeto), bucket),
            disparador=DisparadorDoCloudRun(projeto, regiao, job, sessao),
            transporte=TransporteVertex(projeto, cast(SessaoHttp, sessao)),
            modelos=modelos,
            precos=precos,
            preco_da_gpu=preco_da_gpu,
        )
    except (FaltaNoAmbiente, RuntimeError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    for m in medidas:
        print(
            f"{m.motor:9} {m.modelo:28} entrada={m.tokens_de_entrada} "
            f"saida={m.tokens_de_saida} tempo={m.segundos}s gpu={m.segundos_na_gpu}s "
            f"custo=US${m.custo_usd:.4f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
