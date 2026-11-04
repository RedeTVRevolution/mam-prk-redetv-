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
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.auditoria import FiltroDeAuditoria, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.jobs import ServicoIndisponivel, _confere_permissao
from api.relatorios import confere_o_pedido, csv_em_texto, ou_503, resposta_em_csv
from api.resumos_de_uso import AcessoDoDia, ResumosDeUso
from api.usuarios import ContasDeUsuario

JANELA_DA_ABERTURA = timedelta(minutes=30)
Aba = Literal["acessos"]

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

    return rotas
