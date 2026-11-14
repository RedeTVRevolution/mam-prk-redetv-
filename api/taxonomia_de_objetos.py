"""A lista fechada de tipos de objeto (#544), lida de `taxonomia_de_objetos.json`.

Só lê o arquivo: não importa mais nada de `api/`, porque `decupagem.py` a usa para o texto das
instruções (o esquema não leva o enum, #617) e o `comparador.py` importa `decupagem.py`. O dicionário de nome livre para tipo e as
chaves de junção estão em `api/tipo_do_objeto.py`.
"""

import json
from pathlib import Path
from typing import Any

OUTRO = "outro"  # nenhum tipo da lista serve: não é identidade, a chave é o nome


def _ler() -> list[dict[str, Any]]:
    dados = json.loads(
        (Path(__file__).with_name("taxonomia_de_objetos.json")).read_text("utf-8")
    )
    return list(dados["tipos"])


TAXONOMIA: list[dict[str, Any]] = _ler()
TIPOS_CANONICOS: tuple[str, ...] = tuple(t["tipo"] for t in TAXONOMIA)
CATEGORIA_DO_TIPO: dict[str, str] = {t["tipo"]: t["categoria"] for t in TAXONOMIA}
SINONIMOS_DO_TIPO: dict[str, list[str]] = {
    t["tipo"]: list(t["sinonimos"]) for t in TAXONOMIA
}
# Para o texto das instruções: o esquema não leva o enum, o Vertex recusa (#617).
TEXTO_DOS_TIPOS: str = ", ".join(TIPOS_CANONICOS)
