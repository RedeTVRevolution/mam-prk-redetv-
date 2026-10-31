"""As 3 Decupagens de exemplo, feitas à mão, do teste do filtro composto (#117).

O dublê em memória e o `make medir-busca` indexam as mesmas três: a Sabrina Sato de
vestido vermelho ao lado de outra pessoa de vestido azul; outra pessoa de vestido
vermelho noutro plano; um sapato vermelho sem dono.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from api.decupagem import VERSAO_ESQUEMA, Decupagem
from api.indice_da_busca import Registro, registros_da_decupagem

SABRINA = "cat-sabrina-sato"
OUTRA = "cat-outra"


@dataclass(frozen=True)
class Exemplo:
    job_id: str
    decupagem: Decupagem
    programa: str = "Exemplo"
    data_de_exibicao: date = date(2026, 10, 30)

    def registros(self) -> list[Registro]:
        return registros_da_decupagem(
            self.job_id, self.decupagem, self.programa, self.data_de_exibicao
        )


def _pessoa(
    id: str, nome: str, catalogo_id: str, inicio: int, fim: int
) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "catalogo_id": catalogo_id,
        "na_imagem": [{"inicio_ms": inicio, "fim_ms": fim, "evidencia": "rosto"}],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }


def _objeto(
    id: str, categoria: str, tipo: str, cor: str, dono: str | None, fim: int
) -> dict[str, Any]:
    return {
        "id": id,
        "categoria": categoria,
        "tipo": tipo,
        "cor_base": [cor],
        "pessoa": dono,
        "relacao": None if dono is None else "veste",
        "ocorrencias": [{"inicio_ms": 0, "fim_ms": fim}],
    }


def _decupagem(
    pessoas: list[dict[str, Any]], objetos: list[dict[str, Any]], falas: list[str]
) -> Decupagem:
    return Decupagem.model_validate(
        {
            "versao_esquema": VERSAO_ESQUEMA,
            "video": {"sha256": "b" * 64, "duracao_ms": 8_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": pessoas,
            "objetos": objetos,
            "planos": [
                {
                    "id": "pla1",
                    "inicio_ms": 0,
                    "fim_ms": 4_000,
                    "ambiente": "estúdio",
                    "plano_limpo": False,
                },
                {
                    "id": "pla2",
                    "inicio_ms": 4_000,
                    "fim_ms": 8_000,
                    "ambiente": "bastidor",
                    "plano_limpo": True,
                },
            ],
            "comerciais": [],
            "transcricao": [
                {
                    "inicio_ms": 0,
                    "fim_ms": 3_000,
                    "locutor": "Apresentadora",
                    "texto": t,
                }
                for t in falas
            ],
            "textos_na_tela": [
                {
                    "inicio_ms": 500,
                    "fim_ms": 3_500,
                    "tipo": "gc",
                    "texto": "Noite de gala",
                }
            ],
        }
    )


EXEMPLOS = [
    Exemplo(
        "ex-sabrina",
        _decupagem(
            [
                _pessoa("pes01", "Sabrina Sato", SABRINA, 0, 4_000),
                _pessoa("pes02", "Outra Pessoa", OUTRA, 0, 4_000),
            ],
            [
                _objeto("obj01", "roupa", "vestido", "vermelho", "pes01", 4_000),
                _objeto("obj02", "roupa", "vestido", "azul", "pes02", 4_000),
            ],
            ["Boa noite a todos"],
        ),
    ),
    Exemplo(
        "ex-outra",
        _decupagem(
            [_pessoa("pes01", "Outra Pessoa", OUTRA, 4_000, 8_000)],
            [_objeto("obj01", "roupa", "vestido", "vermelho", "pes01", 8_000)],
            ["Bem-vindos ao programa"],
        ),
    ),
    Exemplo(
        "ex-sapato",
        _decupagem(
            [],
            [_objeto("obj01", "calcado", "sandália", "vermelho", None, 4_000)],
            ["Um sapato esquecido"],
        ),
    ),
]
