"""Catálogo dos tipos de Correção: rótulos, vocabulários e o valor legível.

É o que o front lia de listas copiadas: o rótulo de cada tipo, os vocabulários
do esquema com seus rótulos, os limites e os prefixos de id. O valor legível
de uma Correção (o `antes` e o `depois`) também sai daqui, uma vez por tipo.
"""

import json
import re
from collections.abc import Callable, Mapping
from typing import Any, get_args

from pydantic import BaseModel

from api.decupagem import (
    CATEGORIAS_DE_OBJETO,
    CORES_BASE,
    RELACOES_DO_OBJETO,
    Comercial,
    FonteDoNome,
    RelacaoDoObjeto,
    TextoNaTela,
    TomDaPauta,
    em_mm_ss,
)
from api.indice_da_busca import NOME_DA_CATEGORIA

# Os rótulos dos vocabulários do esquema; o que falta aqui sai igual ao valor.
ROTULOS_DOS_TONS = {
    "informativo": "informativo",
    "polemico": "polêmico",
    "descontraido": "descontraído",
    "exclusivo": "exclusivo",
    "homenagem": "homenagem",
    "analise": "análise",
    "comercial": "comercial",
}
ROTULOS_DAS_RELACOES: dict[RelacaoDoObjeto, str] = {
    "veste": "veste",
    "calca": "calça",
    "usa": "usa",
    "segura": "segura",
}
ROTULOS_DAS_FONTES = {
    "rosto": "rosto",
    "gc": "GC",
    "fala": "fala",
    "referencia": "referência de rosto",
}
ROTULOS_DAS_LISTAS = {
    "na_imagem": "aparição",
    "citada_na_fala": "citada na fala",
    "citada_no_texto": "citada no texto",
}

_OCORRENCIA = re.compile(rf"^({'|'.join(ROTULOS_DAS_LISTAS)}) (\d+)-(\d+)$")
_TEMPOS = re.compile(r"^(\d+)-(\d+)$")


def _faixa(inicio_ms: int, fim_ms: int) -> str:
    return f"{em_mm_ss(inicio_ms)}–{em_mm_ss(fim_ms)}"


def _comercial(c: dict[str, Any]) -> str:
    return f"{c['marca']} ({c['tipo']}) {_faixa(c['inicio_ms'], c['fim_ms'])}"


def _aparicao(a: dict[str, Any]) -> str:
    nome = f"{a['nome']} " if a.get("nome") else ""
    return f"{nome}{_faixa(a['inicio_ms'], a['fim_ms'])} ({a['evidencia']})"


def _texto_na_tela(t: dict[str, Any]) -> str:
    return f"{t['tipo']}: {t['texto']}"


def _texto_acrescentado(t: dict[str, Any]) -> str:
    return f"{_texto_na_tela(t)} {_faixa(t['inicio_ms'], t['fim_ms'])}"


def _pauta_acrescentada(p: dict[str, Any]) -> str:
    tom = ROTULOS_DOS_TONS.get(p["tom"], p["tom"])
    return f"{p['titulo']} ({tom}) {_faixa(p['inicio_ms'], p['fim_ms'])}"


def _atributos_do_objeto(o: dict[str, Any]) -> str:
    cores = ", ".join(o["cor_base"])
    return " · ".join(
        x for x in (o["tipo"], cores, o["cor"], o["detalhe"], o["marca"]) if x
    )


def _objeto_acrescentado(o: dict[str, Any]) -> str:
    partes = [NOME_DA_CATEGORIA[o["categoria"]], o["tipo"], ", ".join(o["cor_base"])]
    texto = " ".join(x for x in partes if x)
    if o["pessoa"] is not None:
        texto += f" (dono: {o['pessoa']})"
    return f"{texto} {_faixa(o['inicio_ms'], o['fim_ms'])}"


def _dono_do_objeto(o: dict[str, Any]) -> str:
    if o["pessoa"] is None:
        return "sem dono"
    return f"dono: {o['pessoa']} ({o['relacao']})"


def _pauta_estrutural(p: dict[str, Any]) -> str:
    """O título e a faixa de uma pauta (antes e depois de juntar, antes de dividir) ou
    as duas metades de uma divisão."""
    if "titulos" in p:
        primeira, segunda = p["titulos"]
        return f"{primeira} | {segunda} (corte em {em_mm_ss(p['em_ms'])})"
    return f"{p['titulo']} {_faixa(p['inicio_ms'], p['fim_ms'])}"


def _papel_visual(d: dict[str, Any]) -> str:
    return " · ".join(x for x in (d["papel"], d["visual"]) if x) or (
        "sem papel na cena e visual"
    )


def _plano(d: dict[str, Any]) -> str:
    if not isinstance(d["objetos"], list):
        raise TypeError("os objetos vêm numa lista")
    return " · ".join(
        x for x in (d["ambiente"], d["acao"], ", ".join(d["objetos"])) if x
    )


