import type * as React from 'react'
import { cn } from 'cn'
import { Popover as PopoverPrimitive } from 'radix-ui'

// shadcn/ui: o que flutua fica em `sobreposto`, com canto de 6 px, borda e a sombra única.
export function Popover(props: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

export function PopoverTrigger(props: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

export function PopoverContent({ className, align = 'center', sideOffset = 4, ...props }: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'z-50 w-72 max-w-[calc(100vw-1rem)] origin-(--radix-popover-content-transform-origin) rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-float outline-hidden duration-150 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0',
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}
