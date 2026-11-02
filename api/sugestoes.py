"""Sugestões que o editor confirma com uma tecla (#152, #153, #154).

Cada regra olha a decupagem entregue (o modelo com as correções) e devolve as
sugestões abertas: uma pergunta, o contexto que a sustenta e a correção proposta, no
formato das correções. A regra nunca muda nada: o editor aceita ou recusa. Uma regra
nova entra em `REGRAS`, e a lista, as rotas e a tela não mudam.

Regras da ADR 0005: o GC de identificação sustenta o nome; a chamada nunca. O
palpite sem prova vira a pergunta, e o aceite do editor é a prova.
"""

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.catalogo import Catalogo, PessoaDoCatalogo
from api.comparador import normalizar
from api.correcoes import LIMITE_DO_NOME, Ocorrencia, TipoNovo
from api.decupagem import CORES_BASE
from api.identidade import nao_identificado

TipoDeSugestao = Literal["identificar_pessoa", "pauta_do_trecho", "objeto_do_visual"]
Decisao = Literal["aceita", "recusada"]

MOTIVO_CONFIRMADA = "sugestão confirmada pelo editor"
MOTIVO_CORRIGIDA = "sugestão corrigida pelo editor"

TRECHO_MINIMO_SEM_PAUTA_MS = 30_000
TOM_PROPOSTO = "informativo"
_PALAVRAS_DO_NOME = 5
# Separa o nome da função no GC: "LEÃO LOBO · colunista", "Leão Lobo - colunista".
_SEPARADOR_DO_GC = re.compile(r"\s*[·•|\n\r–—]\s*|\s+-\s+")
_PALAVRA_DE_NOME = re.compile(r"^[^\W\d_]+(?:['’.\-][^\W\d_]+)*\.?$")
_PARTICULAS = {"da", "das", "de", "do", "dos", "e"}


class Proposta(BaseModel):
    """Uma correção no formato do `POST /v1/jobs/{id}/correcoes`, sem motivo nem
    versão: quem aceita os põe."""

    tipo: TipoNovo
    item_id: str
    valor: str
    catalogo_id: str | None = None
    ocorrencia: Ocorrencia | None = None


class Sugestao(BaseModel):
    # Derivado da regra, do item e do trecho: a mesma sugestão tem sempre o mesmo id.
    id: str
    tipo: TipoDeSugestao
    inicio_ms: int
    fim_ms: int
    pergunta: str
    contexto: str
    correcao: Proposta
    # O que vem depois da correção, na ordem, quando o editor aceita.
    depois: list[Proposta] = []


@dataclass(frozen=True)
class Contexto:
    """O que as regras consultam."""

    entregue: dict[str, Any]
    catalogo: Catalogo
    # Os tipos de objeto já vistos no acervo (#149); só se consulta quando precisa.
    tipos_de_objeto: Callable[[], list[str]] = list


Regra = Callable[[Contexto], Iterable[Sugestao]]


def _id(regra: str, item: str, inicio_ms: int, fim_ms: int) -> str:
    """Os tempos em segundos: uma medição que muda alguns milissegundos ao
    reprocessar é o mesmo trecho."""
    chave = f"{regra}|{item}|{inicio_ms // 1000}|{fim_ms // 1000}"
    return hashlib.sha256(chave.encode()).hexdigest()[:20]