def _fala(f: dict[str, Any]) -> str:
    return f"{f['locutor']}: {f['texto']}"


def _fontes(fontes: list[str]) -> str:
    if not isinstance(fontes, list):
        raise TypeError("as fontes vêm numa lista")
    return ", ".join(ROTULOS_DAS_FONTES.get(f, f) for f in fontes) or "nenhuma fonte"


def de_json(formatar: Callable[[Any], str]) -> Callable[[str], str]:
    """O valor legível de um tipo cujo valor é um JSON: a função recebe o JSON lido."""

    def legivel(valor: str) -> str:
        return formatar(json.loads(valor))

    return legivel


comercial_acrescentado = de_json(_comercial)
aparicao_acrescentada = de_json(_aparicao)
texto_na_tela = de_json(_texto_na_tela)
texto_na_tela_acrescentado = de_json(_texto_acrescentado)
pauta_acrescentada = de_json(_pauta_acrescentada)
pauta_estrutural = de_json(_pauta_estrutural)
atributos_do_objeto = de_json(_atributos_do_objeto)
dono_do_objeto = de_json(_dono_do_objeto)
objeto_acrescentado = de_json(_objeto_acrescentado)
papel_visual = de_json(_papel_visual)
fontes_do_nome = de_json(_fontes)
descricao_do_plano = de_json(_plano)
fala = de_json(_fala)


def como_veio(valor: str) -> str:
    return valor


def tom_da_pauta(valor: str) -> str:
    return ROTULOS_DOS_TONS.get(valor, valor)


def objeto_na_imagem(valor: str) -> str:
    return "Objeto na imagem" if valor == "existe" else "Objeto não está na imagem"


def plano_limpo(valor: str) -> str:
    return "plano limpo" if valor == "true" else "plano não limpo"


def ocorrencia(valor: str) -> str:
    achada = _OCORRENCIA.match(valor)
    if not achada:
        return valor
    lista, inicio, fim = achada.groups()
    return f"{ROTULOS_DAS_LISTAS[lista]} {_faixa(int(inicio), int(fim))}"


def tempos(valor: str) -> str:
    achado = _TEMPOS.match(valor)
    return _faixa(int(achado[1]), int(achado[2])) if achado else valor


class Opcao(BaseModel):
    valor: str
    rotulo: str


class Limites(BaseModel):
    nome: int
    texto: int
    motivo: int


class Prefixos(BaseModel):
    acrescentado: str
    nao_identificado: str


class CatalogoDeCorrecoes(BaseModel):
    """Resposta de `GET /v1/correcoes/catalogo`."""

    tipos: list[Opcao]
    tipos_de_comercial: list[Opcao]
    tipos_de_texto_na_tela: list[Opcao]
    tons_da_pauta: list[Opcao]
    fontes_do_nome: list[Opcao]
    categorias_de_objeto: list[Opcao]
    cores_base: list[Opcao]
    relacoes_do_objeto: list[Opcao]
    limites: Limites
    prefixos: Prefixos


def _opcoes(valores: tuple[str, ...], rotulos: Mapping[Any, str]) -> list[Opcao]:
    return [Opcao(valor=v, rotulo=rotulos.get(v, v)) for v in valores]


def catalogo() -> CatalogoDeCorrecoes:
    # A tabela, os limites e os prefixos moram em `api.correcoes`, que importa este módulo.
    from api import correcoes

    return CatalogoDeCorrecoes(
        tipos=correcoes.rotulos_dos_tipos(),
        tipos_de_comercial=_opcoes(
            get_args(Comercial.model_fields["tipo"].annotation), {}
        ),
        tipos_de_texto_na_tela=_opcoes(
            get_args(TextoNaTela.model_fields["tipo"].annotation), {}
        ),
        tons_da_pauta=_opcoes(get_args(TomDaPauta), ROTULOS_DOS_TONS),
        fontes_do_nome=_opcoes(get_args(FonteDoNome), ROTULOS_DAS_FONTES),
        categorias_de_objeto=_opcoes(CATEGORIAS_DE_OBJETO, NOME_DA_CATEGORIA),
        cores_base=_opcoes(CORES_BASE, {}),
        relacoes_do_objeto=_opcoes(RELACOES_DO_OBJETO, ROTULOS_DAS_RELACOES),
        limites=Limites(
            nome=correcoes.LIMITE_DO_NOME,
            texto=correcoes.LIMITE_DO_TEXTO,
            motivo=correcoes.LIMITE_DO_MOTIVO,
        ),
        prefixos=Prefixos(
            acrescentado=correcoes.PREFIXO_ACRESCENTADO,
            nao_identificado=correcoes.PREFIXO_NAO_IDENTIFICADO,
        ),
    )
