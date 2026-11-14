"""O Registro da Correção (#614): a sequência única de gravar uma Correção.

Cinco operações, uma por regra de `api/regras_das_correcoes.py`: corrigir, desfazer, reaplicar,
descartar e decidir (aprovar e recusar). Cada uma lê só o que precisa (o decidir não lê a
Decupagem), aplica a regra, grava, registra o evento de uso e atualiza o Catálogo do Job. O evento
e o catálogo são de melhor esforço: a falha deles vai ao log e não desfaz a Correção gravada.

O que fica na rota (`api/jobs.py`): a conferência do Job concluído, a regra de aprovação, a
autoria e o mapa das exceções para HTTP. Não importa `api.jobs` (que importa este módulo).

ponytail: sem chave de idempotência. O web não repete o POST; repetir continua dando 409 (o id do
registro é fixo por alvo, e o repositório não sobrescreve). Sem transação entre gravar, o evento e
o Catálogo do Job: se o catálogo falhar, o Job fica velho até a próxima indexação ou até
`make preencher-catalogo-dos-jobs`. Chave de idempotência e transação só se o web passar a repetir.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from api.catalogo import Catalogo
from api.catalogo_dos_jobs import atualizar_catalogo_do_job
from api.correcoes import (
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
from api.regras_das_correcoes import (
    corrigir,
    decidir,
    descartar,
    desfazer,
    reaplicar,
)

if TYPE_CHECKING:  # api.jobs importa este módulo
    from api.jobs import Job, RepositorioDeJobs


class RegistroDaCorrecao:
    def __init__(
        self,
        decupagens: AbreDecupagem,
        correcoes: RepositorioDeCorrecoes,
        catalogo: Catalogo,
        marcas: CatalogoDeMarcas,
        jobs: "RepositorioDeJobs",
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
        job: "Job",
        novo: NovaCorrecao,
        autoria: Autoria,
        *,
        exige_aprovacao: bool,
    ) -> tuple[Correcao, str]:
        """A Correção gravada e a versão da Decupagem em que ela se apoia."""
        modelo, versao = ler_modelo(self._decupagens, job.id)
        correcao = corrigir(
            modelo,
            versao,
            self._correcoes.listar(job.id),
            novo,
            job.id,
            autoria,
            exige_aprovacao=exige_aprovacao,
            catalogo=self._catalogo,
            marcas=self._marcas,
        )
        self._gravar(job, correcao, autoria)
        return correcao, versao

    def desfazer(
        self, job: "Job", alvo_id: str, motivo: str, autoria: Autoria
    ) -> Correcao:
        return self._sobre_o_modelo(
            job,
            lambda m, v, todas: desfazer(m, v, todas, alvo_id, motivo, job.id, autoria),
            autoria,
            NaoDesfazivel,
        )

    def reaplicar(
        self, job: "Job", alvo_id: str, item_id: str, motivo: str, autoria: Autoria
    ) -> Correcao:
        return self._sobre_o_modelo(
            job,
            lambda m, v, todas: reaplicar(
                m, v, todas, alvo_id, item_id, motivo, job.id, autoria
            ),
            autoria,
            NaoNaFila,
        )

    def descartar(
        self, job: "Job", alvo_id: str, motivo: str, autoria: Autoria
    ) -> Correcao:
        return self._sobre_o_modelo(
            job,
            lambda m, v, todas: descartar(
                m, v, todas, alvo_id, motivo, job.id, autoria
            ),
            autoria,
            NaoNaFila,
        )

    def decidir(
        self, job: "Job", alvo_id: str, aprovada: bool, motivo: str, autoria: Autoria
    ) -> Correcao:
        """Aprova ou recusa uma Correção pendente; não lê a Decupagem antes de gravar."""
        registro = decidir(
            self._correcoes.listar(job.id),
            alvo_id,
            aprovada,
            motivo,
            job.id,
            autoria,
        )
        return self._gravar(job, registro, autoria, NaoPendente)

    def _sobre_o_modelo(
        self,
        job: "Job",
        regra: Callable[[dict[str, Any], str, list[Correcao]], Correcao],
        autoria: Autoria,
        se_ja_existe: type[Exception],
    ) -> Correcao:
        """Lê o modelo e as Correções, aplica a regra e grava o registro que ela devolve."""
        modelo, versao = ler_modelo(self._decupagens, job.id)
        registro = regra(modelo, versao, self._correcoes.listar(job.id))
        return self._gravar(job, registro, autoria, se_ja_existe)

    def _gravar(
        self,
        job: "Job",
        registro: Correcao,
        autoria: Autoria,
        se_ja_existe: type[Exception] | None = None,
    ) -> Correcao:
        """Grava, registra o evento e atualiza o Catálogo do Job. `se_ja_existe` é a exceção
        da operação para o registro que outro pedido gravou no meio."""
        try:
            self._correcoes.acrescentar(registro)
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
        atualizar_catalogo_do_job(job, self._jobs, self._leitura)
        return registro
