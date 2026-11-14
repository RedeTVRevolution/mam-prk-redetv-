"""Conjunto de regressão (#253): trechos de vídeo com o esperado por categoria.

Cada caso é um JSON em `evals/regressao/casos/`, sem vídeo: aponta o vídeo pelo SHA-256 do
bloco `video` da Decupagem (o do arquivo enviado, o mesmo do gabarito do comparador). O esperado usa os `Item` e os tipos do `api/comparador.py`, então o
comparador mede um caso como mede um gabarito. Duas origens: `anotado` (o CSV do gabarito,
#252) e `correcao` (uma correção em vigor, com o Job, o trecho e a versão do pipeline que
errou). Cada caso tem `reservado`: os reservados só entram na avaliação final e nunca no
ajuste de instrução; o sorteio é pelo id, então o caso fica sempre do mesmo lado.
`evals/regressao/metas.json` guarda a meta de cada requisito (o #252 preenche).

Comando: `make exportar-regressao [PASTA=evals/regressao/casos]` grava os casos das
correções em vigor (aprovadas, ou de tipo que não exige aprovação, e não desfeitas).
Ambiente: `GCP_PROJECT_ID`, `BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`.
"""

import hashlib
import json
import logging
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.ambiente import FaltaNoAmbiente, exigir_do_ambiente
from api.bancos import cliente_do_firestore
from api.comparador import Item, Tipo
from api.correcoes import (
    CORRIGIVEIS,
    Correcao,
    RepositorioDeCorrecoes,
    tempos_de,
    versao_do_modelo,
)
from api.erros import ServicoIndisponivel
from api.identidade import identidade_do_nome
from api.jobs import RepositorioDeJobs
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)
from api.regras_das_correcoes import estado_das
from api.reprocessar_versao import LeitorDeDecupagem

log = logging.getLogger(__name__)

PASTA_DOS_CASOS = Path("evals/regressao/casos")
ARQUIVO_DE_METAS = Path("evals/regressao/metas.json")
PERCENTUAL_RESERVADO = 20

__all__ = [
    "Caso",
    "ItemEsperado",
    "caso_do_gabarito",
    "casos_das_correcoes",
    "exportar",
    "gravar_caso",
    "id_do_caso_anotado",
    "ler_casos",
    "ler_metas",
    "main",
    "para_ajuste",
    "reservado_pelo_sorteio",
    "reservados",
]


def reservado_pelo_sorteio(id: str) -> bool:
    """Estável: depende só do id do caso, nunca da ordem nem do que já existe."""
    return int(hashlib.sha256(id.encode()).hexdigest()[:8], 16) % 100 < (
        PERCENTUAL_RESERVADO
    )


