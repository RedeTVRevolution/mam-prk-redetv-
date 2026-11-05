import { useRef } from 'react'

/*
 * O Radix só devolve o foco ao próprio Trigger. Aqui os diálogos e gavetas abrem
 * por estado, muitas vezes de um item de menu que some, e o foco caía no body.
 * Guarda-se quem tinha o foco ao abrir; se era um item de menu (ou ninguém),
 * vale o último controle tocado ou focado fora de um menu, que é o botão que abriu
 * o menu. O pointerdown conta porque o Radix impede o foco no clique do botão do menu.
 */
let ultimoForaDeMenu: HTMLElement | null = null
const lembrar = (e: Event) => {
  const el = (e.target as Element).closest?.<HTMLElement>('button, a[href], input, select, textarea, [tabindex]')
  if (el && !el.closest('[role=menu]')) ultimoForaDeMenu = el
}
document.addEventListener('focusin', lembrar)
document.addEventListener('pointerdown', lembrar, true)

type Eventos = { onOpenAutoFocus?: (e: Event) => void; onCloseAutoFocus?: (e: Event) => void }

/** Para o Content de Dialog e Sheet: espalhe o retorno depois das props. */
export function useDevolverFoco({ onOpenAutoFocus, onCloseAutoFocus }: Eventos): Required<Eventos> {
  const origem = useRef<HTMLElement | null>(null)
  return {
    onOpenAutoFocus: (e) => {
      const ativo = document.activeElement as HTMLElement | null
      origem.current = ativo && ativo !== document.body && !ativo.closest('[role=menu]') ? ativo : ultimoForaDeMenu
      onOpenAutoFocus?.(e)
    },
    onCloseAutoFocus: (e) => {
      onCloseAutoFocus?.(e)
      const el = origem.current
      if (e.defaultPrevented || !el?.isConnected) return
      e.preventDefault()
      el.focus()
    },
  }
}
