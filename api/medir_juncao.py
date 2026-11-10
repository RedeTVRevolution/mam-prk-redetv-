"""`make medir-juncao` (#547): mede a junção das pessoas sem nome em Decupagens gravadas.

    python -m api.medir_juncao DECUPAGEM.json [DECUPAGEM.json ...]

Lê arquivos locais (baixe a Decupagem do bucket antes); não chama o Gemini nem a nuvem.
Para cada uma imprime a contagem de pessoas antes e depois (só com as uniões sem
modelo), os pares candidatos, os que se unem sem perguntar e os da faixa ambígua, e o
tamanho do lote que iria ao modelo (pares, quadros). O custo e o tempo da chamada
saem do `custo` do Job no dev: este script dá só o tamanho do pedido.

Com `--amostra N`, sorteia até N grupos juntados (um par por grupo, estável pelo hash
do id do grupo, como `reservado_pelo_sorteio`) para a pessoa conferir a precisão.
"""

import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from api.decupagem import Decupagem
from api.juncao_de_pessoas import (
    LIMITE_DE_PARES,
    juntar_sem_nome,
    planejar,
)


@dataclass(frozen=True)
class Medicao:
    arquivo: str
    pessoas_antes: int
    pessoas_depois: int
    sem_nome_antes: int
    sem_nome_depois: int
    candidatas: int
    unidas_sem_perguntar: int
    na_duvida: int
    pares_no_lote: int
    quadros_no_lote: int
    horas: float


def _sem_nome(d: Decupagem) -> int:
    return len(planejar(d)[0])


def medir(arquivo: str, d: Decupagem) -> Medicao:
    candidatas, diretas, duvidosas = planejar(d)
    lote = duvidosas[:LIMITE_DE_PARES]
    depois = juntar_sem_nome(d)
    return Medicao(
        arquivo=arquivo,
        pessoas_antes=len(d.pessoas),
        pessoas_depois=len(depois.pessoas),
        sem_nome_antes=len(candidatas),
        sem_nome_depois=_sem_nome(depois),
        candidatas=len(candidatas),
        unidas_sem_perguntar=len(diretas),
        na_duvida=len(duvidosas),
        pares_no_lote=len(lote),
        quadros_no_lote=len({p.id for e in lote for p in (e.a, e.b)}),
        horas=d.video.duracao_ms / 3_600_000,
    )


def amostra(decupagens: dict[str, Decupagem], n: int) -> list[dict[str, str]]:
    """Até `n` grupos juntados, na ordem do hash do id do grupo (`arquivo:pessoa`), com
    o par de origens que o hash escolhe em cada um. Os mesmos grupos caem na amostra
    antes e depois de uma mudança."""
    achados: list[tuple[str, dict[str, str]]] = []
    for arquivo, d in decupagens.items():
        for p in juntar_sem_nome(d).pessoas:
            if len(p.origens) < 2:
                continue
            grupo = f"{arquivo}:{p.id}"
            a, b = sorted(
                p.origens,
                key=lambda o: hashlib.sha256(f"{grupo}:{o.id}".encode()).hexdigest(),
            )[:2]
            achados.append(
                (
                    hashlib.sha256(grupo.encode()).hexdigest(),
                    {"grupo": grupo, "a": a.chave, "b": b.chave},
                )
            )
    return [par for _, par in sorted(achados, key=lambda x: x[0])[:n]]


def main(argv: Sequence[str]) -> int:
    args = list(argv)
    n = 0
    if "--amostra" in args:
        i = args.index("--amostra")
        n = int(args[i + 1])
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2
    lidas = {
        Path(a).name: Decupagem.model_validate_json(Path(a).read_text()) for a in args
    }
    for arquivo, d in lidas.items():
        print(json.dumps(medir(arquivo, d).__dict__, ensure_ascii=False))
    if n:
        for par in amostra(lidas, n):
            print(json.dumps(par, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
