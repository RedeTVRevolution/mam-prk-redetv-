import { IconDots, IconDownload, IconLink, IconPlayerPlay, IconRefresh, IconTrash, type Icon } from '@tabler/icons-react'
import { cn } from 'cn'
import { useState, type MouseEvent, type ReactNode } from 'react'
import { fraseDaFalha } from '../../falhas.ts'
import { dataDeExibicao, dataEHora, type Job } from '../../jobs.ts'
import { tempo } from '../../linhaDoTempo.ts'
import { enderecoDoVideo, navegar, seguir } from '../../rotas.ts'
import { estadoDoVideo, TALLY } from '../comum/estado.ts'
import { podeIrParaALixeira, podeReprocessar } from '../comum/regras.ts'
import { SeloDeEstado } from '../comum/SeloDeEstado.tsx'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '../ui/dropdown-menu.tsx'
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip.tsx'
import { urlSegura } from '../../urlSegura.ts'

export type Acao = 'copiar' | 'baixar' | 'reprocessar' | 'lixeira'
export interface PropsDoVideo {
  job: Job
  indice: number
  permissoes: readonly string[]
  aoAcao: (acao: Acao, job: Job) => void
}

/** A tela do vídeo também explica a falha, então o concluído e o que falhou abrem; o resto não. */
const abre = (job: Job) => job.estado === 'concluido' || job.estado === 'falhou'

/** O clique em qualquer lugar do cartão abre o vídeo, menos nos controles e nos menus (que chegam pelo portal). */
function aoClicar(job: Job) {
  return (e: MouseEvent<HTMLElement>) => {
    const alvo = e.target as Element
    if (!abre(job) || e.defaultPrevented || !e.currentTarget.contains(alvo) || alvo.closest('a, button, [role=menu]')) return
    navegar(enderecoDoVideo(job.id))
  }
}

/** O quadro de capa 16:9, com o tally do estado (só quando não está concluído) e a duração. */
function Miniatura({ job }: { job: Job }) {
  const [falhou, setFalhou] = useState<string | null>(null)
  const e = estadoDoVideo(job)
  const capa = urlSegura(job.capa_url)
  const url = capa && capa !== falhou ? capa : null
  const quadro = (
    <span className="relative block aspect-video w-full overflow-hidden bg-canvas">
      {e.tom !== 'ok' && <span aria-hidden className={cn('absolute inset-x-0 top-0 z-10 h-[3px]', TALLY[e.tom])} />}
      {url && <img src={url} alt="" loading="lazy" decoding="async" onError={() => setFalhou(url)} className="absolute inset-0 size-full object-cover" />}
      {job.duracao_s != null && (
        <span className="absolute right-1 bottom-1 rounded-xs bg-black/75 px-1 font-mono text-2xs text-white tabular-nums">{tempo(job.duracao_s * 1000)}</span>
      )}
    </span>
  )
  // O nome é o link que entra no Tab; a imagem é o mesmo destino, só para o ponteiro.
  return abre(job) ? (
    <a href={enderecoDoVideo(job.id)} onClick={(ev) => seguir(ev, enderecoDoVideo(job.id))} tabIndex={-1} aria-hidden className="block">
      {quadro}
    </a>
  ) : (
    quadro
  )
}

function Nome({ job, indice }: { job: Job; indice: number }) {
  const endereco = enderecoDoVideo(job.id)
  return abre(job) ? (
    <a href={endereco} onClick={(e) => seguir(e, endereco)} data-foco={indice} title={job.nome} className="block truncate rounded-xs hover:underline">
      {job.nome}
    </a>
  ) : (
    <span data-foco={indice} tabIndex={0} title={job.nome} className="block truncate rounded-xs">
      {job.nome}
    </span>
  )
}

/** A frase da falha; o código para o suporte fica na dica. */
function FraseDaFalha({ codigo }: { codigo: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="min-w-0 truncate text-xs text-destructive">{fraseDaFalha(codigo)}</span>
      </TooltipTrigger>
      <TooltipContent>Código para o suporte: {codigo}</TooltipContent>
    </Tooltip>
  )
}

