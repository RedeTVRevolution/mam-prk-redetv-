"""Porta do índice da busca (#117): um registro por plano, fala, texto na tela e ocorrência de objeto.

O adaptador do Agent Retrieval mora em `agent_retrieval.py`; o dublê em memória daqui
implementa os filtros exatos e o texto, e é o que os testes usam.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

from api.comparador import normalizar
from api.decupagem import (
    CategoriaDeObjeto,
    Decupagem,
    ObjetoDoInventario,
    Pessoa,
    _Intervalo,
)
from api.identidade import nao_identificado

TipoDeRegistro = Literal["plano", "fala", "texto_na_tela", "objeto"]


@dataclass(frozen=True)
class Registro:
    id: str
    tipo: TipoDeRegistro
    job_id: str
    inicio_ms: int
    fim_ms: int
    programa: str | None = None
    data_de_exibicao: date | None = None
    pessoas: list[str] = field(default_factory=list)  # ids do catálogo, na imagem
    # Só no registro de objeto.
    categoria: str | None = None
    tipo_do_objeto: str | None = None
    cor_base: list[str] = field(default_factory=list)
    cor: str | None = None
    marca: str | None = None
    dono: str | None = None  # o `catalogo_id` da pessoa
    relacao: str | None = None
    # Fala, texto na tela ou a frase do objeto: o que a busca por texto lê.
    texto: str | None = None
    descricao: str | None = None  # o plano; leva o vetor da descrição
    quadro: str | None = None  # o JPEG do momento, para a grade da busca
    # De 1 a 3, só no objeto do inventário (#245); pesa na ordem dos resultados.
    destaque: int | None = None


@dataclass(frozen=True)
class Filtros:
    """Igualdade exata; o que for `None` não filtra. Um registro tem de casar com todos."""

    tipo: TipoDeRegistro | None = None
    job_id: str | None = None
    programa: str | None = None
    categoria: str | None = None
    cor_base: str | None = None  # uma das cores do objeto
    dono: str | None = None
    pessoa: str | None = None  # uma das pessoas na imagem
    marca: str | None = None
    relacao: str | None = None
    exibido_desde: date | None = None
    exibido_ate: date | None = None


@dataclass(frozen=True)
class Consulta:
    filtros: Filtros = field(default_factory=Filtros)
    texto: str | None = None
    # Texto para a busca por significado na descrição (embedding automático).
    significado: str | None = None
    limite: int = 20
    # O que vem só da busca por significado passa pelo corte da configuração; o que a
    # busca por texto acha fica. Falso quando o significado só leva os filtros ao índice.
    cortar_significado: bool = False


class IndiceDaBusca(Protocol):
    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        """Os registros do vídeo; os que já havia dele saem."""

    def apagar(self, job_id: str) -> None: ...

    def buscar(self, consulta: Consulta) -> list[Registro]: ...

    def total(self) -> int:
        """Quantos registros há no índice, de todos os vídeos."""
        ...


def palavras(texto: str) -> list[str]:
    """As palavras como o índice real as separa: sem acento, maiúscula nem pontuação."""
    return re.findall(r"\w+", normalizar(texto))


def _frase(*partes: str | None) -> str | None:
    texto = " ".join(p for p in partes if p)
    return texto or None


# A categoria como a tela a mostra (`web/src/painel.ts`), para a consulta em português casar.
NOME_DA_CATEGORIA: dict[CategoriaDeObjeto, str] = {
    "roupa": "roupa",
    "calcado": "calçado",
    "acessorio": "acessório",
    "na_mao": "na mão",
    "em_cena": "em cena",
    "veiculo": "veículo",
    "outro": "outro",
    "eletronico": "eletrônico",
    "produto": "produto",
    "animal": "animal",
    "alimento": "alimento",
    "movel": "móvel",
    "decoracao": "decoração",
    "instrumento_musical": "instrumento musical",
    "utensilio": "utensílio",
    "documento": "documento",
    "planta": "planta",
    "bebida": "bebida",
}
# O dono de quem não tem nome, e o do objeto sem pessoa.
DONO_SEM_NOME = "de pessoa não identificada"
SEM_DONO = "objeto de cena"


def _texto_curto(peca: str | None, categoria: CategoriaDeObjeto, dono: str) -> str:
    """A peça, a categoria e o dono ("blazer preto, roupa, de Flávia Noronha"; sem
    dono, "objeto de cena"): um objeto de uma palavra passa do piso de palavras da
    busca por significado."""
    return ", ".join(p for p in (peca, NOME_DA_CATEGORIA[categoria], dono) if p)


def _inventario_em_texto(inventario: list[ObjetoDoInventario]) -> str | None:
    """Todos os objetos do plano, para a consulta achar o plano por qualquer um deles."""
    itens = [
        f"{_frase(i.nome, i.cor, i.marca)} ({NOME_DA_CATEGORIA[i.categoria]})"
        for i in inventario
    ]
    return f"Objetos: {', '.join(itens)}" if itens else None


def registros_da_decupagem(
    job_id: str,
    decupagem: Decupagem,
    programa: str | None,
    data_de_exibicao: date | None,
) -> list[Registro]:
    """Os registros do índice de uma Decupagem.

    Pessoa e dono vão pelo `catalogo_id`; quem não tem não entra nas listas (a busca por
    pessoa só acha quem o catálogo conhece).
    """
    base: dict[str, Any] = {
        "job_id": job_id,
        "programa": programa,
        "data_de_exibicao": data_de_exibicao,
    }
    catalogo = {p.id: p.catalogo_id for p in decupagem.pessoas}

    def na_imagem(i: _Intervalo) -> list[str]:
        achados: list[str] = []
        for pessoa in decupagem.pessoas:
            if pessoa.catalogo_id and _aparece(pessoa, i):
                achados.append(pessoa.catalogo_id)
        return achados

    def quadro_do_plano(i: _Intervalo) -> str | None:
        """O quadro-chave do plano em que o momento começa."""
        for plano in decupagem.planos:
            if plano.inicio_ms <= i.inicio_ms < plano.fim_ms:
                return plano.quadro
        return None

    nomes = {p.id: p.nome for p in decupagem.pessoas}

    def dono(id: str | None) -> str:
        nome = nomes.get(id) if id else None
        if nome is None:
            return SEM_DONO
        return DONO_SEM_NOME if nao_identificado(nome) else f"de {nome}"

    registros: list[Registro] = []
    for n, plano in enumerate(decupagem.planos):
        registros.append(
            Registro(
                id=f"{job_id}:plano:{n}",
                tipo="plano",
                inicio_ms=plano.inicio_ms,
                fim_ms=plano.fim_ms,
                pessoas=na_imagem(plano),
                descricao=_frase(
                    plano.ambiente,
                    plano.acao,
                    ", ".join(plano.objetos),
                    _inventario_em_texto(plano.inventario),
                ),
                quadro=plano.quadro,
                **base,
            )
        )
        for k, item in enumerate(plano.inventario):
            registros.append(
                Registro(
                    id=f"{job_id}:inventario:{n}:{k}",
                    tipo="objeto",
                    inicio_ms=plano.inicio_ms,
                    fim_ms=plano.fim_ms,
                    categoria=item.categoria,
                    tipo_do_objeto=item.nome,
                    cor_base=[item.cor] if item.cor else [],
                    cor=item.cor,
                    marca=item.marca,
                    texto=_texto_curto(
                        _frase(item.nome, item.cor, item.marca),
                        item.categoria,
                        SEM_DONO,
                    ),
                    # O quadro da maior caixa, o mesmo que o player mostra.
                    quadro=max(item.caixas, key=lambda c: c.largura * c.altura).quadro,
                    destaque=item.destaque,
                    **base,
                )
            )
    for n, fala in enumerate(decupagem.transcricao):
        registros.append(
            Registro(
                id=f"{job_id}:fala:{n}",
                tipo="fala",
                inicio_ms=fala.inicio_ms,
                fim_ms=fala.fim_ms,
                pessoas=na_imagem(fala),
                texto=fala.texto,
                quadro=quadro_do_plano(fala),
                **base,
            )
        )
    for n, texto in enumerate(decupagem.textos_na_tela):
        registros.append(
            Registro(
                id=f"{job_id}:texto:{n}",
                tipo="texto_na_tela",
                inicio_ms=texto.inicio_ms,
                fim_ms=texto.fim_ms,
                pessoas=na_imagem(texto),
                texto=texto.texto,
                quadro=quadro_do_plano(texto),
                **base,
            )
        )
    for n, objeto in enumerate(decupagem.objetos):
        # Cada ocorrência é um momento: um registro do primeiro ao último aparecimento
        # viraria um bloco que aponta para o lugar errado.
        for k, ocorrencia in enumerate(objeto.ocorrencias):
            registros.append(
                Registro(
                    id=f"{job_id}:objeto:{n}:{k}",
                    tipo="objeto",
                    inicio_ms=ocorrencia.inicio_ms,
                    fim_ms=ocorrencia.fim_ms,
                    categoria=objeto.categoria,
                    tipo_do_objeto=objeto.tipo,
                    cor_base=list(objeto.cor_base),
                    cor=objeto.cor,
                    marca=objeto.marca,
                    dono=catalogo.get(objeto.pessoa) if objeto.pessoa else None,
                    relacao=objeto.relacao,
                    texto=_texto_curto(
                        _frase(
                            objeto.tipo,
                            objeto.cor or " ".join(objeto.cor_base),
                            objeto.marca,
                            objeto.detalhe,
                        ),
                        objeto.categoria,
                        dono(objeto.pessoa),
                    ),
                    # O quadro do objeto é o da primeira ocorrência.
                    quadro=(objeto.quadro if k == 0 else None)
                    or quadro_do_plano(ocorrencia),
                    **base,
                )
            )
    return registros


def _aparece(pessoa: Pessoa, i: _Intervalo) -> bool:
    return any(
        a.inicio_ms < i.fim_ms and i.inicio_ms < a.fim_ms for a in pessoa.na_imagem
    )


def _casa(r: Registro, f: Filtros) -> bool:
    return (
        (f.tipo is None or r.tipo == f.tipo)
        and (f.job_id is None or r.job_id == f.job_id)
        and (f.programa is None or r.programa == f.programa)
        and (f.categoria is None or r.categoria == f.categoria)
        and (f.cor_base is None or f.cor_base in r.cor_base)
        and (f.dono is None or r.dono == f.dono)
        and (f.pessoa is None or f.pessoa in r.pessoas)
        and (f.marca is None or r.marca == f.marca)
        and (f.relacao is None or r.relacao == f.relacao)
        and (
            f.exibido_desde is None
            or (
                r.data_de_exibicao is not None and r.data_de_exibicao >= f.exibido_desde
            )
        )
        and (
            f.exibido_ate is None
            or (r.data_de_exibicao is not None and r.data_de_exibicao <= f.exibido_ate)
        )
    )


class IndiceEmMemoria:
    """Dublê do índice: filtros exatos e texto (qualquer palavra inteira da consulta, sem acento nem maiúscula)."""

    def __init__(self) -> None:
        self._por_job: dict[str, list[Registro]] = {}

    def gravar(self, job_id: str, registros: list[Registro]) -> None:
        self._por_job[job_id] = list(registros)

    def apagar(self, job_id: str) -> None:
        self._por_job.pop(job_id, None)

    def total(self) -> int:
        return sum(len(r) for r in self._por_job.values())

    def buscar(self, consulta: Consulta) -> list[Registro]:
        da_consulta = palavras(consulta.texto) if consulta.texto else []
        achados: list[Registro] = []
        for registros in self._por_job.values():
            for r in registros:
                if not _casa(r, consulta.filtros):
                    continue
                palavras_do_registro = set(palavras(_frase(r.texto, r.descricao) or ""))
                if not da_consulta or any(
                    p in palavras_do_registro for p in da_consulta
                ):
                    achados.append(r)
        return achados[: consulta.limite]
