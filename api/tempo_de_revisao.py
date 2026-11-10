"""Lista o tempo de revisão por vídeo e por pessoa, em CSV (#251): `make tempo-de-revisao`.

Argumento: `DESDE` (data ou data e hora ISO, em UTC se sem fuso): só as medidas com pulso de
então em diante. Os minutos de cada linha são o total acumulado do vídeo e da pessoa, não só os
de depois de `DESDE`. Ambiente: `GCP_PROJECT_ID`.
"""

import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from api.bancos import cliente_do_firestore
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.nuvem import RepositorioDeRevisaoFirestore
from api.revisao import RepositorioDeRevisao, relatorio_em_csv

__all__ = ["listar", "main"]


def listar(
    revisao: RepositorioDeRevisao,
    desde: datetime | None = None,
    escrever: Callable[[str], None] = print,
) -> None:
    escrever(relatorio_em_csv(revisao.todas(desde)).rstrip("\n"))


def _desde(texto: str) -> datetime:
    quando = datetime.fromisoformat(texto)
    return quando if quando.tzinfo else quando.replace(tzinfo=UTC)


def main(argumentos: list[str], ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        desde = _desde(argumentos[0]) if argumentos and argumentos[0] else None
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    listar(RepositorioDeRevisaoFirestore(cliente_do_firestore(projeto)), desde)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
