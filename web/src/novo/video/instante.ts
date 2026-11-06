import { useSyncExternalStore } from 'react'

/**
 * O instante do vídeo, fora do estado do React: o `timeupdate` chega 4 vezes por segundo, e cada
 * parte da tela assina só o que lê dele (o relógio, o cursor, o "Agora", o item atual da lista).
 */
export interface Instante {
  ms: () => number
  definir: (ms: number) => void
  assinar: (aviso: () => void) => () => void
}

export function criarInstante(inicial = 0): Instante {
  let atual = inicial
  const avisos = new Set<() => void>()
  return {
    ms: () => atual,
    definir: (ms) => {
      if (ms === atual) return
      atual = ms
      for (const aviso of avisos) aviso()
    },
    assinar: (aviso) => {
      avisos.add(aviso)
      return () => {
        avisos.delete(aviso)
      }
    },
  }
}

/** O que a parte lê do instante. Ela só renderiza de novo quando o valor muda: devolva um primitivo. */
export function useNoInstante<T extends string | number | boolean | null>(instante: Instante, ler: (ms: number) => T): T {
  return useSyncExternalStore(instante.assinar, () => ler(instante.ms()))
}
