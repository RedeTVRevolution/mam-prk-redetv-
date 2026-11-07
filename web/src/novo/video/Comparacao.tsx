import { IconX } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { type Ref, useState } from 'react'
import { type ClienteDoJob, codigoDoErro, SessaoExpirada } from '../../api.ts'
import { relogio } from '../../linhaDoTempo.ts'
import type { ComparacaoDaPassada, ItemMarcado, ResumoDaPassada } from '../../passadas.ts'
import { Button } from '../ui/button.tsx'
import { AvisoDeFalha, BotaoDeIcone } from './comum.tsx'
import { chaveDoVideo } from './tipos.ts'

const TITULOS: Record<string, string> = {
  famosos: 'Famosos',
  mencoes: 'Menções',
  pautas: 'Pautas',
  broll_limpos: 'B-roll: planos limpos',
  broll_descricoes: 'B-roll: descrições',
  comerciais: 'Comerciais',
}

const DATA = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo' })

/** O seletor "Comparar com": o valor vazio volta ao inspetor de sempre. */
export function SeletorDePassada({ passadas, valor, aoEscolher, ref }: { passadas: ResumoDaPassada[]; valor: string | null; aoEscolher: (id: string | null) => void; ref?: Ref<HTMLSelectElement> }) {
  return (
    <select
      ref={ref}
      aria-label="Comparar com"
      value={valor ?? ''}
      onChange={(e) => aoEscolher(e.currentTarget.value || null)}
      className="h-7 w-28 min-w-0 rounded-sm border border-strong bg-input px-1.5 text-xs text-foreground focus:border-primary 2xl:w-44"
    >
      <option value="">Comparar com</option>
      {passadas.map((p) => (
        <option key={p.id} value={p.id}>
          {`${p.modelo} · ${DATA.format(new Date(p.criada_em))}`}
        </option>
      ))}
    </select>
  )
}

const dinheiro = (usd: number | null): string => (usd === null ? 'n/d' : `US$ ${usd.toFixed(2).replace('.', ',')} por hora`)

function marcaDoItem(i: ItemMarcado): string | null {
  if (i.marca === 'so_aqui') return 'só neste lado'
  if (i.marca === 'difere') return `difere: ${i.motivos.join(', ')}`
  return null
}

// Quantos itens de cada lado existem de uma vez: com milhares, a tela passaria de 3 mil elementos.
const POR_VEZ = 30

function Lado({ rotulo, itens, aoSaltar }: { rotulo: string; itens: ItemMarcado[]; aoSaltar: (ms: number) => void }) {
  const [mostrados, setMostrados] = useState(POR_VEZ)
  if (itens.length === 0) return <p className="text-xs text-muted-foreground">Nada</p>
  return (
    <div className="grid gap-0.5">
      {itens.slice(0, mostrados).map((i) => {
        const marca = marcaDoItem(i)
        return (
          <button
            key={`${i.inicio_ms}-${i.fim_ms}-${i.identidade}`}
            type="button"
            onClick={() => aoSaltar(i.inicio_ms)}
            aria-label={`${rotulo}: ${i.identidade} ${relogio(i.inicio_ms)}`}
            className="flex min-w-0 items-start gap-1.5 rounded-xs px-1 py-0.5 text-left hover:bg-card"
          >
            <span className="font-mono text-xs text-muted-foreground tabular-nums">{relogio(i.inicio_ms)}</span>
            <span className="min-w-0 flex-1 text-sm break-words">
              {i.identidade || '(sem descrição)'}
              {i.detalhe ? ` [${i.detalhe}]` : ''}
            </span>
            {/* Diferença não é estado do Job: selo neutro, e a palavra diz o que é. */}
            {marca && <span className="shrink-0 rounded-xs border border-strong px-1 text-xs text-muted-foreground">{marca}</span>}
          </button>
        )
      })}
      {itens.length > mostrados && (
        <Button type="button" size="sm" variant="secondary" className="justify-self-center" onClick={() => setMostrados(mostrados + POR_VEZ)}>
          {`Mostrar mais ${Math.min(POR_VEZ, itens.length - mostrados)}`}
        </Button>
      )}
    </div>
  )
}

