import { POR_PAGINA, finalizando, type Job } from './jobs.ts'
import { ESTADOS_DO_JOB } from './cores.ts'

// A aba Entradas da administração: os filtros que viajam na URL e as contas das linhas.

export interface FiltrosDasEntradas {
  /** Vazio (todos), `pessoas` ou `sistema:<nome>`. */
  por: string
  estado: string[]
  /** Período do envio, em `AAAA-MM-DD` (dia de São Paulo), inclusive. */
  de: string
  ate: string
}

export const SEM_FILTROS_DAS_ENTRADAS: FiltrosDasEntradas = { por: '', estado: [], de: '', ate: '' }

const DATA = /^\d{4}-\d{2}-\d{2}$/
const PREFIXO_DO_SISTEMA = 'sistema:'
const SEM_PERIODO = 'tudo'

export function porSistema(nome: string): string {
  return `${PREFIXO_DO_SISTEMA}${nome}`
}

/** O nome do sistema do filtro "enviado por", ou `null` para todos e para pessoas. */
export function sistemaDoFiltro(por: string): string | null {
  return por.startsWith(PREFIXO_DO_SISTEMA) && por.length > PREFIXO_DO_SISTEMA.length ? por.slice(PREFIXO_DO_SISTEMA.length) : null
}

export function haFiltroDeEntradas(f: FiltrosDasEntradas): boolean {
  return Boolean(f.por || f.estado.length || f.de || f.ate)
}

/**
 * Os filtros na query da URL (`?por=&estado=&de=&ate=`). Sem `de` o endereço vale o padrão
 * (a última semana, que não vai escrita: o link não congela a semana); "sem período" é `de=tudo`.
 */
export function filtrosParaEnderecoDasEntradas(f: FiltrosDasEntradas, agora: Date = new Date()): string {
  const p = new URLSearchParams()
  if (f.por) p.set('por', f.por)
  for (const e of f.estado) p.append('estado', e)
  if (f.ate || f.de !== inicioDaUltimaSemana(agora)) p.set('de', f.de || SEM_PERIODO)
  if (f.ate) p.set('ate', f.ate)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

// Um formatador só: o `toLocaleDateString` com fuso monta um a cada chamada, e a lista chama por linha a cada desenho.
const DIA_EM_SAO_PAULO = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Sao_Paulo' })

/** O padrão da aba: hoje menos 6 dias, no dia de São Paulo (`AAAA-MM-DD`). */
function inicioDaUltimaSemana(agora: Date): string {
  const hoje = DIA_EM_SAO_PAULO.format(agora)
  return new Date(Date.parse(`${hoje}T00:00:00Z`) - 6 * 86_400_000).toISOString().slice(0, 10)
}

export function filtrosDasEntradas(busca: string, agora: Date = new Date()): FiltrosDasEntradas {
  const p = new URLSearchParams(busca)
  const por = p.get('por') ?? ''
  const data = (nome: string) => {
    const valor = p.get(nome) ?? ''
    return DATA.test(valor) ? valor : ''
  }
  return {
    por: por === 'pessoas' || sistemaDoFiltro(por) !== null ? por : '',
    // Estado desconhecido num link editado à mão sai do filtro, em vez de fazer a API recusar.
    estado: [...new Set(p.getAll('estado'))].filter((e) => Object.hasOwn(ESTADOS_DO_JOB, e)),
    // O padrão da semana só vale sem período nenhum: com `ate`, o início fica aberto.
    de: p.get('de') === SEM_PERIODO ? '' : data('de') || (data('ate') ? '' : inicioDaUltimaSemana(agora)),
    ate: data('ate'),
  }
}

/** A query de `GET /v1/jobs` para a aba: sistema, estado e o período do envio filtram na API. */
export function consultaDasEntradas(f: FiltrosDasEntradas, cursor: string | null): string {
  const p = new URLSearchParams({ limite: String(POR_PAGINA) })
  const sistema = sistemaDoFiltro(f.por)
  if (sistema) p.set('sistema', sistema)
  for (const e of f.estado) p.append('estado', e)
  if (f.de) p.set('enviado_de', f.de)
  if (f.ate) p.set('enviado_ate', f.ate)
  if (cursor) p.set('cursor', cursor)
  return p.toString()
}

/** O que a API não filtra: a lista de "pessoas", que só esconde linhas já carregadas. */
export function casaComOsFiltrosDoCliente(job: Job, f: FiltrosDasEntradas): boolean {
  return f.por !== 'pessoas' || job.enviado_por?.tipo === 'pessoa'
}

const EM_ANDAMENTO = ['aguardando_upload', 'validando', 'analisando']

/** Anda: ainda não terminou, ou um vídeo concluído tem uma etapa rodando ou entre duas etapas. */
export function emAndamento(job: Job): boolean {
  return EM_ANDAMENTO.includes(job.estado) || Boolean(job.etapa_atual) || finalizando(job)
}

/** As etapas rodando agora (sem fim), uma ou mais; sem a lista, a `etapa_atual` do Job. */
export function etapasEmAndamento(job: Job): string[] {
  const rodando = (job.etapas ?? []).filter((e) => !e.fim).map((e) => e.nome)
  return rodando.length || !job.etapa_atual ? rodando : [job.etapa_atual]
}

/**
 * O tempo total da passada: do início dela até agora, ou até a última etapa quando terminou.
 * Com a indexação concluída na passada, para no fim dela (uma etapa refeita depois não conta).
 * `null` no legado reprocessado sem início.
 */
export function tempoDaEntradaMs(job: Job, agora: number): number | null {
  if (!job.inicio_da_passada && (job.reprocessamentos ?? 0) > 0) return null
  const inicio = new Date(job.inicio_da_passada ?? job.criado_em).getTime()
  const indexada = (job.etapas ?? []).find(
    (e) => e.nome === 'indexacao' && e.resultado === 'concluida' && e.fim && new Date(e.fim).getTime() >= inicio,
  )
  if (indexada?.fim) return new Date(indexada.fim).getTime() - inicio
  if (emAndamento(job)) return Math.max(agora - inicio, 0)
  const fins = (job.etapas ?? []).flatMap((e) => (e.fim ? [new Date(e.fim).getTime()] : []))
  const fim = fins.length ? Math.max(...fins) : new Date(job.atualizado_em ?? job.criado_em).getTime()
  return Math.max(fim - inicio, 0)
}
