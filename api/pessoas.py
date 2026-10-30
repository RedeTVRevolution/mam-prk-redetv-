"""Pessoas: junta as pessoas de várias janelas sem misturar aparição e menção.

Aparição (`na_imagem`) e menção (`citada_na_fala`, `citada_no_texto`) ficam em
listas separadas: uma menção nunca vira aparição. Só as aparições contam no
tempo de tela.
"""

from api.comparador import normalizar
from api.decupagem import Pessoa, _Intervalo

_NAO_IDENTIFICADO = normalizar("não identificado")
LISTAS = ("na_imagem", "citada_na_fala", "citada_no_texto")


def nao_identificado(nome: str) -> bool:
    """O nome é o "não identificado" que o modelo usa para quem não reconhece,
    com ou sem a descrição curta que a instrução pede ("não identificado,
    repórter de cabelo curto")."""
    return normalizar(nome).startswith(_NAO_IDENTIFICADO)


def unir_pessoas(
    grupos: list[list[Pessoa]],
) -> tuple[list[Pessoa], dict[int, dict[str, str]]]:
    """Une as pessoas de cada janela, em ordem.

    Devolve as pessoas com ids `pes01`, `pes02`… (ordem da primeira ocorrência)
    e, por índice de janela, o mapa do id antigo para o novo. Um id repetido
    na mesma janela é erro: o mapa não teria como apontar para as duas.
    """
    unidas: list[Pessoa] = []
    por_nome: dict[str, int] = {}
    mapa: dict[int, dict[str, str]] = {}
    for janela, pessoas in enumerate(grupos):
        mapa[janela] = {}
        for p in pessoas:
            if p.id in mapa[janela]:
                raise ValueError(f"id de pessoa repetido na janela {janela}: {p.id}")
            chave = normalizar(p.nome)
            sem_nome = nao_identificado(p.nome)
            posicao = None if sem_nome else por_nome.get(chave)
            if posicao is None:
                posicao = len(unidas)
                unidas.append(p.model_copy(update={"id": f"pes{posicao + 1:02d}"}))
                if not sem_nome:
                    por_nome[chave] = posicao
            else:
                unidas[posicao] = _juntar(unidas[posicao], p)
            mapa[janela][p.id] = unidas[posicao].id
    for i, p in enumerate(unidas):
        unidas[i] = p.model_copy(
            update={campo: _em_ordem(getattr(p, campo)) for campo in LISTAS}
        )
    return unidas, mapa


def _juntar(base: Pessoa, outra: Pessoa) -> Pessoa:
    revisao = "revisao" in (base.origem, outra.origem)
    return base.model_copy(
        update={
            "origem": "revisao" if revisao else "modelo",
            "fontes_do_nome": list(
                dict.fromkeys([*base.fontes_do_nome, *outra.fontes_do_nome])
            ),
            **{c: [*getattr(base, c), *getattr(outra, c)] for c in LISTAS},
        }
    )


def _em_ordem[T: _Intervalo](itens: list[T]) -> list[T]:
    return sorted(itens, key=lambda i: (i.inicio_ms, i.fim_ms))


def tempo_de_tela_ms(pessoa: Pessoa) -> int:
    """Soma das aparições, sem contar duas vezes o trecho sobreposto."""
    total = 0
    fim_atual = 0
    for a in _em_ordem(pessoa.na_imagem):
        inicio = max(a.inicio_ms, fim_atual)
        if a.fim_ms > inicio:
            total += a.fim_ms - inicio
        fim_atual = max(fim_atual, a.fim_ms)
    return total
