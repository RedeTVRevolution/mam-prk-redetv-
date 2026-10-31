import { createContext, useContext, useEffect, useRef } from 'react'

/** Um atalho de teclado: a tela declara a tecla, a ação e o grupo. */
export interface Atalho {
  /** O que a lista mostra; com `executar`, é também o `KeyboardEvent.key` que dispara. */
  tecla: string
  acao: string
  grupo: string
  /** Sem `executar`, a linha só informa (o Esc de janelas e menus é do próprio componente). */
  executar?: () => void
}

export interface Registro {
  mostrarAtalhos(): void
  registrar(atalhos: () => Atalho[]): () => void
}

export const Contexto = createContext<Registro | null>(null)

export const GERAIS: Atalho[] = [
  { tecla: '?', acao: 'Mostrar os atalhos desta tela', grupo: 'Geral' },
  { tecla: 'Esc', acao: 'Fechar o que estiver aberto', grupo: 'Geral' },
]

function useRegistro(): Registro {
  const registro = useContext(Contexto)
  if (!registro) throw new Error('Falta o AtalhosProvider.')
  return registro
}

/** A tela declara os atalhos dela enquanto estiver montada. */
export function useAtalhos(atalhos: Atalho[]) {
  const { registrar } = useRegistro()
  const ultimos = useRef(atalhos)
  useEffect(() => {
    ultimos.current = atalhos
  })
  useEffect(() => registrar(() => ultimos.current), [registrar])
}

export function useMostrarAtalhos(): () => void {
  return useRegistro().mostrarAtalhos
}
