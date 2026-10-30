"""Consolidação: junta os resultados das janelas de análise numa decupagem só.

Os tempos dos resultados já chegam em tempo do arquivo. Cada item fica com a
janela em cujo núcleo ele começa; o que começa só no contexto é descartado
nela, porque a vizinha o decupa.
"""

from collections.abc import Sequence
from typing import cast

from api.comparador import normalizar
from api.decupagem import (
    VERSAO_ESQUEMA,
    Bloco,
    Comercial,
    Decupagem,
    Fala,
    Pauta,
    Plano,
    Programa,
    TextoNaTela,
    Video,
    _Intervalo,
)
from api.janelas import Janela
from api.pessoas import LISTAS, unir_pessoas
from api.tempos import aplicar_regra_de_tempos

_LIMITE_DO_RESUMO = 2000  # tamanho máximo de `Texto` no esquema


def _sobrepoe(a: _Intervalo, b: _Intervalo) -> bool:
    return a.inicio_ms < b.fim_ms and b.inicio_ms < a.fim_ms


def _dono[T: _Intervalo](itens: Sequence[T], janela: Janela, ultima: bool) -> list[T]:
    """Itens que começam no núcleo da janela (a última inclui o fim)."""
    return [
        i
        for i in itens
        if janela.inicio_ms <= i.inicio_ms
        and (i.inicio_ms < janela.fim_ms or (ultima and i.inicio_ms == janela.fim_ms))
    ]


def _antes_do_nucleo[T: _Intervalo](itens: Sequence[T], janela: Janela) -> list[T]:
    """Itens que a janela descarta por começarem no contexto, antes do núcleo."""
    return [i for i in itens if i.inicio_ms < janela.inicio_ms]


def _emendar[T: _Intervalo](item: T, pares: Sequence[_Intervalo]) -> T:
    """Estende o fim até o maior fim dos pares da janela seguinte que se sobrepõem.

    Os pares são só os itens que a janela seguinte descarta: o que ela mantém é
    outro item, e emendar nele daria dois itens com o mesmo fim.
    """
    fim = max([item.fim_ms, *(p.fim_ms for p in pares if _sobrepoe(item, p))])
    return item if fim == item.fim_ms else item.model_copy(update={"fim_ms": fim})


def _em_ordem[T: _Intervalo](itens: Sequence[T]) -> list[T]:
    return sorted(itens, key=lambda i: (i.inicio_ms, i.fim_ms))


def _sem_repetir(itens: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(itens))


def _agrupar_por_sobreposicao[T: _Intervalo](
    janelas: Sequence[Sequence[T]],
) -> list[list[T]]:
    """Agrupa os itens da janela N e da N+1 que se sobrepõem, em cadeia.

    Um item novo entra em todo grupo que tem um item da janela anterior
    sobreposto a ele, e esses grupos viram um só.
    """
    grupos: list[list[tuple[int, T]]] = []
    for k, itens in enumerate(janelas):
        for novo in itens:
            alvos = [
                g
                for g in grupos
                if any(j == k - 1 and _sobrepoe(i, novo) for j, i in g)
            ]
            unido = [par for g in alvos for par in g] + [(k, novo)]
            grupos = [g for g in grupos if not any(g is a for a in alvos)]
            grupos.append(unido)
    return [[i for _, i in g] for g in grupos]


def _duracao(i: _Intervalo) -> int:
    return i.fim_ms - i.inicio_ms


