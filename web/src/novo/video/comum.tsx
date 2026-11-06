import { IconAlertTriangle } from '@tabler/icons-react'
import { cn } from 'cn'
import type { ComponentProps, ReactNode } from 'react'
import { Button } from '../ui/button.tsx'
import { Kbd } from '../ui/kbd.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'

/** Botão de ícone com dica e nome acessível: todo ícone tem rótulo (MAM_DESIGN_SYSTEM 7). */
export function BotaoDeIcone({
  rotulo,
  atalho,
  ativo,
  className,
  children,
  ...props
}: { rotulo: string; atalho?: string; ativo?: boolean } & ComponentProps<'button'>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={rotulo}
          aria-pressed={ativo}
          className={cn(
            'inline-flex size-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-50',
            ativo && 'bg-selected text-link',
            className,
          )}
          {...props}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>
        {rotulo}
        {atalho && <Kbd>{atalho}</Kbd>}
      </TooltipContent>
    </Tooltip>
  )
}

/** O aviso de falha: a frase, o código para o suporte e, quando houver, o "Tentar de novo". */
export function AvisoDeFalha({
  mensagem,
  codigo,
  aoTentar,
  className,
}: {
  mensagem: ReactNode
  codigo?: string | null
  aoTentar?: () => void
  className?: string
}) {
  return (
    <div role="alert" className={cn('flex items-start gap-2 rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2 text-sm', className)}>
      <IconAlertTriangle size={16} stroke={1.75} className="mt-0.5 shrink-0 text-destructive" aria-hidden />
      <div className="grid min-w-0 gap-1">
        <p className="text-destructive">{mensagem}</p>
        {codigo && <p className="text-xs text-muted-foreground">Código para o suporte: {codigo}</p>}
        {aoTentar && (
          <Button type="button" size="sm" variant="secondary" className="justify-self-start" onClick={aoTentar}>
            Tentar de novo
          </Button>
        )}
      </div>
    </div>
  )
}
