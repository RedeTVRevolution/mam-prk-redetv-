import { createContext, useContext } from 'react'

export interface ContextoDoSidebar {
  aberto: boolean
  movel: boolean
  abertoNoMovel: boolean
  setAbertoNoMovel: (aberto: boolean) => void
  alternar: () => void
}

export const SidebarContext = createContext<ContextoDoSidebar | null>(null)

export function useSidebar(): ContextoDoSidebar {
  const contexto = useContext(SidebarContext)
  if (!contexto) throw new Error('Falta o SidebarProvider.')
  return contexto
}
