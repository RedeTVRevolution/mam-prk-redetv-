"""Painel da diretoria (E9): quem pode ver, os filtros comuns, as rotas `/v1/painel/...` e o
registro de cada acesso na auditoria.

A abertura de uma aba e cada exportação em CSV gravam quem, quando, a aba e o filtro. Uma
aba aberta de novo com o mesmo filtro dentro de 30 minutos (recarga) não grava outra
abertura; filtro novo, sim: é outra coisa vista. As rotas leem só as tabelas resumidas
(`api/resumos_de_uso.py`) e nunca a tabela de eventos.
"""

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from api.auditoria import FiltroDeAuditoria, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.custo_do_painel import (
    COLUNAS_DO_CSV_DE_CUSTO,
    FonteDeCusto,
    RelatorioDeCusto,
    base_de_custo,
    linhas_do_csv_de_custo,
    relatorio_de_custo,
)
from api.jobs import (
    Estado,
    FiltroDeJobs,
    Job,
    RepositorioDeJobs,
    ServicoIndisponivel,
    _confere_permissao,
)
from api.qualidade_do_painel import SAO_PAULO, QualidadeDoPainel, RevisaoNoVideo
from api.relatorios import (
    confere_o_pedido,
    csv_em_texto,
    em_paralelo,
    ou_503,
    resposta_em_csv,
)
from api.resumos_de_uso import (
    AcessoDoDia,
    ChamadaDoDia,
    CorrecaoDoDia,
    ResumosDeUso,
    UsoDoDia,
)
from api.taxa_de_correcao import LinhaDaTaxa
from api.usuarios import ContasDeUsuario

JANELA_DA_ABERTURA = timedelta(minutes=30)
Aba = Literal["acessos", "videos", "buscas", "revisao", "api", "custo"]
Grupo = Literal["dia", "semana", "mes", "trimestre"]
MAXIMO_DE_PONTOS = 400  # um agrupamento pedido que dê mais pontos que isto é 422
# Com `agrupar=auto`: o menor grupo que deixa o gráfico com até ~90 pontos. Os dias são
# do primeiro ao último dia com dados: até 90 dias, por dia; até ~1,5 ano, por semana;
# até ~7 anos, por mês; depois, por trimestre.
FAIXAS_DO_AUTO: tuple[tuple[int, Grupo], ...] = (
    (90, "dia"),
    (548, "semana"),
    (2557, "mes"),
)

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


# Os Jobs ainda em andamento; os terminados ficam de fora (a falha já tem alerta próprio).
ESTADOS_DA_FILA: tuple[Estado, ...] = ("aguardando_upload", "validando", "analisando")
assert set(ESTADOS_DA_FILA) | {"concluido", "falhou", "cancelado"} == set(
    get_args(Estado)
)


class EstadoNaFila(BaseModel):
    estado: Estado
    quantidade: int
    idade_do_mais_antigo_s: int  # desde a criação; 0 sem Job no estado


class FilaAgora(BaseModel):
    por_estado: list[EstadoNaFila]


def fila_agora(na_fila: list[Job], agora: datetime) -> FilaAgora:
    por_estado = []
    for estado in ESTADOS_DA_FILA:
        do_estado = [j for j in na_fila if j.estado == estado]
        idade = max((agora - j.criado_em for j in do_estado), default=timedelta())
        por_estado.append(
            EstadoNaFila(
                estado=estado,
                quantidade=len(do_estado),
                idade_do_mais_antigo_s=round(idade.total_seconds()),
            )
        )
    return FilaAgora(por_estado=por_estado)


COLUNAS_DO_CSV_DE_ACESSOS = ("dia", "uid", "email", "acessos", "ativo", "ultimo_acesso")


