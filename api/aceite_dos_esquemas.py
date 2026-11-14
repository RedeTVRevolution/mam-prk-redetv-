"""Aceite dos três esquemas de resposta do Gemini contra o Vertex (#617).

O CI usa cassete e não fala com o Vertex, então um esquema que o serviço recusa (400) só
aparecia num vídeo de verdade. Este módulo manda cada esquema, gerado do código que vai ao
ar, numa chamada curta só de texto, e o `scripts/deploy-dev.sh` o chama depois do apply.
Fica fora do `make verificar` e do CI: lá não há credenciais.

Uso: `make aceitar-esquemas` ou `python -m api.aceite_dos_esquemas`. Ambiente: `GCP_PROJECT_ID`
e, para falar como a mam-terraform, `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`.
Saída: 0 aceito (ou só 429/5xx, passageiros), 1 algum 400 (esquema recusado), 2 outro erro
(sem prova: acesso, modelo, rede).
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Literal

import google.auth
import google.auth.transport.requests
from google.auth import impersonated_credentials

from api import gemini
from api.clientes_de_nuvem import ESCOPO_DA_NUVEM
from api.decupagem import esquema_do_modelo
from api.gemini import Chamada, ErroHttp, Transporte, TransporteVertex
from api.inventario import RespostaConvertida, RespostaVista, _esquema

Veredito = Literal["aceito", "recusado", "passageiro", "sem_prova"]


@dataclass(frozen=True)
class Resultado:
    nome: str
    veredito: Veredito
    detalhe: str = ""


def _esquemas() -> dict[str, dict[str, Any]]:
    return {
        "analise": esquema_do_modelo(),
        "inventario_convertido": _esquema(RespostaConvertida),
        "inventario_visto": _esquema(RespostaVista),
    }


def aceitar(transporte: Transporte) -> list[Resultado]:
    resultados = []
    for nome, esquema in _esquemas().items():
        chamada = Chamada(
            modelo=gemini.MODELO,
            instrucao="Responda ao esquema com o mínimo possível.",
            video_uri="",
            esquema=esquema,
            rotulos={"etapa": "aceite_dos_esquemas"},
            texto="Diga ok.",
        )
        try:
            transporte.gerar(chamada)
            resultados.append(Resultado(nome, "aceito"))
        except ErroHttp as e:
            # 429 e 5xx: falta de capacidade ou falha do serviço, nada a ver com o esquema.
            if e.status == 400:
                veredito: Veredito = "recusado"
            elif e.status == 429 or e.status >= 500:
                veredito = "passageiro"
            else:
                veredito = "sem_prova"
            resultados.append(Resultado(nome, veredito, str(e)))
    return resultados


def codigo_de_saida(resultados: list[Resultado]) -> int:
    vereditos = {r.veredito for r in resultados}
    return 1 if "recusado" in vereditos else 2 if "sem_prova" in vereditos else 0


def _sessao() -> Any:
    credenciais, _ = google.auth.default(scopes=[ESCOPO_DA_NUVEM])
    conta = os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    if conta:
        credenciais = impersonated_credentials.Credentials(  # type: ignore[no-untyped-call]
            source_credentials=credenciais,
            target_principal=conta,
            target_scopes=[ESCOPO_DA_NUVEM],
        )
    return google.auth.transport.requests.AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]


def main() -> int:
    transporte = TransporteVertex(
        os.environ["GCP_PROJECT_ID"], _sessao(), etapa="aceite_dos_esquemas"
    )
    resultados = aceitar(transporte)
    for r in resultados:
        print(f"{r.nome}: {r.veredito} {r.detalhe}".rstrip(), flush=True)
    return codigo_de_saida(resultados)


if __name__ == "__main__":
    sys.exit(main())
