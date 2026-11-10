"""Carga dos planos recorrentes no acervo antigo (#546): `make preencher-planos-recorrentes`.

Agrupa os planos de cada Job concluído (os da lixeira também) com os quadros-chave e a
Decupagem que já estão no bucket das decupagens, sem chamar modelo, e grava `plano_recorrente`
em cada plano que tem par. Por padrão é só a prévia: mostra a contagem antes e depois e não
escreve nada; com `--gravar`, regrava a Decupagem dos vídeos cujo grupo mudou. Repetir não muda
nada (o mesmo agrupamento dá os mesmos ids, e vídeo sem mudança não é regravado). Não toca o
Job, o resultado bruto do Florence-2 nem as Correções: só o campo novo dos planos entra na
Decupagem, e as Correções, que se apoiam em tipo, identidade e intervalo do item, continuam
casando com a versão nova pela reconciliação de sempre.

Ambiente: `GCP_PROJECT_ID`, `BUCKET_DECUPAGENS`.
"""

import logging
import os
import sys
from functools import partial
from typing import Protocol

from google.cloud.storage import Client as ClienteStorage

from api import log_estruturado
from api.bancos import cliente_do_firestore
from api.decupagem import Decupagem
from api.jobs import FiltroDeJobs, RepositorioDeJobs
from api.nuvem import ObjetosStorage, RepositorioFirestore
from api.planos_recorrentes import com_os_planos_recorrentes, contagem

log = logging.getLogger(__name__)

POR_PAGINA = 500


class ArmazenamentoDosGrupos(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def ler_quadro(self, job_id: str, caminho: str) -> bytes: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...


def preencher(
    repositorio: RepositorioDeJobs,
    armazenamento: ArmazenamentoDosGrupos,
    *,
    gravar: bool,
    por_pagina: int = POR_PAGINA,
) -> dict[str, int]:
    """Devolve, do acervo lido, os `planos` e `grupos` antes e depois, os `videos` lidos, os
    que `mudam` (ou mudaram, com `gravar`) e os que `falhou` (ficam para a próxima rodada)."""
    total = dict.fromkeys(
        (
            "videos",
            "mudam",
            "planos_antes",
            "grupos_antes",
            "planos_depois",
            "grupos_depois",
            "falhou",
        ),
        0,
    )
    cursor: str | None = None
    while True:
        pagina = repositorio.consultar(
            FiltroDeJobs(na_lixeira=None, limite=por_pagina, cursor=cursor)
        )
        for job in pagina.jobs:
            if job.estado != "concluido":
                continue
            try:
                antes = armazenamento.ler_decupagem(job.id)
                if antes is None:
                    raise RuntimeError("sem Decupagem no bucket")
                depois = com_os_planos_recorrentes(
                    antes, partial(armazenamento.ler_quadro, job.id)
                )
                mudou = [p.plano_recorrente for p in antes.planos] != [
                    p.plano_recorrente for p in depois.planos
                ]
                if mudou and gravar:
                    armazenamento.gravar_decupagem(job.id, depois.model_dump_json())
            except Exception:
                log.exception("planos recorrentes não preenchidos para %s", job.id)
                total["falhou"] += 1
                continue
            c_antes, c_depois = contagem(antes), contagem(depois)
            total["videos"] += 1
            total["mudam"] += mudou
            total["planos_antes"] += c_antes["planos"]
            total["grupos_antes"] += c_antes["grupos"]
            total["planos_depois"] += c_depois["planos"]
            total["grupos_depois"] += c_depois["grupos"]
        cursor = pagina.proximo_cursor
        if cursor is None:
            return total


def main(argumentos: list[str]) -> int:
    gravar = "--gravar" in argumentos
    projeto = os.environ["GCP_PROJECT_ID"]
    total = preencher(
        RepositorioFirestore(cliente_do_firestore(projeto)),
        ObjetosStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_DECUPAGENS"]
        ),
        gravar=gravar,
    )
    for nome, quantos in total.items():
        print(f"{nome}: {quantos}")
    if not gravar:
        print("Prévia: nada foi gravado. Para gravar, rode com GRAVAR=1.")
    return 1 if total["falhou"] else 0


if __name__ == "__main__":
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main(sys.argv[1:]))
