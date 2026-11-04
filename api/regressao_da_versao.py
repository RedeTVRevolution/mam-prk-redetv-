"""`make regressao` (#254): uma versão do pipeline contra o conjunto de regressão.

    python -m api.regressao_da_versao VERSAO [RESERVADOS] [PASTA]

Para cada caso do conjunto (`api/regressao.py`), pede ao transporte os itens da `VERSAO`
e os da versão aprovada (a `VERSAO_PIPELINE` de hoje, ou `VERSAO_APROVADA`) no trecho do
caso e mede os dois contra o esperado com o pareamento e a tolerância do
`api/comparador.py`: um item esperado é acerto quando tem par dentro da tolerância. Por
requisito, o relatório conta os acertos de cada versão, diz por caso se melhorou, piorou ou
ficou igual e confere a meta (`metas.json`). Grava Markdown e JSON em `PASTA`
(`regressao-da-versao`). Saída 1 se algum requisito com meta fica abaixo dela (o portão
antes de trocar a versão), 2 se a entrada é inválida (meta de requisito que não existe,
versão igual à aprovada).

Sem `RESERVADOS=1` os casos reservados ficam fora; com ele, só eles entram. Sem `CONFIRMAR=1`
só mostra o custo estimado (`CUSTO_POR_HORA_USD` por hora de trecho, já no preço do Batch).

O transporte real (`DecupagensEmPasta`) lê as decupagens que o pipeline gerou, em `DECUPAGENS`
(uma pasta de `*.json`): a de cada versão é achada pelo SHA-256 do vídeo e pela
`versao_pipeline`. Quem roda a versão em Batch grava as decupagens ali. Opcionais, para
testes e para trocar de lugar: `CASOS` e `METAS`.
"""

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from api.comparador import Item, itens_do_modelo, parear, se_sobrepoem
from api.decupagem import Decupagem
from api.regressao import (
    ARQUIVO_DE_METAS,
    PASTA_DOS_CASOS,
    Caso,
    ler_casos,
    ler_metas,
    para_ajuste,
    reservados,
)
from api.versao_pipeline import VERSAO_PIPELINE

PASTA_DO_RELATORIO = Path("regressao-da-versao")

# O requisito de cada tipo de item: os nomes do `api/comparar_passadas.py` onde existem.
REQUISITO_DO_TIPO: dict[str, str] = {
    "aparicao": "famosos",
    "mencao": "mencoes",
    "pauta": "pautas",
    "comercial": "comerciais",
    "plano": "broll_descricoes",
    "fala": "falas",
    "texto_na_tela": "textos_na_tela",
    "objeto": "objetos",
    "bloco": "blocos",
}

Veredito = Literal["melhorou", "piorou", "igual"]


class Transporte(Protocol):
    def itens(self, versao: str, caso: Caso) -> list[Item]:
        """Os itens que a `versao` do pipeline achou no vídeo do caso."""
        ...


@dataclass(frozen=True)
class DoCaso:
    total: int
    acertos_nova: int
    acertos_aprovada: int
    veredito: Veredito


@dataclass(frozen=True)
class ResultadoDoCaso:
    caso_id: str
    requisitos: dict[str, DoCaso]


@dataclass(frozen=True)
class DoRequisito:
    total: int
    acertos_nova: int
    acertos_aprovada: int
    melhoraram: int
    pioraram: int
    iguais: int
    meta: float | None
    atingida: bool | None  # `None`: sem meta

    @property
    def taxa_nova(self) -> float:
        return self.acertos_nova / self.total

    @property
    def taxa_aprovada(self) -> float:
        return self.acertos_aprovada / self.total


@dataclass(frozen=True)
class Relatorio:
    versao: str
    versao_aprovada: str
    gerado_em: datetime
    casos: list[ResultadoDoCaso]
    requisitos: dict[str, DoRequisito]
    sem_caso: list[str]  # requisitos com meta e nenhum caso

    @property
    def passou(self) -> bool:
        return all(r.atingida is not False for r in self.requisitos.values())


def selecionar(casos: list[Caso], so_reservados: bool) -> list[Caso]:
    return reservados(casos) if so_reservados else para_ajuste(casos)


def _no_trecho(itens: list[Item], caso: Caso) -> list[Item]:
    trecho = Item("bloco", "", caso.inicio_ms, caso.fim_ms)
    return [i for i in itens if se_sobrepoem(i, trecho)]


