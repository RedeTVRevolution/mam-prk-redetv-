"""Adaptadores vazios para quando falta o serviço de verdade (testes e máquina local).

Sem efeito de import: quem só precisa de um deles (a sonda da busca) não monta o app.
"""

from api.auth import ChaveInvalida, Sistema, TokenInvalido, Usuario
from api.gemini import Chamada, ErroHttp


class SemVerificador:
    """Sem projeto do Identity Platform (testes e máquina local): nega tudo."""

    def verificar(self, token: str) -> Usuario:
        raise TokenInvalido


class SemChaves:
    """Sem adaptador de chaves de API: recusa toda chave."""

    def verificar(self, chave: str) -> Sistema:
        raise ChaveInvalida


class SemModelo:
    """Sem modelo ligado: a busca por imagem fica indisponível."""

    def gerar(self, chamada: Chamada) -> str:
        raise ErroHttp(503)
