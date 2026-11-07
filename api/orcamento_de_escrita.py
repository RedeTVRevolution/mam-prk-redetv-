"""Orçamento de escrita da coleção da busca, compartilhado entre os processos (#460).

A cota `data_object_writes` do Agent Retrieval é da coleção inteira, e cada objeto de um
`batchCreate`, `batchUpdate` ou `batchDelete` conta. O ritmo local de cada processo não
enxerga o do vizinho; aqui as reservas ficam num documento do Firestore, uma lista de
`(quando, objetos)` dos últimos 60 s, e cada lote reserva por transação antes de seguir.
O documento tem o nome da coleção da busca (que vem da configuração), então coleções
diferentes (a de medida) têm orçamentos diferentes. Cada reserva vai como um mapa
`{quando, objetos}`: o Firestore não aceita lista dentro de lista.

Uma reserva cuja escrita falhou não é devolvida: sai sozinha da janela de 60 s. O
relógio é o de parede (`time.time`), igual em todos os processos; a folga de
`FRACAO_DA_COTA` cobre a diferença entre os relógios e o do serviço.
"""

import random
from typing import Any, Protocol

from google.api_core.exceptions import Aborted
from google.cloud import firestore

COLECAO_DO_ORCAMENTO_DA_BUSCA = "orcamento_da_busca"
JANELA_S = 60.0
# Com muitos processos no mesmo documento, a transação esgota as tentativas (ValueError
# causado por Aborted). Quem perdeu espera um pouco, ao acaso, e reserva de novo, em vez
# de cair no ritmo local, que não enxerga os vizinhos.
TETO_DA_ESPERA_SOB_DISPUTA_S = 1.0

Reserva = tuple[float, int]


class Orcamento(Protocol):
    def reservar(
        self, colecao: str, objetos: int, limite: float, agora: float
    ) -> float:
        """Reserva `objetos` e devolve 0, ou não reserva e devolve os segundos até
        valer a pena tentar de novo."""
        ...


def reservar_na_janela(
    reservas: list[Reserva], objetos: int, limite: float, agora: float
) -> tuple[list[Reserva], float]:
    """As reservas que sobram na janela e a espera: 0 se `objetos` coube (e então a
    reserva já vai na lista). Com a janela vazia o lote entra mesmo acima do limite,
    senão um lote maior que ele nunca sairia."""
    vivas = sorted(r for r in reservas if r[0] > agora - JANELA_S)
    gasto = sum(n for _, n in vivas)
    saidas = 0
    while vivas[saidas:] and gasto + objetos > limite:
        gasto -= vivas[saidas][1]
        saidas += 1
    if saidas:
        return vivas, vivas[saidas - 1][0] + JANELA_S - agora
    return [*vivas, (agora, objetos)], 0.0


class OrcamentoFirestore:
    def __init__(
        self, cliente: Any, colecao: str = COLECAO_DO_ORCAMENTO_DA_BUSCA
    ) -> None:
        self._cliente = cliente
        self._colecao = cliente.collection(colecao)

    def reservar(
        self, colecao: str, objetos: int, limite: float, agora: float
    ) -> float:
        referencia = self._colecao.document(colecao)

        @firestore.transactional
        def reservar_na_transacao(transacao: Any) -> float:
            dados = referencia.get(transaction=transacao).to_dict() or {}
            reservas = [
                (float(r["quando"]), int(r["objetos"]))
                for r in dados.get("reservas", [])
            ]
            novas, espera = reservar_na_janela(reservas, objetos, limite, agora)
            if not espera:
                transacao.set(
                    referencia,
                    {"reservas": [{"quando": t, "objetos": n} for t, n in novas]},
                )
            return espera

        try:
            espera: float = reservar_na_transacao(self._cliente.transaction())
        except (ValueError, Aborted) as erro:
            if isinstance(erro, ValueError) and not isinstance(erro.__cause__, Aborted):
                raise
            return random.uniform(0.0, TETO_DA_ESPERA_SOB_DISPUTA_S)
        return espera
