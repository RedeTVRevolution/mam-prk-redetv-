import { IconAlertTriangle, IconCircleCheck, IconLoader2, type Icon } from '@tabler/icons-react'
import { cn } from 'cn'
import type { ReactNode, RefObject } from 'react'
import { Button } from '../ui/button.tsx'
import { iniciais } from './iniciais.ts'

/** As peças que as abas da administração dividem. Os campos são nativos: o `<select>` vale como o Select do shadcn aqui. */
export const CAMPO =
  'h-8 min-w-0 rounded-sm border border-strong bg-input px-2 text-sm text-foreground outline-none placeholder:text-subtle focus:border-primary disabled:opacity-50 [color-scheme:dark]'

export const TABELA = 'w-full table-fixed border-collapse text-sm'
export const CABECALHO = 'h-8 border-b px-2 text-left text-xs font-medium text-muted-foreground'
export const CELULA = 'h-8 border-b px-2 py-1 align-middle'
export const LINHA_CLICAVEL = 'cursor-pointer hover:bg-card aria-expanded:bg-selected'

/** A área que rola, por aba: o cabeçalho da Administração fica parado em cima. */
export function Aba({ ref, children }: { ref?: RefObject<HTMLDivElement | null>; children: ReactNode }) {
  return (
    <div ref={ref} className="relative min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto grid max-w-[1600px] content-start gap-3 p-3 md:p-4">{children}</div>
    </div>
  )
}

/** Título da aba, contagem e ações; as ações descem para a linha de baixo no celular. */
export function TopoDaAba({ titulo, contagem, children }: { titulo: string; contagem?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <h2 className="text-lg font-semibold">{titulo}</h2>
      {contagem !== undefined && <span className="text-sm text-muted-foreground">{contagem}</span>}
      {children && <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">{children}</div>}
    </div>
  )
}

/** O estado vazio desenhado: o ícone da aba num círculo, a frase e, se houver, a ação. */
export function Vazio({ Icone, children, acao }: { Icone: Icon; children: ReactNode; acao?: ReactNode }) {
  return (
    <div className="grid justify-items-center gap-3 rounded-sm border border-dashed border-strong px-4 py-10 text-center">
      <span className="grid size-12 place-items-center rounded-full bg-card text-subtle">
        <Icone size={24} stroke={1.5} aria-hidden />
      </span>
      <p className="max-w-sm text-sm text-muted-foreground">{children}</p>
      {acao}
    </div>
  )
}

export function Carregando({ rotulo }: { rotulo: string }) {
  return (
    <div role="status" aria-label={rotulo} className="grid place-items-center py-10 text-muted-foreground">
      <IconLoader2 size={20} stroke={1.75} className="animate-spin" aria-hidden />
    </div>
  )
}

/** O erro do sistema visual: a frase com a ação, o código para o suporte e, se houver, "Tentar de novo". */
export function Erro({ mensagem, codigo, aoTentar }: { mensagem: string; codigo: string; aoTentar?: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-sm border border-destructive/40 bg-destructive/12 px-3 py-2">
      <IconAlertTriangle size={16} stroke={1.75} className="shrink-0 text-destructive" aria-hidden />
      <span>{mensagem}</span>
      <span className="text-xs text-muted-foreground">Código para o suporte: {codigo}</span>
      {aoTentar && (
        <Button type="button" size="sm" variant="secondary" onClick={aoTentar}>
          Tentar de novo
        </Button>
      )}
    </div>
  )
}

/** O aviso do que acabou de dar certo, na própria tela. */
export function Aviso({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <p role="status" className="flex items-center gap-2 rounded-sm border border-ok/40 bg-ok/12 px-3 py-2">
      <IconCircleCheck size={16} stroke={1.75} className="shrink-0 text-ok" aria-hidden />
      {children}
    </p>
  )
}

const TOM = {
  ok: 'bg-ok/12 text-ok',
  andamento: 'bg-andamento/12 text-andamento',
  falha: 'bg-destructive/12 text-destructive',
  neutro: 'bg-input text-muted-foreground',
} as const

/** O selo de estado: ícone e palavra na cor do estado, sobre a mesma cor a 12%. */
export function Selo({ tom, Icone, children }: { tom: keyof typeof TOM; Icone?: Icon; children: ReactNode }) {
  return (
    <span className={cn('inline-flex h-5 shrink-0 items-center gap-1 rounded-xs px-1.5 text-xs whitespace-nowrap', TOM[tom])}>
      {Icone && <Icone size={12} stroke={2} aria-hidden />}
      {children}
    </span>
  )
}

export function Iniciais({ nome, className }: { nome: string; className?: string }) {
  return (
    <span aria-hidden className={cn('grid size-6 shrink-0 place-items-center rounded-full bg-input text-2xs font-semibold text-muted-foreground', className)}>
      {iniciais(nome)}
    </span>
  )
}

/** As linhas vazias que guardam o lugar das que não estão no DOM. */
export function Folga({ altura, colunas }: { altura: number; colunas: number }) {
  if (altura <= 0) return null
  return (
    <tbody aria-hidden>
      <tr style={{ height: altura }}>
        <td colSpan={colunas} className="p-0" />
      </tr>
    </tbody>
  )
}
