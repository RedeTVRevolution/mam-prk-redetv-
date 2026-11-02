"""Conjunto de regressão (#253): trechos de vídeo com o esperado por categoria.

Cada caso é um JSON em `evals/regressao/casos/`, sem vídeo (o vídeo fica no bucket, pelo
SHA-256 do proxy). O esperado usa os `Item` e os tipos do `api/comparador.py`, então o
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
from typing import Annotated, Literal, Self

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.comparador import TIPOS, Item, Tipo
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.correcoes import (
    CORRIGIVEIS,
    Correcao,
    RepositorioDeCorrecoes,
    estado_das,
    tempos_de,
)
from api.jobs import RepositorioDeJobs, ServicoIndisponivel
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)
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


def id_do_caso_anotado(sha256: str, inicio_ms: int, fim_ms: int) -> str:
    return f"anotado-{sha256[:12]}-{inicio_ms}-{fim_ms}"


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
    "pessoa": "aparicao",
    "pauta": "pauta",
    "comercial": "comercial",
    "plano": "plano",
    "fala": "fala",
    "texto_na_tela": "texto_na_tela",
}
_CATEGORIA_DO_TIPO: dict[str, Tipo] = {
    "pessoa.aparicao_para_mencao": "mencao",
    "pessoa.mencao_para_aparicao": "aparicao",
}
# O `depois` é o nome novo: vira a identidade esperada.
_DEPOIS_E_A_IDENTIDADE = frozenset(
    {"pessoa.renomear", "comercial.marca", "texto_na_tela.texto", "pauta.titulo"}
)
# Dizem o que a pessoa não é: não há item esperado para medir.
_SEM_ITEM = frozenset({"pessoa.nao_e"})


def _item_da_correcao(c: Correcao) -> Item | None:
    categoria = _CATEGORIA_DO_TIPO.get(c.tipo) or _CATEGORIA_DO_ITEM.get(
        c.ancora.tipo_do_item
    )
    if c.tipo in _SEM_ITEM or categoria is None or categoria not in TIPOS:
        return None
    inicio, fim = c.ancora.inicio_ms, c.ancora.fim_ms
    if c.tipo == "item.tempos":
        inicio, fim = tempos_de(c.depois)
    identidade = c.depois if c.tipo in _DEPOIS_E_A_IDENTIDADE else c.ancora.identidade
    return Item(categoria, identidade, inicio, fim)


def casos_das_correcoes(
    sha256: str,
    versao_pipeline: str | None,
    correcoes: list[Correcao],
) -> list[Caso]:
    """Um caso por correção em vigor, com o Job e a versão do pipeline que errou."""
    estado = estado_das(correcoes)
    casos: list[Caso] = []
    for c in correcoes:
        if c.tipo not in CORRIGIVEIS or not estado.em_vigor(c.id):
            continue
        try:
            esperado = _item_da_correcao(c)
        except ValueError:
            log.warning("correção %s com tempos ilegíveis: fora do conjunto", c.id)
            continue
        if esperado is None:
            continue
        # O trecho cobre o que o modelo entregou (a âncora) e o que ficou.
        inicio = min(esperado.inicio_ms, c.ancora.inicio_ms)
        fim = max(esperado.fim_ms, c.ancora.fim_ms)
        id = f"correcao-{c.id}".lower()
        casos.append(
            Caso(
                id=id,
                origem="correcao",
                sha256=sha256,
                inicio_ms=inicio,
                fim_ms=fim,
                esperado=[ItemEsperado.de(esperado)],
                reservado=reservado_pelo_sorteio(id),
                job_id=c.job_id,
                versao_pipeline=versao_pipeline,
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
    """Grava os casos das correções dos Jobs concluídos; o mesmo caso sai no mesmo arquivo."""
    gravados: list[Caso] = []
    for job in sorted(repositorio.listar(), key=lambda j: (j.criado_em, j.id)):
        if job.estado != "concluido":
            continue
        feitas = correcoes.listar(job.id)
        if not feitas:
            continue
        try:
            dados = json.loads(b"".join(decupagens.abrir_decupagem(job.id)))
            sha = dados["video"]["sha256"]
        except (ServicoIndisponivel, ValueError, KeyError, TypeError):
            log.warning("decupagem de %s não lida: fora do conjunto", job.id)
            continue
        versao = dados.get("versao_pipeline")
        for caso in casos_das_correcoes(sha, str(versao) if versao else None, feitas):
            gravar_caso(pasta, caso)
            gravados.append(caso)
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
    banco = firestore.Client(project=projeto)
    exportar(
        RepositorioFirestore(banco),
        DecupagensStorage(ClienteStorage(project=projeto), aceitos, decupagens),
        RepositorioDeCorrecoesFirestore(banco),
        pasta,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
