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
import logging
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from api.catalogo_apagado import CATALOGO_ID, ids_do_catalogo, sem_catalogo_apagado
from api.comparador import normalizar
from api.correcoes import Correcao, RepositorioDeCorrecoes, versao_do_modelo
from api.marcas import CatalogoDeMarcas
from api.quem_conta import Destino, PessoasEmLote, QuemConta
from api.regras_das_correcoes import decupagem_com_correcoes

if TYPE_CHECKING:  # api.jobs importa este módulo
    from api.jobs import FiltroDeJobs, Job, RepositorioDeJobs

log = logging.getLogger(__name__)


class AbreDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


def ler_modelo(decupagens: AbreDecupagem, job_id: str) -> tuple[dict[str, Any], str]:
    """O JSON do modelo e a versão (SHA-256 dos bytes guardados)."""
    conteudo = b"".join(decupagens.abrir_decupagem(job_id))
    return json.loads(conteudo), versao_do_modelo(conteudo)


class ListaCorrecoes(Protocol):
    def listar(self, job_id: str) -> list[Correcao]: ...


class LeituraDaDecupagem:
    def __init__(
        self,
        decupagens: AbreDecupagem,
        correcoes: ListaCorrecoes,
        pessoas: PessoasEmLote | None = None,
        marcas: CatalogoDeMarcas | None = None,
    ) -> None:
        self._decupagens = decupagens
        self._correcoes = correcoes
        self._pessoas = pessoas
        self._marcas = marcas

    def corrigida(self, job_id: str) -> dict[str, Any]:
        return self._corrigida(job_id)[0]

    def entregue(self, job_id: str) -> dict[str, Any]:
        corrigida, quem, sem_vinculo = self._corrigida(job_id)
        marcas = quem.marcas_vivas(ids_do_catalogo(corrigida, "comerciais"))
        return sem_catalogo_apagado(
            corrigida, lambda p: id(p) not in sem_vinculo, lambda id: id in marcas
        )

    def _corrigida(self, job_id: str) -> tuple[dict[str, Any], QuemConta, set[int]]:
        """A leitura corrigida, o Quem conta que a leu e as pessoas (por `id()` do dicionário)
        que não contam: a `entregue` os reaproveita."""
        lida = decupagem_com_correcoes(
            *ler_modelo(self._decupagens, job_id), self._correcoes.listar(job_id)
        )
        quem = QuemConta(self._pessoas, self._marcas)
        sem_vinculo: set[int] = set()
        if self._pessoas is not None:
            destinos = quem.pessoas(ids_do_catalogo(lida, "pessoas"))
            sem_vinculo = _com_destinos(lida, destinos)
        return lida, quem, sem_vinculo


def _com_destinos(lida: dict[str, Any], destinos: Mapping[str, Destino]) -> set[int]:
    """O destino no lugar da pessoa fundida (#209): `catalogo_id` e nome passam a ser os do
    destino; o gravado não muda. Também troca o nome que a pessoa teve antes de uma
    renomeação em todos os vídeos (#263) pelo atual; um nome que o editor corrigiu no vídeo
    para outro fica. Destino purgado ou ciclo: vale a renomeação da origem, como antes, e a `entregue` tira
    o vínculo.

    Devolve o `id()` de cada pessoa que não conta (`Destino.conta` do id gravado, não do
    trocado): a `entregue` tira o vínculo dela, como a busca e o tempo de tela não a contam."""
    sem_vinculo: set[int] = set()
    for pessoa in lida.get("pessoas") or []:
        gravado = pessoa.get(CATALOGO_ID) if isinstance(pessoa, dict) else None
        destino = destinos.get(gravado) if gravado is not None else None
        if destino is None:
            continue
        if not destino.conta:
            sem_vinculo.add(id(pessoa))
        if destino.fundida and destino.pessoa is not None:
            pessoa.update(nome=destino.pessoa.nome, catalogo_id=destino.pessoa.id)
            continue
        origem = destino.origem
        if origem is not None and origem.renomeacao is not None:
            antigos = {normalizar(n) for n in origem.renomeacao.nomes_anteriores}
            if normalizar(str(pessoa.get("nome"))) in antigos:
                pessoa["nome"] = origem.nome
    return sem_vinculo


def decupagens_dos_jobs(
    repositorio: "RepositorioDeJobs",
    correcoes: RepositorioDeCorrecoes,
    decupagens: AbreDecupagem,
    pessoas: PessoasEmLote | None = None,
    filtro: "FiltroDeJobs | None" = None,
) -> Iterator[tuple["Job", dict[str, Any]]]:
    """Cada vídeo concluído fora da lixeira (e que casa com `filtro`) com a Decupagem
    corrigida; a que não lê é pulada, com log."""
    from api.jobs import FiltroDeJobs  # local: api.jobs importa este módulo

    leitura = LeituraDaDecupagem(decupagens, correcoes, pessoas)
    for job in repositorio.consultar(filtro or FiltroDeJobs()).jobs:
        if job.estado != "concluido":
            continue
        try:
            corrigida = leitura.corrigida(job.id)
        except Exception:  # noqa: BLE001 - uma Decupagem ruim não trava quem percorre
            log.warning("decupagem de %s não lida; pulada", job.id)
            continue
        yield job, corrigida


def decupagens_corrigidas(
    repositorio: "RepositorioDeJobs",
    correcoes: RepositorioDeCorrecoes,
    decupagens: AbreDecupagem,
    pessoas: PessoasEmLote | None = None,
    filtro: "FiltroDeJobs | None" = None,
) -> Iterator[dict[str, Any]]:
    """A Decupagem corrigida de cada vídeo concluído fora da lixeira; a que não lê é pulada."""
    for _job, corrigida in decupagens_dos_jobs(
        repositorio, correcoes, decupagens, pessoas, filtro
    ):
        yield corrigida
