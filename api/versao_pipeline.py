"""A versão fixa do pipeline (#250): o único lugar que a define.

A `VERSAO_PIPELINE` é um nome curto; o manifesto diz o que ela fixa: o modelo de cada
etapa, o hash de cada instrução, a versão do esquema e os motores de transcrição, OCR e
objetos. Cada decupagem nova grava os dois (`api/analise.py`); a antiga, sem o campo, é
lida como "anterior à versão". `api/tests/test_versao_pipeline.py` falha quando o
manifesto muda sem a versão mudar. Trocar a versão é o que permite reprocessar o acervo
de propósito (`make reprocessar-versao`).
"""

import hashlib
from typing import Any

from api import (
    entendimento_da_consulta,
    florence,
    gemini,
    inventario,
    modelo_forte,
    paddle,
    whisper,
)
from api.agent_retrieval import MODELO_DO_EMBEDDING
from api.decupagem import VERSAO_ESQUEMA

VERSAO_PIPELINE = "2026.11.3"


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def manifesto() -> dict[str, Any]:
    return {
        "esquema": VERSAO_ESQUEMA,
        "modelos": {
            "analise": gemini.MODELO,
            "versao_do_modelo_da_analise": gemini.VERSAO_DO_MODELO,
            "modelo_forte": modelo_forte.MODELO_FORTE,
            "consulta": entendimento_da_consulta.MODELO_DA_CONSULTA,
            "embedding": MODELO_DO_EMBEDDING,
        },
        # O modo de cobrança faz parte do pipeline (#402): Flex em tudo, menos a identificação.
        "modos": {
            "analise": gemini.MODO_FLEX,
            "inventario": gemini.MODO_FLEX,
            "modelo_forte": gemini.MODO_STANDARD,
            "consulta": gemini.MODO_STANDARD,
        },
        "instrucoes": {
            "analise": _hash(gemini.INSTRUCAO),
            "modelo_forte": _hash(modelo_forte.INSTRUCAO),
            "consulta": _hash(entendimento_da_consulta.INSTRUCAO),
            "conversao_do_inventario": _hash(inventario.INSTRUCAO_DA_CONVERSAO),
            "olhar_do_inventario": _hash(inventario.INSTRUCAO_DO_OLHAR),
        },
        "motores": {
            "transcricao": {
                "motor": "faster-whisper",
                "modelo": whisper.NOME_DO_MODELO,
                "idioma": whisper.IDIOMA,
                "vad": whisper.VAD_PARAMETROS,
            },
            "ocr": {
                "motor": "paddleocr",
                "detector": paddle.DETECTOR,
                "reconhecedor": paddle.RECONHECEDOR,
            },
            # O padrão do Florence-2; o Job do inventário troca `motor` e `modelo` pelos
            # do ambiente (`MOTOR_OBJETOS`, `MODELO_OBJETOS`) ao gravar (`aplicar_inventario`).
            "objetos": {
                "motor": "florence",
                "modelo": None,
                "florence": florence.NOME_DO_MODELO,
                "tarefas": [florence.DETECCAO, florence.REGIOES],
                "geracao": florence.GERACAO,
            },
        },
    }
