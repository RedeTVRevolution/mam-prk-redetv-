"""Comparador de tempos da decupagem com o gabarito (aceite da E0).

Uso: `python -m api.comparador GABARITO_DIR DECUPAGENS_DIR`. Cada CSV do
gabarito traz na primeira linha `# sha256: <hex>`, depois o cabeçalho
`tipo,identidade,inicio,fim` com tempos em `MM:SS`. Cada decupagem é um JSON
`*.json`; o clipe é pareado com o gabarito pelo SHA-256 do bloco `video`.
Código de saída: 0 passou, 1 falhou, 2 entrada inválida.
"""

import csv
import re
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from api.decupagem import Decupagem

Tipo = Literal["aparicao", "mencao", "pauta", "comercial"]
TIPOS: tuple[Tipo, ...] = ("aparicao", "mencao", "pauta", "comercial")
TIPOS_COM_IDENTIDADE = {"aparicao", "mencao", "comercial"}  # pauta: só tempo
TOLERANCIA_MS = 2000
META = 0.95


@dataclass(frozen=True)
class Item:
    tipo: Tipo
    identidade: str
    inicio_ms: int
    fim_ms: int


@dataclass(frozen=True)
class Pareado:
    gabarito: Item
    modelo: Item

    @property
    def erro_inicio_ms(self) -> int:
        return abs(self.modelo.inicio_ms - self.gabarito.inicio_ms)

    @property
    def erro_fim_ms(self) -> int:
        return abs(self.modelo.fim_ms - self.gabarito.fim_ms)

    @property
    def erro_ms(self) -> int:
        return max(self.erro_inicio_ms, self.erro_fim_ms)

    @property
    def dentro(self) -> bool:
        return self.erro_ms <= TOLERANCIA_MS


@dataclass(frozen=True)
class ResultadoDoClipe:
    nome: str
    pareados: list[Pareado]
    nao_encontrados: list[Item]

    @property
    def dentro(self) -> int:
        return sum(p.dentro for p in self.pareados)

    @property
    def piores(self) -> list[Pareado]:
        return sorted(self.pareados, key=lambda p: -p.erro_ms)


