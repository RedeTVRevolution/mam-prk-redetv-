"""Comparador de tempos da decupagem com o gabarito (aceite da E0).

Uso: `python -m api.comparador GABARITO_DIR DECUPAGENS_DIR`. Os tipos são todas as
categorias da decupagem (`TIPOS`, de `api/pareamento.py`); os casos do conjunto de regressão
(`api/regressao.py`) usam os mesmos `Item` e `Tipo`. Cada CSV do
gabarito traz na primeira linha `# sha256: <hex>`, depois o cabeçalho
`tipo,identidade,inicio,fim` com tempos em `MM:SS` ou `HH:MM:SS`. Cada decupagem é um JSON
`*.json`; o clipe é pareado com o gabarito pelo SHA-256 do bloco `video`.
Código de saída: 0 passou, 1 falhou, 2 entrada inválida.
"""

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from api.decupagem import Decupagem
from api.pareamento import (
    TIPOS,
    TOLERANCIA_MS,
    Item,
    Pareado,
    itens_do_modelo,
    parear,
)

META = 0.95


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


_TEMPO = re.compile(r"^(?:(\d+):(\d{2})|(\d+)):(\d{2})$")


def tempo_ms(texto: str) -> int:
    """`MM:SS` (minutos podem passar de 59) ou `HH:MM:SS` (minutos e segundos de 0 a 59)."""
    fora_do_formato = ValueError(f"tempo fora do formato MM:SS ou HH:MM:SS: {texto!r}")
    achou = _TEMPO.match(texto.strip())
    if not achou:
        raise fora_do_formato
    horas, minutos_com_horas, minutos_sem_horas, segundos = achou.groups()
    minutos = int(minutos_com_horas or minutos_sem_horas)
    if int(segundos) > 59 or (horas is not None and minutos > 59):
        raise fora_do_formato
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
