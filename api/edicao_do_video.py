"""Editar a data de exibição e o programa de um vídeo já decupado (#519).

Só a pessoa com `decupagem.editar`, só em Job `concluido`. A edição grava o Job, pede a
reindexação (`versao_pedida`, como a troca do nome do programa, #419) e registra a auditoria
com o valor antigo e o novo; a decupagem não é refeita (nenhuma chamada ao Gemini). A cópia
do BigQuery acumula os anos já copiados (`copia_bigquery.anos`), então a troca de ano limpa
as linhas do ano antigo na próxima cópia.
"""

import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import Usuario
from api.jobs import (
    FUSO_DA_EMISSORA,
    DisparoDaIndexacao,
    Indexacao,
    JobPublico,
    RepositorioDeJobs,
    _exige_editar,
)
from api.programas import RepositorioDeProgramas
from api.texto_como_dado import Linha


class EdicaoDoVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_exibicao: date | None = None
    programa: Annotated[str, Linha(100)] | None = None

    @field_validator("data_exibicao", mode="before")
    @classmethod
    def _data_so_como_texto(cls, valor: Any) -> Any:
        # Como no `NovoJob`: só "AAAA-MM-DD" (um número viraria timestamp).
        if valor is not None and not (isinstance(valor, str) and len(valor) == 10):
            raise ValueError("data_exibicao deve ser texto AAAA-MM-DD")
        return valor

    @model_validator(mode="after")
    def _algo_a_mudar(self) -> "EdicaoDoVideo":
        if self.data_exibicao is None and self.programa is None:
            raise ValueError("informe data_exibicao e/ou programa")
        return self


def criar_rotas_da_edicao(
    repositorio: RepositorioDeJobs,
    programas: RepositorioDeProgramas,
    auditoria: RepositorioDeAuditoria,
    disparo: DisparoDaIndexacao,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")

    @rotas.patch("/{job_id}")
    def editar(
        job_id: str,
        pedido: EdicaoDoVideo,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> JobPublico:
        job = repositorio.obter(job_id)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        if job.estado != "concluido":
            raise HTTPException(409, f"Job em {job.estado}, não concluido")
        agora = relogio()
        if (
            pedido.data_exibicao is not None
            and pedido.data_exibicao > agora.astimezone(FUSO_DA_EMISSORA).date()
        ):
            raise HTTPException(422, "Data de exibição no futuro")
        if pedido.programa is not None:
            validos = sorted(p.nome for p in programas.listar())
            if pedido.programa not in validos:
                raise HTTPException(
                    422, "programa sem perfil; programas válidos: " + ", ".join(validos)
                )
        antes: dict[str, str | None] = {}
        depois: dict[str, str | None] = {}
        if pedido.data_exibicao not in (None, job.data_exibicao):
            antes["data_exibicao"] = (
                job.data_exibicao.isoformat() if job.data_exibicao else None
            )
            depois["data_exibicao"] = pedido.data_exibicao.isoformat()
        if pedido.programa not in (None, job.programa):
            antes["programa"], depois["programa"] = job.programa, pedido.programa
        if not depois:
            # Um disparo que falhou (503) deixa a `versao_pedida` gravada: repetir o pedido
            # o refaz, sem nova auditoria, se a indexação não está em andamento.
            if job.versao_pedida > job.versao_indexada and (
                job.indexacao is None or job.indexacao.estado != "pendente"
            ):
                disparo.iniciar(job.id)
            return JobPublico.de(job)
        # O registro vem antes de gravar: nunca há edição sem rastro.
        auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=agora,
                uid=autor.uid,
                email=autor.email,
                acao="video.editado",
                alvo_tipo="job",
                alvo_id=job.id,
                alvo_nome=job.nome,
                detalhes={"antes": antes, "depois": depois},
            )
        )
        anterior = job.indexacao

        def mudar(atual: Any) -> dict[str, Any] | None:
            if atual.estado != "concluido":
                return None
            mudancas: dict[str, Any] = {
                "versao_pedida": max(atual.versao_pedida, atual.versao_indexada) + 1,
                "indexacao": Indexacao(estado="pendente", em=agora),
            }
            if pedido.data_exibicao is not None:
                # `model_copy` não roda o validador que deriva o mês.
                mudancas["data_exibicao"] = pedido.data_exibicao
                mudancas["mes_exibicao"] = pedido.data_exibicao.isoformat()[:7]
            if pedido.programa is not None:
                mudancas["programa"] = pedido.programa
            return mudancas

        gravado = repositorio.trocar(job.id, mudar)
        if gravado is None:
            raise HTTPException(409, "O vídeo saiu de concluído")
        try:
            disparo.iniciar(job.id)
        except Exception:
            # A edição e a `versao_pedida` ficam: o próximo disparo as atende.
            repositorio.transitar(job.id, "concluido", {"indexacao": anterior})
            raise
        return JobPublico.de(gravado)

    return rotas
