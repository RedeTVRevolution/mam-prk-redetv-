import * as React from 'react'
import { cn } from 'cn'
import { Slot } from 'radix-ui'
import { SidebarContext, useSidebar } from './sidebar-contexto.ts'
import { Sheet, SheetContent } from './sheet.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip.tsx'

// O `Sidebar` do shadcn/ui em `collapsible="icon"`, só com as peças que a casca usa. Abaixo de
// 768 px vira gaveta. Aberto ou fechado fica num cookie, lido na próxima carga.
const COOKIE = 'sidebar_state'
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365
const CONSULTA_MOVEL = '(max-width: 767px)'

function assinarMovel(aviso: () => void) {
  const consulta = window.matchMedia(CONSULTA_MOVEL)
  consulta.addEventListener('change', aviso)
  return () => consulta.removeEventListener('change', aviso)
}

export function SidebarProvider({ className, style, children, ...props }: React.ComponentProps<'div'>) {
  const movel = React.useSyncExternalStore(assinarMovel, () => window.matchMedia(CONSULTA_MOVEL).matches)
  const [abertoNoMovel, setAbertoNoMovel] = React.useState(false)
  // Começa fechado (o design system), salvo se a pessoa o deixou aberto.
  const [aberto, setAberto] = React.useState(() => document.cookie.split('; ').includes(`${COOKIE}=true`))

  const alternar = React.useCallback(() => {
    if (movel) return setAbertoNoMovel((a) => !a)
    setAberto((a) => {
      document.cookie = `${COOKIE}=${!a}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`
      return !a
    })
  }, [movel])

  const valor = React.useMemo(
    () => ({ aberto, movel, abertoNoMovel, setAbertoNoMovel, alternar }),
    [aberto, movel, abertoNoMovel, alternar],
  )

  return (
    <SidebarContext.Provider value={valor}>
      <div
        data-slot="sidebar-wrapper"
        style={{ '--sidebar-width': '208px', '--sidebar-width-icon': '48px', ...style } as React.CSSProperties}
        className={cn('group/sidebar-wrapper flex w-full', className)}
        {...props}
      >
        {children}
      </div>
    </SidebarContext.Provider>
  )
}

/** O trilho. No desktop fica preso à esquerda, de `top` até o fim da janela. */
export function Sidebar({ className, children, ...props }: React.ComponentProps<'div'>) {
  const { aberto, movel, abertoNoMovel, setAbertoNoMovel } = useSidebar()

  if (movel) {
    return (
      <Sheet open={abertoNoMovel} onOpenChange={setAbertoNoMovel}>
        <SheetContent titulo="Menu" data-sidebar="sidebar" className="w-(--sidebar-width) bg-sidebar p-0 text-sidebar-foreground">
          <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        </SheetContent>
      </Sheet>
    )
  }

  return (
    <div
      className="group peer hidden shrink-0 text-sidebar-foreground md:block"
      data-state={aberto ? 'expanded' : 'collapsed'}
      data-collapsible={aberto ? '' : 'icon'}
      data-slot="sidebar"
    >
      {/* Ocupa no fluxo a largura do trilho fixo. */}
      <div className="w-(--sidebar-width) transition-[width] duration-150 ease-out group-data-[collapsible=icon]:w-(--sidebar-width-icon)" />
      <div
        className={cn(
          'fixed bottom-0 left-0 z-10 hidden w-(--sidebar-width) border-r transition-[width] duration-150 ease-out group-data-[collapsible=icon]:w-(--sidebar-width-icon) md:flex',
          className,
        )}
        {...props}
      >
        <div data-sidebar="sidebar" className="flex size-full min-h-0 flex-col bg-sidebar">
          {children}
        </div>
      </div>
    </div>
  )
}

export function SidebarContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-sidebar="content" className={cn('flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto', className)} {...props} />
}

export function SidebarFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-sidebar="footer" className={cn('flex shrink-0 flex-col p-1', className)} {...props} />
}

export function SidebarSeparator({ className }: { className?: string }) {
  return <div aria-hidden className={cn('mx-2 h-px shrink-0 bg-sidebar-border', className)} />
}

export function SidebarMenu({ className, ...props }: React.ComponentProps<'ul'>) {
  return <ul data-sidebar="menu" className={cn('flex w-full min-w-0 flex-col gap-0.5', className)} {...props} />
}

export function SidebarMenuItem({ className, ...props }: React.ComponentProps<'li'>) {
  return <li data-sidebar="menu-item" className={cn('relative', className)} {...props} />
}

/** Item de 40 px com ícone de 20; fechado, vira um quadrado de 40 com o rótulo na dica. */
export function SidebarMenuButton({
  asChild = false,
  isActive = false,
  dica,
  className,
  ...props
}: React.ComponentProps<'button'> & { asChild?: boolean; isActive?: boolean; dica?: React.ReactNode }) {
  const Comp = asChild ? Slot.Root : 'button'
  const { aberto, movel } = useSidebar()
  const botao = (
    <Comp
      data-sidebar="menu-button"
      data-active={isActive}
      className={cn(
        'relative flex h-10 w-full items-center gap-3 overflow-hidden rounded-sm px-3 text-left text-sm text-sidebar-foreground transition-[width,padding] hover:bg-sidebar-accent group-data-[collapsible=icon]:size-10! group-data-[collapsible=icon]:p-2.5! [&>span:last-child]:truncate [&_svg]:size-5 [&_svg]:shrink-0',
        className,
      )}
      {...props}
    />
  )
  if (!dica) return botao
  return (
    <Tooltip>
      <TooltipTrigger asChild>{botao}</TooltipTrigger>
      <TooltipContent side="right" hidden={aberto || movel}>
        {dica}
      </TooltipContent>
    </Tooltip>
  )
}
