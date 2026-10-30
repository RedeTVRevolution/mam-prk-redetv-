"""Aprovação opcional de Curador (E3): quais tipos de correção exigem aprovação.

A lista fica num documento do Firestore e é definida por comando, sem tela de
administração. Vazia por padrão: nada exige aprovação.
"""

from collections.abc import Callable

from api.correcoes import CORRIGIVEIS, RepositorioDeAprovacao


def definir_aprovacao_main(
    argv: list[str],
    repositorio: RepositorioDeAprovacao,
    imprimir: Callable[[str], None] = print,
) -> int:
    uso = f"uso: make definir-aprovacao TIPOS=<tipos separados por vírgula, vazio para nenhum> (tipos: {', '.join(CORRIGIVEIS)})"
    if len(argv) != 1:
        imprimir(uso)
        return 2
    pedidos = sorted({t.strip() for t in argv[0].split(",") if t.strip()})
    desconhecidos = [t for t in pedidos if t not in CORRIGIVEIS]
    if desconhecidos:
        imprimir(f"tipo desconhecido: {', '.join(desconhecidos)}. {uso}")
        return 2
    repositorio.definir(frozenset(pedidos))
    imprimir(f"exigem aprovação: {', '.join(pedidos) or 'nenhum tipo'}")
    return 0
