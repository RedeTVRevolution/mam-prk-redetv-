"""Amostragem dos planos recorrentes (#546) para a pessoa marcar: ferramenta, fora da produção.

Diagnóstico sobre pastas locais por vídeo e as amostras de precisão e de cobertura:
`python -m api.ferramentas.amostra_dos_planos_recorrentes [--amostra=N] PASTA [PASTA...]`.
"""

import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import Path

from PIL import Image

from api.decupagem import Decupagem, Plano
from api.ferramentas.comum import hash_estavel
from api.medir_agrupamento_de_objetos import margem_de_confianca, pares_para_margem
from api.planos_recorrentes import (
    Sinal,
    _quadro_chave,
    com_os_planos_recorrentes,
    contagem,
    sinal_do_quadro,
)


def resumo(decupagem: Decupagem, quantos: int = 5) -> list[tuple[str, int, int]]:
    """Os maiores grupos: (id, planos, tempo total em ms), o maior primeiro."""
    por_grupo: dict[str, list[Plano]] = {}
    for p in decupagem.planos:
        if p.plano_recorrente:
            por_grupo.setdefault(p.plano_recorrente, []).append(p)
    achados = [
        (g, len(ps), sum(p.fim_ms - p.inicio_ms for p in ps))
        for g, ps in por_grupo.items()
    ]
    return sorted(achados, key=lambda t: (-t[1], t[0]))[:quantos]


@dataclass(frozen=True)
class PlanoDaAmostra:
    programa: str
    video: str
    plano: str
    grupo: str | None
    sinal: Sinal


def _hash(chave: str) -> int:
    return hash_estavel(chave, 12)


def _por_programa(
    pares: dict[str, list[dict[str, str]]], quantos: int
) -> list[dict[str, str]]:
    """Estratifica: cada programa dá um item por rodada, na ordem já sorteada dele."""
    sorteados: list[dict[str, str]] = []
    for rodada in range(max(map(len, pares.values()), default=0)):
        for programa in sorted(pares):
            if rodada < len(pares[programa]) and len(sorteados) < quantos:
                sorteados.append(pares[programa][rodada])
    return sorteados


def amostra_de_precisao(
    planos: Sequence[PlanoDaAmostra], quantos: int
) -> list[dict[str, str]]:
    """Até `quantos` pares para a pessoa marcar se são a mesma câmera e o mesmo
    enquadramento: um par por grupo (não pares soltos, que os grupos grandes dominariam),
    grupos sorteados de forma estável pelo hash do id (como `reservado_pelo_sorteio`) e
    estratificados por programa. O par são os dois planos de menor hash do grupo."""
    grupos: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for p in planos:
        if p.grupo:
            grupos[(p.programa, p.video, p.grupo)].append(p.plano)
    por_programa: dict[str, list[dict[str, str]]] = defaultdict(list)
    for (programa, video, grupo), ids in sorted(
        grupos.items(), key=lambda g: _hash("/".join(g[0]))
    ):
        if len(ids) >= 2:
            a, b = sorted(ids, key=lambda i: _hash(f"{video}/{i}"))[:2]
            por_programa[programa].append(
                {
                    "programa": programa,
                    "video": video,
                    "grupo": grupo,
                    "plano_a": a,
                    "plano_b": b,
                }
            )
    return _por_programa(por_programa, quantos)


def _afastamento(a: Sinal, b: Sinal) -> tuple[int, float]:
    return (
        (a.impressao ^ b.impressao).bit_count(),
        sum(abs(x - y) for x, y in zip(a.cor, b.cor, strict=True)) / 2,
    )


