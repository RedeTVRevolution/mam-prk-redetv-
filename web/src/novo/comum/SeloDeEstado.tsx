import { cn } from 'cn'
import type { Job } from '../../jobs.ts'
import { estadoDoVideo, TONS } from './estado.ts'

export function SeloDeEstado({ job, compacto, className }: { job: Job; compacto?: boolean; className?: string }) {
  const e = estadoDoVideo(job)
  return (
    <span className={cn('inline-flex h-5 shrink-0 items-center gap-1 rounded-xs px-1.5 text-xs font-medium whitespace-nowrap', TONS[e.tom], className)}>
      <e.Icone size={12} stroke={2} className={cn(e.gira && 'animate-spin motion-reduce:animate-none')} aria-hidden />
      {compacto ? <span className="sr-only">{e.rotulo}</span> : e.rotulo}
    </span>
  )
}