class ItemEsperado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Tipo
    identidade: str
    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _inicio_antes_do_fim(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        return self

    @classmethod
    def de(cls, item: Item) -> Self:
        return cls(
            tipo=item.tipo,
            identidade=item.identidade,
            inicio_ms=item.inicio_ms,
            fim_ms=item.fim_ms,
        )

    def como_item(self) -> Item:
        return Item(self.tipo, self.identidade, self.inicio_ms, self.fim_ms)


class CorrecaoDoCaso(BaseModel):
    """O que o modelo errou e como ficou, como na correção aprovada."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tipo: str
    antes: str
    depois: str


class Caso(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=120)]
    origem: Literal["anotado", "correcao"]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    inicio_ms: Annotated[int, Field(ge=0)]
    fim_ms: Annotated[int, Field(ge=0)]
    esperado: Annotated[list[ItemEsperado], Field(min_length=1)]
    reservado: bool
    # Só no caso de correção: o Job, a versão do pipeline que errou (`None` na decupagem
    # anterior à versão) e a correção.
    job_id: str | None = None
    versao_pipeline: str | None = None
    correcao: CorrecaoDoCaso | None = None

    @model_validator(mode="after")
    def _coerente(self) -> Self:
        if self.inicio_ms > self.fim_ms:
            raise ValueError("início depois do fim")
        if self.reservado != reservado_pelo_sorteio(self.id):
            raise ValueError(f"{self.id}: `reservado` não é o do sorteio do id")
        if self.origem == "correcao" and (self.job_id is None or not self.correcao):
            raise ValueError(f"{self.id}: caso de correção pede `job_id` e `correcao`")
        return self

    def itens(self) -> list[Item]:
        return [e.como_item() for e in self.esperado]


def prefixo_do_caso_anotado(sha256: str) -> str:
    """O começo do id de todo caso anotado do vídeo, qualquer que seja o trecho."""
    return f"anotado-{sha256[:12]}-"


def id_do_caso_anotado(sha256: str, inicio_ms: int, fim_ms: int) -> str:
    return f"{prefixo_do_caso_anotado(sha256)}{inicio_ms}-{fim_ms}"


def caso_do_gabarito(
    sha256: str,
    itens: list[Item],
    inicio_ms: int | None = None,
    fim_ms: int | None = None,
) -> Caso:
    """Um caso anotado: o trecho é o pedido ou, sem ele, do primeiro ao último item."""
    inicio = min(i.inicio_ms for i in itens) if inicio_ms is None else inicio_ms
    fim = max(i.fim_ms for i in itens) if fim_ms is None else fim_ms
    id = id_do_caso_anotado(sha256, inicio, fim)
    return Caso(
        id=id,
        origem="anotado",
        sha256=sha256,
        inicio_ms=inicio,
        fim_ms=fim,
        esperado=[ItemEsperado.de(i) for i in itens],
        reservado=reservado_pelo_sorteio(id),
    )


def reservados(casos: Iterable[Caso]) -> list[Caso]:
    """Só a avaliação final usa."""
    return [c for c in casos if c.reservado]


def para_ajuste(casos: Iterable[Caso]) -> list[Caso]:
    """O que se pode olhar para ajustar instrução: nunca um reservado."""
    return [c for c in casos if not c.reservado]


def ler_casos(pasta: Path) -> list[Caso]:
    casos: list[Caso] = []
    for arq in sorted(pasta.glob("*.json")):
        try:
            casos.append(Caso.model_validate_json(arq.read_bytes()))
        except ValueError as e:  # pydantic.ValidationError é ValueError
            raise ValueError(f"{arq.name}: {e}") from e
    return casos


def gravar_caso(pasta: Path, caso: Caso) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{caso.id}.json"
    destino.write_text(
        json.dumps(caso.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destino


def ler_metas(caminho: Path = ARQUIVO_DE_METAS) -> dict[str, float]:
    """A meta de cada requisito, de 0 a 1: `{"requisito": 0.95}`."""
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise TypeError(f"{caminho.name}: deve ser um objeto requisito -> meta")
    metas: dict[str, float] = {}
    for requisito, meta in dados.items():
        if (
            not requisito.strip()
            or isinstance(meta, bool)
            or not isinstance(meta, int | float)
            or not 0 <= meta <= 1
        ):
            raise ValueError(f"{caminho.name}: meta de {requisito!r} deve ir de 0 a 1")
        metas[requisito] = float(meta)
    return metas


_CATEGORIA_DO_ITEM: dict[str, Tipo] = {
    "pauta": "pauta",
    "comercial": "comercial",
    "plano": "plano",
    "fala": "fala",
    "texto_na_tela": "texto_na_tela",
}
# O `depois` é o nome novo do item: vira a identidade esperada nesta e nas outras
# correções do mesmo item (a renomeação e os tempos de uma pessoa não se contradizem).
_NOME_NOVO: dict[str, Callable[[str], str]] = {
    "pessoa.renomear": lambda depois: depois,
    "comercial.marca": lambda depois: depois,
    "texto_na_tela.texto": lambda depois: str(json.loads(depois)["texto"]),
    "pauta.titulo": lambda depois: depois,
}
# Dizem o que a pessoa não é: não há item esperado para medir.
_SEM_ITEM = frozenset({"pessoa.nao_e"})


def _nomes_novos(
    correcoes: list[Correcao], em_vigor: Callable[[str], bool]
) -> dict[str, str]:
    """O nome em vigor de cada item renomeado, pelo `item_id`; a mais nova vence."""
    nomes: dict[str, str] = {}
    for c in sorted(correcoes, key=lambda c: c.criada_em):
        if c.tipo in _NOME_NOVO and em_vigor(c.id):
            nomes[f"{c.ancora.tipo_do_item}:{c.item_id}"] = _NOME_NOVO[c.tipo](c.depois)
    return nomes


def _aparicoes_no_modelo(
    modelo: Mapping[str, Any], item_id: str
) -> list[tuple[int, int]]:
    for pessoa in modelo.get("pessoas", []):
        if isinstance(pessoa, dict) and pessoa.get("id") == item_id:
            return [(a["inicio_ms"], a["fim_ms"]) for a in pessoa.get("na_imagem", [])]
    return []


def _itens_da_pessoa(
    c: Correcao, nome: str | None, modelo: Mapping[str, Any]
) -> list[Item]:
    """Pessoa sem nome não se pareia no comparador; a correção da ocorrência mede
    só ela, e a do nome mede todas as aparições da pessoa."""
    if c.tipo == "pessoa.acrescentar_aparicao":
        nova = json.loads(c.depois)
        nome = nova.get("nome") or nome
        intervalos = [(nova["inicio_ms"], nova["fim_ms"])]
        categoria: Tipo = "aparicao"
    elif c.ocorrencia is not None:
        o = c.ocorrencia
        intervalos = [
            tempos_de(c.depois) if c.tipo == "item.tempos" else (o.inicio_ms, o.fim_ms)
        ]
        if c.tipo == "pessoa.aparicao_para_mencao":
            categoria = "mencao"
        elif c.tipo == "pessoa.mencao_para_aparicao" or o.lista == "na_imagem":
            categoria = "aparicao"
        else:
            categoria = "mencao"
    else:
        intervalos = _aparicoes_no_modelo(modelo, c.item_id)
        categoria = "aparicao"
    if nome is None or identidade_do_nome(nome) is None:
        return []
    return [Item(categoria, nome, inicio, fim) for inicio, fim in intervalos]


def _itens_da_correcao(
    c: Correcao, nomes: Mapping[str, str], modelo: Mapping[str, Any]
) -> list[Item]:
    a = c.ancora
    if c.tipo in _SEM_ITEM:
        return []
    nome = nomes.get(f"{a.tipo_do_item}:{c.item_id}")
    if a.tipo_do_item == "pessoa":
        return _itens_da_pessoa(c, nome or a.identidade, modelo)
    if a.tipo_do_item == "comercial":
        # A âncora do comercial é `marca|tipo`; o comparador pareia pela marca.
        nome = nome or a.identidade.rsplit("|", 1)[0]
    inicio, fim = a.inicio_ms, a.fim_ms
    if c.tipo == "item.tempos":
        inicio, fim = tempos_de(c.depois)
    return [Item(_CATEGORIA_DO_ITEM[a.tipo_do_item], nome or a.identidade, inicio, fim)]


def casos_das_correcoes(
    modelo: Mapping[str, Any], versao: str, correcoes: list[Correcao]
) -> list[Caso]:
    """Um caso por correção em vigor feita sobre este JSON do modelo (`versao`, o
    SHA-256 do arquivo), com o Job e a versão do pipeline que errou.

    A correção feita sobre outro JSON (antes de um reprocessamento) fica de fora:
    a versão do pipeline que errou e o trecho são os daquele JSON, que não é este.
    """
    sha256 = str(modelo["video"]["sha256"])
    versao_pipeline = modelo.get("versao_pipeline")
    estado = estado_das(correcoes)
    nomes = _nomes_novos(correcoes, estado.em_vigor)
    casos: list[Caso] = []
    for c in correcoes:
        if c.tipo not in CORRIGIVEIS or not estado.em_vigor(c.id):
            continue
        if c.ancora.versao != versao:
            log.warning("correção %s de outro JSON do modelo: fora do conjunto", c.id)
            continue
        try:
            esperado = _itens_da_correcao(c, nomes, modelo)
        except (ValueError, KeyError, TypeError):
            log.warning("correção %s com valor ilegível: fora do conjunto", c.id)
            continue
        if not esperado:
            continue
        # O trecho cobre o que o modelo entregou (a âncora) e o que ficou.
        inicio = min(c.ancora.inicio_ms, *(e.inicio_ms for e in esperado))
        fim = max(c.ancora.fim_ms, *(e.fim_ms for e in esperado))
        id = f"correcao-{c.id}".lower()
        casos.append(
            Caso(
                id=id,
                origem="correcao",
                sha256=sha256,
                inicio_ms=inicio,
                fim_ms=fim,
                esperado=[ItemEsperado.de(e) for e in esperado],
                reservado=reservado_pelo_sorteio(id),
                job_id=c.job_id,
                versao_pipeline=str(versao_pipeline) if versao_pipeline else None,
                correcao=CorrecaoDoCaso(
                    id=c.id, tipo=c.tipo, antes=c.antes, depois=c.depois
                ),
            )
        )
    return casos


def exportar(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    pasta: Path,
    escrever: Callable[[str], None] = print,
) -> list[Caso]:
    """Grava os casos das correções dos Jobs concluídos; o mesmo caso sai no mesmo
    arquivo. O caso de uma correção deste JSON que deixou de valer (desfeita,
    recusada) sai da pasta; o de uma correção de outro JSON fica como está."""
    gravados: list[Caso] = []
    for job in sorted(repositorio.listar(), key=lambda j: (j.criado_em, j.id)):
        if job.estado != "concluido":
            continue
        feitas = correcoes.listar(job.id)
        if not feitas:
            continue
        try:
            conteudo = b"".join(decupagens.abrir_decupagem(job.id))
            versao = versao_do_modelo(conteudo)
            casos = casos_das_correcoes(json.loads(conteudo), versao, feitas)
        except (ServicoIndisponivel, ValueError, KeyError, TypeError):
            log.warning("decupagem de %s não lida: fora do conjunto", job.id)
            continue
        for caso in casos:
            gravar_caso(pasta, caso)
        validos = {caso.id for caso in casos}
        for c in feitas:
            id = f"correcao-{c.id}".lower()
            if c.ancora.versao == versao and id not in validos:
                (pasta / f"{id}.json").unlink(missing_ok=True)
        gravados += casos
    separados = sum(c.reservado for c in gravados)
    escrever(
        f"{len(gravados)} casos gravados em {pasta} "
        f"({separados} reservados, {len(gravados) - separados} para ajuste)"
    )
    return gravados


def main(argumentos: list[str], ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    pasta = Path(argumentos[0]) if argumentos and argumentos[0] else PASTA_DOS_CASOS
    banco = cliente_do_firestore(projeto)
    exportar(
        RepositorioFirestore(banco),
        DecupagensStorage(ClienteStorage(project=projeto), aceitos, decupagens),
        RepositorioDeCorrecoesFirestore(banco),
        pasta,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
