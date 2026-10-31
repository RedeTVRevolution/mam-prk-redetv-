"""Identificação das pessoas: o código confere as provas do nome (ADR 0005).

Roda depois da consolidação. Um nome só é confirmado por uma prova que o código
acha nos dados, nunca pela declaração do modelo (`fontes_do_nome`):

- **GC:** um `TextoNaTela` `gc` ou `tarja` com o nome ou um apelido, enquanto a
  pessoa está na imagem;
- **Fala:** o nome ou um apelido no texto original do Whisper (nunca no texto
  do Gemini), enquanto a pessoa está na imagem, com tolerância.

Nenhuma das duas vale se outra pessoa sem nome está na imagem no mesmo intervalo:
o GC ou a fala podem ser dela. Estar no perfil do programa ou no catálogo só dá
os apelidos; não confirma nada. O nome sem prova vira palpite.
"""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from api.catalogo import Catalogo
from api.comparador import normalizar
from api.decupagem import Decupagem, FonteDoNome, Pessoa, _Intervalo
from api.identidade import nao_identificado
from api.programas import DADOS
from api.transcricao import Transcricao

TOLERANCIA_DA_FALA_MS = 2000  # a fala e a imagem não se alinham ao quadro
TIPOS_DE_GC = frozenset({"gc", "tarja"})


@dataclass(frozen=True)
class Candidato:
    nome: str
    papel: str
    apelidos: tuple[str, ...] = ()


def candidatos_do_video(
    programa: str | None,
    catalogo: Catalogo | None = None,
    perfis: Mapping[str, Mapping[str, Any]] = DADOS,
) -> list[Candidato]:
    """As pessoas do perfil do programa e as do catálogo, com os apelidos. Quem
    aparece nos dois é um candidato só, com os apelidos unidos."""
    achados: list[Candidato] = [
        Candidato(p["nome"], p["papel"], tuple(p.get("apelidos", [])))
        for p in (perfis.get(programa or "") or {}).get("pessoas", [])
    ]
    if catalogo:
        achados += [
            Candidato(p.nome, p.papel, tuple(p.apelidos)) for p in catalogo.todas()
        ]
    unidos: dict[str, Candidato] = {}
    for c in achados:
        chave = normalizar(c.nome)
        antes = unidos.get(chave)
        unidos[chave] = (
            c
            if antes is None
            else Candidato(
                antes.nome,
                antes.papel,
                tuple(dict.fromkeys([*antes.apelidos, *c.apelidos])),
            )
        )
    return list(unidos.values())


def _palavras(texto: str) -> list[str]:
    return re.findall(r"\w+", normalizar(texto))


def _sobrepoe(a: _Intervalo, inicio_ms: int, fim_ms: int, folga_ms: int = 0) -> bool:
    return a.inicio_ms - folga_ms < fim_ms and inicio_ms < a.fim_ms + folga_ms


def _nomes_da_pessoa(
    pessoa: Pessoa, candidatos: Iterable[Candidato]
) -> list[list[str]]:
    """O nome e os apelidos dos candidatos que têm esse nome, como listas de palavras."""
    chave = normalizar(pessoa.nome)
    nomes = [pessoa.nome]
    for c in candidatos:
        if chave in {normalizar(n) for n in (c.nome, *c.apelidos)}:
            nomes += [c.nome, *c.apelidos]
    return [list(p) for p in dict.fromkeys(tuple(_palavras(n)) for n in nomes) if p]


def _ocorrencias(palavras: Sequence[str], nome: Sequence[str]) -> list[tuple[int, int]]:
    """Posições `[inicio, fim)` de `nome` em `palavras`."""
    n = len(nome)
    return [
        (i, i + n)
        for i in range(len(palavras) - n + 1)
        if list(palavras[i : i + n]) == list(nome)
    ]


def _livre_de_outro_sem_nome(
    decupagem: Decupagem,
    pessoa: Pessoa,
    inicio_ms: int,
    fim_ms: int,
    folga_ms: int,
    sem_nome: Collection[str],
) -> bool:
    return not any(
        (nao_identificado(o.nome) or o.id in sem_nome)
        and any(_sobrepoe(a, inicio_ms, fim_ms, folga_ms) for a in o.na_imagem)
        for o in decupagem.pessoas
        if o.id != pessoa.id
    )


