import { Anchor, type AnchorProps } from '@mantine/core'
import type { ReactNode } from 'react'
import { seguir } from './rotas.ts'

/** `<a href>` de verdade: Ctrl+clique, botão do meio e "abrir em nova aba" seguem o navegador. */
export function Link({
  para,
  children,
  ...resto
}: { para: string; children: ReactNode } & Omit<AnchorProps, 'href' | 'onClick'>) {
  return (
    <Anchor href={para} onClick={(e) => seguir(e, para)} {...resto}>
      {children}
    </Anchor>
  )
}
