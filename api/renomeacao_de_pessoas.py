"""Renomear uma pessoa em todos os vídeos de uma vez (E3, #263), em
`/v1/catalogo/pessoas/{id_da_pessoa}/renomear`.

O nome novo vale no catálogo e na leitura de todas as Decupagens na mesma hora (veja
`api.quem_conta`: o gravado não é reescrito, ADR 0010), então catálogo e decupagens
nunca ficam com nomes diferentes. O índice da busca e a cópia no BigQuery não guardam o
nome da pessoa, só o `catalogo_id` (#417): a renomeação não reindexa nem copia nada, e a
busca e o relatório de tempo de tela leem o nome novo do catálogo.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auditoria import RepositorioDeAuditoria, registro_de_auditoria
from api.auth import Usuario
from api.catalogo import (
    Catalogo,
    PessoaDoCatalogo,
    RenomeacaoDaPessoa,
)
from api.correcoes import RepositorioDeCorrecoes, sem_controle
from api.decupagem import LIMITE_DO_NOME
from api.leitura_da_decupagem import AbreDecupagem, decupagens_dos_jobs
from api.modelo_do_job import FiltroDeJobs, RepositorioDeJobs
from api.permissoes import exige
from api.texto import normalizar
from api.texto_como_dado import Linha


class PedidoDeRenomeacao(BaseModel):
    nome: Annotated[str, Linha(LIMITE_DO_NOME, min_length=1, strip=True)]
    previa: bool = False

    _sem_controle_no_nome = field_validator("nome")(sem_controle)


class ImpactoDaRenomeacao(BaseModel):
    nome_antigo: str
    nome_novo: str
    # Vídeos (concluídos, fora da lixeira) onde a pessoa aparece ou é citada, e os momentos
    # (aparições na imagem e citações na fala e no texto) que passam a mostrar o nome novo.
    videos: int
    momentos_afetados: int
    previa: bool


def criar_rotas_da_renomeacao(
    pessoas: Catalogo,
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: AbreDecupagem,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
    ao_renomear: Callable[[], None],
) -> APIRouter:
    """`ao_renomear` descarta a cópia da lista de pessoas."""
    rotas = APIRouter()

    def viva(id: str) -> PessoaDoCatalogo:
        pessoa = pessoas.obter(id)
        if pessoa is None:
            raise HTTPException(404, "Pessoa não encontrada")
        if pessoa.lixeira is not None or pessoa.fundida is not None:
            raise HTTPException(
                422, "Esta pessoa está na lixeira ou já foi fundida em outra"
            )
        return pessoa

    def afetados(pessoa: PessoaDoCatalogo) -> tuple[list[str], int]:
        """Os vídeos em que o nome da pessoa muda (pela leitura de hoje) e quantos momentos
        ela tem neles; onde o editor pôs outro nome no vídeo, nada muda e não conta."""
        ids: list[str] = []
        momentos = 0
        nome = normalizar(pessoa.nome)
        for job, corrigida in decupagens_dos_jobs(
            repositorio,
            correcoes,
            decupagens,
            pessoas,
            FiltroDeJobs(pessoa_do_catalogo=pessoa.id),
        ):
            nelas = [
                p
                for p in corrigida.get("pessoas") or []
                if isinstance(p, dict)
                and p.get("catalogo_id") == pessoa.id
                and normalizar(str(p.get("nome"))) == nome
            ]
            if not nelas:
                continue
            ids.append(job.id)
            momentos += sum(
                len(p.get(campo) or [])
                for p in nelas
                for campo in ("na_imagem", "citada_na_fala", "citada_no_texto")
            )
        return ids, momentos

    @rotas.post("/pessoas/{id_da_pessoa}/renomear")
    def renomear(
        id_da_pessoa: str,
        pedido: PedidoDeRenomeacao,
        autor: Annotated[
            Usuario,
            Depends(exige("correcao.aprovar", "Chave de sistema não mexe no catálogo")),
        ],
    ) -> ImpactoDaRenomeacao:
        pessoa = viva(id_da_pessoa)
        novo = pedido.nome
        if novo == pessoa.nome:
            raise HTTPException(422, "O nome novo é igual ao atual")
        if any(o.id != pessoa.id for o in pessoas.achar(novo)):
            raise HTTPException(
                422, "Já existe outra pessoa com esse nome: use Fundir com…"
            )
        ids, momentos = afetados(pessoa)
        impacto = ImpactoDaRenomeacao(
            nome_antigo=pessoa.nome,
            nome_novo=novo,
            videos=len(ids),
            momentos_afetados=momentos,
            previa=pedido.previa,
        )
        if pedido.previa:
            return impacto
        quando = relogio()
        anteriores = (
            list(pessoa.renomeacao.nomes_anteriores) if pessoa.renomeacao else []
        )
        if normalizar(pessoa.nome) not in {normalizar(n) for n in anteriores}:
            anteriores.append(pessoa.nome)
        # O nome antigo fica como apelido (como na fusão): a busca e a tarja antiga ainda acham a pessoa.
        apelidos = list(pessoa.apelidos)
        if normalizar(pessoa.nome) not in {normalizar(a) for a in apelidos}:
            apelidos.append(pessoa.nome)
        apelidos = [a for a in apelidos if normalizar(a) != normalizar(novo)]
        pessoas.corrigir(pessoa.id, nome=novo, apelidos=apelidos)
        pessoas.definir_renomeacao(
            pessoa.id,
            RenomeacaoDaPessoa(
                nome_antigo=pessoa.nome,
                nome_novo=novo,
                nomes_anteriores=anteriores,
                em=quando,
                por_uid=autor.uid,
                por_email=autor.email.lower(),
            ),
        )
        try:
            auditoria.acrescentar(
                registro_de_auditoria(
                    quando=quando,
                    quem=autor,
                    acao="pessoa.renomeada",
                    alvo_tipo="pessoa",
                    alvo_id=pessoa.id,
                    alvo_nome=novo,
                    detalhes={
                        "nome_antigo": pessoa.nome,
                        "nome_novo": novo,
                        "videos": len(ids),
                        "momentos_afetados": momentos,
                    },
                )
            )
        except Exception:
            # Sem registro a troca não vale: desfaz.
            pessoas.corrigir(pessoa.id, nome=pessoa.nome, apelidos=pessoa.apelidos)
            pessoas.definir_renomeacao(pessoa.id, pessoa.renomeacao)
            ao_renomear()
            raise
        ao_renomear()
        return impacto

    return rotas
