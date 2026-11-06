import { IconCalendar, IconCheck, IconChevronDown, IconSearch, IconX, type Icon } from '@tabler/icons-react'
import { cn } from 'cn'
import { useEffect, useRef, useState } from 'react'
import { dataDeExibicao, type FiltrosDoAcervo } from '../../jobs.ts'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '../ui/command.tsx'
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover.tsx'

const ESPERA_DA_BUSCA_MS = 300

/** O botão de um filtro: o nome (ou o valor escolhido) e, com valor, o X que limpa. */
function Gatilho({ rotulo, Icone, texto, ativo, aoLimpar }: { rotulo: string; Icone: Icon; texto: string; ativo: boolean; aoLimpar: () => void }) {
  return (
    <div
      className={cn(
        'flex h-7 max-w-full min-w-0 items-center rounded-sm border transition-colors',
        ativo ? 'border-primary/60 bg-selected text-foreground' : 'border-strong bg-input text-muted-foreground hover:text-foreground',
      )}
    >
      <PopoverTrigger asChild>
        <button type="button" aria-label={ativo ? `${rotulo}: ${texto}` : rotulo} className={cn('flex h-full min-w-0 items-center gap-1 pl-2', ativo ? 'pr-1' : 'pr-2')}>
          <Icone size={16} stroke={1.75} className="shrink-0" aria-hidden />
          <span className="truncate text-sm">{texto}</span>
          {!ativo && <IconChevronDown size={14} className="shrink-0 opacity-60" aria-hidden />}
        </button>
      </PopoverTrigger>
      {ativo && (
        <button type="button" aria-label={`Limpar ${rotulo.toLowerCase()}`} onClick={aoLimpar} className="mr-1 flex size-5 shrink-0 items-center justify-center rounded-xs hover:bg-accent">
          <IconX size={14} aria-hidden />
        </button>
      )}
    </div>
  )
}

/** Um filtro com lista de valores (Popover + Command do shadcn); `unico` troca o valor em vez de somar. */
export function Faceta({
  rotulo,
  Icone,
  opcoes,
  valor,
  aoMudar,
  unico,
}: {
  rotulo: string
  Icone: Icon
  opcoes: { valor: string; rotulo: string }[]
  valor: string[]
  aoMudar: (valor: string[]) => void
  unico?: boolean
}) {
  const [aberto, setAberto] = useState(false)
  const nomeDe = (v: string) => opcoes.find((o) => o.valor === v)?.rotulo ?? v
  const escolher = (v: string) => {
    if (unico) {
      aoMudar(valor.includes(v) ? [] : [v])
      setAberto(false)
    } else aoMudar(valor.includes(v) ? valor.filter((x) => x !== v) : [...valor, v])
  }
  const texto = valor.length === 0 ? rotulo : valor.length === 1 ? nomeDe(valor[0]) : `${rotulo}: ${valor.length}`
  return (
    <Popover open={aberto} onOpenChange={setAberto}>
      <Gatilho rotulo={rotulo} Icone={Icone} texto={texto} ativo={valor.length > 0} aoLimpar={() => aoMudar([])} />
      <PopoverContent
        align="start"
        className="w-64 p-0"
        // Sem o campo de filtro nada é tabulável: o foco vai à raiz do cmdk, que é quem ouve as setas e o Enter.
        onOpenAutoFocus={(e) => {
          if (opcoes.length > 8) return
          e.preventDefault()
          const conteudo = e.target as HTMLElement
          conteudo.querySelector<HTMLElement>('[cmdk-root]')?.focus()
        }}
      >
        <Command label={rotulo}>
          {opcoes.length > 8 && <CommandInput placeholder={`Filtrar ${rotulo.toLowerCase()}…`} />}
          <CommandList>
            <CommandEmpty>Nenhum valor com esse nome.</CommandEmpty>
            <CommandGroup>
              {opcoes.map((o) => {
                const marcado = valor.includes(o.valor)
                return (
                  <CommandItem key={o.valor} value={o.rotulo} onSelect={() => escolher(o.valor)} aria-checked={marcado}>
                    <span className={cn('flex size-4 shrink-0 items-center justify-center rounded-xs border', marcado ? 'border-primary bg-primary text-primary-foreground' : 'border-strong')} aria-hidden>
                      {marcado && <IconCheck size={12} stroke={2.5} />}
                    </span>
                    <span className="flex-1 truncate">{o.rotulo}</span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

/** O período de exibição, de e até; cada data vai à URL ao mudar. */
export function Periodo({ de, ate, aoMudar }: { de: string; ate: string; aoMudar: (p: { de: string; ate: string }) => void }) {
  const ativo = Boolean(de || ate)
  const texto = !ativo ? 'Exibição' : de && ate ? `${dataDeExibicao(de)} a ${dataDeExibicao(ate)}` : de ? `Desde ${dataDeExibicao(de)}` : `Até ${dataDeExibicao(ate)}`
  const campo = 'h-8 w-full rounded-sm border border-strong bg-input px-2 text-sm font-normal scheme-dark'
  return (
    <Popover>
      <Gatilho rotulo="Exibição" Icone={IconCalendar} texto={texto} ativo={ativo} aoLimpar={() => aoMudar({ de: '', ate: '' })} />
      <PopoverContent align="start" className="grid w-64 gap-3">
        <label className="grid gap-1 text-xs font-medium">
          Exibido de
          <input type="date" value={de} max={ate || undefined} onChange={(e) => aoMudar({ de: e.target.value, ate })} className={campo} />
        </label>
        <label className="grid gap-1 text-xs font-medium">
          Exibido até
          <input type="date" value={ate} min={de || undefined} onChange={(e) => aoMudar({ de, ate: e.target.value })} className={campo} />
        </label>
      </PopoverContent>
    </Popover>
  )
}

/**
 * A busca por nome: espera 300 ms e vai à URL sem os espaços das pontas; o espaço que se acabou de
 * digitar fica na caixa. Mudança vinda da URL (Limpar, voltar) a sobrescreve.
 */
export function BuscaPorNome({ filtros, aoBuscar }: { filtros: FiltrosDoAcervo; aoBuscar: (q: string) => void }) {
  const [busca, setBusca] = useState(filtros.q)
  const [qVisto, setQVisto] = useState(filtros.q)
  if (filtros.q !== qVisto) {
    setQVisto(filtros.q)
    if (busca.trim() !== filtros.q) setBusca(filtros.q)
  }
  const aoBuscarAtual = useRef(aoBuscar)
  useEffect(() => {
    aoBuscarAtual.current = aoBuscar
  })
  useEffect(() => {
    if (busca.trim() === filtros.q) return
    const relogio = setTimeout(() => aoBuscarAtual.current(busca.trim()), ESPERA_DA_BUSCA_MS)
    return () => clearTimeout(relogio)
  }, [busca, filtros.q])
  return (
    <div className="relative w-full min-w-0 sm:w-56">
      <IconSearch size={16} stroke={1.75} className="pointer-events-none absolute top-1.5 left-2 text-muted-foreground" aria-hidden />
      <input
        type="search"
        aria-label="Buscar por nome"
        placeholder="Buscar por nome"
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
        className="h-7 w-full rounded-sm border border-strong bg-input pr-2 pl-8 text-sm placeholder:text-muted-foreground"
      />
    </div>
  )
}