def amostra_de_cobertura(
    planos: Sequence[PlanoDaAmostra], quantos: int
) -> list[dict[str, str]]:
    """Até `quantos` pares de planos de grupos diferentes (o plano sem grupo conta como um
    grupo só dele), no mesmo vídeo e programa: o vizinho mais próximo de cada plano pelo
    sinal (bits do hash, depois cor), onde os retornos que ficaram separados aparecem, em
    vez de pares ao acaso. Estável e estratificado por programa, como a precisão."""
    por_video: dict[tuple[str, str], list[PlanoDaAmostra]] = defaultdict(list)
    for p in planos:
        por_video[(p.programa, p.video)].append(p)
    pares: set[tuple[str, str, str, str]] = set()
    # ponytail: O(n²) por vídeo; filtrar por vizinhança do hash se passar de milhares.
    for (programa, video), do_video in por_video.items():
        for a in do_video:
            vizinhos = [
                b
                for b in do_video
                if b.plano != a.plano and (b.grupo is None or b.grupo != a.grupo)
            ]
            if vizinhos:
                b = min(
                    vizinhos, key=lambda b: (*_afastamento(a.sinal, b.sinal), b.plano)
                )
                menor, maior = sorted((a.plano, b.plano))
                pares.add((programa, video, menor, maior))
    por_programa: dict[str, list[dict[str, str]]] = defaultdict(list)
    for programa, video, id_a, id_b in sorted(pares, key=lambda p: _hash("|".join(p))):
        por_programa[programa].append(
            {"programa": programa, "video": video, "plano_a": id_a, "plano_b": id_b}
        )
    return _por_programa(por_programa, quantos)


def amostras(planos: Sequence[PlanoDaAmostra], quantos: int) -> dict[str, object]:
    """As duas amostras para marcar, com a margem de confiança de 95% da precisão."""
    return {
        "amostra_de_precisao": amostra_de_precisao(planos, quantos),
        "amostra_de_cobertura": amostra_de_cobertura(planos, quantos),
        "margem_da_precisao_com_100_pares_pontos": round(margem_de_confianca(100), 1),
        "pares_para_margem_de_3_pontos": pares_para_margem(3),
    }


def _ler(pasta: Path, caminho: str) -> bytes:
    return (pasta / caminho).read_bytes()


def main(argumentos: list[str]) -> int:
    """Diagnóstico sobre pastas locais por vídeo (`decupagem.json` e `quadros/`, como em
    `api.ferramentas.planos_curtos`): o número de grupos e os 5 maiores, sem tocar a nuvem. Com
    `--amostra=N`, imprime em JSON as amostras de precisão e de cobertura para a pessoa
    marcar; o programa de cada vídeo é o nome da pasta que o contém (`PROGRAMA/VIDEO`)."""
    quantos = next((int(a[10:]) for a in argumentos if a.startswith("--amostra=")), 0)
    pastas = [a for a in argumentos if not a.startswith("--amostra=")]
    if not pastas:
        print(
            "uso: python -m api.ferramentas.amostra_dos_planos_recorrentes [--amostra=N] PASTA [PASTA...]",
            file=sys.stderr,
        )
        return 2
    para_marcar: list[PlanoDaAmostra] = []
    for argumento in pastas:
        pasta = Path(argumento)
        antes = Decupagem.model_validate_json((pasta / "decupagem.json").read_bytes())
        depois = com_os_planos_recorrentes(antes, partial(_ler, pasta))
        total = contagem(depois)
        print(
            f"{pasta.name}: {len(depois.planos)} planos, {total['planos']} em "
            f"{total['grupos']} grupos",
            file=sys.stderr if quantos else sys.stdout,
        )
        for grupo, planos, ms in resumo(depois):
            print(
                f"  {grupo}: {planos} planos, {ms / 60_000:.1f} min",
                file=sys.stderr if quantos else sys.stdout,
            )
        if quantos:
            para_marcar += _planos_da_amostra(depois, pasta)
    if quantos:
        json.dump(
            amostras(para_marcar, quantos), sys.stdout, ensure_ascii=False, indent=2
        )
        sys.stdout.write("\n")
    return 0


def _planos_da_amostra(decupagem: Decupagem, pasta: Path) -> list[PlanoDaAmostra]:
    planos: list[PlanoDaAmostra] = []
    for p in decupagem.planos:
        caminho = _quadro_chave(p)
        try:
            imagem = Image.open(BytesIO(_ler(pasta, caminho))) if caminho else None
        except Exception:  # noqa: BLE001 - quadro que falta só tira o plano da amostra
            imagem = None
        if imagem is not None:
            planos.append(
                PlanoDaAmostra(
                    pasta.resolve().parent.name,
                    pasta.name,
                    p.id,
                    p.plano_recorrente,
                    sinal_do_quadro(imagem),
                )
            )
    return planos


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
