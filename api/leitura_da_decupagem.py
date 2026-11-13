"""Como se lê a Decupagem de um Job: um lugar só (#582, #584).

A ordem é: modelo -> Correções em vigor -> fusão e renomeação -> lixeira do catálogo.
Duas leituras, nomeadas pelo que entregam:

- `corrigida`: modelo + Correções em vigor + fusão e renomeação. Mantém o `catalogo_id`
  de quem está na lixeira do catálogo (ou foi purgado).
- `entregue`: a corrigida + o efeito da lixeira e da purga (`sem_catalogo_apagado`).

Quem usa qual, e por quê:

| leitor                                              | leitura   |
|-----------------------------------------------------|-----------|
| Decupagem do vídeo na tela e download em JSON       | entregue  |
| indexação (índice, BigQuery, Catálogo do Job nela)  | corrigida |
| Catálogo do Job depois de cada Correção             | corrigida |
| carga que preenche o Catálogo do Job                | corrigida |
| impacto da lixeira do catálogo                      | corrigida |
| prévia da fusão e prévia da renomeação              | corrigida |
| carga de marcas                                     | corrigida |

Motivo: o Catálogo do Job, o índice e o BigQuery precisam do `catalogo_id` de quem está
na lixeira do catálogo; os filtros por pessoa e marca do catálogo (impacto, fusão,
renomeação) dependem dele para achar os vídeos dela. Só a tela e o download mostram a
Decupagem sem esse vínculo. (A regra da lixeira na busca e nos relatórios é outro spec.)

Catálogo de pessoas ou de marcas não fornecido (`None`): aquela espécie não é resolvida
nem filtrada, os vínculos ficam como estão. Catálogo fornecido e id fora dele (purgado):
na `entregue` o vínculo sai.

Cada chamada lê de novo e devolve um dicionário só seu: aplicar a lixeira numa leitura
não altera a outra. Falha de leitura (arquivo ausente, JSON inválido) sobe; quem percorre
vários Jobs decide pular e registrar.
"""

import json
from collections.abc import Iterable, Iterator
from typing import Any, Protocol, cast

from api.catalogo import PessoaDoCatalogo
from api.catalogo_apagado import (
    com_pessoas_fundidas,
    ids_do_catalogo,
    lido_em_lote,
    sem_catalogo_apagado,
)
from api.correcoes import Correcao, decupagem_entregue, versao_do_modelo
from api.marcas import MarcaDoCatalogo


class AbreDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


class ListaCorrecoes(Protocol):
    def listar(self, job_id: str) -> list[Correcao]: ...


class PessoasEmLote(Protocol):
    def obter(self, id: str) -> PessoaDoCatalogo | None: ...
    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]: ...


class MarcasEmLote(Protocol):
    def obter(self, id: str) -> MarcaDoCatalogo | None: ...
    def obter_varios(self, ids: Iterable[str]) -> dict[str, MarcaDoCatalogo]: ...


class LeituraDaDecupagem:
    def __init__(
        self,
        decupagens: AbreDecupagem,
        correcoes: ListaCorrecoes,
        pessoas: PessoasEmLote | None = None,
        marcas: MarcasEmLote | None = None,
    ) -> None:
        self._decupagens = decupagens
        self._correcoes = correcoes
        self._pessoas = pessoas
        self._marcas = marcas

    def corrigida(self, job_id: str) -> dict[str, Any]:
        return self._corrigida(job_id)[0]

    def entregue(self, job_id: str) -> dict[str, Any]:
        corrigida, pessoa = self._corrigida(job_id)
        marca = (
            lido_em_lote(
                ids_do_catalogo(corrigida, "comerciais"),
                cast(Any, self._marcas.obter_varios),  # dict invariante: T é a marca
                self._marcas.obter,
            )
            if self._marcas is not None
            else None
        )
        return sem_catalogo_apagado(
            corrigida,
            lambda id: (
                pessoa is None or (p := pessoa(id)) is not None and p.lixeira is None
            ),
            lambda id: (
                marca is None or (m := marca(id)) is not None and m.lixeira is None
            ),
        )

    def _corrigida(self, job_id: str) -> tuple[dict[str, Any], Any]:
        """A leitura corrigida e o `obter` em lote das pessoas (ou `None`, sem catálogo)."""
        conteudo = b"".join(self._decupagens.abrir_decupagem(job_id))
        lida = decupagem_entregue(
            json.loads(conteudo),
            versao_do_modelo(conteudo),
            self._correcoes.listar(job_id),
        )
        if self._pessoas is None:
            return lida, None
        # Um lote com os ids depois das Correções; o destino de uma fusão fora dele cai
        # em `obter` uma vez, e o id ausente do lote não gera nova leitura.
        pessoa = lido_em_lote(
            ids_do_catalogo(lida, "pessoas"),
            self._pessoas.obter_varios,
            self._pessoas.obter,
        )
        return com_pessoas_fundidas(lida, pessoa), pessoa
