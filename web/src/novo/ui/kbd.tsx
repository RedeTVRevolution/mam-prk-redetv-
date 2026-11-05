import type * as React from 'react'
import { cn } from 'cn'

export function Kbd({ className, ...props }: React.ComponentProps<'kbd'>) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        'pointer-events-none inline-flex h-5 w-fit min-w-5 items-center justify-center gap-1 rounded-sm border border-strong bg-card px-1 font-sans text-xs font-medium text-muted-foreground select-none',
        className,
      )}
      {...props}
    />
  )
}
