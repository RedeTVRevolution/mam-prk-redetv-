"""Log em JSON, uma linha por registro (#475).

O texto de quem usa (consulta, nome, correção) vai como argumento do registro (`%s`), nunca
montado com f-string, e sai dentro do campo `message` do JSON, com a quebra de linha
escapada pelo `json.dumps`. Assim um texto com `\\n` não forja outra linha de log.
"""

import json
import logging
from typing import Any


class FormatadorJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        campos: dict[str, Any] = {
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            campos["exception"] = self.formatException(record.exc_info)
        return json.dumps(campos, ensure_ascii=False, default=str)


def configurar(nivel: int = logging.INFO) -> None:
    """Põe o formatador JSON na saída padrão; vale para o serviço e para os Jobs."""
    manejador = logging.StreamHandler()
    manejador.setFormatter(FormatadorJson())
    logging.basicConfig(level=nivel, handlers=[manejador], force=True)
