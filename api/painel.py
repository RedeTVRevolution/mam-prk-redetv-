"""Painel da diretoria (E9): quem pode ver, os filtros comuns, as rotas `/v1/painel/...` e o
registro de cada acesso na auditoria.

A abertura de uma aba e cada exportação em CSV gravam quem, quando, a aba e o filtro. Uma
aba aberta de novo com o mesmo filtro dentro de 30 minutos (recarga) não grava outra
abertura; filtro novo, sim: é outra coisa vista. As rotas leem só as tabelas resumidas
(`api/resumos_de_uso.py`) e nunca a tabela de eventos.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.auditoria import FiltroDeAuditoria, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.jobs import ServicoIndisponivel, _confere_permissao
from api.relatorios import confere_o_pedido, csv_em_texto, ou_503, resposta_em_csv
from api.resumos_de_uso import AcessoDoDia, ResumosDeUso, UsoDoDia
from api.usuarios import ContasDeUsuario

JANELA_DA_ABERTURA = timedelta(minutes=30)
Aba = Literal["acessos", "videos", "buscas"]

log = logging.getLogger(__name__)


def exige_painel(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência das rotas do painel: só pessoa com `painel.ver`; chave de sistema não vê."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não vê o painel")
    _confere_permissao(request, chamador, "painel.ver")
    return chamador


class FiltroDoPainel(BaseModel):
    """Os filtros comuns das abas. `desde` e `ate` são dias de São Paulo, os dois inclusive;
    `programa` e `usuario` (o uid) vazios valem "todos"."""

    desde: date | None = None
    ate: date | None = None
    programa: str | None = None
    usuario: str | None = None

    def aplicado(self) -> dict[str, str]:
        """Só o que foi pedido, em texto: é o que vai para a auditoria."""
        return self.model_dump(mode="json", exclude_none=True)


def filtro_do_painel(
    desde: date | None = None,
    ate: date | None = None,
    programa: Annotated[str | None, Query(max_length=100)] = None,
    usuario: Annotated[str | None, Query(max_length=128)] = None,
) -> FiltroDoPainel:
    return FiltroDoPainel(
        desde=desde, ate=ate, programa=programa or None, usuario=usuario or None
    )


class AcessosAoPainel:
    def __init__(
        self, auditoria: RepositorioDeAuditoria, relogio: Callable[[], datetime]
    ) -> None:
        self._auditoria = auditoria
        self._relogio = relogio

    def _gravar(
        self,
        pessoa: Usuario,
        acao: Literal["painel.aberto", "painel.exportado"],
        aba: Aba,
        filtro: FiltroDoPainel,
    ) -> None:
        try:
            self._auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=self._relogio(),
                    uid=pessoa.uid,
                    email=pessoa.email,
                    acao=acao,
                    alvo_tipo="painel",
                    alvo_id="diretoria",
                    alvo_nome="Painel da diretoria",
                    detalhes={"aba": aba, "filtro": filtro.aplicado()},
                )
            )
        except Exception:
            # Sem registro, nada sai: o acesso sem rastro não passa.
            log.exception("Falha ao registrar %s de %s", acao, pessoa.uid)
            raise ServicoIndisponivel from None

    def abriu(self, pessoa: Usuario, aba: Aba, filtro: FiltroDoPainel) -> None:
        agora = self._relogio()
        try:
            recentes = self._auditoria.consultar(
                FiltroDeAuditoria(
                    pessoa=pessoa.uid,
                    acao="painel.aberto",
                    de=agora - JANELA_DA_ABERTURA,
                )
            ).registros
        except Exception:
            log.exception("Falha ao ler as aberturas do painel de %s", pessoa.uid)
            raise ServicoIndisponivel from None
        igual = {"aba": aba, "filtro": filtro.aplicado()}
        if not any(r.detalhes == igual for r in recentes):
            self._gravar(pessoa, "painel.aberto", aba, filtro)

    def exportou(self, pessoa: Usuario, aba: Aba, filtro: FiltroDoPainel) -> None:
        self._gravar(pessoa, "painel.exportado", aba, filtro)


PodeVerOPainel = Annotated[Usuario, Depends(exige_painel)]


class DiaDeAcessos(BaseModel):
    dia: date
    acessos: int
    usuarios_ativos: int


class UsuarioDeAcessos(BaseModel):
    uid: str
    email: str | None
    acessos: int
    dias_ativos: int
    ultimo_acesso: datetime | None


class AtivosNoPeriodo(BaseModel):
    """Uma semana (começa na segunda) ou um mês (começa no dia 1): `inicio` é o primeiro dia."""

    inicio: date
    usuarios_ativos: int


class TotalDeAcessos(BaseModel):
    acessos: int
    usuarios_ativos: int


class RelatorioDeAcessos(BaseModel):
    desde: date | None
    ate: date | None
    usuario: str | None
    total: TotalDeAcessos
    por_dia: list[DiaDeAcessos]
    por_semana: list[AtivosNoPeriodo]
    por_mes: list[AtivosNoPeriodo]
    por_usuario: list[UsuarioDeAcessos]


class UsuarioDoFiltro(BaseModel):
    uid: str
    email: str | None


class OpcoesDosFiltros(BaseModel):
    programas: list[str]
    usuarios: list[UsuarioDoFiltro]


COLUNAS_DO_CSV_DE_ACESSOS = ("dia", "uid", "email", "acessos", "ativo", "ultimo_acesso")


def _emails(contas: ContasDeUsuario) -> dict[str, str]:
    """Uid -> e-mail das contas; sem a lista, o painel mostra só o uid."""
    try:
        return {c.uid: c.email for c in contas.listar()}
    except Exception:
        log.exception("Falha ao listar as contas para o painel")
        return {}


def _ativos_por(
    ativos_do_dia: dict[date, set[str]], inicio: Callable[[date], date]
) -> list[AtivosNoPeriodo]:
    """Os distintos de cada semana ou mês: quem agiu em três dias da semana conta uma vez."""
    juntos: dict[date, set[str]] = defaultdict(set)
    for dia, uids in ativos_do_dia.items():
        juntos[inicio(dia)] |= uids
    return [
        AtivosNoPeriodo(inicio=i, usuarios_ativos=len(uids))
        for i, uids in sorted(juntos.items())
    ]


def _com_acesso(linhas: list[AcessoDoDia]) -> list[AcessoDoDia]:
    """Sai a linha sem login nem ação (só o fim do processamento de um vídeo da pessoa):
    não é acesso, e viraria um dia ou uma pessoa com zero em tudo."""
    return [a for a in linhas if a.acessos or a.ativo]


def _com_os_dias_vazios(por_dia: dict[date, int]) -> dict[date, int]:
    if not por_dia:
        return {}
    primeiro, ultimo = min(por_dia), max(por_dia)
    return {
        primeiro + timedelta(days=i): por_dia.get(primeiro + timedelta(days=i), 0)
        for i in range((ultimo - primeiro).days + 1)
    }


def relatorio_de_acessos(
    linhas: list[AcessoDoDia], emails: dict[str, str], filtro: FiltroDoPainel
) -> RelatorioDeAcessos:
    """Os números do período a partir das linhas por dia e pessoa. Usuário ativo é quem agiu
    (o fim do processamento do vídeo dela não conta: o #280 já o deixou de fora). A primeira
    e a última semana ou mês contam só os dias do filtro. `por_dia` traz também, com zero, os
    dias sem login entre o primeiro e o último, para o gráfico não colar dias distantes."""
    acessos_do_dia: dict[date, int] = defaultdict(int)
    ativos_do_dia: dict[date, set[str]] = defaultdict(set)
    acessos_da_pessoa: dict[str, int] = defaultdict(int)
    dias_da_pessoa: dict[str, int] = defaultdict(int)
    ultimo: dict[str, datetime] = {}
    for a in linhas:
        acessos_do_dia[a.dia] += a.acessos
        acessos_da_pessoa[a.uid] += a.acessos
        if a.ativo:
            ativos_do_dia[a.dia].add(a.uid)
            dias_da_pessoa[a.uid] += 1
        if a.ultimo_acesso and (a.uid not in ultimo or a.ultimo_acesso > ultimo[a.uid]):
            ultimo[a.uid] = a.ultimo_acesso
    return RelatorioDeAcessos(
        desde=filtro.desde,
        ate=filtro.ate,
        usuario=filtro.usuario,
        total=TotalDeAcessos(
            acessos=sum(acessos_do_dia.values()),
            usuarios_ativos=len({u for dia in ativos_do_dia.values() for u in dia}),
        ),
        por_dia=[
            DiaDeAcessos(
                dia=d,
                acessos=n,
                usuarios_ativos=len(ativos_do_dia.get(d, ())),
            )
            for d, n in sorted(_com_os_dias_vazios(acessos_do_dia).items())
        ],
        por_semana=_ativos_por(
            ativos_do_dia, lambda d: d - timedelta(days=d.weekday())
        ),
        por_mes=_ativos_por(ativos_do_dia, lambda d: d.replace(day=1)),
        por_usuario=sorted(
            (
                UsuarioDeAcessos(
                    uid=uid,
                    email=emails.get(uid),
                    acessos=n,
                    dias_ativos=dias_da_pessoa.get(uid, 0),
                    ultimo_acesso=ultimo.get(uid),
                )
                for uid, n in acessos_da_pessoa.items()
            ),
            key=lambda u: (-u.acessos, u.email or u.uid),
        ),
    )


COLUNAS_DO_CSV_DE_VIDEOS = (
    "dia",
    "quem_tipo",
    "quem_id",
    "email",
    "programa",
    "enviados",
    "concluidos",
    "falhos",
    "horas_concluidas",
    "segundos_de_processamento",
)
COLUNAS_DO_CSV_DE_BUSCAS = (
    "dia",
    "quem_tipo",
    "quem_id",
    "email",
    "programa",
    "buscas",
    "sem_resultado",
)


class NumerosDeVideos(BaseModel):
    """Os vídeos de um recorte (o dia, o programa, a pessoa ou o total). O tempo de
    processamento é o dos concluídos, do registro do Job ao fim: `tempo_medio_s` é a média
    dele entre os que trazem o tempo, vazia sem nenhum."""

    enviados: int
    concluidos: int
    falhos: int
    horas_concluidas: float
    tempo_medio_s: float | None


class DiaDeVideos(NumerosDeVideos):
    dia: date


class ProgramaDeVideos(NumerosDeVideos):
    programa: str


class QuemDeVideos(NumerosDeVideos):
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    email: str | None


class RelatorioDeVideos(BaseModel):
    desde: date | None
    ate: date | None
    programa: str | None
    usuario: str | None
    total: NumerosDeVideos
    por_dia: list[DiaDeVideos]
    # Vazio quando o filtro é de usuário: o programa só existe na tabela por programa.
    por_programa: list[ProgramaDeVideos]
    # Vazio quando o filtro é de programa, pelo mesmo motivo.
    por_usuario: list[QuemDeVideos]


class NumerosDeBuscas(BaseModel):
    buscas: int
    sem_resultado: int


class DiaDeBuscas(NumerosDeBuscas):
    dia: date
    usuarios_que_buscam: int | None


class QuemDeBuscas(NumerosDeBuscas):
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    email: str | None


class TotalDeBuscas(NumerosDeBuscas):
    usuarios_que_buscam: int | None


class RelatorioDeBuscas(BaseModel):
    desde: date | None
    ate: date | None
    programa: str | None
    usuario: str | None
    total: TotalDeBuscas
    por_dia: list[DiaDeBuscas]
    # Vazio quando o filtro é de programa: a tabela por programa não sabe quem buscou, e
    # `usuarios_que_buscam` fica sem valor.
    por_usuario: list[QuemDeBuscas]


@dataclass
class _SomaDeUso:
    enviados: int = 0
    concluidos: int = 0
    falhos: int = 0
    horas: float = 0.0
    segundos: int = 0
    com_tempo: int = 0
    buscas: int = 0
    sem_resultado: int = 0

    def somar(self, u: UsoDoDia) -> None:
        self.enviados += u.videos_enviados
        self.concluidos += u.videos_concluidos
        self.falhos += u.videos_falhos
        self.horas += u.horas_concluidas
        self.segundos += u.segundos_de_processamento
        self.com_tempo += u.videos_concluidos_com_tempo
        self.buscas += u.buscas
        self.sem_resultado += u.buscas_sem_resultado

    def videos(self) -> dict[str, Any]:
        return NumerosDeVideos(
            enviados=self.enviados,
            concluidos=self.concluidos,
            falhos=self.falhos,
            horas_concluidas=round(self.horas, 2),
            tempo_medio_s=(
                round(self.segundos / self.com_tempo, 1) if self.com_tempo else None
            ),
        ).model_dump()

    def de_buscas(self) -> dict[str, Any]:
        return NumerosDeBuscas(
            buscas=self.buscas, sem_resultado=self.sem_resultado
        ).model_dump()


def _somas_por[C](
    linhas: list[UsoDoDia], chave: Callable[[UsoDoDia], C]
) -> dict[C, _SomaDeUso]:
    somas: dict[C, _SomaDeUso] = defaultdict(_SomaDeUso)
    for u in linhas:
        somas[chave(u)].somar(u)
    return somas


def _soma(linhas: list[UsoDoDia]) -> _SomaDeUso:
    total = _SomaDeUso()
    for u in linhas:
        total.somar(u)
    return total


def _por_quem(
    linhas: list[UsoDoDia],
    emails: dict[str, str],
    ordem: Callable[[_SomaDeUso], int],
) -> list[tuple[dict[str, Any], _SomaDeUso]]:
    """Cada pessoa ou sistema (`quem_tipo`, `quem_id` e `email`) e a soma das suas linhas,
    de quem tem mais (`ordem`) para quem tem menos."""
    somas = _somas_por(
        [u for u in linhas if u.quem_id is not None],
        lambda u: (u.quem_tipo or "", u.quem_id or ""),
    )
    return [
        ({"quem_tipo": tipo, "quem_id": quem_id, "email": emails.get(quem_id)}, soma)
        for (tipo, quem_id), soma in sorted(
            somas.items(), key=lambda i: (-ordem(i[1]), i[0][1])
        )
    ]


def _tem_video(u: UsoDoDia) -> bool:
    return bool(u.videos_enviados or u.videos_concluidos or u.videos_falhos)


def _dias_do_intervalo(dias: Iterable[date]) -> list[date]:
    """Do primeiro ao último dia, sem buracos: o gráfico não cola dias distantes."""
    dias = list(dias)
    if not dias:
        return []
    primeiro = min(dias)
    return [
        primeiro + timedelta(days=i) for i in range((max(dias) - primeiro).days + 1)
    ]


def relatorio_de_videos(
    base: list[UsoDoDia],
    por_programa: list[UsoDoDia],
    emails: dict[str, str],
    filtro: FiltroDoPainel,
) -> RelatorioDeVideos:
    """`base` são as linhas do filtro (por programa ou por pessoa, veja `_base_de_uso`);
    `por_programa` são as linhas por programa de um pedido sem filtro de usuário."""
    base = [u for u in base if _tem_video(u)]
    por_dia = _somas_por(base, lambda u: u.dia)
    total = _soma(base)
    programas = _somas_por(
        [u for u in por_programa if _tem_video(u) and u.programa is not None],
        lambda u: u.programa or "",
    )
    return RelatorioDeVideos(
        desde=filtro.desde,
        ate=filtro.ate,
        programa=filtro.programa,
        usuario=filtro.usuario,
        total=NumerosDeVideos(**total.videos()),
        por_dia=[
            DiaDeVideos(dia=d, **por_dia.get(d, _SomaDeUso()).videos())
            for d in _dias_do_intervalo(por_dia)
        ],
        por_programa=[
            ProgramaDeVideos(programa=p, **soma.videos())
            for p, soma in sorted(programas.items())
        ],
        por_usuario=[
            QuemDeVideos(**quem, **soma.videos())
            for quem, soma in _por_quem(base, emails, lambda s: s.enviados)
        ],
    )


def relatorio_de_buscas(
    base: list[UsoDoDia], emails: dict[str, str], filtro: FiltroDoPainel
) -> RelatorioDeBuscas:
    """Quem busca são só pessoas (o sistema que busca pela API aparece em `por_usuario`,
    mas não conta em `usuarios_que_buscam`)."""
    base = [u for u in base if u.buscas]
    por_programa = filtro.programa is not None
    por_dia = _somas_por(base, lambda u: u.dia)
    pessoas_do_dia: dict[date, set[str]] = defaultdict(set)
    for u in base:
        if u.quem_tipo == "usuario" and u.quem_id is not None:
            pessoas_do_dia[u.dia].add(u.quem_id)
    total = _soma(base)
    return RelatorioDeBuscas(
        desde=filtro.desde,
        ate=filtro.ate,
        programa=filtro.programa,
        usuario=filtro.usuario,
        total=TotalDeBuscas(
            **total.de_buscas(),
            usuarios_que_buscam=(
                None
                if por_programa
                else len({p for ps in pessoas_do_dia.values() for p in ps})
            ),
        ),
        por_dia=[
            DiaDeBuscas(
                dia=d,
                **por_dia.get(d, _SomaDeUso()).de_buscas(),
                usuarios_que_buscam=None
                if por_programa
                else len(pessoas_do_dia.get(d, ())),
            )
            for d in _dias_do_intervalo(por_dia)
        ],
        por_usuario=[
            QuemDeBuscas(**quem, **soma.de_buscas())
            for quem, soma in _por_quem(base, emails, lambda s: s.buscas)
        ],
    )


def _base_de_uso(fonte: ResumosDeUso, filtro: FiltroDoPainel) -> list[UsoDoDia]:
    """As linhas do filtro: da tabela por programa se pediu programa, senão da por pessoa.
    As duas não se cruzam: pedir os dois é erro, em vez de devolver números que um dos
    filtros não aplicou."""
    if filtro.programa is not None and filtro.usuario is not None:
        raise HTTPException(422, "Escolha o programa ou o usuário, não os dois")
    if filtro.programa is not None:
        return ou_503(
            lambda: fonte.uso_por_programa(filtro.desde, filtro.ate, filtro.programa)
        )
    return ou_503(lambda: fonte.uso_por_quem(filtro.desde, filtro.ate, filtro.usuario))


def _linha_do_csv(
    u: UsoDoDia, emails: dict[str, str], numeros: Sequence[object]
) -> list[object]:
    return [
        u.dia.isoformat(),
        u.quem_tipo or "",
        u.quem_id or "",
        emails.get(u.quem_id, "") if u.quem_id else "",
        u.programa or "",
        *numeros,
    ]


def criar_rotas_do_painel(
    resumos: ResumosDeUso | None,
    contas: ContasDeUsuario,
    acessos_ao_painel: AcessosAoPainel,
) -> APIRouter:
    rotas = APIRouter(prefix="/painel")

    @rotas.get("/filtros", response_model=OpcoesDosFiltros)
    def filtros(_pessoa: PodeVerOPainel) -> OpcoesDosFiltros:
        """O que a tela oferece nos filtros de programa e de usuário."""
        fonte = confere_o_pedido(resumos, None, None)
        programas, uids = ou_503(lambda: (fonte.programas(), fonte.usuarios()))
        emails = _emails(contas)
        return OpcoesDosFiltros(
            programas=programas,
            usuarios=[UsuarioDoFiltro(uid=u, email=emails.get(u)) for u in uids],
        )

    @rotas.get("/acessos", response_model=RelatorioDeAcessos)
    def acessos(
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
    ) -> RelatorioDeAcessos | object:
        """Logins por dia, usuários ativos (por dia, semana e mês), por usuário e no total. O login não tem programa:
        pedir `programa` é erro, em vez de devolver números que ele não filtrou."""
        if filtro.programa is not None:
            raise HTTPException(422, "Os acessos não têm programa")
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        linhas = _com_acesso(
            ou_503(lambda: fonte.acessos(filtro.desde, filtro.ate, filtro.usuario))
        )
        emails = _emails(contas)
        if formato == "csv":
            acessos_ao_painel.exportou(pessoa, "acessos", filtro)
            return resposta_em_csv(
                csv_em_texto(
                    COLUNAS_DO_CSV_DE_ACESSOS,
                    [
                        [
                            a.dia.isoformat(),
                            a.uid,
                            emails.get(a.uid, ""),
                            a.acessos,
                            "sim" if a.ativo else "não",
                            # Em UTC com `Z`, como no JSON.
                            a.ultimo_acesso.strftime("%Y-%m-%dT%H:%M:%SZ")
                            if a.ultimo_acesso
                            else "",
                        ]
                        for a in sorted(linhas, key=lambda a: (a.dia, a.uid))
                    ],
                ),
                "acessos.csv",
            )
        acessos_ao_painel.abriu(pessoa, "acessos", filtro)
        return relatorio_de_acessos(linhas, emails, filtro)

    @rotas.get("/videos", response_model=RelatorioDeVideos)
    def videos(
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
    ) -> RelatorioDeVideos | object:
        """Vídeos enviados, concluídos e com falha, horas e tempo de processamento, por dia,
        programa e usuário (ou sistema). Programa e usuário não se combinam: 422."""
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        base = _base_de_uso(fonte, filtro)
        emails = _emails(contas)
        if formato == "csv":
            acessos_ao_painel.exportou(pessoa, "videos", filtro)
            return resposta_em_csv(
                csv_em_texto(
                    COLUNAS_DO_CSV_DE_VIDEOS,
                    [
                        _linha_do_csv(
                            u,
                            emails,
                            [
                                u.videos_enviados,
                                u.videos_concluidos,
                                u.videos_falhos,
                                round(u.horas_concluidas, 2),
                                u.segundos_de_processamento,
                            ],
                        )
                        for u in sorted(
                            filter(_tem_video, base),
                            key=lambda u: (u.dia, u.programa or "", u.quem_id or ""),
                        )
                    ],
                ),
                "videos.csv",
            )
        if filtro.programa is not None:
            por_programa = base
        elif filtro.usuario is None:
            por_programa = ou_503(
                lambda: fonte.uso_por_programa(filtro.desde, filtro.ate, None)
            )
        else:
            por_programa = []
        acessos_ao_painel.abriu(pessoa, "videos", filtro)
        return relatorio_de_videos(base, por_programa, emails, filtro)

    @rotas.get("/buscas", response_model=RelatorioDeBuscas)
    def buscas(
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
    ) -> RelatorioDeBuscas | object:
        """Buscas, usuários que buscam e buscas sem resultado, por dia e por usuário. A
        busca só tem programa quando foi filtrada por ele. Programa e usuário não se
        combinam: 422."""
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        base = _base_de_uso(fonte, filtro)
        emails = _emails(contas)
        if formato == "csv":
            acessos_ao_painel.exportou(pessoa, "buscas", filtro)
            return resposta_em_csv(
                csv_em_texto(
                    COLUNAS_DO_CSV_DE_BUSCAS,
                    [
                        _linha_do_csv(u, emails, [u.buscas, u.buscas_sem_resultado])
                        for u in sorted(
                            (u for u in base if u.buscas),
                            key=lambda u: (u.dia, u.programa or "", u.quem_id or ""),
                        )
                    ],
                ),
                "buscas.csv",
            )
        acessos_ao_painel.abriu(pessoa, "buscas", filtro)
        return relatorio_de_buscas(base, emails, filtro)

    return rotas
