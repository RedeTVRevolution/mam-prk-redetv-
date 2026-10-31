import { useMemo, useSyncExternalStore, type MouseEvent } from 'react'

// Rotas com endereço sobre a History API, sem biblioteca (princípio 9 de docs/design/principios.md).

export type Rota =
  | { tipo: 'raiz' }
  | { tipo: 'acervo' }
  | { tipo: 'video'; id: string; t: number | null }
  | { tipo: 'amostra' }
  | { tipo: 'nao_encontrada' }

export const ACERVO = '/acervo'

/** O endereço do vídeo, com o instante em segundos inteiros quando houver. */
export function enderecoDoVideo(id: string, t?: number | null): string {
  const base = `/video/${encodeURIComponent(id)}`
  return t != null && t > 0 ? `${base}?t=${Math.floor(t)}` : base
}

function instante(busca: string): number | null {
  const valor = new URLSearchParams(busca).get('t')
  if (valor === null || !/^\d+(\.\d+)?$/.test(valor)) return null
  return Math.floor(Number(valor))
}

export function lerRota(caminho: string, busca = ''): Rota {
  const partes = caminho.split('/').filter(Boolean)
  if (partes.length === 0) return { tipo: 'raiz' }
  if (partes.length === 1 && partes[0] === 'acervo') return { tipo: 'acervo' }
  if (partes.length === 1 && partes[0] === 'amostra') return { tipo: 'amostra' }
  if (partes.length === 2 && partes[0] === 'video') {
    try {
      return { tipo: 'video', id: decodeURIComponent(partes[1]), t: instante(busca) }
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