def _relogio(ms: int) -> str:
    minutos, segundos = divmod(ms // 1000, 60)
    return f"{minutos:02d}:{segundos:02d}"


def _intervalo(item: dict[str, Any]) -> tuple[int, int]:
    return int(item["inicio_ms"]), int(item["fim_ms"])


def _sobrepoe(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) > 0


# --- GC de identificação sobre um "não identificado" -----------------------------


def _nome_do_gc(texto: str) -> str | None:
    """O nome no GC ("LEÃO LOBO · colunista" → "Leão Lobo"); `None` se o texto
    não parece um nome próprio (dígitos, frase, nada)."""
    nome = _SEPARADOR_DO_GC.split(texto.strip())[0].strip()
    palavras = nome.split()
    if not 1 <= len(palavras) <= _PALAVRAS_DO_NOME:
        return None
    if not all(_PALAVRA_DE_NOME.match(p) for p in palavras):
        return None
    return " ".join(
        p.lower() if i and p.lower() in _PARTICULAS else p[:1].upper() + p[1:].lower()
        for i, p in enumerate(palavras)
    )


def _aparicoes(pessoa: dict[str, Any]) -> list[tuple[int, int]]:
    return [_intervalo(a) for a in pessoa.get("na_imagem", [])]


def _gc_de_identificacao(mundo: Contexto) -> Iterable[Sugestao]:
    pessoas = [p for p in mundo.entregue.get("pessoas", []) if isinstance(p, dict)]
    for texto in mundo.entregue.get("textos_na_tela", []):
        if not isinstance(texto, dict) or texto.get("tipo") != "gc":
            continue
        nome = _nome_do_gc(str(texto.get("texto", "")))
        if nome is None:
            continue
        tempo = _intervalo(texto)
        em_cena = [
            p for p in pessoas if any(_sobrepoe(tempo, a) for a in _aparicoes(p))
        ]
        sem_nome = [p for p in em_cena if nao_identificado(str(p["nome"]))]
        # Dois "não identificados" no trecho: o GC não diz de qual; ninguém é sugerido.
        if len(sem_nome) != 1:
            continue
        if any(normalizar(str(p["nome"])) == normalizar(nome) for p in em_cena):
            continue
        alvo = sem_nome[0]
        nome, do_catalogo = _no_catalogo(mundo, nome)
        yield Sugestao(
            id=_id("gc_de_identificacao", normalizar(str(texto["texto"])), *tempo),
            tipo="identificar_pessoa",
            inicio_ms=tempo[0],
            fim_ms=tempo[1],
            pergunta=f"É {nome}?",
            contexto=f"GC às {_relogio(tempo[0])}: {' '.join(str(texto['texto']).split())}",
            correcao=Proposta(
                tipo="pessoa.renomear",
                item_id=str(alvo["id"]),
                valor=nome,
                catalogo_id=do_catalogo.id if do_catalogo else None,
            ),
            depois=_mencoes_para_aparicao(alvo, tempo),
        )


def _no_catalogo(mundo: Contexto, nome: str) -> tuple[str, PessoaDoCatalogo | None]:
    """O nome como está no catálogo e a pessoa, quando só uma tem esse nome."""
    achadas = mundo.catalogo.achar(nome)
    if len(achadas) != 1:
        return nome, None
    return achadas[0].nome, achadas[0]


def _mencoes_para_aparicao(
    pessoa: dict[str, Any], gc: tuple[int, int]
) -> list[Proposta]:
    """A menção no texto da pessoa, no tempo do GC, passa a aparição."""
    return [
        Proposta(
            tipo="pessoa.mencao_para_aparicao",
            item_id=str(pessoa["id"]),
            valor=" ".join(str(m["texto"]).split())[:LIMITE_DO_NOME],
            ocorrencia=Ocorrencia(
                lista="citada_no_texto", inicio_ms=m["inicio_ms"], fim_ms=m["fim_ms"]
            ),
        )
        for m in pessoa.get("citada_no_texto", [])
        if _sobrepoe(gc, _intervalo(m)) and str(m.get("texto", "")).strip()
    ]


# --- Palpite sem prova ---------------------------------------------------------------

_DE_ONDE_VEM_O_PALPITE = {
    "modelo": "Palpite da análise do vídeo",
    "modelo_forte": "Palpite do modelo forte, que olhou a pessoa sem nome",
}


def _palpite_nao_confirmado(mundo: Contexto) -> Iterable[Sugestao]:
    """O palpite sem prova (ADR 0005) vira a pergunta; o aceite do editor é a prova."""
    for pessoa in mundo.entregue.get("pessoas", []):
        if not isinstance(pessoa, dict) or pessoa.get("estado_do_nome") != "palpite":
            continue
        aparicoes = sorted(_aparicoes(pessoa))
        if not aparicoes:
            continue
        palpite = " ".join(str(pessoa["nome"]).split())
        nome, do_catalogo = _no_catalogo(mundo, palpite)
        inicio, fim = aparicoes[0][0], max(a[1] for a in aparicoes)
        onde = ", ".join(f"{_relogio(a[0])}–{_relogio(a[1])}" for a in aparicoes)
        # Por pessoa e nome, não pelo trecho: mudar as aparições não reabre a pergunta;
        # outro palpite para a mesma pessoa, sim.
        chave = f"{pessoa['id']}:{normalizar(palpite)}"
        de_onde = _DE_ONDE_VEM_O_PALPITE.get(str(pessoa.get("origem")), "Palpite")
        yield Sugestao(
            id=_id("palpite_nao_confirmado", chave, 0, 0),
            tipo="identificar_pessoa",
            inicio_ms=inicio,
            fim_ms=fim,
            pergunta=f"O modelo acha que é {nome}. Confirma?",
            contexto=(
                f"{de_onde}, sem prova (GC, fala ou fotos de referência). "
                f"Aparece às {onde}"
            ),
            correcao=Proposta(
                tipo="pessoa.renomear",
                item_id=str(pessoa["id"]),
                valor=nome,
                catalogo_id=do_catalogo.id if do_catalogo else None,
            ),
        )


# --- Trecho do vídeo sem pauta ------------------------------------------------------


def _trechos_sem_pauta(entregue: dict[str, Any]) -> list[tuple[int, int]]:
    duracao = int(entregue["video"]["duracao_ms"])
    cobertos = sorted(
        _intervalo(p) for p in entregue.get("pautas", []) if isinstance(p, dict)
    )
    livres: list[tuple[int, int]] = []
    ate = 0
    for inicio, fim in [*cobertos, (duracao, duracao)]:
        if inicio - ate >= TRECHO_MINIMO_SEM_PAUTA_MS:
            livres.append((ate, min(inicio, duracao)))
        ate = max(ate, fim)
    return livres


def _trecho_sem_pauta(mundo: Contexto) -> Iterable[Sugestao]:
    for inicio, fim in _trechos_sem_pauta(mundo.entregue):
        yield Sugestao(
            id=_id("trecho_sem_pauta", "", inicio, fim),
            tipo="pauta_do_trecho",
            inicio_ms=inicio,
            fim_ms=fim,
            pergunta=f"Criar uma pauta de {_relogio(inicio)} a {_relogio(fim)}?",
            contexto=f"Nenhuma pauta cobre de {_relogio(inicio)} a {_relogio(fim)}",
            correcao=Proposta(
                tipo="pauta.acrescentar",
                item_id="",
                valor=json.dumps(
                    {
                        "titulo": "",
                        "tom": TOM_PROPOSTO,
                        "inicio_ms": inicio,
                        "fim_ms": fim,
                    },
                    ensure_ascii=False,
                ),
            ),
        )


# --- Peça citada no visual da aparição ---------------------------------------------

# A relação pela categoria do objeto; o que não está aqui é "usa".
_RELACAO_DA_CATEGORIA = {"roupa": "veste", "calcado": "calca", "na_mao": "segura"}
_PALAVRA = re.compile(r"[^\W_]+")


def _palavras(texto: str) -> list[str]:
    return _PALAVRA.findall(normalizar(texto))


def _forma(palavra: str, citada: str) -> bool:
    """`citada` é `palavra`, no plural simples ou no feminino ("vermelha", "pretas")."""
    formas = {palavra, palavra + "s", palavra + "es"}
    if palavra.endswith("o"):
        formas |= {palavra[:-1] + "a", palavra[:-1] + "as"}
    return citada in formas


def _onde_cita(tipo: str, palavras: list[str]) -> int | None:
    """A posição em que o tipo (uma ou mais palavras) aparece nas `palavras`."""
    do_tipo = _palavras(tipo)
    if not do_tipo:
        return None
    for i in range(len(palavras) - len(do_tipo) + 1):
        if all(
            _forma(t, palavras[i + k])
            if k == len(do_tipo) - 1
            else t == palavras[i + k]
            for k, t in enumerate(do_tipo)
        ):
            return i
    return None


def _cor_perto(inicio: int, fim: int, palavras: list[str]) -> str | None:
    """A cor da lista fechada mais perto do tipo (palavras `inicio` a `fim`), que é
    de quem ela descreve em "terno preto e camisa rosa"."""
    achadas = [
        (min(abs(i - fim), abs(inicio - i)), i, cor)
        for i, p in enumerate(palavras)
        for cor in CORES_BASE
        if _forma(cor, p)
    ]
    return min(achadas)[2] if achadas else None


def _ja_tem(
    objetos: list[dict[str, Any]], pessoa: str, tipo: str, trecho: tuple[int, int]
) -> bool:
    alvo = _palavras(tipo)
    for o in objetos:
        if o.get("pessoa") != pessoa:
            continue
        if not any(_sobrepoe(trecho, _intervalo(x)) for x in o.get("ocorrencias", [])):
            continue
        do_objeto = _palavras(str(o.get("tipo", "")))
        if len(do_objeto) == len(alvo) and all(
            _forma(a, b) or _forma(b, a) for a, b in zip(alvo, do_objeto, strict=True)
        ):
            return True
    return False


def _objeto_citado_no_visual(mundo: Contexto) -> Iterable[Sugestao]:
    """O visual da aparição cita um tipo de objeto conhecido que a pessoa não tem
    naquele trecho: a sugestão acrescenta o objeto, com o trecho da aparição."""
    pessoas = [p for p in mundo.entregue.get("pessoas", []) if isinstance(p, dict)]
    aparicoes = [
        (p, a)
        for p in pessoas
        for a in p.get("na_imagem", [])
        if str(a.get("visual") or "").strip()
    ]
    if not aparicoes:
        return
    objetos = [o for o in mundo.entregue.get("objetos", []) if isinstance(o, dict)]
    categorias = {
        normalizar(str(o["tipo"])): str(o["categoria"])
        for o in objetos
        if o.get("tipo") and o.get("categoria")
    }
    # Os tipos mais longos primeiro: "óculos de sol" antes de "óculos".
    conhecidos = sorted(
        {" ".join(t.split()): None for t in mundo.tipos_de_objeto() if t.strip()},
        key=lambda t: (-len(_palavras(t)), t),
    )
    for pessoa, aparicao in aparicoes:
        trecho = _intervalo(aparicao)
        palavras = _palavras(str(aparicao["visual"]))
        usadas: list[tuple[int, int]] = []
        for tipo in conhecidos:
            onde = _onde_cita(tipo, palavras)
            if onde is None:
                continue
            fim = onde + len(_palavras(tipo)) - 1
            if any(onde <= b and a <= fim for a, b in usadas):
                continue
            usadas.append((onde, fim))
            if _ja_tem(objetos, str(pessoa["id"]), tipo, trecho):
                continue
            cor = _cor_perto(onde, fim, palavras)
            categoria = categorias.get(normalizar(tipo), "roupa")
            descricao = f"{tipo} {cor}" if cor else tipo
            yield Sugestao(
                id=_id(
                    "objeto_no_visual",
                    f"{pessoa['id']}:{normalizar(tipo)}",
                    *trecho,
                ),
                tipo="objeto_do_visual",
                inicio_ms=trecho[0],
                fim_ms=trecho[1],
                pergunta=f"Acrescentar {descricao} de {pessoa['nome']}?",
                contexto=(
                    f"Visual às {_relogio(trecho[0])}: "
                    f"{' '.join(str(aparicao['visual']).split())}"
                ),
                correcao=Proposta(
                    tipo="objeto.acrescentar",
                    item_id="",
                    valor=json.dumps(
                        {
                            "tipo": tipo,
                            "cor_base": [cor] if cor else [],
                            "categoria": categoria,
                            "pessoa": str(pessoa["id"]),
                            "relacao": _RELACAO_DA_CATEGORIA.get(categoria, "usa"),
                            "inicio_ms": trecho[0],
                            "fim_ms": trecho[1],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )


REGRAS: tuple[Regra, ...] = (
    _gc_de_identificacao,
    _palpite_nao_confirmado,
    _trecho_sem_pauta,
    _objeto_citado_no_visual,
)


def sugestoes_abertas(
    entregue: dict[str, Any],
    catalogo: Catalogo,
    decididas: set[str],
    tipos_de_objeto: Callable[[], list[str]] = list,
) -> list[Sugestao]:
    """As sugestões do vídeo que o editor ainda não aceitou nem recusou, na ordem do
    tempo. A aceita sai pela decisão, não só pela correção: a correção pendente fica
    fora da decupagem entregue, e a regra a sugeriria de novo."""
    mundo = Contexto(entregue, catalogo, tipos_de_objeto)
    todas = [s for regra in REGRAS for s in regra(mundo) if s.id not in decididas]
    return sorted(todas, key=lambda s: (s.inicio_ms, s.fim_ms, s.id))


def com_o_valor_do_editor(sugestao: Sugestao, valor: str) -> Sugestao:
    """A sugestão com o "outro nome" (o título da pauta, o tipo do objeto) que o editor deu no lugar
    do proposto."""
    proposta = sugestao.correcao
    if sugestao.tipo == "pauta_do_trecho":
        pauta = json.loads(proposta.valor)
        pauta["titulo"] = valor
        novo = json.dumps(pauta, ensure_ascii=False)
        return sugestao.model_copy(
            update={"correcao": proposta.model_copy(update={"valor": novo})}
        )
    if sugestao.tipo == "objeto_do_visual":
        objeto = json.loads(proposta.valor)
        objeto["tipo"] = valor
        novo = json.dumps(objeto, ensure_ascii=False)
        return sugestao.model_copy(
            update={"correcao": proposta.model_copy(update={"valor": novo})}
        )
    # O id do catálogo era do nome proposto; o do nome dado o servidor acha sozinho.
    trocada = proposta.model_copy(update={"valor": valor, "catalogo_id": None})
    return sugestao.model_copy(update={"correcao": trocada})


# --- As decisões do editor e a contagem ---------------------------------------------


class ContagemDoTipo(BaseModel):
    aceitas: int = 0
    recusadas: int = 0


class RepositorioDeSugestoes(Protocol):
    """Porta para o Firestore: uma decisão por vídeo e sugestão."""

    def registrar(
        self, job_id: str, sugestao_id: str, tipo: TipoDeSugestao, decisao: Decisao
    ) -> None: ...

    def decididas(self, job_id: str) -> set[str]:
        """Os ids das sugestões que o editor aceitou ou recusou nesse vídeo."""
        ...

    def contagem(self) -> dict[str, ContagemDoTipo]:
        """Aceitas e recusadas por tipo de sugestão, em todos os vídeos."""
        ...


class RepositorioDeSugestoesEmMemoria:
    def __init__(self) -> None:
        self._decisoes: dict[tuple[str, str], tuple[TipoDeSugestao, Decisao]] = {}

    def registrar(
        self, job_id: str, sugestao_id: str, tipo: TipoDeSugestao, decisao: Decisao
    ) -> None:
        self._decisoes[(job_id, sugestao_id)] = (tipo, decisao)

    def decididas(self, job_id: str) -> set[str]:
        return {sid for job, sid in self._decisoes if job == job_id}

    def contagem(self) -> dict[str, ContagemDoTipo]:
        return contar(self._decisoes.values())


def contar(
    decisoes: Iterable[tuple[str, Decisao]],
) -> dict[str, ContagemDoTipo]:
    contagem: dict[str, ContagemDoTipo] = {}
    for tipo, decisao in decisoes:
        c = contagem.setdefault(tipo, ContagemDoTipo())
        if decisao == "aceita":
            c.aceitas += 1
        else:
            c.recusadas += 1
    return contagem


def criar_rotas_da_contagem(
    repositorio: RepositorioDeSugestoes,
    exige_aprovar: Callable[..., Any],
) -> APIRouter:
    rotas = APIRouter(prefix="/sugestoes")

    @rotas.get("/contagem", dependencies=[Depends(exige_aprovar)])
    def contagem() -> dict[str, ContagemDoTipo]:
        return repositorio.contagem()

    return rotas
