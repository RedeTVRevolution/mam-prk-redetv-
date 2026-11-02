"""Inventário de objetos por plano (#244): destaque, repetidos e conversão.

O inventário é do servidor: não entra no esquema da análise, e a Decupagem só recebe
texto em português.
"""

from api.decupagem import CaixaDoQuadro

# Regra do destaque (1 a 3), só da maior caixa do objeto: área em fração do quadro e
# distância do centro da caixa ao centro do quadro (0 a ~0,71).
AREA_GRANDE = 0.10
AREA_MEDIA = 0.02
PERTO_DO_CENTRO = 0.25


def destaque_da_caixa(caixa: CaixaDoQuadro) -> int:
    area = caixa.largura * caixa.altura
    distancia = (
        (caixa.x + caixa.largura / 2 - 0.5) ** 2
        + (caixa.y + caixa.altura / 2 - 0.5) ** 2
    ) ** 0.5
    central = distancia <= PERTO_DO_CENTRO
    if area >= AREA_GRANDE and central:
        return 3
    if area >= AREA_GRANDE or (area >= AREA_MEDIA and central):
        return 2
    return 1
