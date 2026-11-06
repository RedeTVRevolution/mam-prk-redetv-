import { IconAlertTriangle } from '@tabler/icons-react'
import { cn } from 'cn'
import { Button } from '../ui/button.tsx'

/** O alerta de erro: a frase com a ação, o código para o suporte e, se houver, o botão de tentar de novo. */
export function Falha({ mensagem, codigo, aoTentar, className }: { mensagem: string; codigo?: string | null; aoTentar?: () => void; className?: string }) {
  return (
    <div role="alert" className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2', className)}>
      <IconAlertTriangle size={16} stroke={1.75} className="shrink-0 text-destructive" aria-hidden />
      <span className="min-w-0 flex-1 text-destructive">{mensagem}</span>
      {codigo && <span className="text-xs text-muted-foreground">Código para o suporte: {codigo}</span>}
      {aoTentar && (
        <Button type="button" size="sm" variant="secondary" onClick={aoTentar}>
          Tentar de novo
        </Button>
      )}
    </div>
  )
}
