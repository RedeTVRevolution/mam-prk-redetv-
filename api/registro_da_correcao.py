"""O Registro da Correção (#614): a sequência única de gravar uma Correção.

Cinco operações, uma por regra de `api/regras_das_correcoes.py`: corrigir, desfazer, reaplicar,
descartar e decidir (aprovar e recusar). Cada uma lê só o que precisa (o decidir não lê a
Decupagem), aplica a regra, grava, registra o evento de uso e atualiza o Catálogo do Job. O evento
e o catálogo são de melhor esforço: a falha deles vai ao log e não desfaz a Correção gravada.

O que fica na rota (`api/jobs.py`): a conferência do Job concluído, a regra de aprovação, a
autoria e o mapa das exceções para HTTP. Não importa `api.jobs` (que importa este módulo).
"""

import logging
from collections.abc import Callable
from typing import Any

from api.catalogo import Catalogo
from api.catalogo_apagado import ids_do_catalogo
from api.catalogo_dos_jobs import atualizar_catalogo_do_job
from api.correcoes import (
    TIPOS,
    Autoria,
    Correcao,
    CorrecaoJaExiste,
    NaoDesfazivel,
    NaoNaFila,
    NaoPendente,
    NovaCorrecao,
    RepositorioDeCorrecoes,
)
from api.eventos_de_uso import Eventos, registrar
from api.leitura_da_decupagem import AbreDecupagem, LeituraDaDecupagem, ler_modelo
from api.marcas import CatalogoDeMarcas
from api.modelo_do_job import Job, RepositorioDeJobs
from api.regras_das_correcoes import (
    aplicar,
    corrigir,
    corrigir_grupo,
    decidir,
    descartar,
    desfazer,
    reaplicar,
)

log = logging.getLogger(__name__)

# O tipo do item que uma Correção corrige, quando não é pessoa nem comercial: ela não pode
# mexer nos `catalogo_id` nem, indiretamente, no efeito de outra Correção sobre eles.
_SEM_CATALOGO = frozenset(
    {"pauta", "plano", "fala", "texto_na_tela", "objeto", "inventario"}
)


def pode_mudar_os_ids(tipo: str) -> bool:
    """Se uma Correção deste tipo, criada, aprovada ou desfeita, pode mudar o conjunto de
    `catalogo_id` da Decupagem, em qualquer sequência. Pelo tipo do item na tabela `TIPOS`:
    o `item.tempos` (sem tipo de item fixo) conta, porque leva a aparição para onde um
    `pessoa.nao_e` deixa de casar. Tipo desconhecido conta."""
    entrada = TIPOS.get(tipo)
    return entrada is None or entrada.tipo_do_item not in _SEM_CATALOGO


