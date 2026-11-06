import type * as React from 'react'
import { IconSearch } from '@tabler/icons-react'
import { Command as CommandPrimitive } from 'cmdk'
import { cn } from 'cn'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './dialog.tsx'

// shadcn/ui (cmdk), com os cantos e as cores do design system.
export function Command({ className, ...props }: React.ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn('flex size-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground', className)}
      {...props}
    />
  )
}

export function CommandDialog({
  titulo,
  descricao,
  children,
  className,
  ...props
}: React.ComponentProps<typeof Dialog> & { titulo: string; descricao: string; className?: string }) {
  return (
    <Dialog {...props}>
      <DialogContent mostrarFechar={false} className={cn('top-[15dvh] translate-y-0 gap-0 p-0', className)}>
        <DialogTitle className="sr-only">{titulo}</DialogTitle>
        <DialogDescription className="sr-only">{descricao}</DialogDescription>
        <CommandPrimitive data-slot="command" label={titulo} className="flex min-h-0 min-w-0 flex-col bg-popover text-popover-foreground">
          {children}
        </CommandPrimitive>
      </DialogContent>
    </Dialog>
  )
}

export function CommandInput({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b px-3">
      <IconSearch size={16} stroke={1.75} className="shrink-0 text-muted-foreground" aria-hidden />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn('h-full w-full min-w-0 bg-transparent text-sm outline-hidden placeholder:text-muted-foreground', className)}
        {...props}
      />
    </div>
  )
}

export function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn('max-h-[min(420px,60dvh)] scroll-py-1 overflow-x-hidden overflow-y-auto p-1', className)}
      {...props}
    />
  )
}

export function CommandEmpty({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Empty>) {
  return <CommandPrimitive.Empty className={cn('px-2 py-6 text-center text-sm text-muted-foreground', className)} {...props} />
}

export function CommandGroup({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      className={cn(
        'overflow-hidden p-1 **:[[cmdk-group-heading]]:px-2 **:[[cmdk-group-heading]]:py-1 **:[[cmdk-group-heading]]:text-xs **:[[cmdk-group-heading]]:font-medium **:[[cmdk-group-heading]]:text-muted-foreground',
        className,
      )}
      {...props}
    />
  )
}

export function CommandItem({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      className={cn(
        "group/item relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 data-selected:bg-selected [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  )
}

export function CommandShortcut({ className, ...props }: React.ComponentProps<'span'>) {
  return <span className={cn('ml-auto text-xs tracking-widest text-muted-foreground', className)} {...props} />
}
