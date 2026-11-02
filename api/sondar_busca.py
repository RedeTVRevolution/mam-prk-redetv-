"""`make sondar-busca`: roda as consultas de `consultas_da_sonda.toml` na busca do dev (índice, Firestore e plano B
reais, com o corte do serviço) e dá um veredito por consulta. Roda só com credenciais
e fica fora do CI.

    python -m api.sondar_busca

Os casos valem para os clipes do dev (clipe1, clipe2 e clipe3); o formato do arquivo está
no cabeçalho dele. Há três tipos de caso:
  existe  -> o 1º momento do 1º vídeo cita o termo, com até `teto` momentos no todo;
  exatos  -> `teto` momentos citam o termo e, em cada vídeo, vêm antes dos parecidos;
  ausente -> nenhum vídeo.

O aceite (#258): a média, entre as consultas com anotação de pertinência (`termo` ou
`pertinentes`), da fração dos 5 primeiros resultados pertinentes, de pelo menos 80%. O relatório
lista as consultas abaixo disso; a consulta sem anotação roda, mas fica fora da conta.
"""

import logging
import os
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from google.cloud import firestore

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.busca import Ajustes, Busca, Momento, RankingEmOrdem, VideoDoResultado
from api.gemini import Chamada, ErroHttp
from api.jobs import Armazenamento
from api.nuvem import CatalogoFirestore, RepositorioFirestore
from api.programas import PERFIS


@dataclass(frozen=True)
class Trecho:
    """Momentos pertinentes de um vídeo: o início do id do Job e o intervalo, em segundos."""

    job: str
    de_s: float
    ate_s: float


@dataclass(frozen=True)
class Caso:
    consulta: str
    termo: str | None = None  # None: nada nos vídeos fala disso
    teto: int = 0
    exatos: bool = False
    programa: str | None = None
    desde: date | None = None
    ate: date | None = None
    pertinentes: tuple[Trecho, ...] = ()

    @property
    def anotado(self) -> bool:
        return self.termo is not None or bool(self.pertinentes)


ARQUIVO_DAS_CONSULTAS = Path(__file__).parent / "consultas_da_sonda.toml"
ACEITE = 0.8
RESULTADOS_DO_ACEITE = 5
_CAMPOS = {
    "texto",
    "termo",
    "teto",
    "exatos",
    "programa",
    "desde",
    "ate",
    "pertinentes",
}


def _trecho(dado: dict[str, Any], consulta: str) -> Trecho:
    trecho = Trecho(job=dado["job"], de_s=dado["de_s"], ate_s=dado["ate_s"])
    if trecho.de_s > trecho.ate_s:
        raise ValueError(f"{consulta!r}: de_s depois de ate_s em {dado}")
    return trecho


def ler_casos(arquivo: Path = ARQUIVO_DAS_CONSULTAS) -> list[Caso]:
    casos = []
    for dado in tomllib.loads(arquivo.read_text()).get("consulta", []):
        texto = dado["texto"]
        if extras := dado.keys() - _CAMPOS:
            raise ValueError(f"{texto!r}: campo desconhecido {sorted(extras)}")
        casos.append(
            Caso(
                consulta=texto,
                termo=dado.get("termo"),
                teto=dado.get("teto", 0),
                exatos=dado.get("exatos", False),
                programa=dado.get("programa"),
                desde=dado.get("desde"),
                ate=dado.get("ate"),
                pertinentes=tuple(
                    _trecho(t, texto) for t in dado.get("pertinentes", [])
                ),
            )
        )
    return casos


CASOS = ler_casos()


def primeiros_resultados(
    videos: list[VideoDoResultado], n: int = RESULTADOS_DO_ACEITE
) -> list[tuple[VideoDoResultado, Momento]]:
    """Os `n` primeiros momentos na ordem em que a tela os mostra (vídeo a vídeo)."""
    return [(v, m) for v in videos for m in v.momentos][:n]


def _pertinente(caso: Caso, video: VideoDoResultado, momento: Momento) -> bool:
    if caso.termo is not None and caso.termo in momento.motivo.lower():
        return True
    inicio_s = momento.inicio_ms / 1000
    return any(
        video.job_id.startswith(t.job) and t.de_s <= inicio_s <= t.ate_s
        for t in caso.pertinentes
    )


def pertinencia(caso: Caso, videos: list[VideoDoResultado]) -> float | None:
    """Fração dos 5 primeiros resultados pertinentes; None se a consulta não tem anotação.

    Com menos de 5 resultados, a fração é dos que vieram; nenhum resultado vale 0."""
    if not caso.anotado:
        return None
    primeiros = primeiros_resultados(videos)
    if not primeiros:
        return 0.0
    return sum(_pertinente(caso, v, m) for v, m in primeiros) / len(primeiros)


