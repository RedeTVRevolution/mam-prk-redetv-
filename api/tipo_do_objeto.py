"""O tipo canônico de um objeto e a chave que o agrupa (#544).

O texto bruto (nome ou tipo livre) nunca é trocado: o tipo canônico é um campo ao lado dele.
Agrupar por tipo é uma visão. Cada ocorrência segue gravada com os próprios atributos.
"""

from collections.abc import Iterable

from api.assinatura_do_nome import assinatura
from api.comparador import normalizar
from api.decupagem import CORES_BASE
from api.taxonomia_de_objetos import (
    OUTRO,
    SINONIMOS_DO_TIPO,
    TIPOS_CANONICOS,
)

# O dicionário de nome livre para tipo: a assinatura do tipo e a de cada sinônimo. Vale para o
# acervo antigo, sem reprocessar.
_DICIONARIO: dict[str, str] = {}
for _tipo in TIPOS_CANONICOS:
    for _nome in [_tipo, *SINONIMOS_DO_TIPO[_tipo]]:
        _DICIONARIO.setdefault(assinatura(_nome), _tipo)


def tipo_pelo_nome(nome: str, cores: Iterable[str] = ()) -> str:
    """O tipo da lista para um nome livre, ou `outro`. A cor do item sai do nome ("carro
    vermelho"); sem cor informada, tenta de novo sem nenhuma das cores base."""
    cores = list(cores)
    chave = assinatura(nome, cores)
    achado = _DICIONARIO.get(chave) if chave else None
    if achado is None and chave:
        achado = _DICIONARIO.get(assinatura(nome, [*cores, *CORES_BASE]))
    return achado or OUTRO


def tipo_canonico_de(gravado: str | None, nome: str, cores: Iterable[str] = ()) -> str:
    """O tipo gravado, se for da lista; senão (vazio, `outro` ou fora da lista, como o de
    uma lista mais antiga) o do dicionário pelo nome, ou `outro`."""
    if gravado in TIPOS_CANONICOS:
        return str(gravado)
    return tipo_pelo_nome(nome, cores)


def chave_de_agrupamento(tipo: str, nome: str, cores: Iterable[str] = ()) -> str:
    """O tipo da lista, ou, em `outro`, a assinatura do próprio nome: dois nomes
    desconhecidos diferentes seguem separados."""
    if tipo != OUTRO:
        return f"tipo:{tipo}"
    return f"nome:{assinatura(nome, cores) or normalizar(nome)}"
