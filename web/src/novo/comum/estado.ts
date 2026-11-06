import { IconAlertTriangle, IconCircleCheck, IconCircleOff, IconClock, IconLoader2, type Icon } from '@tabler/icons-react'
import { ESTADOS_DO_JOB, FINALIZANDO } from '../../cores.ts'
import { finalizando, type Job } from '../../jobs.ts'

export type Tom = 'ok' | 'andamento' | 'falhou' | 'inerte'

// A cor do estado no texto, sobre a mesma cor a 12% (MAM_DESIGN_SYSTEM 2.3); o ícone e a palavra vão sempre junto.
export const TONS: Record<Tom, string> = {
  ok: 'text-ok bg-ok/12',
  andamento: 'text-andamento bg-andamento/12',
  falhou: 'text-destructive bg-destructive/12',
  inerte: 'text-muted-foreground bg-muted-foreground/12',
}
export const TALLY: Record<Tom, string> = { ok: 'bg-ok', andamento: 'bg-andamento', falhou: 'bg-destructive', inerte: 'bg-muted-foreground' }

const POR_ESTADO: Record<string, { tom: Tom; Icone: Icon; gira?: boolean }> = {
  aguardando_upload: { tom: 'andamento', Icone: IconClock },
  validando: { tom: 'andamento', Icone: IconClock },
  analisando: { tom: 'andamento', Icone: IconLoader2, gira: true },
  concluido: { tom: 'ok', Icone: IconCircleCheck },
  falhou: { tom: 'falhou', Icone: IconAlertTriangle },
  cancelado: { tom: 'inerte', Icone: IconCircleOff },
}

/** O estado do vídeo como a tela mostra: o `concluido` com etapas ainda rodando é "Finalizando". */
export function estadoDoVideo(job: Job) {
  if (finalizando(job)) return { tom: 'andamento' as Tom, Icone: IconLoader2, gira: false, rotulo: FINALIZANDO.rotulo }
  const e = POR_ESTADO[job.estado] ?? { tom: 'inerte' as Tom, Icone: IconCircleOff }
  const rotulo = (ESTADOS_DO_JOB as Record<string, { rotulo: string }>)[job.estado]?.rotulo ?? job.estado
  return { ...e, gira: Boolean(e.gira), rotulo }
}
