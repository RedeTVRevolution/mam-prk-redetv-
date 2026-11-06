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

/** Os filtros na query da URL (`?por=&estado=&de=&ate=`). */
export function filtrosParaEnderecoDasEntradas(f: FiltrosDasEntradas): string {
  const p = new URLSearchParams()
  if (f.por) p.set('por', f.por)
  for (const e of f.estado) p.append('estado', e)
  if (f.de) p.set('de', f.de)
  if (f.ate) p.set('ate', f.ate)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

export function filtrosDasEntradas(busca: string): FiltrosDasEntradas {
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
    de: data('de'),
    ate: data('ate'),
  }
}

/** A query de `GET /v1/jobs` para a aba: só o sistema e o estado filtram na API. */
export function consultaDasEntradas(f: FiltrosDasEntradas, cursor: string | null): string {
  const p = new URLSearchParams({ limite: String(POR_PAGINA) })
  const sistema = sistemaDoFiltro(f.por)
  if (sistema) p.set('sistema', sistema)
  for (const e of f.estado) p.append('estado', e)
  if (cursor) p.set('cursor', cursor)
  return p.toString()
}

// Um formatador só: o `toLocaleDateString` com fuso monta um a cada chamada, e a lista chama por linha a cada desenho.
const DIA_EM_SAO_PAULO = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Sao_Paulo' })

/** O dia do envio em São Paulo, `AAAA-MM-DD`. */
function diaDoEnvio(job: Job): string {
  return DIA_EM_SAO_PAULO.format(new Date(job.criado_em))
}

/**
 * O que a API não filtra: a lista de "pessoas" e o período do envio. A lista vem do mais
 * recente para o mais antigo, e este filtro só esconde linhas já carregadas.
 */
export function casaComOsFiltrosDoCliente(job: Job, f: FiltrosDasEntradas): boolean {
  if (f.por === 'pessoas' && job.enviado_por?.tipo !== 'pessoa') return false
  if (!f.de && !f.ate) return true
  const dia = diaDoEnvio(job)
  return (!f.de || dia >= f.de) && (!f.ate || dia <= f.ate)
}

/** Já passou do começo do período: carregar páginas mais antigas não traz mais nada. */
export function passouDoPeriodo(jobs: Job[], f: FiltrosDasEntradas): boolean {
  const ultimo = jobs.at(-1)
  return Boolean(f.de && ultimo && diaDoEnvio(ultimo) < f.de)
}

const EM_ANDAMENTO = ['aguardando_upload', 'validando', 'analisando']

/** Anda: ainda não terminou, ou um vídeo concluído tem uma etapa rodando ou entre duas etapas. */
export function emAndamento(job: Job): boolean {
  return EM_ANDAMENTO.includes(job.estado) || Boolean(job.etapa_atual) || finalizando(job)
}

/**
 * Na etapa atual, o tempo desde que ela começou (ou desde o envio, se ainda não há etapa);
 * terminado, o tempo total do envio até a última etapa.
 */
export function tempoDaEntradaMs(job: Job, agora: number): number {
  const criado = new Date(job.criado_em).getTime()
  if (emAndamento(job)) {
    const etapa = job.etapas?.find((e) => e.nome === job.etapa_atual)
    return Math.max(agora - (etapa ? new Date(etapa.inicio).getTime() : criado), 0)
  }
  const fins = (job.etapas ?? []).flatMap((e) => (e.fim ? [new Date(e.fim).getTime()] : []))
  const fim = fins.length ? Math.max(...fins) : new Date(job.atualizado_em ?? job.criado_em).getTime()
  return Math.max(fim - criado, 0)
}