@dataclass(frozen=True)
class Aceite:
    total: float | None  # média das frações das consultas anotadas
    passou: bool
    abaixo: list[tuple[Caso, float]]


def relatorio_do_aceite(medidas: list[tuple[Caso, float | None]]) -> Aceite:
    contadas = [(c, f) for c, f in medidas if f is not None]
    if not contadas:
        return Aceite(total=None, passou=False, abaixo=[])
    total = sum(f for _, f in contadas) / len(contadas)
    abaixo = [(c, f) for c, f in contadas if f < ACEITE]
    return Aceite(total=total, passou=total >= ACEITE, abaixo=abaixo)


def veredito(caso: Caso, videos: list[VideoDoResultado]) -> bool:
    if caso.termo is None:
        return not videos
    termo = caso.termo
    if caso.exatos:
        cita = [[termo in m.motivo.lower() for m in v.momentos] for v in videos]
        em_ordem = all(c == sorted(c, reverse=True) for c in cita)
        return sum(map(sum, cita)) == caso.teto and em_ordem
    total = sum(v.n_momentos for v in videos)
    return (
        bool(videos)
        and termo in videos[0].momentos[0].motivo.lower()
        and total <= caso.teto
    )


# O plano B do dev: o `criar_app` de `api/main.py` não recebe modelo nem Model Armor.
# Importar o `api.main` montaria o app, que pede o ambiente inteiro.
class _SemModelo:
    def gerar(self, chamada: Chamada) -> str:
        raise ErroHttp(503)


class _SemModelArmor:
    def acusa_injecao(self, texto: str) -> bool:
        raise RuntimeError("Model Armor não ligado")


class _SemQuadro:
    """A sonda não abre quadros: a URL assinada não muda o resultado."""

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        return caminho

    def ler_comparacao(self, job_id: str) -> bytes | None:
        return None

    def url_da_foto(self, objeto: str, validade: timedelta) -> str:
        return objeto


def _ajustes(caso: Caso) -> Ajustes | None:
    if caso.programa is None and caso.desde is None and caso.ate is None:
        return None
    return Ajustes(programa=caso.programa, desde=caso.desde, ate=caso.ate)


def main() -> int:
    # O plano B registra a falta do Model Armor a cada consulta; aqui é o esperado.
    logging.getLogger("api.entendimento_da_consulta").setLevel(logging.CRITICAL)
    cliente = firestore.Client(project=os.environ["GCP_PROJECT_ID"])
    busca = Busca(
        transporte=_SemModelo(),
        catalogo=CatalogoFirestore(cliente),
        armor=_SemModelArmor(),
        programas=sorted(PERFIS),
        indice=AgentRetrieval(ConfigDaBusca.do_ambiente(os.environ), transporte_http()),
        ranking=RankingEmOrdem(),
        repositorio=RepositorioFirestore(cliente),
        armazenamento=cast(Armazenamento, _SemQuadro()),
        relogio=lambda: datetime.now(UTC),
    )
    falhas = 0
    medidas: list[tuple[Caso, float | None]] = []
    for caso in CASOS:
        videos = busca.buscar(caso.consulta, ajustes=_ajustes(caso)).videos
        total = sum(v.n_momentos for v in videos)
        print(f"\n### {caso.consulta!r}: {total} momentos em {len(videos)} vídeos")
        for v in videos:
            print(f"  [{v.job_id[:8]}] {v.nome[:40]} ({v.n_momentos})")
            for m in v.momentos[:8]:
                print(f"     {m.inicio_ms / 1000:7.1f}s {m.motivo[:80]}")
        ok = veredito(caso, videos)
        falhas += not ok
        fracao = pertinencia(caso, videos)
        medidas.append((caso, fracao))
        pertinentes = "sem anotação" if fracao is None else f"{fracao:.0%} pertinentes"
        print("  =>", "VERDE" if ok else "VERMELHO", f"({pertinentes} nos 5 primeiros)")
    print(f"\n{falhas} consulta(s) vermelha(s) de {len(CASOS)}")
    aceite = relatorio_do_aceite(medidas)
    if aceite.total is None:
        print("Aceite: nenhuma consulta com anotação de pertinência")
    else:
        situacao = "PASSOU" if aceite.passou else "NÃO PASSOU"
        print(
            f"Aceite: {aceite.total:.0%} dos 5 primeiros pertinentes (mínimo {ACEITE:.0%}): {situacao}"
        )
    for caso, fracao in aceite.abaixo:
        print(f"  abaixo de {ACEITE:.0%}: {caso.consulta!r} ({fracao:.0%})")
    return 1 if falhas or not aceite.passou else 0


if __name__ == "__main__":
    sys.exit(main())
