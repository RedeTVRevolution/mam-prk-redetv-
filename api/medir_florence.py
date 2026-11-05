"""`make medir-florence` (#329): mede as variações do Florence-2 na GPU num Job já decupado.

Para cada variação, roda o Job de objetos com GPU sobre os quadros já gravados do Job
(com as variáveis `FLORENCE_*` da variação e um destino próprio), converte o bruto com o
Gemini e guarda ao lado do resultado de hoje, sem sobrescrevê-lo, em
`<job>/objetos/medicao/<variacao>/`: `bruto.json`, `inventario.json` e `medida.json`.
A variação `hoje` (sem nenhuma variável) é a base: o critério de qualidade das outras é
calculado contra o inventário convertido dela. No fim imprime a tabela.

    python -m api.medir_florence JOB_ID [VARIACAO ...]

Vem do ambiente (o Makefile lê os nomes do Terraform): `GCP_PROJECT_ID`,
`BUCKET_DECUPAGENS`, `REGIAO_GPU`, `JOB_DE_OBJETOS_GPU` e `MODELO_OBJETOS` (o modelo
do Gemini que converte o bruto para o português).
"""

import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud.storage import Client as ClienteStorage

from api.comparador import normalizar
from api.comparar_objetos import (
    DisparadorDoCloudRun,
    FaltaNoAmbiente,
    exigir_do_ambiente,
)
from api.decupagem import Decupagem
from api.florence import ObjetosDaDecupagem
from api.gemini import SessaoHttp, Transporte, TransporteVertex
from api.inventario import Inventarios, converter_do_florence
from api.nuvem import ObjetosStorage

BASE = "hoje"
FRACAO_MINIMA = 0.9  # do que há hoje, nos objetos de cena e em cada categoria
META_S_POR_QUADRO = 0.7
FORA_DA_CENA = frozenset({"roupa", "acessorio", "calcado"})

# Cada variação é o conjunto de variáveis `FLORENCE_*` que o Job recebe a mais.
VARIACOES: dict[str, dict[str, str]] = {
    BASE: {},
    "guloso": {"FLORENCE_FEIXES": "1"},
    "lote8": {"FLORENCE_LOTE": "8"},
    "lote16": {"FLORENCE_LOTE": "16"},
    "tokens256": {"FLORENCE_MAX_TOKENS": "256"},
    "sem-legendas": {"FLORENCE_LEGENDAS": "0"},
    "repetidos": {"FLORENCE_PULAR_REPETIDOS": "6"},
    "guloso+lote8": {"FLORENCE_FEIXES": "1", "FLORENCE_LOTE": "8"},
    "guloso+lote16": {"FLORENCE_FEIXES": "1", "FLORENCE_LOTE": "16"},
    "guloso+lote8+tokens256": {
        "FLORENCE_FEIXES": "1",
        "FLORENCE_LOTE": "8",
        "FLORENCE_MAX_TOKENS": "256",
    },
    "guloso+lote8+sem-legendas": {
        "FLORENCE_FEIXES": "1",
        "FLORENCE_LOTE": "8",
        "FLORENCE_LEGENDAS": "0",
    },
    "tudo": {
        "FLORENCE_FEIXES": "1",
        "FLORENCE_LOTE": "8",
        "FLORENCE_MAX_TOKENS": "256",
        "FLORENCE_LEGENDAS": "0",
        "FLORENCE_PULAR_REPETIDOS": "6",
    },
}


@dataclass(frozen=True)
class Criterio:
    """Um inventário convertido contra o de hoje (#329)."""

    cena_hoje: int
    cena: int
    pior_categoria: str | None  # a de maior queda, com a fração que sobrou
    pior_fracao: float
    destaque_3_perdidos: list[str] = field(default_factory=list)

    @property
    def fracao_da_cena(self) -> float:
        return self.cena / self.cena_hoje if self.cena_hoje else 1.0

    @property
    def passa(self) -> bool:
        return (
            self.fracao_da_cena >= FRACAO_MINIMA
            and self.pior_fracao >= FRACAO_MINIMA
            and not self.destaque_3_perdidos
        )


