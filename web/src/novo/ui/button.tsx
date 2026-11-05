import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from 'cn'
import { Slot } from 'radix-ui'

// shadcn/ui, ajustado ao docs/design/MAM_DESIGN_SYSTEM.md: canto de 4 px, o anel de foco é o
// contorno global do index.css, e o perigo é contornado (o branco sobre o vermelho fica abaixo do AA).
const variantes = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-sm border border-transparent text-sm font-medium whitespace-nowrap transition-colors select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-accent',
        ghost: 'text-muted-foreground hover:bg-accent hover:text-foreground',
        destructive: 'border-destructive text-destructive hover:bg-destructive/12',
      },
      size: {
        default: 'h-8 px-3',
        sm: 'h-7 px-2',
        lg: 'h-10 px-4',
        'icon-sm': 'size-7',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof variantes> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'button'
  return <Comp data-slot="button" className={cn(variantes({ variant, size, className }))} {...props} />
}
