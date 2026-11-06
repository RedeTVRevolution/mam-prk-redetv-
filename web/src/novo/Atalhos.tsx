import { IconKeyboard } from '@tabler/icons-react'
import type { ReactNode } from 'react'
import { Contexto, useRegistroDeAtalhos } from '../atalhos.ts'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog.tsx'
import { Kbd } from './ui/kbd.tsx'

/** O registro de atalhos (`atalhos.ts`), com a lista no diálogo. */
export function AtalhosProvider({ children }: { children: ReactNode }) {
  const { valor, aberto, setAberto, grupos } = useRegistroDeAtalhos()
  return (
    <Contexto.Provider value={valor}>
      {children}
      <Dialog open={aberto} onOpenChange={setAberto}>
        <DialogContent className="sm:max-w-xl">
          <DialogTitle className="flex items-center gap-2">
            <IconKeyboard size={20} stroke={1.75} className="text-muted-foreground" aria-hidden /> Atalhos de teclado
          </DialogTitle>
          <DialogDescription className="sr-only">Os atalhos desta tela</DialogDescription>
          <div className="grid gap-6 sm:grid-cols-2">
            {[...grupos].map(([grupo, atalhos]) => (
              <section key={grupo} aria-label={grupo}>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{grupo}</h3>
                <dl className="grid gap-1">
                  {atalhos.map((a) => (
                    <div key={a.tecla + a.acao} className="flex items-center justify-between gap-3">
                      <dt>{a.acao}</dt>
                      <dd className="flex shrink-0 gap-1">
                        {a.tecla.split(' ').map((t) => (
                          <Kbd key={t}>{t}</Kbd>
                        ))}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </Contexto.Provider>
  )
}
