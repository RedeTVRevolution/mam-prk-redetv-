import { consultaDaBusca, consultaParaEndereco, type ConsultaDaBusca } from './busca.ts'
import { filtrosParaEnderecoDaAuditoria, type FiltrosDaAuditoria } from './auditoria.ts'
import { filtrosParaEnderecoDasEntradas, type FiltrosDasEntradas } from './entradas.ts'
import { filtrosDaBusca, type FiltrosDoAcervo } from './jobs.ts'
import { filtrosDeMarcas, type FiltrosDeMarcas } from './marcas.ts'
import {
  abaDoPainel,
  filtrosDoPainel,
  filtrosParaEnderecoDoPainel,
  type AbaDoPainel,
  type FiltrosDoPainel,
} from './painelDaDiretoria.ts'
import { filtrosDoRelatorio, filtrosParaEndereco, type FiltrosDoRelatorio } from './tempoDeTela.ts'
import { useMemo, useSyncExternalStore, type MouseEvent } from 'react'

// Rotas com endereço sobre a History API, sem biblioteca (princípio 9 de docs/design/principios.md).

export type Rota =
  | { tipo: 'raiz' }
  | { tipo: 'acervo'; filtros: FiltrosDoAcervo }
  | { tipo: 'busca'; consulta: ConsultaDaBusca }
  | { tipo: 'video'; id: string; t: number | null; busca: string | null }
  | { tipo: 'parecidos'; job: string; plano: number }
  | { tipo: 'tempo_de_tela'; filtros: FiltrosDoRelatorio }
  | { tipo: 'marcas'; filtros: FiltrosDeMarcas }
  | { tipo: 'painel'; aba: AbaDoPainel; filtros: FiltrosDoPainel }
  | { tipo: 'admin'; aba: string | null; busca: string }
  | { tipo: 'amostra' }
  | { tipo: 'nao_encontrada' }

export const ACERVO = '/acervo'
export const TEMPO_DE_TELA = '/relatorios/tempo-de-tela'
export const MARCAS = '/relatorios/marcas'
export const ADMIN = '/admin'
export const PAINEL = '/painel'

/** O endereço de uma aba da administração (`usuarios`, `chaves`, …). */
export function enderecoDaAba(aba: string): string {
  return `${ADMIN}/${aba}`
}

/** O endereço da aba Entradas, com os filtros na query. */
export function enderecoDasEntradas(filtros: FiltrosDasEntradas): string {
  return `${enderecoDaAba('entradas')}${filtrosParaEnderecoDasEntradas(filtros)}`
}

/** O endereço da aba Auditoria, com os filtros na query. */
export function enderecoDaAuditoria(filtros: FiltrosDaAuditoria): string {
  return `${enderecoDaAba('auditoria')}${filtrosParaEnderecoDaAuditoria(filtros)}`
}

/** O endereço do relatório de tempo de tela, com os filtros na query. */
export function enderecoDoTempoDeTela(filtros: FiltrosDoRelatorio): string {
  return `${TEMPO_DE_TELA}${filtrosParaEndereco(filtros)}`
}

/** Para onde `/` leva: o acervo, ou o painel para quem só vê o painel (sem `decupagem.ver`). */
export function telaInicial(permissoes: readonly string[]): string {
  return !permissoes.includes('decupagem.ver') && permissoes.includes('painel.ver') ? PAINEL : ACERVO
}

/** O endereço de uma aba do painel da diretoria, com os filtros na query. */
export function enderecoDoPainel(aba: AbaDoPainel, filtros: FiltrosDoPainel): string {
  return `${PAINEL}/${aba}${filtrosParaEnderecoDoPainel(filtros)}`
}

/** O endereço do relatório de marcas, com os filtros na query. */
export function enderecoDasMarcas(filtros: FiltrosDeMarcas): string {
  return `${MARCAS}${filtrosParaEndereco(filtros, { tipo: filtros.tipo })}`
}

/** O endereço da busca, com a consulta e os filtros na query. */
export function enderecoDaBusca(consulta: ConsultaDaBusca): string {
  return `/busca${consultaParaEndereco(consulta)}`
}

