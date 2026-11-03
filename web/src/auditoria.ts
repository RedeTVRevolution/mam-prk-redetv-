import { nomeDaEtapa } from './etapas.ts'
import { NOME_DO_PAPEL } from './papeis.ts'
import { ESTADOS_DO_JOB } from './tema.ts'

// A aba Auditoria da administração: a lista fechada de ações, os filtros da URL e os detalhes em frases.

/** A lista fechada de `api/auditoria.py`: cada ação nova do backend ganha a sua frase aqui. */
export const FRASE_DA_ACAO = {
  'conta.criada': 'Criou a conta',
  'conta.link_reenviado': 'Reenviou o link de senha',
  'conta.desativada': 'Desativou a conta',
  'conta.reativada': 'Reativou a conta',
  'papeis.alterados': 'Trocou os papéis',
  'chave.emitida': 'Emitiu a chave',
  'chave.revogada': 'Revogou a chave',
  'item.para_lixeira': 'Mandou para a lixeira',
  'item.restaurado': 'Restaurou da lixeira',
  'item.purgado': 'Purgou da lixeira',
  'video.reprocessado': 'Reprocessou o vídeo',
  'job.estado_corrigido': 'Corrigiu o estado do envio',
} as const

export type AcaoDaAuditoria = keyof typeof FRASE_DA_ACAO

export const ACOES_DA_AUDITORIA = Object.keys(FRASE_DA_ACAO) as AcaoDaAuditoria[]

/** Um registro de `GET /v1/admin/auditoria`. */
export interface RegistroDeAuditoria {
  id: string
  quando: string
  uid?: string | null
  email?: string | null
  sistema?: string | null
  acao: string
  alvo_tipo: string
  alvo_id: string
  alvo_nome: string
  motivo?: string | null
  detalhes: Record<string, unknown>
}

export interface PaginaDeAuditoria {
  registros: RegistroDeAuditoria[]
  proximo: string | null
}

export interface FiltrosDaAuditoria {
  /** E-mail ou uid. */
  pessoa: string
  /** O id do alvo (por exemplo, o de um vídeo). */
  alvo: string
  acao: string
  /** Período, em `AAAA-MM-DD` (dia de São Paulo), inclusive. */
  de: string
  ate: string
}

export const SEM_FILTROS_DA_AUDITORIA: FiltrosDaAuditoria = { pessoa: '', alvo: '', acao: '', de: '', ate: '' }

const DATA = /^\d{4}-\d{2}-\d{2}$/

/** "De" depois de "Até": a API recusa, então a tela avisa sem consultar. */
export function periodoInvertido(f: FiltrosDaAuditoria): boolean {
  return Boolean(f.de && f.ate && f.de > f.ate)
}

export function haFiltroDaAuditoria(f: FiltrosDaAuditoria): boolean {
  return Object.values(f).some(Boolean)
}

export function fraseDaAcao(acao: string): string {
  return Object.hasOwn(FRASE_DA_ACAO, acao) ? FRASE_DA_ACAO[acao as AcaoDaAuditoria] : acao
}

export function filtrosDaAuditoria(busca: string): FiltrosDaAuditoria {
  const p = new URLSearchParams(busca)
  const data = (nome: string) => (DATA.test(p.get(nome) ?? '') ? p.get(nome)! : '')
  const acao = p.get('acao') ?? ''
  return {
    pessoa: p.get('pessoa') ?? '',
    alvo: p.get('alvo') ?? '',
    // Ação desconhecida num link editado à mão sai do filtro, em vez de fazer a API recusar.
    acao: Object.hasOwn(FRASE_DA_ACAO, acao) ? acao : '',
    de: data('de'),
    ate: data('ate'),
  }
}