function Requisitos({ c, lado, rotulo, aoSaltar }: { c: ComparacaoDaPassada; lado: 'a' | 'b'; rotulo: string; aoSaltar: (ms: number) => void }) {
  return (
    <div className="grid gap-3">
      {c.requisitos.map((r) => (
        <div key={r.nome} className="grid gap-0.5">
          <h4 className="text-xs font-semibold text-muted-foreground">{TITULOS[r.nome] ?? r.nome}</h4>
          <Lado rotulo={rotulo} itens={r[lado]} aoSaltar={aoSaltar} />
        </div>
      ))}
    </div>
  )
}

/**
 * As duas decupagens do mesmo vídeo lado a lado: a do Job (à esquerda) e a da passada. Só leitura:
 * clicar num item leva o player ao início dele, e nada aqui corrige a passada. Toma o lugar do inspetor.
 * Em 1280 px ou mais fica ao lado do vídeo (62%); de 1024 a 1279 px fica embaixo, em largura total, para
 * o cabeçalho e o transporte do vídeo não perderem largura.
 */
export function ComparacaoDePassada({ api, id, passadaId, aoSaltar, aoFechar }: { api: ClienteDoJob; id: string; passadaId: string; aoSaltar: (ms: number) => void; aoFechar: () => void }) {
  const consulta = useQuery({
    queryKey: chaveDoVideo(id, 'comparacao', passadaId),
    queryFn: () => api.comparacao(passadaId),
    retry: false,
    staleTime: Infinity,
  })
  const c = consulta.data
  return (
    <aside aria-label="Comparação com a passada" className="flex h-[80dvh] w-full shrink-0 flex-col overflow-y-auto bg-background lg:h-[45%] lg:min-h-0 xl:h-auto xl:w-[62%]">
      <div className="flex h-8 shrink-0 items-center gap-2 border-b bg-card px-3">
        <h2 className="min-w-0 flex-1 truncate text-sm font-medium">Comparação com a passada</h2>
        <BotaoDeIcone rotulo="Fechar a comparação" onClick={aoFechar}>
          <IconX size={16} stroke={1.75} aria-hidden />
        </BotaoDeIcone>
      </div>
      <div className="grid gap-3 p-3">
        {consulta.isPending && <p className="text-sm text-muted-foreground">Carregando a comparação…</p>}
        {consulta.isError && !(consulta.error instanceof SessaoExpirada) && (
          <AvisoDeFalha mensagem="Não foi possível carregar a comparação. Tente de novo em instantes." codigo={codigoDoErro(consulta.error)} aoTentar={() => void consulta.refetch()} />
        )}
        {c && (
          <>
            <section aria-label="Custo e tempo" className="grid grid-cols-2 gap-3 rounded-sm border p-2">
              <div>
                <p className="text-sm font-semibold">Job ({c.modelo_do_job})</p>
                <p className="text-xs">{dinheiro(c.a.custo_por_hora_usd)}</p>
                <p className="text-xs">Tempo: {relogio(c.a.tempo_total_s * 1000)}</p>
              </div>
              <div>
                <p className="text-sm font-semibold">Passada ({c.modelo})</p>
                <p className="text-xs">{dinheiro(c.b.custo_por_hora_usd)}</p>
                <p className="text-xs">Tempo: {relogio(c.b.tempo_total_s * 1000)}</p>
              </div>
            </section>
            <div className="grid grid-cols-2 items-start gap-3">
              <section aria-label="Decupagem do Job" className="min-w-0">
                <h3 className="mb-1 text-sm font-semibold">Job</h3>
                <Requisitos c={c} lado="a" rotulo="Job" aoSaltar={aoSaltar} />
              </section>
              <section aria-label="Decupagem da passada" className="min-w-0">
                <h3 className="mb-1 text-sm font-semibold">Passada</h3>
                <Requisitos c={c} lado="b" rotulo="Passada" aoSaltar={aoSaltar} />
              </section>
            </div>
          </>
        )}
      </div>
    </aside>
  )
}
