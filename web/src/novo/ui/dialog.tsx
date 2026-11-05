import type * as React from 'react'
import { IconX } from '@tabler/icons-react'
import { cn } from 'cn'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { useDevolverFoco } from '../foco.ts'
import { Button } from './button.tsx'

// shadcn/ui: fundo chapado a 60%, canto de 6 px, borda e a sombra única do que flutua.
export function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

export function DialogContent({
  className,
  children,
  mostrarFechar = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { mostrarFechar?: boolean }) {
  const foco = useDevolverFoco(props)
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 duration-150 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          'fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100dvh-2rem)] w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-md border bg-popover p-4 text-sm text-popover-foreground shadow-float duration-150 outline-none sm:max-w-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0',
          className,
        )}
        {...props}
        {...foco}
      >
        {children}
        {mostrarFechar && (
          <DialogPrimitive.Close asChild>
            <Button variant="ghost" size="icon-sm" className="absolute top-2 right-2" aria-label="Fechar">
              <IconX stroke={1.75} />
            </Button>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title data-slot="dialog-title" className={cn('text-lg font-semibold', className)} {...props} />
}

export function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description data-slot="dialog-description" className={cn('text-sm text-muted-foreground', className)} {...props} />
  )
}