/** O endereço dos planos parecidos com um plano (o número dele no vídeo), #271. */
export function enderecoDosParecidos(job: string, plano: number): string {
  return `/busca/parecidos?${new URLSearchParams({ job, plano: String(plano) })}`
}

/** O endereço do vídeo, com o instante em segundos (até o milissegundo) e a busca de origem, se houver. */
export function enderecoDoVideo(id: string, t?: number | null, busca?: string | null): string {
  const base = `/video/${encodeURIComponent(id)}`
  const p = new URLSearchParams()
  if (t != null && t > 0) p.set('t', String(Math.round(t * 1000) / 1000))
  if (busca) p.set('busca', busca)
  const query = p.toString()
  return query ? `${base}?${query}` : base
}

function instante(busca: string): number | null {
  const valor = new URLSearchParams(busca).get('t')
  if (valor === null || !/^\d+(\.\d+)?$/.test(valor)) return null
  return Number(valor)
}

export function lerRota(caminho: string, busca = ''): Rota {
  const partes = caminho.split('/').filter(Boolean)
  if (partes.length === 0) return { tipo: 'raiz' }
  if (partes.length === 1 && partes[0] === 'acervo') return { tipo: 'acervo', filtros: filtrosDaBusca(busca) }
  if (partes.length === 2 && partes[0] === 'busca' && partes[1] === 'parecidos') {
    const p = new URLSearchParams(busca)
    const job = p.get('job')
    const plano = p.get('plano')
    return job && plano !== null && /^\d+$/.test(plano) ? { tipo: 'parecidos', job, plano: Number(plano) } : { tipo: 'nao_encontrada' }
  }
  if (partes.length === 1 && partes[0] === 'busca') return { tipo: 'busca', consulta: consultaDaBusca(busca) }
  if (partes.length === 2 && partes[0] === 'relatorios' && partes[1] === 'tempo-de-tela') {
    return { tipo: 'tempo_de_tela', filtros: filtrosDoRelatorio(busca) }
  }
  if (partes.length === 2 && partes[0] === 'relatorios' && partes[1] === 'marcas') {
    return { tipo: 'marcas', filtros: filtrosDeMarcas(busca) }
  }
  if (partes[0] === 'painel' && partes.length <= 2) {
    const aba = abaDoPainel(partes[1])
    if (aba) return { tipo: 'painel', aba, filtros: filtrosDoPainel(busca) }
  }
  if (partes[0] === 'admin' && partes.length <= 2) return { tipo: 'admin', aba: partes[1] ?? null, busca }
  if (partes.length === 1 && partes[0] === 'amostra') return { tipo: 'amostra' }
  if (partes.length === 2 && partes[0] === 'video') {
    try {
      return { tipo: 'video', id: decodeURIComponent(partes[1]), t: instante(busca), busca: new URLSearchParams(busca).get('busca') || null }
    } catch {
      return { tipo: 'nao_encontrada' }
    }
  }
  return { tipo: 'nao_encontrada' }
}

const AVISO = 'mam:navegou'

export function navegar(destino: string, opcoes: { substituir?: boolean } = {}) {
  // Ir ao endereço em que já se está não empilha uma entrada repetida no histórico.
  const repetido = destino === location.pathname + location.search
  if (opcoes.substituir || repetido) history.replaceState(null, '', destino)
  else history.pushState(null, '', destino)
  window.dispatchEvent(new Event(AVISO))
}

/** Clique simples navega sem recarregar; com modificador, o navegador abre noutra aba. */
export function seguir(e: MouseEvent<HTMLAnchorElement>, destino: string) {
  if (e.defaultPrevented || e.button !== 0) return
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
  e.preventDefault()
  navegar(destino)
}

function assinar(aviso: () => void) {
  window.addEventListener('popstate', aviso)
  window.addEventListener(AVISO, aviso)
  return () => {
    window.removeEventListener('popstate', aviso)
    window.removeEventListener(AVISO, aviso)
  }
}

const endereco = () => location.pathname + location.search

export function useRota(): Rota {
  const atual = useSyncExternalStore(assinar, endereco)
  return useMemo(() => {
    const [caminho, busca = ''] = atual.split('?')
    return lerRota(caminho, busca)
  }, [atual])
}