function MenuDoVideo({ job, permissoes, aoAcao }: Omit<PropsDoVideo, 'indice'>) {
  const itens: { rotulo: string; Icone: Icon; acao: () => void }[] = []
  if (abre(job)) {
    itens.push({ rotulo: 'Abrir o vídeo', Icone: IconPlayerPlay, acao: () => navegar(enderecoDoVideo(job.id)) })
    itens.push({ rotulo: 'Copiar o link', Icone: IconLink, acao: () => aoAcao('copiar', job) })
  }
  if (job.estado === 'concluido') itens.push({ rotulo: 'Baixar a decupagem', Icone: IconDownload, acao: () => aoAcao('baixar', job) })
  if (podeReprocessar(job, permissoes)) itens.push({ rotulo: 'Reprocessar…', Icone: IconRefresh, acao: () => aoAcao('reprocessar', job) })
  const lixeira = podeIrParaALixeira(job, permissoes)
  if (!itens.length && !lixeira) return null
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Ações de ${job.nome}`}
          className="flex size-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground data-[state=open]:bg-accent"
        >
          <IconDots size={16} aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {itens.map((i) => (
          <DropdownMenuItem key={i.rotulo} onSelect={i.acao}>
            <i.Icone stroke={1.75} aria-hidden /> {i.rotulo}
          </DropdownMenuItem>
        ))}
        {lixeira && (
          <>
            {itens.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem onSelect={() => aoAcao('lixeira', job)} className="text-destructive focus:bg-destructive/12 focus:text-destructive">
              <IconTrash stroke={1.75} aria-hidden /> Mandar para a lixeira…
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

const quem = (job: Job) => job.enviado_por?.nome ?? '—'
const exibido = (job: Job) => (job.data_exibicao ? `exibido em ${dataDeExibicao(job.data_exibicao)}` : 'sem data de exibição')

export function Cartao({ job, indice, permissoes, aoAcao }: PropsDoVideo) {
  return (
    <article
      onClick={aoClicar(job)}
      className={cn('flex min-w-0 flex-col overflow-hidden rounded-sm bg-card ring-1 ring-transparent transition-shadow hover:ring-strong', abre(job) && 'cursor-pointer')}
    >
      <Miniatura job={job} />
      <div className="flex items-start gap-1 pt-2 pl-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium">
            <Nome job={job} indice={indice} />
          </h3>
          <p className="truncate text-xs text-muted-foreground">
            {job.programa ?? 'Sem programa'}, {exibido(job)}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            Enviado em {dataEHora(job.criado_em)} por {quem(job)}
          </p>
        </div>
        <span className="pr-1">
          <MenuDoVideo job={job} permissoes={permissoes} aoAcao={aoAcao} />
        </span>
      </div>
      <div className="flex h-8 min-w-0 items-center gap-2 px-2">
        <SeloDeEstado job={job} />
        {job.codigo_falha && <FraseDaFalha codigo={job.codigo_falha} />}
      </div>
    </article>
  )
}

export function Linha({ job, indice, permissoes, aoAcao }: PropsDoVideo) {
  return (
    <div onClick={aoClicar(job)} className={cn('flex h-20 items-center gap-3 border-b px-3 hover:bg-card', abre(job) && 'cursor-pointer')}>
      <div className="w-28 shrink-0 overflow-hidden rounded-xs">
        <Miniatura job={job} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">
          <Nome job={job} indice={indice} />
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {job.programa ?? 'Sem programa'}, {exibido(job)}
        </p>
        {job.codigo_falha ? (
          <p className="flex min-w-0">
            <FraseDaFalha codigo={job.codigo_falha} />
          </p>
        ) : (
          <p className="truncate text-xs text-muted-foreground">
            Enviado em {dataEHora(job.criado_em)} por {quem(job)}
          </p>
        )}
      </div>
      <SeloDeEstado job={job} className="hidden sm:inline-flex" />
      <SeloDeEstado job={job} compacto className="sm:hidden" />
      <MenuDoVideo job={job} permissoes={permissoes} aoAcao={aoAcao} />
    </div>
  )
}

/** O lugar de um vídeo cuja página ainda não chegou (ou já saiu da memória). Parado, sem cintilar. */
export function Esqueleto({ lista }: { lista: boolean }): ReactNode {
  return lista ? (
    <div data-esqueleto className="flex h-20 items-center gap-3 border-b px-3" aria-hidden>
      <div className="aspect-video w-28 shrink-0 rounded-xs bg-card" />
      <div className="grid flex-1 gap-2">
        <div className="h-3 w-1/2 rounded-xs bg-card" />
        <div className="h-3 w-3/4 rounded-xs bg-card" />
      </div>
    </div>
  ) : (
    <div data-esqueleto className="flex flex-col overflow-hidden rounded-sm bg-card" aria-hidden>
      <div className="aspect-video bg-secondary" />
      {/* A mesma altura do cartão: 58 px do texto e 32 do selo. */}
      <div className="grid h-[58px] content-start gap-2 px-2 pt-2">
        <div className="h-3 w-3/4 rounded-xs bg-secondary" />
        <div className="h-3 w-1/2 rounded-xs bg-secondary" />
      </div>
      <div className="h-8" />
    </div>
  )
}