def _prova_de_gc(
    decupagem: Decupagem,
    pessoa: Pessoa,
    nomes: Sequence[Sequence[str]],
    sem_nome: Collection[str],
) -> bool:
    for t in decupagem.textos_na_tela:
        if t.tipo not in TIPOS_DE_GC:
            continue
        palavras = _palavras(t.texto)
        if not any(_ocorrencias(palavras, n) for n in nomes):
            continue
        if any(_sobrepoe(a, t.inicio_ms, t.fim_ms) for a in pessoa.na_imagem) and (
            _livre_de_outro_sem_nome(
                decupagem, pessoa, t.inicio_ms, t.fim_ms, 0, sem_nome
            )
        ):
            return True
    return False


def _prova_de_fala(
    decupagem: Decupagem,
    pessoa: Pessoa,
    nomes: Sequence[Sequence[str]],
    transcricao: Transcricao | None,
    tolerancia_ms: int,
    sem_nome: Collection[str],
) -> bool:
    if transcricao is None:
        return False
    # (palavra, início, fim) de cada palavra do Whisper, já separada em palavras.
    fluxo = [
        (w, round(p.inicio_s * 1000), round(p.fim_s * 1000))
        for p in transcricao.palavras
        for w in _palavras(p.texto)
    ]
    palavras = [w for w, _, _ in fluxo]
    for nome in nomes:
        for i, j in _ocorrencias(palavras, nome):
            inicio_ms, fim_ms = fluxo[i][1], fluxo[j - 1][2]
            if any(
                _sobrepoe(a, inicio_ms, fim_ms, tolerancia_ms) for a in pessoa.na_imagem
            ) and _livre_de_outro_sem_nome(
                decupagem, pessoa, inicio_ms, fim_ms, tolerancia_ms, sem_nome
            ):
                return True
    return False


def _no_catalogo(catalogo: Catalogo, pessoa: Pessoa) -> str | None:
    """O id da pessoa do catálogo com esse nome ou apelido; acrescenta se não há
    ninguém; `None` se duas pessoas têm o nome (não dá para escolher)."""
    achadas = catalogo.achar(pessoa.nome)
    if len(achadas) > 1:
        return None
    if achadas:
        return achadas[0].id
    papel = next((a.papel for a in pessoa.na_imagem if a.papel), "")
    return catalogo.acrescentar(pessoa.nome, papel, []).id


def identificar(
    decupagem: Decupagem,
    *,
    candidatos: Sequence[Candidato] = (),
    transcricao: Transcricao | None = None,
    catalogo: Catalogo | None = None,
    tolerancia_ms: int = TOLERANCIA_DA_FALA_MS,
    sem_nome: Collection[str] = (),
) -> Decupagem:
    """Confere o nome de cada pessoa. Com prova, o nome é `confirmado` (origem
    `modelo_forte`, só as fontes conferidas) e vai para o catálogo; sem prova, é
    `palpite`, sem fontes. A pessoa da revisora e o "não identificado" ficam como estão.

    `sem_nome` são ids de pessoas que, para a regra "outra pessoa sem nome na imagem",
    contam como sem nome mesmo com um nome (o do modelo forte, ainda sem prova)."""
    pessoas: list[Pessoa] = []
    for p in decupagem.pessoas:
        if p.origem == "revisao" or nao_identificado(p.nome):
            pessoas.append(p)
            continue
        nomes = _nomes_da_pessoa(p, candidatos)
        fontes: list[FonteDoNome] = []
        if _prova_de_gc(decupagem, p, nomes, sem_nome):
            fontes.append("gc")
        if _prova_de_fala(decupagem, p, nomes, transcricao, tolerancia_ms, sem_nome):
            fontes.append("fala")
        if not fontes:
            pessoas.append(
                p.model_copy(update={"estado_do_nome": "palpite", "fontes_do_nome": []})
            )
            continue
        pessoas.append(
            p.model_copy(
                update={
                    "estado_do_nome": "confirmado",
                    "origem": "modelo_forte",
                    "fontes_do_nome": fontes,
                    "catalogo_id": _no_catalogo(catalogo, p)
                    if catalogo
                    else p.catalogo_id,
                }
            )
        )
    return decupagem.model_copy(update={"pessoas": pessoas})