def consolidar(
    video: Video,
    resultados: Sequence[tuple[Janela, Decupagem]],
    cortes: Sequence[int],
) -> Decupagem:
    """Une os resultados das janelas (em ordem) e aplica a regra de tempos."""
    decupagens = [d for _, d in resultados]
    pessoas, mapa = unir_pessoas([d.pessoas for d in decupagens])
    ultimo = len(resultados) - 1

    # Itens das pessoas por janela, já com o id novo, para achar os pares.
    brutas: list[dict[tuple[str, str], list[_Intervalo]]] = []
    for k, d in enumerate(decupagens):
        por_chave: dict[tuple[str, str], list[_Intervalo]] = {}
        for p in d.pessoas:
            for lista in LISTAS:
                por_chave.setdefault((mapa[k][p.id], lista), []).extend(
                    getattr(p, lista)
                )
        brutas.append(por_chave)
    mantidas: dict[tuple[str, str], list[_Intervalo]] = {}
    for k, (janela, _) in enumerate(resultados):
        proximas = brutas[k + 1] if k < ultimo else {}
        for chave, itens in brutas[k].items():
            pares = (
                _antes_do_nucleo(proximas.get(chave, []), resultados[k + 1][0])
                if k < ultimo
                else []
            )
            mantidas.setdefault(chave, []).extend(
                _emendar(i, pares) for i in _dono(itens, janela, k == ultimo)
            )
    # Some a pessoa que só tinha itens descartados e nenhuma pauta cita (o
    # mesmo "não identificado" no contexto de duas janelas, por exemplo); as
    # outras são renumeradas.
    citadas = {
        mapa[k][i]
        for k, d in enumerate(decupagens)
        for pa in d.pautas
        for i in pa.pessoas
    }
    pessoas = [
        p.model_copy(
            update={
                lista: _em_ordem(mantidas.get((p.id, lista), [])) for lista in LISTAS
            }
        )
        for p in pessoas
        if p.id in citadas
        or not any(getattr(p, lista) for lista in LISTAS)
        or any(mantidas.get((p.id, lista)) for lista in LISTAS)
    ]
    renumeracao = {p.id: f"pes{n:02d}" for n, p in enumerate(pessoas, 1)}
    pessoas = [p.model_copy(update={"id": renumeracao[p.id]}) for p in pessoas]
    mapa = {
        k: {a: renumeracao[n] for a, n in m.items() if n in renumeracao}
        for k, m in mapa.items()
    }

    def pauta_da_janela(k: int, p: Pauta) -> Pauta:
        return p.model_copy(
            update={"pessoas": _sem_repetir([mapa[k][i] for i in p.pessoas])}
        )

    def juntar[T: Bloco | Pauta](partes: list[T]) -> T:
        """Início da primeira ao fim da última; título e resumo da parte mais longa."""
        maior = max(partes, key=_duracao)
        mudancas: dict[str, object] = {
            "inicio_ms": min(p.inicio_ms for p in partes),
            "fim_ms": max(p.fim_ms for p in partes),
            "titulo": maior.titulo,
        }
        if isinstance(maior, Pauta):
            so_pautas = [p for p in partes if isinstance(p, Pauta)]
            mudancas["resumo"] = maior.resumo
            mudancas["pessoas"] = _sem_repetir(
                [i for p in so_pautas for i in p.pessoas]
            )
            mudancas["locais"] = _sem_repetir([i for p in so_pautas for i in p.locais])
        return cast(T, maior.model_copy(update=mudancas))

    pautas = _em_ordem(
        [
            juntar(g)
            for g in _agrupar_por_sobreposicao(
                [
                    [pauta_da_janela(k, p) for p in d.pautas]
                    for k, d in enumerate(decupagens)
                ]
            )
        ]
    )
    blocos = _em_ordem(
        [
            juntar(g)
            for g in _agrupar_por_sobreposicao([d.programa.blocos for d in decupagens])
        ]
    )
    pautas = [
        p.model_copy(update={"id": f"pau{n:02d}"}) for n, p in enumerate(pautas, 1)
    ]

    planos: list[Plano] = []
    comerciais: list[Comercial] = []
    transcricao: list[Fala] = []
    textos_na_tela: list[TextoNaTela] = []
    for k, (janela, d) in enumerate(resultados):
        ultima = k == ultimo
        planos += _dono(d.planos, janela, ultima)
        # ponytail: planos e falas não emendam; uma fala que passa mais de 10 s
        # da borda sai cortada no fim do contexto. A emenda só olha a janela
        # seguinte: uma aparição ou comercial que atravessa a janela inteira
        # sai cortado no fim do contexto dela.
        transcricao += _dono(d.transcricao, janela, ultima)
        textos_na_tela += _dono(d.textos_na_tela, janela, ultima)
        proximos = (
            _antes_do_nucleo(decupagens[k + 1].comerciais, resultados[k + 1][0])
            if k < ultimo
            else []
        )
        for c in _dono(d.comerciais, janela, ultima):
            pares = [
                s
                for s in proximos
                if s.tipo == c.tipo and normalizar(s.marca) == normalizar(c.marca)
            ]
            comerciais.append(_emendar(c, pares))
    planos = [
        p.model_copy(update={"id": f"pla{n:03d}"})
        for n, p in enumerate(_em_ordem(planos), 1)
    ]

    resumo = " ".join(d.programa.resumo for d in decupagens if d.programa.resumo)
    # ponytail: o resumo provisório é cortado em 2000 caracteres; a passada
    # narrativa o reescreve.
    consolidada = Decupagem(
        versao_esquema=VERSAO_ESQUEMA,
        video=video,
        programa=Programa(resumo=resumo[:_LIMITE_DO_RESUMO], blocos=blocos),
        pautas=pautas,
        pessoas=pessoas,
        planos=planos,
        comerciais=_em_ordem(comerciais),
        transcricao=_em_ordem(transcricao),
        textos_na_tela=_em_ordem(textos_na_tela),
    )
    # `model_copy` não valida: valida de novo depois da regra de tempos.
    return Decupagem.model_validate(
        aplicar_regra_de_tempos(consolidada, cortes).model_dump()
    )
