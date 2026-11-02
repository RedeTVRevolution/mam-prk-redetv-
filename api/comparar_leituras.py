"""`make comparar-leituras` (#233): compara duas leituras da tela do mesmo vídeo.

A referência (a leitura de um quadro por segundo, detector `server`, em CPU, já gravada) e a
nova (leitura só quando a imagem muda, detector leve, ou os dois). Mostra:

- os textos distintos que a referência achou e a nova não, e o contrário;
- as aparições de um texto cujo início ou fim mudou mais de 1 s (a tolerância do #91), ou
  que a nova não achou;
- quantos quadros cada uma leu e o tempo de processamento.

Os textos e as aparições são os da medição dos textos (`api/medicao_dos_textos.py`): linhas
normalizadas, segundos seguidos formam uma aparição e uma falha isolada não a parte. Os
quadros lidos e o tempo não estão no formato da leitura: vêm do log do Job ("Leitura da
tela: N quadros lidos e M pulados em S s") e da execução, e entram pelas opções; sem elas, a
referência leu todos os quadros e a nova fica "não informado".

    python -m api.comparar_leituras REFERENCIA.json NOVA.json \\
        [--lidos-referencia N] [--lidos-nova N] [--segundos-referencia S] [--segundos-nova S]

Os JSON são `<job>/leitura_da_tela.json` do bucket de aceitos (`gcloud storage cp`). Não
apague nem sobrescreva a leitura de referência antes da medição: grave a nova noutro Job.
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from api.leitura_da_tela import LeituraDaTela
from api.medicao_dos_textos import TOLERANCIA_DE_QUADROS, _aparicoes, _normalizar

TOLERANCIA_DO_TEMPO_S = 1.0
_SEM_FIM = 10**12

Aparicao = tuple[float, float]


@dataclass(frozen=True)
class AparicaoMudada:
    texto: str
    referencia: Aparicao
    nova: Aparicao | None  # None: a nova não achou o texto nesse trecho


@dataclass(frozen=True)
class Execucao:
    quadros_lidos: int | None
    segundos: float | None


@dataclass(frozen=True)
class Comparacao:
    so_na_referencia: list[str]
    so_na_nova: list[str]
    aparicoes_mudadas: list[AparicaoMudada]
    referencia: Execucao
    nova: Execucao
    quadros: int


def aparicoes_por_texto(leitura: LeituraDaTela) -> dict[str, list[Aparicao]]:
    """Cada linha normalizada e as aparições dela, em segundos `(início, fim)`."""
    segundos: dict[str, list[int]] = defaultdict(list)
    for quadro in sorted(leitura.quadros, key=lambda q: q.segundo):
        for texto in {_normalizar(linha.texto) for linha in quadro.linhas}:
            if texto:
                segundos[texto].append(quadro.segundo)
    return {
        texto: [
            (inicio / 1000, fim / 1000)
            for inicio, fim in _aparicoes(lista, TOLERANCIA_DE_QUADROS, _SEM_FIM)
        ]
        for texto, lista in segundos.items()
    }


def _sobreposicao(a: Aparicao, b: Aparicao) -> float:
    return min(a[1], b[1]) - max(a[0], b[0])


def _mudou(referencia: Aparicao, nova: Aparicao) -> bool:
    return (
        abs(referencia[0] - nova[0]) > TOLERANCIA_DO_TEMPO_S
        or abs(referencia[1] - nova[1]) > TOLERANCIA_DO_TEMPO_S
    )


def _aparicoes_mudadas(
    referencia: dict[str, list[Aparicao]], nova: dict[str, list[Aparicao]]
) -> list[AparicaoMudada]:
    mudadas: list[AparicaoMudada] = []
    for texto in sorted(referencia.keys() & nova.keys()):
        for aparicao in referencia[texto]:
            melhor = max(nova[texto], key=lambda n: _sobreposicao(aparicao, n))
            if _sobreposicao(aparicao, melhor) <= 0:
                mudadas.append(AparicaoMudada(texto, aparicao, None))
            elif _mudou(aparicao, melhor):
                mudadas.append(AparicaoMudada(texto, aparicao, melhor))
    return mudadas


def comparar(
    referencia: LeituraDaTela,
    nova: LeituraDaTela,
    execucao_da_referencia: Execucao | None = None,
    execucao_da_nova: Execucao | None = None,
) -> Comparacao:
    da_referencia = aparicoes_por_texto(referencia)
    da_nova = aparicoes_por_texto(nova)
    return Comparacao(
        so_na_referencia=sorted(da_referencia.keys() - da_nova.keys()),
        so_na_nova=sorted(da_nova.keys() - da_referencia.keys()),
        aparicoes_mudadas=_aparicoes_mudadas(da_referencia, da_nova),
        # A referência é de um quadro por segundo: leu todos.
        referencia=execucao_da_referencia
        or Execucao(quadros_lidos=len(referencia.quadros), segundos=None),
        nova=execucao_da_nova or Execucao(quadros_lidos=None, segundos=None),
        quadros=len(nova.quadros),
    )


def _intervalo(aparicao: Aparicao | None) -> str:
    if aparicao is None:
        return "não achado"
    return f"{aparicao[0]:g} s a {aparicao[1]:g} s"


def _execucao(nome: str, execucao: Execucao, quadros: int) -> str:
    lidos = (
        "não informado"
        if execucao.quadros_lidos is None
        else f"{execucao.quadros_lidos} de {quadros}"
    )
    tempo = "não informado" if execucao.segundos is None else f"{execucao.segundos:g} s"
    return f"  {nome}: quadros lidos {lidos}; tempo de processamento {tempo}"


def formatar(comparacao: Comparacao) -> str:
    linhas = ["Textos distintos que só a referência achou:"]
    linhas += [f"  {t}" for t in comparacao.so_na_referencia] or ["  nenhum"]
    linhas += ["Textos distintos que só a nova achou:"]
    linhas += [f"  {t}" for t in comparacao.so_na_nova] or ["  nenhum"]
    linhas += [
        f"Aparições com início ou fim mudado em mais de {TOLERANCIA_DO_TEMPO_S:g} s:"
    ]
    linhas += [
        f"  {m.texto}: referência {_intervalo(m.referencia)}; nova {_intervalo(m.nova)}"
        for m in comparacao.aparicoes_mudadas
    ] or ["  nenhuma"]
    linhas += ["Quadros e tempo:"]
    linhas += [
        _execucao("referência", comparacao.referencia, comparacao.quadros),
        _execucao("nova", comparacao.nova, comparacao.quadros),
    ]
    return "\n".join(linhas)


def _ler(caminho: str) -> LeituraDaTela:
    return LeituraDaTela.model_validate(json.loads(Path(caminho).read_text()))


def main(argv: list[str] | None = None) -> None:
    analisador = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analisador.add_argument("referencia")
    analisador.add_argument("nova")
    analisador.add_argument("--lidos-referencia", type=int)
    analisador.add_argument("--lidos-nova", type=int)
    analisador.add_argument("--segundos-referencia", type=float)
    analisador.add_argument("--segundos-nova", type=float)
    a = analisador.parse_args(argv)
    referencia, nova = _ler(a.referencia), _ler(a.nova)
    print(
        formatar(
            comparar(
                referencia,
                nova,
                Execucao(
                    a.lidos_referencia
                    if a.lidos_referencia is not None
                    else len(referencia.quadros),
                    a.segundos_referencia,
                ),
                Execucao(a.lidos_nova, a.segundos_nova),
            )
        )
    )


if __name__ == "__main__":
    main()