export function filtrosParaEnderecoDaAuditoria(f: FiltrosDaAuditoria): string {
  const p = new URLSearchParams()
  for (const [chave, valor] of Object.entries(f)) if (valor) p.set(chave, valor)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

/** A query de `GET /v1/admin/auditoria`; o período vira o dia inteiro, em São Paulo (UTC-3, sem horário de verão). */
export function consultaDaAuditoria(f: FiltrosDaAuditoria, limite: number, cursor: string | null): string {
  const p = new URLSearchParams({ limite: String(limite) })
  if (f.pessoa.trim()) p.set('pessoa', f.pessoa.trim())
  if (f.alvo.trim()) p.set('alvo', f.alvo.trim())
  if (f.acao) p.set('acao', f.acao)
  if (f.de) p.set('de', `${f.de}T00:00:00-03:00`)
  if (f.ate) p.set('ate', `${f.ate}T23:59:59.999-03:00`)
  if (cursor) p.set('cursor', cursor)
  return p.toString()
}

function lista(valor: unknown): string {
  const itens = Array.isArray(valor) ? valor.map(String) : []
  return itens.length ? itens.map((p) => NOME_DO_PAPEL[p] ?? p).join(', ') : 'nenhum'
}

function numero(valor: unknown): number | null {
  return typeof valor === 'number' ? valor : null
}

function contar(n: number, singular: string, plural: string): string {
  return `${n.toLocaleString('pt-BR')} ${n === 1 ? singular : plural}`
}

function impacto(d: Record<string, unknown>): string[] {
  const arquivos = (d.arquivos ?? {}) as Record<string, unknown>
  const partes: [unknown, string, string][] = [
    [d.decupagem, 'decupagem', 'decupagens'],
    [d.correcoes, 'correção', 'correções'],
    [arquivos.copia_limpa, 'cópia limpa', 'cópias limpas'],
    [arquivos.proxy, 'proxy de reprodução', 'proxies de reprodução'],
    [arquivos.quadros, 'quadro-chave', 'quadros-chave'],
    [d.aparicoes_que_perdem_o_nome, 'aparição perde o nome', 'aparições perdem o nome'],
    [d.fotos_apagadas, 'foto apagada', 'fotos apagadas'],
    [d.ocorrencias_que_perdem_o_vinculo, 'ocorrência perde o vínculo', 'ocorrências perdem o vínculo'],
  ]
  const frases = partes.flatMap(([n, s, p]) => (numero(n) === null ? [] : [contar(numero(n)!, s, p)]))
  const linhas = frases.length ? [`${frases.join(', ')}.`] : []
  if (Array.isArray(d.outros_jobs) && d.outros_jobs.length)
    linhas.push(`${contar(d.outros_jobs.length, 'outro envio tinha', 'outros envios tinham')} o mesmo conteúdo.`)
  if (d.conteudo_compartilhado === true) linhas.push('A decupagem e os arquivos ficaram: outro envio usa o mesmo conteúdo.')
  return linhas
}

function rotuloDoEstado(estado: string): string {
  return Object.hasOwn(ESTADOS_DO_JOB, estado) ? ESTADOS_DO_JOB[estado as keyof typeof ESTADOS_DO_JOB].rotulo : estado
}

/** Os detalhes do registro em frases; o que não se conhece sai como `chave: valor`. */
export function detalhesEmFrases(r: RegistroDeAuditoria): string[] {
  const d = r.detalhes ?? {}
  switch (r.acao) {
    case 'papeis.alterados':
      return [`Antes: ${lista(d.antes)}`, `Depois: ${lista(d.depois)}`]
    case 'conta.criada':
      return [`Papéis: ${lista(d.papeis)}`]
    case 'chave.emitida':
    case 'chave.revogada':
      return [`Escopos: ${Array.isArray(d.escopos) && d.escopos.length ? d.escopos.join(', ') : 'nenhum'}`]
    case 'item.para_lixeira':
    case 'item.restaurado':
    case 'item.purgado':
      return impacto(d)
    case 'video.reprocessado':
      return typeof d.etapa === 'string'
        ? [`A partir da etapa ${nomeDaEtapa(d.etapa)}${d.etapa_escolhida === true ? ' (escolhida)' : ''}`]
        : []
    case 'job.estado_corrigido':
      return typeof d.de === 'string' && typeof d.para === 'string' ? [`Estado: de ${rotuloDoEstado(d.de)} para ${rotuloDoEstado(d.para)}`] : []
    default:
      return Object.entries(d).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
  }
}

/** Quem fez: a pessoa (e-mail) ou o nome do sistema. */
export function autorDoRegistro(r: RegistroDeAuditoria): string {
  return r.email ?? r.sistema ?? '—'
}