def avaliar(hoje: Inventarios, variacao: Inventarios) -> Criterio:
    """Os objetos de cena (fora roupa, acessório e calçado) somam pelo menos 90% dos de
    hoje; nenhuma categoria cai mais que isso; nenhum objeto de destaque 3 de hoje some.
    O objeto é o mesmo se o plano, a categoria e o nome (sem acento nem caixa) são iguais."""

    def contar(inventarios: Inventarios) -> dict[str, int]:
        contagem: dict[str, int] = {}
        for objetos in inventarios.values():
            for o in objetos:
                contagem[o.categoria] = contagem.get(o.categoria, 0) + 1
        return contagem

    antes, depois = contar(hoje), contar(variacao)
    fracoes = {c: depois.get(c, 0) / n for c, n in antes.items() if n}
    pior = min(fracoes, key=lambda c: fracoes[c]) if fracoes else None
    chaves = {
        (p, o.categoria, normalizar(o.nome)) for p, os_ in variacao.items() for o in os_
    }
    perdidos = [
        f"plano {p}: {o.nome} ({o.categoria})"
        for p, os_ in sorted(hoje.items())
        for o in os_
        if o.destaque == 3 and (p, o.categoria, normalizar(o.nome)) not in chaves
    ]
    return Criterio(
        cena_hoje=sum(n for c, n in antes.items() if c not in FORA_DA_CENA),
        cena=sum(n for c, n in depois.items() if c not in FORA_DA_CENA),
        pior_categoria=pior,
        pior_fracao=fracoes[pior] if pior else 1.0,
        destaque_3_perdidos=perdidos,
    )


@dataclass(frozen=True)
class Medida:
    variacao: str
    ambiente: dict[str, str]
    quadros: int
    segundos: float
    segundos_por_quadro: float


@dataclass
class Resultado:
    variacao: str
    medida: Medida | None = None
    inventario: Inventarios | None = None
    criterio: Criterio | None = None
    erro: str | None = None


