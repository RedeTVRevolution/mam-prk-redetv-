"""O cabeçalho que a carga (`api/carga_dev.py`) manda e a chave que a API precisa para respeitá-lo.

Fica fora de `rota_da_busca.py` para o script da carga não carregar a app inteira.
"""

from collections.abc import Mapping

CABECALHO_DE_TESTE = "X-Mam-Teste-De-Carga"
VALOR_DO_CABECALHO = "1"


def aceita_teste_de_carga_do_ambiente(env: Mapping[str, str]) -> bool:
    """`BUSCA_ACEITA_TESTE_DE_CARGA`; ausente, vazia ou qualquer outra coisa que não `true` é desligada."""
    return (env.get("BUSCA_ACEITA_TESTE_DE_CARGA") or "").strip().lower() == "true"