def _acertos(esperado: list[Item], achados: list[Item]) -> int:
    pareados, _ = parear(esperado, achados)
    return sum(p.dentro for p in pareados)


def _por_requisito(caso: Caso) -> dict[str, list[Item]]:
    agrupado: dict[str, list[Item]] = {}
    for item in caso.itens():
        agrupado.setdefault(REQUISITO_DO_TIPO[item.tipo], []).append(item)
    return agrupado


def _veredito(nova: int, aprovada: int) -> Veredito:
    return "melhorou" if nova > aprovada else "piorou" if nova < aprovada else "igual"


def avaliar(
    transporte: Transporte,
    casos: list[Caso],
    versao: str,
    versao_aprovada: str,
    metas: Mapping[str, float],
    relogio: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Relatorio:
    desconhecidos = sorted(set(metas) - set(REQUISITO_DO_TIPO.values()))
    if desconhecidos:
        raise ValueError(f"meta de requisito desconhecido: {', '.join(desconhecidos)}")
    resultados: list[ResultadoDoCaso] = []
    for caso in casos:
        nova = _no_trecho(transporte.itens(versao, caso), caso)
        aprovada = _no_trecho(transporte.itens(versao_aprovada, caso), caso)
        por_requisito: dict[str, DoCaso] = {}
        for nome, esperado in _por_requisito(caso).items():
            tipos = {i.tipo for i in esperado}
            a_nova = _acertos(esperado, [i for i in nova if i.tipo in tipos])
            a_aprovada = _acertos(esperado, [i for i in aprovada if i.tipo in tipos])
            por_requisito[nome] = DoCaso(
                len(esperado), a_nova, a_aprovada, _veredito(a_nova, a_aprovada)
            )
        resultados.append(ResultadoDoCaso(caso.id, por_requisito))
    requisitos: dict[str, DoRequisito] = {}
    for nome in sorted({n for r in resultados for n in r.requisitos}):
        partes = [r.requisitos[nome] for r in resultados if nome in r.requisitos]
        total = sum(p.total for p in partes)
        acertos = sum(p.acertos_nova for p in partes)
        meta = metas.get(nome)
        requisitos[nome] = DoRequisito(
            total=total,
            acertos_nova=acertos,
            acertos_aprovada=sum(p.acertos_aprovada for p in partes),
            melhoraram=sum(p.veredito == "melhorou" for p in partes),
            pioraram=sum(p.veredito == "piorou" for p in partes),
            iguais=sum(p.veredito == "igual" for p in partes),
            meta=meta,
            atingida=None if meta is None else acertos / total >= meta,
        )
    return Relatorio(
        versao,
        versao_aprovada,
        relogio(),
        resultados,
        requisitos,
        sorted(n for n in metas if n not in requisitos),
    )


def custo_estimado(casos: list[Caso], custo_por_hora: float) -> float:
    segundos = sum(c.fim_ms - c.inicio_ms for c in casos) / 1000
    return custo_por_hora * segundos / 3600


def relatorio_em_json(r: Relatorio) -> str:
    dados = asdict(r)
    dados["gerado_em"] = r.gerado_em.isoformat()
    dados["passou"] = r.passou
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"


def _pct(valor: float) -> str:
    return f"{100 * valor:.1f}%"


def relatorio_em_markdown(r: Relatorio) -> str:
    linhas = [
        f"# Regressão da versão {r.versao}",
        "",
        (
            f"Contra a aprovada ({r.versao_aprovada}), em {r.gerado_em:%Y-%m-%d %H:%M} UTC. "
            f"Resultado: **{'PASSOU' if r.passou else 'FALHOU'}**."
        ),
        "",
        "## Por requisito",
        "",
        "| Requisito | Esperados | Nova | Aprovada | Melhorou | Piorou | Igual | Meta |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for nome, q in r.requisitos.items():
        meta = (
            "sem meta"
            if q.meta is None
            else f"{_pct(q.meta)} ({'atingida' if q.atingida else 'abaixo da meta'})"
        )
        linhas.append(
            f"| {nome} | {q.total} | {q.acertos_nova} ({_pct(q.taxa_nova)}) "
            f"| {q.acertos_aprovada} ({_pct(q.taxa_aprovada)}) | {q.melhoraram} "
            f"| {q.pioraram} | {q.iguais} | {meta} |"
        )
    for nome in r.sem_caso:
        linhas.append(f"| {nome} | 0 | - | - | - | - | - | sem caso para medir |")
    linhas += ["", "## Caso a caso", ""]
    for c in r.casos:
        for nome, d in c.requisitos.items():
            linhas.append(
                f"- `{c.caso_id}` · {nome}: {d.veredito} "
                f"(nova {d.acertos_nova}/{d.total}, aprovada {d.acertos_aprovada}/{d.total})"
            )
    return "\n".join(linhas) + "\n"


def gravar(r: Relatorio, pasta: Path) -> tuple[Path, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    md, js = pasta / f"regressao-{r.versao}.md", pasta / f"regressao-{r.versao}.json"
    md.write_text(relatorio_em_markdown(r), encoding="utf-8")
    js.write_text(relatorio_em_json(r), encoding="utf-8")
    return md, js


class DecupagensEmPasta:
    """As decupagens que o pipeline gerou, achadas por versão e SHA-256 do vídeo."""

    def __init__(self, pasta: Path) -> None:
        self.por_chave: dict[tuple[str, str], list[Item]] = {}
        for arq in sorted(pasta.glob("*.json")):
            d = Decupagem.model_validate_json(arq.read_bytes())
            chave = (str(d.versao_pipeline), d.video.sha256)
            if chave in self.por_chave:
                raise ValueError(
                    f"{arq.name}: outra decupagem da versão {chave[0]} para o vídeo "
                    f"{chave[1][:12]}"
                )
            self.por_chave[chave] = itens_do_modelo(d)

    def itens(self, versao: str, caso: Caso) -> list[Item]:
        try:
            return self.por_chave[(versao, caso.sha256)]
        except KeyError:
            raise ValueError(
                f"sem decupagem da versão {versao} para o vídeo {caso.sha256[:12]}"
            ) from None


def main(
    argumentos: list[str],
    ambiente: Mapping[str, str] = os.environ,
    transporte: Transporte | None = None,
    versao_aprovada: str | None = None,
    escrever: Callable[[str], None] = print,
) -> int:
    try:
        if not argumentos or not argumentos[0]:
            raise ValueError("falta a VERSAO")
        versao = argumentos[0]
        so_reservados = len(argumentos) > 1 and argumentos[1] == "1"
        pasta = Path(argumentos[2]) if len(argumentos) > 2 and argumentos[2] else None
        aprovada = versao_aprovada or ambiente.get("VERSAO_APROVADA") or VERSAO_PIPELINE
        if aprovada == versao:
            raise ValueError(
                f"a VERSAO {versao} é a aprovada: diga a aprovada em VERSAO_APROVADA"
            )
        custo = ambiente.get("CUSTO_POR_HORA_USD")
        casos = selecionar(
            ler_casos(Path(ambiente.get("CASOS") or PASTA_DOS_CASOS)), so_reservados
        )
        if not casos:
            raise ValueError("nenhum caso para esta rodada")
        metas = ler_metas(Path(ambiente.get("METAS") or ARQUIVO_DE_METAS))
        escrever(
            f"{len(casos)} casos ({'reservados' if so_reservados else 'de ajuste'}), "
            f"versão {versao} contra {aprovada}."
        )
        estimado = (
            "n/d" if not custo else f"US$ {custo_estimado(casos, float(custo)):.2f}"
        )
        escrever(f"Custo estimado: {estimado}")
        if ambiente.get("CONFIRMAR") != "1":
            escrever("Nada foi rodado: rode de novo com CONFIRMAR=1.")
            return 0
        if transporte is None:
            decupagens = ambiente.get("DECUPAGENS")
            if not decupagens:
                raise ValueError("falta DECUPAGENS, a pasta das decupagens")
            transporte = DecupagensEmPasta(Path(decupagens))
        relatorio = avaliar(transporte, casos, versao, aprovada, metas)
        md, js = gravar(relatorio, pasta or PASTA_DO_RELATORIO)
    # pydantic.ValidationError é ValueError; o `ler_metas` lança TypeError.
    except (ValueError, TypeError, OSError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    escrever(relatorio_em_markdown(relatorio))
    escrever(f"Relatórios: {md}, {js}")
    return 0 if relatorio.passou else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