def _ids(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> list[set[str]]:
    entregue = aplicar(modelo, versao, correcoes)
    return [set(ids_do_catalogo(entregue, c)) for c in ("pessoas", "comerciais")]


class RegistroDaCorrecao:
    def __init__(
        self,
        decupagens: AbreDecupagem,
        correcoes: RepositorioDeCorrecoes,
        catalogo: Catalogo,
        marcas: CatalogoDeMarcas,
        jobs: RepositorioDeJobs,
        publicador: Eventos,
    ) -> None:
        self._decupagens = decupagens
        self._correcoes = correcoes
        self._catalogo = catalogo
        self._marcas = marcas
        self._jobs = jobs
        self._publicador = publicador
        self._leitura = LeituraDaDecupagem(decupagens, correcoes, catalogo)

    def corrigir(
        self,
        job: Job,
        novo: NovaCorrecao,
        autoria: Autoria,
        *,
        exige_aprovacao: bool,
    ) -> tuple[Correcao, str]:
        """A Correção gravada e a versão da Decupagem em que ela se apoia."""
        modelo, versao = ler_modelo(self._decupagens, job.id)
        todas = self._correcoes.listar(job.id)
        registros = (
            corrigir_grupo(
                modelo,
                versao,
                todas,
                novo,
                job.id,
                autoria,
                exige_aprovacao=exige_aprovacao,
            )
            if novo.item_ids
            else [
                corrigir(
                    modelo,
                    versao,
                    todas,
                    novo,
                    job.id,
                    autoria,
                    exige_aprovacao=exige_aprovacao,
                    catalogo=self._catalogo,
                    marcas=self._marcas,
                )
            ]
        )
        return self._gravar(
            job, registros, autoria, todas, lido=(modelo, versao)
        ), versao

    def desfazer(
        self, job: Job, alvo_id: str, motivo: str, autoria: Autoria
    ) -> Correcao:
        return self._sobre_o_modelo(
            job,
            lambda m, v, todas: desfazer(m, v, todas, alvo_id, motivo, job.id, autoria),
            autoria,
            NaoDesfazivel,
        )

    def reaplicar(
        self, job: Job, alvo_id: str, item_id: str, motivo: str, autoria: Autoria
    ) -> Correcao:
        return self._sobre_o_modelo(
            job,
            lambda m, v, todas: [
                reaplicar(m, v, todas, alvo_id, item_id, motivo, job.id, autoria)
            ],
            autoria,
            NaoNaFila,
        )

    def descartar(
        self, job: Job, alvo_id: str, motivo: str, autoria: Autoria
    ) -> Correcao:
        return self._sobre_o_modelo(
            job,
            lambda m, v, todas: [
                descartar(m, v, todas, alvo_id, motivo, job.id, autoria)
            ],
            autoria,
            NaoNaFila,
        )

    def decidir(
        self, job: Job, alvo_id: str, aprovada: bool, motivo: str, autoria: Autoria
    ) -> Correcao:
        """Aprova ou recusa uma Correção pendente (ou o grupo dela); não lê a Decupagem
        antes de gravar."""
        correcoes = self._correcoes.listar(job.id)
        registros = decidir(
            correcoes,
            alvo_id,
            aprovada,
            motivo,
            job.id,
            autoria,
        )
        return self._gravar(job, registros, autoria, correcoes, NaoPendente)

    def _sobre_o_modelo(
        self,
        job: Job,
        regra: Callable[[dict[str, Any], str, list[Correcao]], list[Correcao]],
        autoria: Autoria,
        se_ja_existe: type[Exception],
    ) -> Correcao:
        """Lê o modelo e as Correções, aplica a regra e grava os registros que ela devolve."""
        modelo, versao = ler_modelo(self._decupagens, job.id)
        todas = self._correcoes.listar(job.id)
        registros = regra(modelo, versao, todas)
        return self._gravar(
            job, registros, autoria, todas, se_ja_existe, lido=(modelo, versao)
        )

    # ponytail: sem chave de idempotência. O web não repete o POST; repetir continua dando 409
    # (o id do registro é fixo por alvo, e o repositório não sobrescreve). Sem transação entre
    # gravar, o evento e o Catálogo do Job: se o catálogo falhar, o Job fica velho até a próxima
    # indexação ou até `make preencher-catalogo-dos-jobs`. Chave de idempotência e transação só
    # se o web passar a repetir.
    def _gravar(
        self,
        job: Job,
        registros: list[Correcao],
        autoria: Autoria,
        antes: list[Correcao],
        se_ja_existe: type[Exception] | None = None,
        *,
        lido: tuple[dict[str, Any], str] | None = None,
    ) -> Correcao:
        """Grava os `registros` de um gesto (os de um grupo numa escrita só, todos ou
        nenhum) e devolve o primeiro. Um evento e um recálculo por gesto. Grava, registra o evento e atualiza o Catálogo do Job. `antes` são as Correções que
        a operação leu; `se_ja_existe` é a exceção dela para o registro que outro pedido gravou
        no meio. O catálogo só é recalculado se o tipo da Correção criada ou do alvo pode mudar
        o conjunto de `catalogo_id` (`pode_mudar_os_ids`) ou, com o modelo `lido`, se a
        comparação em memória o muda; o recálculo reusa o `lido`. O `decidir` não leu o modelo:
        vale só o tipo."""
        registro = registros[0]
        try:
            if len(registros) == 1:
                self._correcoes.acrescentar(registro)
            else:
                self._correcoes.acrescentar_varios(registros)
        except CorrecaoJaExiste as erro:
            if se_ja_existe is None:
                raise
            raise se_ja_existe(registro.id) from erro
        registrar(
            self._publicador,
            "correcao",
            ("usuario", autoria.uid),
            autoria.em,
            job_id=job.id,
            programa=job.programa,
            tipo_de_correcao=registro.tipo,
        )
        if self._recalcula(registros, antes, lido):
            # ponytail: reusa o modelo já lido (#720). Se a identificação gravar outra
            # Decupagem nesse meio-tempo, o Catálogo do Job sai da versão velha até a
            # próxima Correção ou o `make preencher-catalogo-dos-jobs` (aceito em 18/11).
            atualizar_catalogo_do_job(job, self._jobs, self._leitura, lido)
        return registro

    @staticmethod
    def _recalcula(
        registros: list[Correcao],
        antes: list[Correcao],
        lido: tuple[dict[str, Any], str] | None,
    ) -> bool:
        registro = registros[0]
        alvo = (
            registro.desfaz or registro.aprova or registro.recusa or registro.descarta
        )
        tipo = next((c.tipo for c in antes if c.id == alvo), registro.tipo)
        if pode_mudar_os_ids(tipo):
            return True
        if lido is None:
            return False
        try:
            return _ids(*lido, antes) != _ids(*lido, [*antes, *registros])
        except Exception:
            log.exception("conjunto de ids de %s não comparado", registro.job_id)
            return True