def normalizar(texto: str) -> str:
    """Sem diferenciar maiúsculas, acentos nem espaços repetidos."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())


def sobreposicao_ms(a: Item, b: Item) -> int:
    return min(a.fim_ms, b.fim_ms) - max(a.inicio_ms, b.inicio_ms)


def parear(
    gabarito: Iterable[Item], modelo: list[Item]
) -> tuple[list[Pareado], list[Item]]:
    """Pareia cada item do gabarito com o do modelo de maior sobreposição.

    Mesmo tipo; aparição, menção e comercial exigem também a mesma identidade.
    Sem sobreposição (nem ponto em comum), não há par.
    """
    pareados: list[Pareado] = []
    sem_par: list[Item] = []
    for g in gabarito:
        candidatos = [
            m
            for m in modelo
            if m.tipo == g.tipo
            and (
                g.tipo not in TIPOS_COM_IDENTIDADE
                or normalizar(m.identidade) == normalizar(g.identidade)
            )
            and sobreposicao_ms(g, m) > 0
        ]
        if not candidatos:
            sem_par.append(g)
            continue
        melhor = max(
            candidatos,
            key=lambda m: (
                sobreposicao_ms(g, m),
                -(abs(m.inicio_ms - g.inicio_ms) + abs(m.fim_ms - g.fim_ms)),
            ),
        )
        pareados.append(Pareado(g, melhor))
    return pareados, sem_par


def itens_do_modelo(d: Decupagem) -> list[Item]:
    itens = [Item("pauta", p.titulo, p.inicio_ms, p.fim_ms) for p in d.pautas]
    itens += [Item("comercial", c.marca, c.inicio_ms, c.fim_ms) for c in d.comerciais]
    for p in d.pessoas:
        itens += [Item("aparicao", p.nome, a.inicio_ms, a.fim_ms) for a in p.na_imagem]
        for m in [*p.citada_na_fala, *p.citada_no_texto]:
            itens.append(Item("mencao", p.nome, m.inicio_ms, m.fim_ms))
    return itens


_MMSS = re.compile(r"^(\d+):([0-5]\d)$")


def tempo_ms(texto: str) -> int:
    achou = _MMSS.match(texto.strip())
    if not achou:
        raise ValueError(f"tempo fora do formato MM:SS: {texto!r}")
    return (int(achou[1]) * 60 + int(achou[2])) * 1000


def ler_gabarito(caminho: Path) -> tuple[str, list[Item]]:
    """Devolve o SHA-256 do clipe e os itens do CSV."""
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    achou = (
        re.fullmatch(r"#\s*sha256:\s*([0-9a-f]{64})", linhas[0].strip())
        if linhas
        else None
    )
    if not achou:
        raise ValueError(f"{caminho.name}: falta a primeira linha '# sha256: <hex>'")
    leitor = csv.DictReader(linhas[1:])
    if leitor.fieldnames != ["tipo", "identidade", "inicio", "fim"]:
        raise ValueError(
            f"{caminho.name}: colunas devem ser tipo,identidade,inicio,fim"
        )
    itens: list[Item] = []
    for n, linha in enumerate(leitor, start=3):
        try:
            tipo = linha["tipo"].strip()
            if tipo not in TIPOS:
                raise ValueError(f"tipo desconhecido: {tipo!r}")
            inicio, fim = tempo_ms(linha["inicio"]), tempo_ms(linha["fim"])
            if inicio > fim:
                raise ValueError("início depois do fim")
            itens.append(Item(tipo, linha["identidade"].strip(), inicio, fim))
        except (ValueError, AttributeError, TypeError) as e:
            raise ValueError(f"{caminho.name}, linha {n}: {e}") from e
    return achou[1], itens


def comparar_clipe(nome: str, gabarito: list[Item], d: Decupagem) -> ResultadoDoClipe:
    pareados, sem_par = parear(gabarito, itens_do_modelo(d))
    return ResultadoDoClipe(nome, pareados, sem_par)


def passou(resultados: list[ResultadoDoClipe]) -> bool:
    pareados = sum(len(r.pareados) for r in resultados)
    dentro = sum(r.dentro for r in resultados)
    return pareados > 0 and dentro / pareados >= META


def _s(ms: int) -> str:
    return f"{ms / 1000:.1f}s"


def relatorio(resultados: list[ResultadoDoClipe]) -> str:
    saida: list[str] = []
    for r in resultados:
        total = len(r.pareados)
        pct = f"{100 * r.dentro / total:.1f}%" if total else "n/d"
        saida.append(f"== {r.nome}")
        saida.append(f"pareados: {total}, dentro de 2 s: {r.dentro} ({pct})")
        saida.append("itens (erro de início / erro de fim):")
        for p in r.pareados:
            marca = "ok" if p.dentro else "FORA"
            g = p.gabarito
            saida.append(
                f"  [{marca}] {g.tipo} {g.identidade}: "
                f"{_s(p.erro_inicio_ms)} / {_s(p.erro_fim_ms)}"
            )
        saida.append("piores casos (maior erro primeiro):")
        for p in r.piores[:5]:
            saida.append(
                f"  {p.gabarito.tipo} {p.gabarito.identidade}: {_s(p.erro_ms)}"
            )
        saida.append(
            f"não encontrados (falha de cobertura, fora do critério): {len(r.nao_encontrados)}"
        )
        for g in r.nao_encontrados:
            saida.append(
                f"  {g.tipo} {g.identidade} ({_s(g.inicio_ms)}–{_s(g.fim_ms)})"
            )
        saida.append("")
    pareados = sum(len(r.pareados) for r in resultados)
    dentro = sum(r.dentro for r in resultados)
    pct = f"{100 * dentro / pareados:.1f}%" if pareados else "n/d"
    nao = sum(len(r.nao_encontrados) for r in resultados)
    saida.append(f"TOTAL: {dentro}/{pareados} dentro de 2 s ({pct}); meta {META:.0%}")
    saida.append(f"cobertura: {nao} itens do gabarito sem par")
    saida.append("PASSOU" if passou(resultados) else "FALHOU")
    return "\n".join(saida)


def executar(gabarito_dir: Path, decupagens_dir: Path) -> tuple[str, bool]:
    decupagens: dict[str, Decupagem] = {}
    for arq in sorted(decupagens_dir.glob("*.json")):
        d = Decupagem.model_validate_json(arq.read_bytes())
        decupagens[d.video.sha256] = d
    resultados: list[ResultadoDoClipe] = []
    csvs = sorted(gabarito_dir.glob("*.csv"))
    if not csvs:
        raise ValueError(f"nenhum CSV em {gabarito_dir}")
    for arq in csvs:
        sha, itens = ler_gabarito(arq)
        if sha not in decupagens:
            raise ValueError(f"{arq.name}: nenhuma decupagem com sha256 {sha}")
        resultados.append(comparar_clipe(arq.stem, itens, decupagens[sha]))
    return relatorio(resultados), passou(resultados)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        texto, ok = executar(Path(argv[0]), Path(argv[1]))
    except (ValueError, OSError) as e:  # pydantic.ValidationError é ValueError
        print(f"erro: {e}", file=sys.stderr)
        return 2
    print(texto)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