class Armazem(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def ler_resultado(
        self, job_id: str, destino: str | None = None
    ) -> ObjetosDaDecupagem | None: ...

    def gravar_texto(self, objeto: str, conteudo: str) -> None: ...


class Disparador(Protocol):
    def rodar(
        self, job_id: str, destino: str, ambiente: Mapping[str, str] | None = None
    ) -> None: ...


def objeto_da_medicao(job_id: str, variacao: str, arquivo: str) -> str:
    """Sempre dentro de `<job>/objetos/medicao/`: nunca o `florence.json` do Job."""
    return f"{job_id}/objetos/medicao/{variacao}/{arquivo}"


def _inventario_em_json(inventarios: Inventarios) -> str:
    return json.dumps(
        {
            str(i): [o.model_dump(mode="json") for o in objetos]
            for i, objetos in inventarios.items()
        },
        ensure_ascii=False,
        indent=2,
    )


def medir(
    job_id: str,
    *,
    armazem: Armazem,
    disparador: Disparador,
    transporte: Transporte,
    modelo: str,
    variacoes: Mapping[str, Mapping[str, str]],
    dormir: Callable[[float], None] = time.sleep,
) -> list[Resultado]:
    """A base (`hoje`) roda primeiro, mesmo que não tenha sido pedida. Uma variação que
    falha (a memória da GPU, por exemplo) vira `erro` na tabela e as outras seguem."""
    decupagem = armazem.ler_decupagem(job_id)
    if decupagem is None:
        raise RuntimeError(f"Não há Decupagem do Job {job_id}.")
    nomes = [BASE, *(n for n in variacoes if n != BASE)]
    resultados: list[Resultado] = []
    for nome in nomes:
        ambiente = dict(variacoes.get(nome, VARIACOES.get(nome, {})))
        resultado = Resultado(nome)
        resultados.append(resultado)
        destino = objeto_da_medicao(job_id, nome, "bruto.json")
        try:
            disparador.rodar(job_id, destino, ambiente)
            bruto = armazem.ler_resultado(job_id, destino)
            if bruto is None or bruto.segundos is None:
                raise RuntimeError("o Job não gravou o resultado com os segundos")
            inventario = converter_do_florence(
                decupagem,
                bruto,
                transporte=transporte,
                modelo=modelo,
                job_id=job_id,
                dormir=dormir,
            )
        except Exception as e:  # noqa: BLE001 - cada variação é independente
            resultado.erro = str(e) or type(e).__name__
            continue
        resultado.inventario = inventario
        resultado.medida = Medida(
            variacao=nome,
            ambiente=ambiente,
            quadros=len(bruto.quadros),
            segundos=bruto.segundos,
            segundos_por_quadro=round(bruto.segundos / len(bruto.quadros), 3),
        )
        base = resultados[0].inventario
        if nome != BASE and base is not None:
            resultado.criterio = avaliar(base, inventario)
        armazem.gravar_texto(
            objeto_da_medicao(job_id, nome, "inventario.json"),
            _inventario_em_json(inventario),
        )
        armazem.gravar_texto(
            objeto_da_medicao(job_id, nome, "medida.json"),
            json.dumps(
                {
                    **asdict(resultado.medida),
                    "criterio": (
                        {
                            **asdict(resultado.criterio),
                            "passa": resultado.criterio.passa,
                        }
                        if resultado.criterio
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return resultados


def tabela(resultados: list[Resultado]) -> str:
    base = resultados[0].medida
    cabecalho = (
        f"{'variação':28} {'s/quadro':>8} {'vezes':>6} {'cena':>12} "
        f"{'pior categoria':>26} {'destaque 3':>10}  critério  meta"
    )
    linhas = [cabecalho]
    for r in resultados:
        if r.medida is None:
            linhas.append(f"{r.variacao:28} falhou: {r.erro}")
            continue
        s = r.medida.segundos_por_quadro
        vezes = f"{base.segundos_por_quadro / s:.1f}x" if base and s else "-"
        meta = "sim" if s <= META_S_POR_QUADRO else "não"
        c = r.criterio
        if c is None:
            linhas.append(
                f"{r.variacao:28} {s:8.3f} {vezes:>6} {'(base)':>12} "
                f"{'':>26} {'':>10}  {'-':8}  {meta}"
            )
            continue
        pior = f"{c.pior_categoria} {c.pior_fracao:.0%}" if c.pior_categoria else "-"
        linhas.append(
            f"{r.variacao:28} {s:8.3f} {vezes:>6} "
            f"{f'{c.cena}/{c.cena_hoje} {c.fracao_da_cena:.0%}':>12} {pior:>26} "
            f"{len(c.destaque_3_perdidos):>10}  {'passa' if c.passa else 'reprova':8}  {meta}"
        )
    escolhida = min(
        (
            r
            for r in resultados
            if r.medida and (r.criterio is None or r.criterio.passa)
        ),
        key=lambda r: cast(Medida, r.medida).segundos_por_quadro,
        default=None,
    )
    if escolhida:
        linhas.append(f"\nA mais rápida que passa no critério: {escolhida.variacao}")
    for r in resultados:
        if r.criterio and r.criterio.destaque_3_perdidos:
            linhas.append(f"\n{r.variacao}: destaque 3 que sumiu:")
            linhas.extend(f"  {p}" for p in r.criterio.destaque_3_perdidos)
    return "\n".join(linhas)


def main(argumentos: list[str], ambiente: Mapping[str, str] | None = None) -> int:
    ambiente = os.environ if ambiente is None else ambiente
    if not argumentos:
        print(
            "uso: python -m api.medir_florence JOB_ID [VARIACAO ...]", file=sys.stderr
        )
        return 2
    job_id, pedidas = argumentos[0], argumentos[1:]
    desconhecidas = [n for n in pedidas if n not in VARIACOES]
    if desconhecidas:
        print(
            f"erro: variação desconhecida: {', '.join(desconhecidas)}. "
            f"As que existem: {', '.join(VARIACOES)}",
            file=sys.stderr,
        )
        return 2
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        bucket = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
        regiao = exigir_do_ambiente(ambiente, "REGIAO_GPU")
        job = exigir_do_ambiente(ambiente, "JOB_DE_OBJETOS_GPU")
        modelo = exigir_do_ambiente(ambiente, "MODELO_OBJETOS")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao: Any = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]
    try:
        resultados = medir(
            job_id,
            armazem=ObjetosStorage(ClienteStorage(project=projeto), bucket),
            disparador=DisparadorDoCloudRun(projeto, regiao, job, sessao),
            transporte=TransporteVertex(projeto, cast(SessaoHttp, sessao)),
            modelo=modelo,
            variacoes={n: VARIACOES[n] for n in (pedidas or VARIACOES)},
        )
    except RuntimeError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    print(tabela(resultados))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
