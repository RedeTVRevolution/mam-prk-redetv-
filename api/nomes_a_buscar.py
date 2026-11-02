"""Os nomes que o Job de referências deve buscar (#222).

O Job de identificação grava a lista depois de olhar o vídeo; o Job de referências a lê.
São os palpites e os candidatos do vídeo que ainda não têm as 3 referências válidas, com
o programa. Quem decide se um palpite fora do catálogo já tem fotos é o Job de
referências, que é o dono do bucket.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel

from api.catalogo import Catalogo
from api.comparador import normalizar
from api.decupagem import Decupagem
from api.identidade import nao_identificado
from api.identificacao import candidatos_do_video
from api.referencias import com_as_tres_fotos


class NomesABuscar(BaseModel):
    programa: str | None = None
    nomes: list[str] = []


def nomes_a_buscar(
    decupagem: Decupagem,
    programa: str | None,
    catalogo: Catalogo,
    agora: datetime,
    validade: timedelta,
) -> NomesABuscar:
    """Primeiro os palpites (na imagem, sem a correção da revisora): os que o catálogo
    não conhece, e os que ele conhece sem as 3 fotos. Depois os candidatos do vídeo, só
    os do catálogo sem as 3 fotos. Nome ambíguo no catálogo não entra."""
    nomes: dict[str, str] = {}
    for p in decupagem.pessoas:
        if (
            p.estado_do_nome == "palpite"
            and p.origem != "revisao"
            and p.na_imagem
            and not nao_identificado(p.nome)
        ):
            achadas = catalogo.achar(p.nome)
            if len(achadas) > 1 or (
                achadas and com_as_tres_fotos(achadas[0], agora, validade)
            ):
                continue
            nomes.setdefault(normalizar(p.nome), p.nome)
    for c in candidatos_do_video(programa, catalogo):
        achadas = catalogo.achar(c.nome)
        if len(achadas) == 1 and not com_as_tres_fotos(achadas[0], agora, validade):
            nomes.setdefault(normalizar(c.nome), c.nome)
    return NomesABuscar(programa=programa, nomes=list(nomes.values()))
