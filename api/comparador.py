"""Comparador de tempos da decupagem com o gabarito (aceite da E0).

Uso: `python -m api.comparador GABARITO_DIR DECUPAGENS_DIR`. Os tipos são todas as
categorias da decupagem (`TIPOS`); os casos do conjunto de regressão (`api/regressao.py`)
usam os mesmos `Item` e `Tipo`. Cada CSV do
gabarito traz na primeira linha `# sha256: <hex>`, depois o cabeçalho
`tipo,identidade,inicio,fim` com tempos em `MM:SS` ou `HH:MM:SS`. Cada decupagem é um JSON
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
from typing import Literal, get_args

from api.decupagem import Decupagem

Tipo = Literal[
    "aparicao",
    "mencao",
    "pauta",
    "comercial",
    "plano",
    "fala",
    "texto_na_tela",
    "objeto",
    "bloco",
]
TIPOS: tuple[Tipo, ...] = get_args(Tipo)
TIPOS_COM_IDENTIDADE: frozenset[Tipo] = frozenset(
    {"aparicao", "mencao", "comercial", "texto_na_tela", "objeto"}
)  # pauta, plano, fala e bloco: só tempo
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


def se_sobrepoem(a: Item, b: Item) -> bool:
    """Têm trecho em comum; um item pontual (início = fim) vale se cair no outro."""
    s = sobreposicao_ms(a, b)
    return s > 0 or (s == 0 and (a.inicio_ms == a.fim_ms or b.inicio_ms == b.fim_ms))


def parear(
    gabarito: Iterable[Item], modelo: list[Item]
) -> tuple[list[Pareado], list[Item]]:
    """Pareia cada item do gabarito com o do modelo de maior sobreposição.

    Mesmo tipo; aparição, menção e comercial exigem também a mesma identidade.
    Sem trecho em comum, não há par; item pontual pareia com o que o contém.
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
            and se_sobrepoem(g, m)
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
    itens += [Item("plano", p.ambiente, p.inicio_ms, p.fim_ms) for p in d.planos]
    itens += [Item("fala", f.locutor, f.inicio_ms, f.fim_ms) for f in d.transcricao]
    itens += [
        Item("texto_na_tela", t.texto, t.inicio_ms, t.fim_ms) for t in d.textos_na_tela
    ]
    for o in d.objetos:
        itens += [Item("objeto", o.tipo, i.inicio_ms, i.fim_ms) for i in o.ocorrencias]
    itens += [Item("bloco", b.titulo, b.inicio_ms, b.fim_ms) for b in d.programa.blocos]
    return itens


_TEMPO = re.compile(r"^(?:(\d+):(\d{2})|(\d+)):(\d{2})$")


def tempo_ms(texto: str) -> int:
    """`MM:SS` (minutos podem passar de 59) ou `HH:MM:SS` (minutos e segundos de 0 a 59)."""
    achou = _TEMPO.match(texto.strip())
    if not achou:
        raise ValueError(f"tempo fora do formato MM:SS ou HH:MM:SS: {texto!r}")
    horas, minutos_com_horas, minutos_sem_horas, segundos = achou.groups()
    minutos = int(minutos_com_horas or minutos_sem_horas)
    if int(segundos) > 59 or (horas is not None and minutos > 59):
        raise ValueError(f"tempo fora do formato MM:SS ou HH:MM:SS: {texto!r}")
    return ((int(horas or 0) * 60 + minutos) * 60 + int(segundos)) * 1000


def ler_gabarito(caminho: Path) -> tuple[str, list[Item]]:
    """Devolve o SHA-256 do clipe e os itens do CSV."""
    linhas = caminho.read_text(encoding="utf-8-sig").splitlines()
    achou = (
        re.fullmatch(r"#\s*sha256:\s*([0-9a-fA-F]{64})", linhas[0].strip())
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
    return achou[1].lower(), itens


def comparar_clipe(nome: str, gabarito: list[Item], d: Decupagem) -> ResultadoDoClipe:
    pareados, sem_par = parear(gabarito, itens_do_modelo(d))
    return ResultadoDoClipe(nome, pareados, sem_par)


def _totais(resultados: list[ResultadoDoClipe]) -> tuple[int, int]:
    """Itens pareados e, entre eles, os dentro da tolerância, somando os clipes."""
    return sum(len(r.pareados) for r in resultados), sum(r.dentro for r in resultados)


def passou(resultados: list[ResultadoDoClipe]) -> bool:
    pareados, dentro = _totais(resultados)
    return pareados > 0 and dentro / pareados >= META


def _segundos(ms: int) -> str:
    return f"{ms / 1000:.3f}s"


def _porcentagem(parte: int, total: int) -> str:
    return f"{100 * parte / total:.1f}%" if total else "n/d"


_DENTRO = f"dentro de {TOLERANCIA_MS / 1000:g} s"


def relatorio(resultados: list[ResultadoDoClipe]) -> str:
    saida: list[str] = []
    for r in resultados:
        total = len(r.pareados)
        saida.append(f"== {r.nome}")
        saida.append(
            f"pareados: {total}, {_DENTRO}: {r.dentro} ({_porcentagem(r.dentro, total)})"
        )
        saida.append("itens (erro de início / erro de fim):")
        for p in r.pareados:
            marca = "ok" if p.dentro else "FORA"
            g = p.gabarito
            saida.append(
                f"  [{marca}] {g.tipo} {g.identidade}: "
                f"{_segundos(p.erro_inicio_ms)} / {_segundos(p.erro_fim_ms)}"
            )
        saida.append("piores casos (maior erro primeiro):")
        for p in r.piores:
            saida.append(
                f"  {p.gabarito.tipo} {p.gabarito.identidade}: {_segundos(p.erro_ms)}"
            )
        saida.append(
            f"não encontrados (falha de cobertura, fora do critério): {len(r.nao_encontrados)}"
        )
        for g in r.nao_encontrados:
            saida.append(
                f"  {g.tipo} {g.identidade} ({_segundos(g.inicio_ms)}–{_segundos(g.fim_ms)})"
            )
        saida.append("")
    pareados, dentro = _totais(resultados)
    nao = sum(len(r.nao_encontrados) for r in resultados)
    saida.append(
        f"TOTAL: {dentro}/{pareados} {_DENTRO} ({_porcentagem(dentro, pareados)});"
        f" meta {META:.0%}"
    )
    saida.append(f"cobertura: {nao} itens do gabarito sem par")
    saida.append("PASSOU" if passou(resultados) else "FALHOU")
    return "\n".join(saida)


def executar(gabarito_dir: Path, decupagens_dir: Path) -> tuple[str, bool]:
    decupagens: dict[str, Decupagem] = {}
    for arq in sorted(decupagens_dir.glob("*.json")):
        d = Decupagem.model_validate_json(arq.read_bytes())
        sha = d.video.sha256
        if sha in decupagens:
            raise ValueError(f"{arq.name}: outra decupagem já tem o sha256 {sha}")
        decupagens[sha] = d
    resultados: list[ResultadoDoClipe] = []
    csvs = sorted(gabarito_dir.glob("*.csv"))
    if not csvs:
        raise ValueError(f"nenhum CSV em {gabarito_dir}")
    vistos: set[str] = set()
    for arq in csvs:
        sha, itens = ler_gabarito(arq)
        if sha in vistos:
            raise ValueError(f"{arq.name}: outro CSV já tem o sha256 {sha}")
        vistos.add(sha)
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
