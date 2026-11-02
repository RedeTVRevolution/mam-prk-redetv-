"""`make sondar-busca`: roda as consultas de `CASOS` na busca do dev (índice, Firestore e plano B
reais, com o corte do serviço) e dá um veredito por consulta. Roda só com credenciais
e fica fora do CI.

    python -m api.sondar_busca

Os casos valem para os clipes do dev (clipe1, clipe2 e clipe3). Há três tipos de caso:
  existe  -> o 1º momento do 1º vídeo cita o termo, com até `teto` momentos no todo;
  exatos  -> `teto` momentos citam o termo e, em cada vídeo, vêm antes dos parecidos;
  ausente -> nenhum vídeo.
"""

import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from google.cloud import firestore

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.busca import Busca, RankingEmOrdem, VideoDoResultado
from api.gemini import Chamada, ErroHttp
from api.jobs import Armazenamento
from api.nuvem import CatalogoFirestore, RepositorioFirestore
from api.programas import PERFIS


@dataclass(frozen=True)
class Caso:
    consulta: str
    termo: str | None  # None: nada nos vídeos fala disso
    teto: int = 0
    exatos: bool = False


CASOS = [
    Caso("terno", "terno", 3),
    Caso("paletó", "terno", 4),
    # 7 aparições da calça vinho nos 3 clipes; o cropped vinho e a calça bege vêm depois.
    Caso("calça vinho", "calça vinho", 7, exatos=True),
    Caso("Flávia Noronha", "flávia", 30),
    Caso("apresentador de terno", "terno", 30),
    Caso("remédio barato", "medicamento", 25),
    Caso("sorteio de prêmios", "prêmios", 15),
    Caso("tchau", "tchau", 15),
    Caso("ultrafarma", "ultrafarma", 25),
    # Objetos de cena (#245): o inventário no registro do plano e os de destaque 3.
    # Gabarito do #121 (o carro BYD, as motos no telão do Bolão) e do programa FAMA
    # (os livros, a revista, o microfone da RedeTV!).
    Caso("carro BYD", "byd", 30),
    Caso("motos no telão", "moto", 30),
    Caso("livros", "livro", 30),
    Caso("revista", "revista", 30),
    Caso("microfone da RedeTV!", "microfone", 30),
    Caso("bicicleta", None),
    Caso("cachorro", None),
    Caso("foguete espacial", None),
    Caso("receita de bolo de chocolate", None),
    Caso("jogo de futebol no estádio", None),
    Caso("xyzzy", None),
]


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
    for caso in CASOS:
        videos = busca.buscar(caso.consulta).videos
        total = sum(v.n_momentos for v in videos)
        print(f"\n### {caso.consulta!r}: {total} momentos em {len(videos)} vídeos")
        for v in videos:
            print(f"  [{v.job_id[:8]}] {v.nome[:40]} ({v.n_momentos})")
            for m in v.momentos[:8]:
                print(f"     {m.inicio_ms / 1000:7.1f}s {m.motivo[:80]}")
        ok = veredito(caso, videos)
        falhas += not ok
        print("  =>", "VERDE" if ok else "VERMELHO")
    print(f"\n{falhas} consulta(s) vermelha(s) de {len(CASOS)}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
