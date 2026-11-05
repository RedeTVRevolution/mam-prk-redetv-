import type * as React from 'react'
import { cn } from 'cn'
import { Dialog as SheetPrimitive } from 'radix-ui'
import { useDevolverFoco } from '../foco.ts'

// shadcn/ui: a gaveta lateral (hoje, o menu no celular). Fundo chapado e a sombra única do que flutua.
export function Sheet(props: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />
}

export function SheetContent({
  className,
  children,
  titulo,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & { titulo: string }) {
  const foco = useDevolverFoco(props)
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        aria-describedby={undefined}
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex h-full w-3/4 flex-col border-r bg-popover text-sm text-popover-foreground shadow-float duration-150 sm:max-w-sm data-open:animate-in data-open:slide-in-from-left-10 data-closed:animate-out data-closed:slide-out-to-left-10',
          className,
        )}
        {...props}
        {...foco}
      >
        <SheetPrimitive.Title className="sr-only">{titulo}</SheetPrimitive.Title>
        {children}
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  )
}