class EmailsDasContas:
    """Uid -> e-mail das contas, lembrado por `validade` segundos nesta instância: listar as
    contas no Identity Platform custa ~0,3 s por requisição. Uma conta nova leva até esse
    tempo para aparecer com e-mail. Sem a lista, o painel mostra só o uid (e a falha não
    fica guardada: a próxima requisição tenta de novo)."""

    def __init__(
        self,
        contas: ContasDeUsuario,
        validade: float = 60.0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._contas = contas
        self._validade = validade
        self._relogio = relogio
        self._trava = threading.Lock()
        self._emails: dict[str, str] = {}
        self._vence_em: float | None = None

    def __call__(self) -> dict[str, str]:
        # A trava segura a leitura inteira: quem chega junto espera uma só listagem.
        with self._trava:
            if self._vence_em is None or self._relogio() >= self._vence_em:
                try:
                    self._emails = {c.uid: c.email for c in self._contas.listar()}
                except Exception:
                    log.exception("Falha ao listar as contas para o painel")
                    return {}
                self._vence_em = self._relogio() + self._validade
            return dict(self._emails)


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


def inicio_do_grupo(dia: date, grupo: Grupo) -> date:
    """O primeiro dia do grupo: a segunda da semana, o dia 1 do mês ou do trimestre."""
    if grupo == "semana":
        return dia - timedelta(days=dia.weekday())
    if grupo == "mes":
        return dia.replace(day=1)
    if grupo == "trimestre":
        return dia.replace(month=(dia.month - 1) // 3 * 3 + 1, day=1)
    return dia


def _agrupar_dias[V](
    por_dia: dict[date, V], grupo: Grupo, juntar: Callable[[V, V], V]
) -> dict[date, V]:
    juntos: dict[date, V] = {}
    for dia, valor in por_dia.items():
        g = inicio_do_grupo(dia, grupo)
        juntos[g] = juntar(juntos[g], valor) if g in juntos else valor
    return juntos


def escolhe_o_grupo(agrupar: Grupo | Literal["auto"], dias: Iterable[date]) -> Grupo:
    """O grupo dos gráficos por dia. `auto` escolhe pelo tamanho do período com dados; um
    grupo pedido que dê mais de `MAXIMO_DE_PONTOS` pontos é 422."""
    dias = list(dias)
    if agrupar == "auto":
        tamanho = (max(dias) - min(dias)).days + 1 if dias else 0
        return next((g for ate, g in FAIXAS_DO_AUTO if tamanho <= ate), "trimestre")
    pontos = len(_dias_do_intervalo(dias, agrupar))
    if pontos > MAXIMO_DE_PONTOS:
        raise HTTPException(
            422,
            f"`agrupar={agrupar}` dá {pontos} pontos (o máximo é {MAXIMO_DE_PONTOS}); "
            "use um grupo maior ou `auto`",
        )
    return agrupar


def _com_os_dias_vazios(por_dia: dict[date, int], grupo: Grupo) -> dict[date, int]:
    return {d: por_dia.get(d, 0) for d in _dias_do_intervalo(por_dia, grupo)}


def relatorio_de_acessos(
    linhas: list[AcessoDoDia],
    emails: dict[str, str],
    filtro: FiltroDoPainel,
    grupo: Grupo = "dia",
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
    # No grupo, os ativos são os distintos dele: quem agiu em três dias conta uma vez.
    acessos_do_grupo = _agrupar_dias(acessos_do_dia, grupo, int.__add__)
    ativos_do_grupo = _agrupar_dias(ativos_do_dia, grupo, set.union)
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
                usuarios_ativos=len(ativos_do_grupo.get(d, ())),
            )
            for d, n in sorted(_com_os_dias_vazios(acessos_do_grupo, grupo).items())
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


def _dias_do_intervalo(dias: Iterable[date], grupo: Grupo = "dia") -> list[date]:
    """Do primeiro ao último dia, sem buracos: o gráfico não cola dias distantes. Com um
    grupo, o primeiro dia de cada grupo do intervalo."""
    dias = list(dias)
    if not dias:
        return []
    primeiro = min(dias)
    return list(
        dict.fromkeys(
            inicio_do_grupo(primeiro + timedelta(days=i), grupo)
            for i in range((max(dias) - primeiro).days + 1)
        )
    )


def relatorio_de_videos(
    base: list[UsoDoDia],
    por_programa: list[UsoDoDia],
    emails: dict[str, str],
    filtro: FiltroDoPainel,
    grupo: Grupo = "dia",
) -> RelatorioDeVideos:
    """`base` são as linhas do filtro (por programa ou por pessoa, veja `_base_de_uso`);
    `por_programa` são as linhas por programa de um pedido sem filtro de usuário."""
    base = [u for u in base if _tem_video(u)]
    por_dia = _somas_por(base, lambda u: inicio_do_grupo(u.dia, grupo))
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
            for d in _dias_do_intervalo(por_dia, grupo)
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
    base: list[UsoDoDia],
    emails: dict[str, str],
    filtro: FiltroDoPainel,
    grupo: Grupo = "dia",
) -> RelatorioDeBuscas:
    """Quem busca são só pessoas (o sistema que busca pela API aparece em `por_usuario`,
    mas não conta em `usuarios_que_buscam`)."""
    base = [u for u in base if u.buscas]
    por_programa = filtro.programa is not None
    por_dia = _somas_por(base, lambda u: inicio_do_grupo(u.dia, grupo))
    pessoas_do_dia: dict[date, set[str]] = defaultdict(set)
    for u in base:
        if u.quem_tipo == "usuario" and u.quem_id is not None:
            pessoas_do_dia[inicio_do_grupo(u.dia, grupo)].add(u.quem_id)
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
            for d in _dias_do_intervalo(por_dia, grupo)
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


COLUNAS_DO_CSV_DE_REVISAO = (
    "indicador",
    "dia",
    "quem_id",
    "email",
    "programa",
    "tipo",
    "correcoes",
    "itens",
    "taxa_de_correcao",
    "minutos",
    "horas_de_video",
    "minutos_por_hora_de_video",
)
COLUNAS_DO_CSV_DE_API = (
    "dia",
    "quem_tipo",
    "quem_id",
    "metodo",
    "rota",
    "chamadas",
    "erros_do_cliente",
    "erros_do_servidor",
    "videos_enviados",
)


class DiaDeCorrecoes(BaseModel):
    dia: date
    correcoes: int


class TipoDeCorrecoes(BaseModel):
    # Vazio no evento que não trouxe o tipo.
    tipo: str | None
    correcoes: int


class QuemDeCorrecoes(BaseModel):
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    email: str | None
    correcoes: int


class CorrecoesNoPeriodo(BaseModel):
    total: int
    por_dia: list[DiaDeCorrecoes]
    por_tipo: list[TipoDeCorrecoes]
    por_usuario: list[QuemDeCorrecoes]


class TaxaDoTipo(BaseModel):
    tipo: str
    correcoes: int
    itens: int
    taxa: float | None


class TaxaDoPrograma(BaseModel):
    programa: str | None
    correcoes: int
    itens: int
    taxa: float | None


class TaxaDeCorrecaoNoPainel(BaseModel):
    """A taxa de correção (#265) com as versões do pipeline somadas. Não tem pessoa: com
    filtro de usuário as duas listas vêm vazias."""

    por_tipo: list[TaxaDoTipo]
    por_programa: list[TaxaDoPrograma]


class NumerosDeRevisao(BaseModel):
    """`minutos` é o tempo ativo de revisão; `horas_de_video`, a duração dos vídeos
    revisados (cada um uma vez); `minutos_por_hora_de_video` só conta os vídeos com
    duração conhecida e vem vazio sem nenhum."""

    minutos: float
    videos: int
    horas_de_video: float
    minutos_por_hora_de_video: float | None


class PessoaNaRevisaoDoPainel(NumerosDeRevisao):
    uid: str
    email: str


class ProgramaNaRevisao(NumerosDeRevisao):
    programa: str | None


class TempoDeRevisaoNoPainel(BaseModel):
    total: NumerosDeRevisao
    por_pessoa: list[PessoaNaRevisaoDoPainel]
    por_programa: list[ProgramaNaRevisao]


class RelatorioDeRevisao(BaseModel):
    desde: date | None
    ate: date | None
    programa: str | None
    usuario: str | None
    correcoes: CorrecoesNoPeriodo
    taxa_de_correcao: TaxaDeCorrecaoNoPainel
    tempo_de_revisao: TempoDeRevisaoNoPainel


def relatorio_de_correcoes(
    linhas: list[CorrecaoDoDia], emails: dict[str, str], grupo: Grupo = "dia"
) -> CorrecoesNoPeriodo:
    por_dia: dict[date, int] = defaultdict(int)
    por_tipo: dict[str | None, int] = defaultdict(int)
    por_quem: dict[tuple[str, str], int] = defaultdict(int)
    for c in linhas:
        por_dia[inicio_do_grupo(c.dia, grupo)] += c.correcoes
        por_tipo[c.tipo_de_correcao] += c.correcoes
        por_quem[(c.quem_tipo, c.quem_id)] += c.correcoes
    return CorrecoesNoPeriodo(
        total=sum(por_dia.values()),
        por_dia=[
            DiaDeCorrecoes(dia=d, correcoes=por_dia.get(d, 0))
            for d in _dias_do_intervalo(por_dia, grupo)
        ],
        por_tipo=[
            TipoDeCorrecoes(tipo=t, correcoes=n)
            for t, n in sorted(
                por_tipo.items(), key=lambda i: (-i[1], i[0] is None, i[0] or "")
            )
        ],
        por_usuario=[
            QuemDeCorrecoes.model_validate(
                {
                    "quem_tipo": tipo,
                    "quem_id": quem_id,
                    "email": emails.get(quem_id),
                    "correcoes": n,
                }
            )
            for (tipo, quem_id), n in sorted(
                por_quem.items(), key=lambda i: (-i[1], i[0][1])
            )
        ],
    )


def _taxa(correcoes: int, itens: int) -> float | None:
    return round(correcoes / itens, 4) if itens else None


def taxa_no_painel(linhas: list[LinhaDaTaxa]) -> TaxaDeCorrecaoNoPainel:
    por_tipo: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    por_programa: dict[str | None, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for t in linhas:
        c, i = por_tipo[t.tipo]
        por_tipo[t.tipo] = (c + t.correcoes, i + t.itens)
        c, i = por_programa[t.programa]
        por_programa[t.programa] = (c + t.correcoes, i + t.itens)
    return TaxaDeCorrecaoNoPainel(
        por_tipo=[
            TaxaDoTipo(tipo=t, correcoes=c, itens=i, taxa=_taxa(c, i))
            for t, (c, i) in sorted(por_tipo.items())
        ],
        por_programa=[
            TaxaDoPrograma(programa=p, correcoes=c, itens=i, taxa=_taxa(c, i))
            for p, (c, i) in sorted(por_programa.items(), key=lambda x: x[0] or "")
        ],
    )


def _numeros_de_revisao(medidas: list[RevisaoNoVideo]) -> dict[str, Any]:
    """Os minutos de revisão dos vídeos dados. A duração é a do vídeo (a maior que alguma
    medida trouxe) e conta uma vez, mesmo revisado por mais de uma pessoa."""
    duracao: dict[str, float] = {}
    for m in medidas:
        if m.duracao_s:
            duracao[m.job_id] = max(duracao.get(m.job_id, 0), m.duracao_s)
    ativo_s = sum(m.ativo_s for m in medidas)
    ativo_com_duracao_s = sum(m.ativo_s for m in medidas if m.job_id in duracao)
    horas = sum(duracao.values()) / 3600
    return NumerosDeRevisao(
        minutos=round(ativo_s / 60, 2),
        videos=len({m.job_id for m in medidas}),
        horas_de_video=round(horas, 2),
        minutos_por_hora_de_video=(
            round(ativo_com_duracao_s / 60 / horas, 2) if horas else None
        ),
    ).model_dump()


def _agrupar[C](
    medidas: list[RevisaoNoVideo], chave: Callable[[RevisaoNoVideo], C]
) -> dict[C, list[RevisaoNoVideo]]:
    grupos: dict[C, list[RevisaoNoVideo]] = defaultdict(list)
    for m in medidas:
        grupos[chave(m)].append(m)
    return grupos


def tempo_no_painel(medidas: list[RevisaoNoVideo]) -> TempoDeRevisaoNoPainel:
    pessoas = _agrupar(medidas, lambda m: (m.uid, m.email))
    programas = _agrupar(medidas, lambda m: m.programa)
    return TempoDeRevisaoNoPainel(
        total=NumerosDeRevisao(**_numeros_de_revisao(medidas)),
        por_pessoa=[
            PessoaNaRevisaoDoPainel(uid=uid, email=email, **numeros)
            for (uid, email), numeros in sorted(
                ((quem, _numeros_de_revisao(ms)) for quem, ms in pessoas.items()),
                key=lambda i: (-i[1]["minutos"], i[0][1]),
            )
        ],
        por_programa=[
            ProgramaNaRevisao(programa=p, **_numeros_de_revisao(ms))
            for p, ms in sorted(programas.items(), key=lambda i: i[0] or "")
        ],
    )


def _linhas_do_csv_de_revisao(
    correcoes: list[CorrecaoDoDia],
    taxa: list[LinhaDaTaxa],
    medidas: list[RevisaoNoVideo],
    emails: dict[str, str],
) -> list[list[object]]:
    """Uma tabela só, com a coluna `indicador`: as correções por dia, pessoa, programa e
    tipo; a taxa por programa e tipo (as versões somadas); o tempo por pessoa e programa."""
    linhas: list[list[object]] = []
    for c in sorted(
        correcoes,
        key=lambda c: (c.dia, c.quem_id, c.programa or "", c.tipo_de_correcao or ""),
    ):
        linhas.append(
            [
                "correcoes",
                c.dia.isoformat(),
                c.quem_id,
                emails.get(c.quem_id, ""),
                c.programa or "",
                c.tipo_de_correcao or "",
                c.correcoes,
                "",
                "",
                "",
                "",
                "",
            ]
        )
    somas: dict[tuple[str, str], tuple[int, int]] = defaultdict(lambda: (0, 0))
    for t in taxa:
        feitas, itens = somas[(t.programa or "", t.tipo)]
        somas[(t.programa or "", t.tipo)] = (feitas + t.correcoes, itens + t.itens)
    for (programa, tipo), (feitas, itens) in sorted(somas.items()):
        taxa_ = _taxa(feitas, itens)
        linhas.append(
            [
                "taxa",
                "",
                "",
                "",
                programa,
                tipo,
                feitas,
                itens,
                "" if taxa_ is None else taxa_,
            ]
            + [""] * 3
        )
    for (uid, email, programa), ms in sorted(
        _agrupar(medidas, lambda m: (m.uid, m.email, m.programa or "")).items()
    ):
        n = _numeros_de_revisao(ms)
        por_hora = n["minutos_por_hora_de_video"]
        linhas.append(
            ["tempo", "", uid, email, programa, "", "", "", ""]
            + [n["minutos"], n["horas_de_video"], "" if por_hora is None else por_hora]
        )
    return linhas


class NumerosDeChamadas(BaseModel):
    chamadas: int
    erros_do_cliente: int
    erros_do_servidor: int


class DiaDeApi(NumerosDeChamadas):
    dia: date
    videos_enviados: int


class SistemaDeApi(NumerosDeChamadas):
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    videos_enviados: int


class RotaDeApi(NumerosDeChamadas):
    metodo: str | None
    rota: str | None


class TotalDeApi(NumerosDeChamadas):
    sistemas: int
    videos_enviados: int


class RelatorioDeApi(BaseModel):
    """`videos_enviados` são só os enviados por sistema (as pessoas pela tela não contam)."""

    desde: date | None
    ate: date | None
    usuario: str | None
    total: TotalDeApi
    por_dia: list[DiaDeApi]
    por_sistema: list[SistemaDeApi]
    por_rota: list[RotaDeApi]


def _numeros_de_chamadas(linhas: Iterable[ChamadaDoDia]) -> dict[str, int]:
    linhas = list(linhas)
    return {
        "chamadas": sum(c.chamadas for c in linhas),
        "erros_do_cliente": sum(c.erros_do_cliente for c in linhas),
        "erros_do_servidor": sum(c.erros_do_servidor for c in linhas),
    }


def relatorio_de_api(
    chamadas: list[ChamadaDoDia],
    envios: list[UsoDoDia],
    filtro: FiltroDoPainel,
    grupo: Grupo = "dia",
) -> RelatorioDeApi:
    """`envios` são as linhas por pessoa ou sistema; só valem as de sistema com vídeo enviado."""
    envios = [u for u in envios if u.quem_tipo == "sistema" and u.videos_enviados]
    enviados_do_dia: dict[date, int] = defaultdict(int)
    enviados_do_sistema: dict[tuple[str, str], int] = defaultdict(int)
    for u in envios:
        enviados_do_dia[inicio_do_grupo(u.dia, grupo)] += u.videos_enviados
        enviados_do_sistema[("sistema", u.quem_id or "")] += u.videos_enviados
    do_dia: dict[date, list[ChamadaDoDia]] = defaultdict(list)
    do_sistema: dict[tuple[str, str], list[ChamadaDoDia]] = defaultdict(list)
    da_rota: dict[tuple[str | None, str | None], list[ChamadaDoDia]] = defaultdict(list)
    for c in chamadas:
        do_dia[inicio_do_grupo(c.dia, grupo)].append(c)
        do_sistema[(c.quem_tipo, c.quem_id)].append(c)
        da_rota[(c.metodo, c.rota)].append(c)
    quem = sorted(
        set(do_sistema) | set(enviados_do_sistema),
        key=lambda q: (-_numeros_de_chamadas(do_sistema[q])["chamadas"], q[1]),
    )
    return RelatorioDeApi(
        desde=filtro.desde,
        ate=filtro.ate,
        usuario=filtro.usuario,
        total=TotalDeApi(
            **_numeros_de_chamadas(chamadas),
            sistemas=len(quem),
            videos_enviados=sum(enviados_do_dia.values()),
        ),
        por_dia=[
            DiaDeApi(
                dia=d,
                videos_enviados=enviados_do_dia.get(d, 0),
                **_numeros_de_chamadas(do_dia.get(d, [])),
            )
            for d in _dias_do_intervalo(set(do_dia) | set(enviados_do_dia), grupo)
        ],
        por_sistema=[
            SistemaDeApi.model_validate(
                {
                    "quem_tipo": tipo,
                    "quem_id": quem_id,
                    "videos_enviados": enviados_do_sistema.get((tipo, quem_id), 0),
                    **_numeros_de_chamadas(do_sistema.get((tipo, quem_id), [])),
                }
            )
            for tipo, quem_id in quem
        ],
        por_rota=[
            RotaDeApi(metodo=m, rota=r, **_numeros_de_chamadas(cs))
            for (m, r), cs in sorted(
                da_rota.items(),
                key=lambda i: (
                    -sum(c.chamadas for c in i[1]),
                    i[0][1] or "",
                    i[0][0] or "",
                ),
            )
        ],
    )


def criar_rotas_do_painel(
    resumos: ResumosDeUso | None,
    contas: ContasDeUsuario,
    acessos_ao_painel: AcessosAoPainel,
    qualidade: QualidadeDoPainel,
    faturamento: FonteDeCusto | None,
    jobs: RepositorioDeJobs,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/painel")
    emails_das_contas = EmailsDasContas(contas)

    def _grupo(
        agrupar: Grupo | Literal["auto"] | None,
        dias: Iterable[date],
        resposta: Response,
    ) -> Grupo:
        """Sem `agrupar`, por dia como sempre; com ele, o grupo usado vai no cabeçalho
        `X-Agrupamento` (o `auto` diz qual escolheu). O CSV não agrupa."""
        if agrupar is None:
            return "dia"
        grupo = escolhe_o_grupo(agrupar, dias)
        resposta.headers["X-Agrupamento"] = grupo
        return grupo

    @rotas.get("/fila", response_model=FilaAgora)
    def fila(_pessoa: PodeVerOPainel) -> FilaAgora:
        """Os Jobs em andamento por estado e a idade do mais antigo, lidos na hora (#420).
        Fica na aba Vídeos, cuja abertura já vai para a auditoria pela rota `/videos`."""
        na_fila = ou_503(
            lambda: (
                jobs.consultar(FiltroDeJobs(estados=frozenset(ESTADOS_DA_FILA))).jobs
            )
        )
        return fila_agora(na_fila, relogio())

    @rotas.get("/filtros", response_model=OpcoesDosFiltros)
    def filtros(_pessoa: PodeVerOPainel) -> OpcoesDosFiltros:
        """O que a tela oferece nos filtros de programa e de usuário."""
        fonte = confere_o_pedido(resumos, None, None)
        programas, uids, emails = ou_503(
            lambda: em_paralelo(fonte.programas, fonte.usuarios, emails_das_contas)
        )
        return OpcoesDosFiltros(
            programas=programas,
            usuarios=[UsuarioDoFiltro(uid=u, email=emails.get(u)) for u in uids],
        )

    @rotas.get("/acessos", response_model=RelatorioDeAcessos)
    def acessos(
        resposta: Response,
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
        agrupar: Grupo | Literal["auto"] | None = None,
    ) -> RelatorioDeAcessos | object:
        """Logins por dia, usuários ativos (por dia, semana e mês), por usuário e no total. O login não tem programa:
        pedir `programa` é erro, em vez de devolver números que ele não filtrou."""
        if filtro.programa is not None:
            raise HTTPException(422, "Os acessos não têm programa")
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        linhas = _com_acesso(
            ou_503(lambda: fonte.acessos(filtro.desde, filtro.ate, filtro.usuario))
        )
        emails = emails_das_contas()
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
                            # Em São Paulo, com o deslocamento, como o `dia`; o JSON segue em UTC.
                            a.ultimo_acesso.astimezone(SAO_PAULO).isoformat(
                                timespec="seconds"
                            )
                            if a.ultimo_acesso
                            else "",
                        ]
                        for a in sorted(linhas, key=lambda a: (a.dia, a.uid))
                    ],
                ),
                "acessos.csv",
            )
        grupo = _grupo(agrupar, (a.dia for a in linhas), resposta)
        acessos_ao_painel.abriu(pessoa, "acessos", filtro)
        return relatorio_de_acessos(linhas, emails, filtro, grupo)

    @rotas.get("/videos", response_model=RelatorioDeVideos)
    def videos(
        resposta: Response,
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
        agrupar: Grupo | Literal["auto"] | None = None,
    ) -> RelatorioDeVideos | object:
        """Vídeos enviados, concluídos e com falha, horas e tempo de processamento, por dia,
        programa e usuário (ou sistema). Programa e usuário não se combinam: 422."""
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        # O CSV não tem a tabela por programa; com `programa` ela é a própria base.
        com_tabela_por_programa = (
            formato == "json" and filtro.programa is None and filtro.usuario is None
        )
        base, por_programa, emails = em_paralelo(
            lambda: _base_de_uso(fonte, filtro),
            lambda: (
                ou_503(lambda: fonte.uso_por_programa(filtro.desde, filtro.ate, None))
                if com_tabela_por_programa
                else []
            ),
            emails_das_contas,
        )
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
        grupo = _grupo(agrupar, (u.dia for u in base if _tem_video(u)), resposta)
        acessos_ao_painel.abriu(pessoa, "videos", filtro)
        return relatorio_de_videos(base, por_programa, emails, filtro, grupo)

    @rotas.get("/buscas", response_model=RelatorioDeBuscas)
    def buscas(
        resposta: Response,
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
        agrupar: Grupo | Literal["auto"] | None = None,
    ) -> RelatorioDeBuscas | object:
        """Buscas, usuários que buscam e buscas sem resultado, por dia e por usuário. A
        busca só tem programa quando foi filtrada por ele. Programa e usuário não se
        combinam: 422."""
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        base = _base_de_uso(fonte, filtro)
        emails = emails_das_contas()
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
        grupo = _grupo(agrupar, (u.dia for u in base if u.buscas), resposta)
        acessos_ao_painel.abriu(pessoa, "buscas", filtro)
        return relatorio_de_buscas(base, emails, filtro, grupo)

    @rotas.get("/revisao", response_model=RelatorioDeRevisao)
    def revisao(
        resposta: Response,
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
        agrupar: Grupo | Literal["auto"] | None = None,
    ) -> RelatorioDeRevisao | object:
        """Correções por dia, tipo e usuário; a taxa de correção por tipo e por programa
        (#265); os minutos de revisão por hora de vídeo por pessoa e por programa (#251).
        Os filtros se cruzam; a taxa não tem pessoa e vem vazia com filtro de usuário."""
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        correcoes = ou_503(
            lambda: fonte.correcoes(
                filtro.desde, filtro.ate, filtro.programa, filtro.usuario
            )
        )
        taxa = (
            []
            if filtro.usuario is not None
            else ou_503(
                lambda: qualidade.taxa_de_correcao(
                    filtro.desde, filtro.ate, filtro.programa
                )
            )
        )
        medidas = ou_503(
            lambda: qualidade.tempo_de_revisao(
                filtro.desde, filtro.ate, filtro.programa, filtro.usuario
            )
        )
        emails = emails_das_contas()
        if formato == "csv":
            acessos_ao_painel.exportou(pessoa, "revisao", filtro)
            return resposta_em_csv(
                csv_em_texto(
                    COLUNAS_DO_CSV_DE_REVISAO,
                    _linhas_do_csv_de_revisao(correcoes, taxa, medidas, emails),
                ),
                "revisao.csv",
            )
        grupo = _grupo(agrupar, (c.dia for c in correcoes), resposta)
        acessos_ao_painel.abriu(pessoa, "revisao", filtro)
        return RelatorioDeRevisao(
            desde=filtro.desde,
            ate=filtro.ate,
            programa=filtro.programa,
            usuario=filtro.usuario,
            correcoes=relatorio_de_correcoes(correcoes, emails, grupo),
            taxa_de_correcao=taxa_no_painel(taxa),
            tempo_de_revisao=tempo_no_painel(medidas),
        )

    @rotas.get("/api", response_model=RelatorioDeApi)
    def api(
        resposta: Response,
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
        agrupar: Grupo | Literal["auto"] | None = None,
    ) -> RelatorioDeApi | object:
        """Chamadas por sistema e por rota, erros e vídeos enviados pela API. A chamada não
        tem programa: pedir `programa` é erro. `usuario` filtra o sistema."""
        if filtro.programa is not None:
            raise HTTPException(422, "As chamadas de API não têm programa")
        fonte = confere_o_pedido(resumos, filtro.desde, filtro.ate)
        chamadas, uso = ou_503(
            lambda: em_paralelo(
                lambda: fonte.chamadas(filtro.desde, filtro.ate, filtro.usuario),
                lambda: fonte.uso_por_quem(filtro.desde, filtro.ate, filtro.usuario),
            )
        )
        envios = [u for u in uso if u.quem_tipo == "sistema"]
        if formato == "csv":
            acessos_ao_painel.exportou(pessoa, "api", filtro)
            return resposta_em_csv(
                csv_em_texto(
                    COLUNAS_DO_CSV_DE_API,
                    [
                        [
                            c.dia.isoformat(),
                            c.quem_tipo,
                            c.quem_id,
                            c.metodo or "",
                            c.rota or "",
                            c.chamadas,
                            c.erros_do_cliente,
                            c.erros_do_servidor,
                            "",
                        ]
                        for c in sorted(
                            chamadas,
                            key=lambda c: (
                                c.dia,
                                c.quem_id,
                                c.rota or "",
                                c.metodo or "",
                            ),
                        )
                    ]
                    + [
                        [
                            u.dia.isoformat(),
                            u.quem_tipo,
                            u.quem_id,
                            "",
                            "",
                            "",
                            "",
                            "",
                            u.videos_enviados,
                        ]
                        for u in sorted(
                            (u for u in envios if u.videos_enviados),
                            key=lambda u: (u.dia, u.quem_id or ""),
                        )
                    ],
                ),
                "api.csv",
            )
        dias = [c.dia for c in chamadas] + [u.dia for u in envios if u.videos_enviados]
        grupo = _grupo(agrupar, dias, resposta)
        acessos_ao_painel.abriu(pessoa, "api", filtro)
        return relatorio_de_api(chamadas, envios, filtro, grupo)

    @rotas.get("/custo", response_model=RelatorioDeCusto)
    def custo(
        pessoa: PodeVerOPainel,
        filtro: Annotated[FiltroDoPainel, Depends(filtro_do_painel)],
        formato: Literal["json", "csv"] = "json",
    ) -> RelatorioDeCusto | object:
        """Custo por hora de vídeo e por mês, por usuário (ou sistema) e no total, do
        faturamento cruzado com os Jobs (#285). O custo sem dono (fixo ou sem rótulo) só
        entra sem filtro de programa ou de usuário."""
        fonte = confere_o_pedido(faturamento, filtro.desde, filtro.ate)
        base = ou_503(
            lambda: base_de_custo(
                fonte.custos(filtro.desde),
                jobs.listar(),
                filtro.desde,
                filtro.ate,
                filtro.programa,
                filtro.usuario,
            )
        )
        emails = emails_das_contas()
        if formato == "csv":
            acessos_ao_painel.exportou(pessoa, "custo", filtro)
            return resposta_em_csv(
                csv_em_texto(
                    COLUNAS_DO_CSV_DE_CUSTO, linhas_do_csv_de_custo(base, emails)
                ),
                "custo.csv",
            )
        acessos_ao_painel.abriu(pessoa, "custo", filtro)
        return relatorio_de_custo(
            base, emails, filtro.desde, filtro.ate, filtro.programa, filtro.usuario
        )

    return rotas
