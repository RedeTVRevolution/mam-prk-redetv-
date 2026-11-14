"""Aceite dos cinco esquemas de resposta do Gemini contra o Vertex (#617).

O CI usa cassete e não fala com o Vertex, então um esquema que o serviço recusa (400) só
aparecia num vídeo de verdade. Este módulo manda cada esquema, gerado do código que vai ao
ar, numa chamada curta só de texto, e o `scripts/deploy-dev.sh` o chama antes do build, para
um esquema recusado não ir ao ar.
Fica fora do `make verificar` e do CI: lá não há credenciais.

Uso: `make aceitar-esquemas` ou `python -m api.aceite_dos_esquemas`. Ambiente: `GCP_PROJECT_ID`
e, para falar como a mam-terraform, `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`.
Saída: 0 aceito (ou só 429/5xx, passageiros), 1 algum 400 (esquema recusado: derruba o
deploy), 2 sem prova (falha antes da primeira chamada, ou outra exceção sem nenhum 400:
acesso ainda não propagado no primeiro deploy, modelo, rede: o deploy só avisa e segue).
Todos os esquemas são tentados e o 400 colhido nunca se perde por erro numa chamada seguinte.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Literal

from api import gemini
from api.clientes_de_nuvem import sessao_autenticada
from api.decupagem import esquema_do_modelo
from api.entendimento_da_consulta import MODELO_DA_CONSULTA, esquema_do_termo_da_foto
from api.gemini import (
    MODO_STANDARD,
    Chamada,
    ErroHttp,
    Transporte,
    TransporteVertex,
    repetivel,
)
from api.inventario import RespostaConvertida, RespostaVista, esquema_obrigatorio
from api.modelo_forte import MODELO_FORTE, esquema_da_resposta

Veredito = Literal["aceito", "recusado", "passageiro", "sem_prova"]


@dataclass(frozen=True)
class Resultado:
    nome: str
    veredito: Veredito
    detalhe: str = ""


def _esquemas() -> dict[str, tuple[str, dict[str, Any]]]:
    """Nome -> (modelo, esquema), cada um como a produção o manda."""
    return {
        "analise": (gemini.MODELO, esquema_do_modelo()),
        "inventario_convertido": (
            gemini.MODELO,
            esquema_obrigatorio(RespostaConvertida),
        ),
        "inventario_visto": (gemini.MODELO, esquema_obrigatorio(RespostaVista)),
        "identificacao": (MODELO_FORTE, esquema_da_resposta()),
        "busca_por_foto": (MODELO_DA_CONSULTA, esquema_do_termo_da_foto()),
    }


def aceitar(transporte: Transporte) -> list[Resultado]:
    resultados = []
    for nome, (modelo, esquema) in _esquemas().items():
        chamada = Chamada(
            modelo=modelo,
            instrucao="Responda ao esquema com o mínimo possível.",
            video_uri="",
            esquema=esquema,
            rotulos={"etapa": "aceite_dos_esquemas"},
            texto="Diga ok.",
            # Standard e prazo curto: o Flex pode enfileirar, e o deploy não espera por isso.
            modo=MODO_STANDARD,
            timeout_s=60,
        )
        try:
            transporte.gerar(chamada)
            resultados.append(Resultado(nome, "aceito"))
        except ErroHttp as e:
            # 429 e 5xx: falta de capacidade ou falha do serviço, nada a ver com o esquema.
            if e.status == 400:
                veredito: Veredito = "recusado"
            elif repetivel(e.status):
                veredito = "passageiro"
            else:
                veredito = "sem_prova"
            resultados.append(Resultado(nome, veredito, str(e)))
        except Exception as e:  # noqa: BLE001
            # Token, rede, JSON: não prova nada, mas não pode jogar fora um 400 já colhido.
            resultados.append(Resultado(nome, "sem_prova", f"{type(e).__name__}: {e}"))
    return resultados


def codigo_de_saida(resultados: list[Resultado]) -> int:
    vereditos = {r.veredito for r in resultados}
    return 1 if "recusado" in vereditos else 2 if "sem_prova" in vereditos else 0


def main() -> int:
    try:
        transporte = TransporteVertex(
            os.environ["GCP_PROJECT_ID"],
            sessao_autenticada(
                personificar=os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
            ),
            etapa="aceite_dos_esquemas",
        )
    except Exception as e:  # noqa: BLE001
        # Antes da primeira chamada: não prova nada sobre o esquema.
        print(f"sem prova: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return 2
    resultados = aceitar(transporte)
    for r in resultados:
        print(f"{r.nome}: {r.veredito} {r.detalhe}".rstrip(), flush=True)
    return codigo_de_saida(resultados)


if __name__ == "__main__":
    sys.exit(main())
