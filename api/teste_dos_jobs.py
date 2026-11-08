"""Modo de teste dos Jobs com GPU (#238): confere o dispositivo e o resultado, sem bucket.

Depois de cada publicação, o `scripts/testar-jobs-gpu.sh` roda o Job com `MODO_TESTE=1`
(uma substituição da execução, que não fica no Job). O Job lê uma amostra que já está na
imagem (`AMOSTRAS`: alguns segundos de fala e um quadro com `REDETV`), carrega o modelo
no dispositivo e confere o texto lido. Nada é lido nem gravado no Storage ou no Firestore.
A saída diz ao script o que deu errado: `SAIDA_GPU_NAO_FUNCIONOU` quando a instância não
tem GPU ou o modelo não roda nela (inclusive amostra ausente ou modelo que não carrega),
`SAIDA_RESULTADO_ERRADO` quando roda e o texto não confere.

A construção das imagens roda a mesma conferência em CPU (`exigir_gpu=False`), para
pegar a biblioteca ou o modelo quebrado antes da publicação.
"""

import logging
import os
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path

from api.dispositivo import Dispositivo, ler_dispositivo

log = logging.getLogger(__name__)

VARIAVEL = "MODO_TESTE"
PASTA_DAS_AMOSTRAS = "/amostras"
SAIDA_OK = 0
SAIDA_GPU_NAO_FUNCIONOU = 20
SAIDA_RESULTADO_ERRADO = 21

# O que a amostra diz e mostra. O Dockerfile (alvo `amostras`) fala esta frase; o teste
# confere que as duas pontas combinam.
FRASE_FALADA = "bom dia"
TEXTO_DO_QUADRO = "REDETV"
# O quadro de amostra do Florence-2 é um carro (o Dockerfile baixa a foto conferindo o hash).
OBJETO_DO_QUADRO = "car"


def ativo(ambiente: Mapping[str, str] | None = None) -> bool:
    return (os.environ if ambiente is None else ambiente).get(VARIAVEL, "") == "1"


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento nem pontuação, com um espaço entre as palavras."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    letras = "".join(c if c.isalnum() else " " for c in sem_acento.lower())
    return " ".join(letras.split())


def _conferir(
    nome: str,
    dispositivo: Dispositivo,
    exigir_gpu: bool,
    esperado: str,
    ler: Callable[[], str],
) -> int:
    try:
        if exigir_gpu and dispositivo != "gpu":
            raise RuntimeError(f"o teste pede DISPOSITIVO=gpu, e veio {dispositivo!r}")
        lido = ler()
    except Exception:
        log.exception("Teste de %s: o modelo não rodou em %s", nome, dispositivo)
        return SAIDA_GPU_NAO_FUNCIONOU
    if normalizar(esperado) not in normalizar(lido):
        log.error(
            "Teste de %s: resultado errado em %s: esperava %r e veio %r",
            nome,
            dispositivo,
            esperado,
            lido,
        )
        return SAIDA_RESULTADO_ERRADO
    log.info("Teste de %s: ok em %s (leu %r)", nome, dispositivo, lido)
    return SAIDA_OK


def testar_transcricao(
    dispositivo: Dispositivo | None = None,
    exigir_gpu: bool = True,
    ambiente: Mapping[str, str] | None = None,
) -> int:
    from api.whisper import TranscritorFasterWhisper

    ambiente = os.environ if ambiente is None else ambiente
    dispositivo = dispositivo or ler_dispositivo(ambiente)
    amostra = Path(ambiente.get("AMOSTRAS", PASTA_DAS_AMOSTRAS)) / "fala.wav"

    def ler() -> str:
        transcritor = TranscritorFasterWhisper.da_pasta(
            ambiente["PASTA_DO_MODELO"], dispositivo
        )
        return transcritor.transcrever(amostra).texto

    return _conferir("transcrição", dispositivo, exigir_gpu, FRASE_FALADA, ler)


def testar_ocr(
    dispositivo: Dispositivo | None = None,
    exigir_gpu: bool = True,
    ambiente: Mapping[str, str] | None = None,
) -> int:
    from api.paddle import LeitorPaddle

    ambiente = os.environ if ambiente is None else ambiente
    dispositivo = dispositivo or ler_dispositivo(ambiente)
    amostra = Path(ambiente.get("AMOSTRAS", PASTA_DAS_AMOSTRAS)) / "quadro.png"

    def ler() -> str:
        leitor = LeitorPaddle.da_pasta(ambiente["PASTA_DOS_MODELOS"], dispositivo)
        return " ".join(linha.texto for linha in leitor.ler(amostra))

    return _conferir("OCR", dispositivo, exigir_gpu, TEXTO_DO_QUADRO, ler)


def testar_objetos(
    dispositivo: Dispositivo | None = None,
    exigir_gpu: bool = True,
    ambiente: Mapping[str, str] | None = None,
) -> int:
    from PIL import Image

    from api.florence import DetectorFlorence, ler_configuracao

    ambiente = os.environ if ambiente is None else ambiente
    dispositivo = dispositivo or ler_dispositivo(ambiente)
    amostra = Path(ambiente.get("AMOSTRAS", PASTA_DAS_AMOSTRAS)) / "objetos.jpg"

    def ler() -> str:
        detector = DetectorFlorence.da_pasta(
            ambiente["PASTA_DO_MODELO"],
            dispositivo,
            configuracao=ler_configuracao(ambiente),
        )
        with Image.open(amostra) as foto:
            objetos, _ = detector.detectar(foto.convert("RGB"))
        return " ".join(o.rotulo for o in objetos)

    return _conferir("objetos", dispositivo, exigir_gpu, OBJETO_DO_QUADRO, ler)
