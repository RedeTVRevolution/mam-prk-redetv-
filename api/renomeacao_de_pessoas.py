"""Renomear uma pessoa em todos os vídeos de uma vez (E3, #263), em
`/v1/catalogo/pessoas/{id_da_pessoa}/renomear`.

O nome novo vale no catálogo e na leitura de todas as Decupagens na mesma hora (veja
`com_pessoas_fundidas`: o gravado não é reescrito, ADR 0010), então catálogo e decupagens
nunca ficam com nomes diferentes. O índice da busca e a cópia no BigQuery não guardam o
nome da pessoa, só o `catalogo_id` (#417): a renomeação não reindexa nem copia nada, e a
busca e o relatório de tempo de tela leem o nome novo do catálogo.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints, field_validator

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.catalogo import Catalogo, PessoaDoCatalogo, RenomeacaoDaPessoa
from api.catalogo_apagado import com_pessoas_fundidas
from api.comparador import normalizar
from api.correcoes import LIMITE_DO_NOME, RepositorioDeCorrecoes, _sem_controle
from api.jobs import RepositorioDeJobs, _confere_permissao
from api.lixeira_do_catalogo import LeituraDeDecupagens, decupagens_dos_jobs


class PedidoDeRenomeacao(BaseModel):
    nome: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME
        ),
    ]
    previa: bool = False

    _sem_controle_no_nome = field_validator("nome")(_sem_controle)


class ImpactoDaRenomeacao(BaseModel):
    nome_antigo: str
    nome_novo: str
    # Vídeos (concluídos, fora da lixeira) onde a pessoa aparece ou é citada, e os momentos
    # (aparições na imagem e citações na fala e no texto) que passam a mostrar o nome novo.
    videos: int
    momentos_afetados: int
    previa: bool


class AndamentoDaRenomeacao(BaseModel):
    estado: Literal["em_andamento", "concluida", "falhou"]
    feitos: int
    total: int
    nome_antigo: str
    nome_novo: str


def _exige_aprovar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `correcao.aprovar` (Curador); chave de sistema não mexe no catálogo."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não mexe no catálogo")
    _confere_permissao(request, chamador, "correcao.aprovar")
    return chamador


def _andamento(r: RenomeacaoDaPessoa) -> AndamentoDaRenomeacao:
    return AndamentoDaRenomeacao(
        estado=r.estado,
        feitos=r.total - len(r.pendentes),
        total=r.total,
        nome_antigo=r.nome_antigo,
        nome_novo=r.nome_novo,
    )


def criar_rotas_da_renomeacao(
    pessoas: Catalogo,
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: LeituraDeDecupagens,
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
        for job, entregue in decupagens_dos_jobs(repositorio, correcoes, decupagens):
            entregue = com_pessoas_fundidas(entregue, pessoas.obter)
            nelas = [
                p
                for p in entregue.get("pessoas") or []
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
        autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> ImpactoDaRenomeacao:
        pessoa = viva(id_da_pessoa)
        if pessoa.renomeacao is not None and pessoa.renomeacao.estado != "concluida":
            raise HTTPException(
                409, "A renomeação anterior ainda não terminou: aguarde ou retome"
            )
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
                total=len(ids),
                pendentes=[],
                estado="concluida",
            ),
        )
        try:
            auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=quando,
                    uid=autor.uid,
                    email=autor.email,
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

    @rotas.get("/pessoas/{id_da_pessoa}/renomear/andamento")
    def andamento(
        id_da_pessoa: str,
        _autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> AndamentoDaRenomeacao:
        pessoa = pessoas.obter(id_da_pessoa)
        if pessoa is None or pessoa.renomeacao is None:
            raise HTTPException(404, "Nenhuma renomeação desta pessoa")
        return _andamento(pessoa.renomeacao)

    @rotas.post("/pessoas/{id_da_pessoa}/renomear/retomar")
    def retomar(
        id_da_pessoa: str,
        _autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> AndamentoDaRenomeacao:
        """Fecha uma renomeação que ficou em andamento antes de o índice largar o nome:
        não há mais o que reindexar."""
        pessoa = pessoas.obter(id_da_pessoa)
        if pessoa is None or pessoa.renomeacao is None:
            raise HTTPException(404, "Nenhuma renomeação desta pessoa")
        r = pessoa.renomeacao
        if r.estado != "concluida":
            r = r.model_copy(update={"estado": "concluida", "pendentes": []})
            pessoas.definir_renomeacao(pessoa.id, r)
        return _andamento(r)

    return rotas
