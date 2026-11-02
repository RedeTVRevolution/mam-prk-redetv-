import { createContext, useContext, useEffect, useRef } from 'react'

/** Um atalho de teclado: a tela declara a tecla, a ação e o grupo. */
export interface Atalho {
  /** O que a lista mostra; com `executar`, é também o `KeyboardEvent.key` que dispara. */
  tecla: string
  acao: string
  grupo: string
  /** Sem `executar`, a linha só informa (o Esc de janelas e menus é do próprio componente). */
  executar?: (e: KeyboardEvent) => void
  /** Quando a linha agrupa várias teclas (ou exige `Shift`), diz se o evento é dela. */
  casa?: (e: KeyboardEvent) => boolean
  /** O atalho exige o Ctrl; sem isto, o Ctrl desliga o atalho (é o do navegador). */
  ctrl?: boolean
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

/** Se o foco está num campo de texto: aí nenhum atalho age. */
export function emCampoDeTexto(alvo: EventTarget | null): boolean {
  if (!(alvo instanceof HTMLElement)) return false
  return (
    alvo.isContentEditable ||
    alvo.getAttribute('contenteditable') === 'true' ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(alvo.tagName)
  )
}
