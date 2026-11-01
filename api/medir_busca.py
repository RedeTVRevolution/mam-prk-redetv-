"""`make medir-busca` (#117): indexa as 3 Decupagens de exemplo, confere o filtro composto
e mede a latência da busca híbrida. Roda só com credenciais e fica fora do CI.

    python -m api.medir_busca [CONSULTAS] [DIMENSAO ...]

Cada dimensão pede uma coleção própria (a dimensão dos vetores é fixa na criação): a da
configuração (`BUSCA_DIMENSAO`) é usada como está; cada uma das outras, uma de cada vez,
ganha a coleção temporária `BUSCA_COLECAO_DE_MEDIDA` (o nome vem do `infra/main.tf`) com
os seus índices, apagada no fim com tudo o que tiver dentro, mesmo se a medição falhar.
"""

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import perf_counter

from api.agent_retrieval import (
    AgentRetrieval,
    ConfigDaBusca,
    apagar_colecao,
    criar_colecao,
    transporte_http,
)
from api.exemplos_da_busca import EXEMPLOS, SABRINA
from api.indice_da_busca import Consulta, Filtros, IndiceDaBusca

CONSULTA = "vestido vermelho da Sabrina Sato"


@dataclass(frozen=True)
class Medicao:
    dimensao: int
    registros: int
    so_o_objeto_da_sabrina: bool
    # O vestido dela é vermelho: pedir azul não pode voltar nada. Servido pelo índice ANN,
    # um filtro que ele não aceita pode ser ignorado sem erro.
    cor_filtra: bool
    tempos_s: list[float]

    @property
    def p50_s(self) -> float:
        return percentil(self.tempos_s, 50)

    @property
    def p95_s(self) -> float:
        return percentil(self.tempos_s, 95)


def percentil(tempos: list[float], p: int) -> float:
    """O valor na posição mais próxima do percentil (sem interpolar)."""
    ordenados = sorted(tempos)
    posicao = max(1, -(-len(ordenados) * p // 100))
    return ordenados[posicao - 1]


def _consulta(vetor: list[float] | None = None, cor: str = "vermelho") -> Consulta:
    """ "vestido vermelho da Sabrina Sato" como o entendimento da consulta a entregaria:
    filtros exatos, o texto que sobra e o significado da frase inteira."""
    return Consulta(
        filtros=Filtros(tipo="objeto", categoria="roupa", cor_base=cor, dono=SABRINA),
        texto="vestido",
        significado=CONSULTA,
        vetor_do_quadro=vetor,
        limite=10,
    )


def medir(
    indice: IndiceDaBusca,
    dimensao: int,
    consultas: int,
    relogio: Callable[[], float] = perf_counter,
    vetor: list[float] | None = None,
) -> Medicao:
    """Indexa os exemplos, mede `consultas` buscas e apaga os exemplos no fim."""
    if consultas < 1:
        raise ValueError("é preciso ao menos uma consulta para medir")
    try:
        for exemplo in EXEMPLOS:
            indice.gravar(exemplo.job_id, exemplo.registros())
        registros = indice.total()
        achados = indice.buscar(_consulta(vetor))
        so_a_sabrina = len(achados) == 1 and (
            (achados[0].job_id, achados[0].dono, achados[0].cor_base)
            == ("ex-sabrina", SABRINA, ["vermelho"])
        )
        cor_filtra = not indice.buscar(_consulta(vetor, cor="azul"))
        tempos: list[float] = []
        for _ in range(consultas):
            inicio = relogio()
            indice.buscar(_consulta(vetor))
            tempos.append(relogio() - inicio)
        return Medicao(dimensao, registros, so_a_sabrina, cor_filtra, tempos)
    finally:
        for exemplo in EXEMPLOS:
            indice.apagar(exemplo.job_id)


def _sim(ok: bool) -> str:
    return "sim" if ok else "NÃO"


def tabela(medicoes: list[Medicao]) -> str:
    linhas = ["dimensão | registros | só a Sabrina | cor filtra | p50 (ms) | p95 (ms)"]
    for m in medicoes:
        linhas.append(
            f"{m.dimensao:>8} | {m.registros:>9} | {_sim(m.so_o_objeto_da_sabrina):>12}"
            f" | {_sim(m.cor_filtra):>10} | {m.p50_s * 1000:>8.0f} | {m.p95_s * 1000:>8.0f}"
        )
    return "\n".join(linhas)


def main(argumentos: list[str]) -> int:
    consultas = int(argumentos[0]) if argumentos else 30
    config = ConfigDaBusca.do_ambiente(os.environ)
    dimensoes = [int(d) for d in argumentos[1:]] or [config.dimensao]
    medida = replace(config, colecao=os.environ["BUSCA_COLECAO_DE_MEDIDA"])
    transporte = transporte_http()
    medicoes: list[Medicao] = []
    for dimensao in dimensoes:
        temporaria = dimensao != config.dimensao
        alvo = replace(medida, dimensao=dimensao) if temporaria else config
        try:
            # Dentro do try: se um índice falhar ao nascer, a coleção não fica no ar.
            if temporaria:
                criar_colecao(alvo, transporte)
            medicoes.append(
                medir(AgentRetrieval(alvo, transporte), dimensao, consultas)
            )
        finally:
            if temporaria:
                apagar_colecao(alvo, transporte)
    print(tabela(medicoes))
    return 0 if all(m.so_o_objeto_da_sabrina and m.cor_filtra for m in medicoes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
