import { cn } from 'cn'
import { memo, type KeyboardEvent, type PointerEvent, type RefObject, useEffect, useRef, useState } from 'react'
import {
  type BlocoDaFaixa,
  type Borda,
  type FaixaDoVisualizador,
  type LimitesDaAlca,
  limitesDasAlcas,
  marcasDaRegua,
  percentualDoTempo,
  posicaoDoBloco,
  posicaoDoCursor,
  relogio,
  riscosDeCorte,
  teclaDaAlca,
  tempoDoPonteiro,
  trechosSemPauta,
  vizinhoNaFaixa,
} from '../../linhaDoTempo.ts'
import { TIPOS, type TipoDaFaixa } from './tipos.ts'
import type { Instante } from './instante.ts'

/** As alças de tempo do item em correção: os tempos de agora e o que fazer quando se movem. */
export interface AlcasDaCorrecao {
  chave: string
  inicio_ms: number
  fim_ms: number
  aoMover: (borda: Borda, ms: number) => void
  /** Enter na alça grava os tempos, como no formulário. */
  aoSalvar: () => void
  /** Esc na alça descarta. */
  aoDescartar: () => void
}

// O trecho sem pauta: listras de 2 px a cada 6 px em `linha` (MAM_DESIGN_SYSTEM 2.5).
const HACHURA = 'repeating-linear-gradient(135deg, var(--color-strong) 0 2px, transparent 2px 6px)'
/** Quantos pixels em volta do ponteiro ainda pegam um bloco fino. */
const FOLGA_PX = 3
/** A partir de que fração da largura a pauta mostra o título dentro do bloco. */
const PAUTA_COM_TITULO = 0.06

/** Os chips que ligam e desligam as faixas, com o ícone, o nome e a contagem de cada tipo. */
export function ChipsDasFaixas({
  faixas,
  ligadas,
  aoAlternar,
}: {
  faixas: FaixaDoVisualizador[]
  ligadas: ReadonlySet<string>
  aoAlternar: (chave: string) => void
}) {
  return (
    <div role="group" aria-label="Faixas da linha do tempo" className="flex h-9 shrink-0 items-center gap-1 overflow-x-auto border-t px-2">
      <span className="mr-1 hidden text-xs text-muted-foreground sm:inline">Faixas</span>
      {faixas.map((f) => {
        const { Icone, cor } = TIPOS[f.chave as TipoDaFaixa]
        const ligada = ligadas.has(f.chave)
        return (
          <button
            key={f.chave}
            type="button"
            aria-pressed={ligada}
            aria-label={`${f.rotulo}, ${f.blocos.length}`}
            title={f.rotulo}
            onClick={() => aoAlternar(f.chave)}
            style={ligada ? { color: cor } : undefined}
            className={cn(
              'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-sm border px-2 text-xs font-medium whitespace-nowrap transition-colors',
              ligada ? 'border-current bg-card' : 'border-strong text-muted-foreground hover:bg-card hover:text-foreground',
            )}
          >
            <Icone size={14} stroke={1.75} style={{ color: cor }} aria-hidden />
            <span className="hidden sm:inline">{f.rotulo}</span>
            <span className={cn('tabular-nums', !ligada && 'text-muted-foreground')}>{f.blocos.length}</span>
          </button>
        )
      })}
    </div>
  )
}

/** O bloco sob o ponteiro: o mais curto que cobre o tempo (com a folga), num laço só sobre os blocos em ordem. */
// ponytail: laço linear a cada pointermove (2.500 falas custaram até 68 ms com a CPU 4×); se uma faixa
// passar de ~10 mil blocos, buscar o início por bisseção no `inicio_ms`, que já vem em ordem.
function blocoNoTempo(blocos: BlocoDaFaixa[], ms: number, folgaMs: number): BlocoDaFaixa | null {
  let achado: BlocoDaFaixa | null = null
  for (const b of blocos) {
    if (b.inicio_ms > ms + folgaMs) break
    if (b.fim_ms + folgaMs < ms) continue
    if (!achado || b.fim_ms - b.inicio_ms < achado.fim_ms - achado.inicio_ms) achado = b
  }
  return achado
}

/**
 * Os blocos de uma faixa num `<path>` só, em milissegundos: milhares de ocorrências custam um
 * elemento. O traço de 1 px que não escala garante que o bloco mais curto ainda aparece.
 */
const TracosDaFaixa = memo(function TracosDaFaixa({
  blocos,
  duracaoMs,
  cor,
  separar,
  opaca,
}: {
  blocos: BlocoDaFaixa[]
  duracaoMs: number
  cor: string
  /** Pautas encostadas: um risco de 1 px no começo de cada uma as separa. */
  separar: boolean
  opaca: boolean
}) {
  let d = ''
  let riscos = ''
  for (const b of blocos) {
    const inicio = Math.round(Math.min(b.inicio_ms, duracaoMs))
    const largura = Math.max(Math.round(Math.min(b.fim_ms, duracaoMs)) - inicio, 0)
    d += `M${inicio} 0h${largura}v1h${-largura}z`
    if (separar && inicio > 0) riscos += `M${inicio} 0v1`
  }
  return (
    <svg aria-hidden className="absolute inset-0 size-full" viewBox={`0 0 ${Math.max(duracaoMs, 1)} 1`} preserveAspectRatio="none">
      <path d={d} fill={cor} stroke={cor} strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={opaca ? 0.9 : 0.55} />
      {riscos && <path d={riscos} stroke="var(--color-background)" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
    </svg>
  )
})

/** Alça de início ou de fim: arrasta com o ponteiro ou move com as setas (0,1 s; com Shift, 1 s). */
function AlcaDoTempo({
  rotulo,
  borda,
  ms,
  limites,
  duracaoMs,
  aoMover,
  aoSalvar,
  aoDescartar,
}: {
  rotulo: string
  borda: Borda
  ms: number
  limites: LimitesDaAlca
  duracaoMs: number
  aoMover: (borda: Borda, ms: number) => void
  aoSalvar: () => void
  aoDescartar: () => void
}) {
  const arrastando = useRef(false)
  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label={rotulo}
      aria-valuemin={limites.minMs}
      aria-valuemax={limites.maxMs}
      aria-valuenow={ms}
      aria-valuetext={relogio(ms)}
      title="Arraste, ou use ← → (0,1 s) e Shift (1 s)"
      className="absolute -top-0.5 -bottom-0.5 z-20 w-2 -translate-x-1/2 cursor-ew-resize touch-none rounded-xs bg-foreground"
      style={{ left: `${percentualDoTempo(ms, duracaoMs)}%` }}
      onPointerDown={(e: PointerEvent<HTMLElement>) => {
        e.stopPropagation()
        arrastando.current = true
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }}
      onPointerMove={(e: PointerEvent<HTMLElement>) => {
        const caixa = e.currentTarget.parentElement?.getBoundingClientRect()
        if (!arrastando.current || !caixa) return
        const novo = tempoDoPonteiro(e.clientX, { esquerda: caixa.left, largura: caixa.width }, duracaoMs, limites)
        if (novo !== null) aoMover(borda, novo)
      }}
      onPointerUp={() => {
        arrastando.current = false
      }}
      onPointerCancel={() => {
        arrastando.current = false
      }}
      onKeyDown={(e: KeyboardEvent<HTMLElement>) => {
        if (e.key === 'Enter' || e.key === 'Escape') {
          e.preventDefault()
          e.stopPropagation()
          if (e.key === 'Enter') aoSalvar()
          else aoDescartar()
          return
        }
        const novo = teclaDaAlca(e.key, e.shiftKey, ms, limites)
        if (novo === null) return
        // As setas movem a alça, não o player nem o bloco ativo da faixa.
        e.preventDefault()
        e.stopPropagation()
        aoMover(borda, novo)
      }}
    />
  )
}

const pct = (n: number) => `${n}%`

/** A largura de um algarismo do IBM Plex Mono em 11 px, para os rótulos da régua não se encostarem. */
const PX_POR_ALGARISMO = 6.7

/** A largura do elemento, que muda com a janela; 0 enquanto não se mede (e no jsdom). */
function useLargura(ref: RefObject<HTMLElement | null>): number {
  const [largura, setLargura] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observador = new ResizeObserver(() => setLargura(el.clientWidth))
    observador.observe(el)
    return () => observador.disconnect()
  }, [ref])
  return largura
}

/**
 * A linha do tempo: a régua com os cortes, uma faixa por tipo ligado e o cursor. Cada faixa é uma
 * parada de Tab só: o botão do bloco ativo, que ← → trocam e Enter abre. O cursor anda sem
 * renderizar a linha: ele assina o instante e mexe no próprio estilo.
 */
export function LinhaDoTempo({
  faixas,
  cortesMs,
  duracaoMs,
  instante,
  selecionada,
  alcas,
  aoSaltar,
  aoSelecionar,
}: {
  faixas: FaixaDoVisualizador[]
  cortesMs: number[] | null | undefined
  duracaoMs: number
  instante: Instante
  selecionada: string | null
  alcas: AlcasDaCorrecao | null
  aoSaltar: (ms: number) => void
  aoSelecionar: (chave: string) => void
}) {
  const cursor = useRef<HTMLDivElement>(null)
  const regua = useRef<HTMLDivElement>(null)
  const largura = useLargura(regua)
  const arrastando = useRef(false)
  // O bloco que tem a parada de Tab em cada faixa.
  const [ativos, setAtivos] = useState<Record<string, string>>({})
  const [dica, setDica] = useState<{ x: number; y: number; direita: boolean; nome: string } | null>(null)

  useEffect(() => {
    const mover = () => {
      if (cursor.current) cursor.current.style.left = pct(posicaoDoCursor(instante.ms(), duracaoMs))
    }
    mover()
    return instante.assinar(mover)
  }, [instante, duracaoMs])

  const msNoPonteiro = (e: PointerEvent<HTMLElement>) => {
    const caixa = e.currentTarget.getBoundingClientRect()
    const ms = tempoDoPonteiro(e.clientX, { esquerda: caixa.left, largura: caixa.width }, duracaoMs, { minMs: 0, maxMs: duracaoMs })
    return { ms, folgaMs: caixa.width > 0 ? (FOLGA_PX * duracaoMs) / caixa.width : 0, caixa }
  }

  const naRegua = (e: PointerEvent<HTMLElement>) => {
    const { ms } = msNoPonteiro(e)
    if (ms !== null) aoSaltar(ms)
  }

  function aoTeclarNoBloco(e: KeyboardEvent<HTMLButtonElement>, faixa: FaixaDoVisualizador, atual: string) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    // Com o foco na faixa, as setas passam de bloco e não movem o player.
    e.preventDefault()
    setAtivos((a) => ({ ...a, [faixa.chave]: vizinhoNaFaixa(faixa.blocos, atual, e.key === 'ArrowRight' ? 1 : -1) }))
  }

  // Numa régua estreita os rótulos pulam marcas, e nenhum encosta no do fim do vídeo.
  const marcas = marcasDaRegua(duracaoMs)
  const larguraDoRotulo = (texto: string) => texto.length * PX_POR_ALGARISMO + 8
  const fim = marcas.at(-1)
  const espaco = marcas.length > 1 ? (largura * marcas[1].percentual) / 100 : largura
  const pulo = espaco > 0 ? Math.ceil((larguraDoRotulo(marcas[0]?.rotulo ?? '') + 4) / espaco) : 1
  const rotuloCabe = (m: (typeof marcas)[number], i: number) =>
    m.noFim ||
    largura === 0 ||
    (i % pulo === 0 && (largura * m.percentual) / 100 + larguraDoRotulo(m.rotulo) + 4 <= largura - larguraDoRotulo(fim?.rotulo ?? ''))

  const pautas = faixas.find((f) => f.chave === 'pauta')
  const semPauta = pautas ? trechosSemPauta(pautas.blocos, duracaoMs) : []
  const cortes = riscosDeCorte(cortesMs, duracaoMs)

  return (
    <div className="flex shrink-0 border-t pb-1 text-xs select-none">
      <div className="w-9 shrink-0 border-r sm:w-32" aria-hidden>
        <div className="h-5 border-b border-strong/60" />
        {faixas.map((f) => {
          const { Icone, cor } = TIPOS[f.chave as TipoDaFaixa]
          return (
            <div key={f.chave} className="flex h-[18px] items-center gap-1.5 px-2" title={f.rotulo}>
              <Icone size={14} stroke={1.75} className="shrink-0" style={{ color: cor }} />
              <span className="hidden flex-1 truncate text-muted-foreground sm:inline">{f.rotulo}</span>
              <span className="hidden text-muted-foreground tabular-nums sm:inline">{f.blocos.length}</span>
            </div>
          )
        })}
      </div>
      <div className="relative min-w-0 flex-1">
        <div
          data-regua=""
          ref={regua}
          className="relative h-5 cursor-pointer touch-none border-b border-strong/60"
          onPointerDown={(e) => {
            arrastando.current = true
            e.currentTarget.setPointerCapture?.(e.pointerId)
            naRegua(e)
          }}
          onPointerMove={(e) => {
            if (arrastando.current) naRegua(e)
          }}
          onPointerUp={() => {
            arrastando.current = false
          }}
          onPointerCancel={() => {
            arrastando.current = false
          }}
        >
          {marcas.map((m, i) => (
            <span
              key={m.ms}
              className={cn('pointer-events-none absolute top-0 h-full border-strong', m.noFim ? 'border-r' : 'border-l')}
              style={m.noFim ? { right: 0 } : { left: pct(m.percentual) }}
            >
              {rotuloCabe(m, i) && <span className="mx-1 font-mono text-2xs text-muted-foreground tabular-nums">{m.rotulo}</span>}
            </span>
          ))}
          <svg
            aria-hidden
            data-cortes={cortes.length}
            className="pointer-events-none absolute inset-x-0 bottom-0 h-1.5 w-full"
            viewBox="0 0 100 1"
            preserveAspectRatio="none"
          >
            <path d={cortes.map((p) => `M${p} 0v1`).join('')} stroke="var(--color-muted-foreground)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
        {faixas.map((faixa) => {
          const { cor } = TIPOS[faixa.chave as TipoDaFaixa]
          const selecionado = faixa.blocos.find((b) => b.chave === selecionada)
          const ativo =
            faixa.blocos.find((b) => b.chave === ativos[faixa.chave]) ?? selecionado ?? faixa.blocos[0]
          const comAlcas = alcas && faixa.blocos.some((b) => b.chave === alcas.chave) ? alcas : null
          const rotulo = `${faixa.rotulo} ${faixa.blocos.length}`
          return (
            <div
              key={faixa.chave}
              role="group"
              aria-label={rotulo}
              // A faixa sem blocos ainda é uma parada de Tab.
              tabIndex={faixa.blocos.length === 0 ? 0 : undefined}
              className="relative h-[18px] cursor-pointer py-0.5"
              onPointerDown={(e) => {
                // O botão do bloco ativo cobre os blocos sobrepostos a ele: o clique também se resolve pela posição.
                if ((e.target as Element).closest('[role=slider]')) return
                const { ms, folgaMs } = msNoPonteiro(e)
                if (ms === null) return
                const bloco = blocoNoTempo(faixa.blocos, ms, folgaMs)
                if (bloco) {
                  setAtivos((a) => ({ ...a, [faixa.chave]: bloco.chave }))
                  aoSelecionar(bloco.chave)
                } else aoSaltar(ms)
              }}
              onPointerMove={(e) => {
                const { ms, folgaMs, caixa } = msNoPonteiro(e)
                const bloco = ms === null ? null : blocoNoTempo(faixa.blocos, ms, folgaMs)
                const x = e.clientX - caixa.left
                // Lido agora: o `currentTarget` do evento já não existe quando o React roda o atualizador.
                const y = e.currentTarget.offsetTop
                const nome = bloco?.nome ?? null
                setDica((atual) => (nome === null ? null : atual?.nome === nome && atual.y === y ? atual : { x, y, direita: x > caixa.width / 2, nome }))
              }}
              onPointerLeave={() => setDica(null)}
            >
              <div className="relative size-full">
                <TracosDaFaixa blocos={faixa.blocos} duracaoMs={duracaoMs} cor={cor} separar={faixa.chave === 'pauta'} opaca={faixa.chave !== 'fala'} />
                {faixa.chave === 'pauta' &&
                  semPauta.map((t) => {
                    const nome = `Sem decupagem, ${relogio(t.inicio_ms)}–${relogio(t.fim_ms)}`
                    const { esquerda, largura } = posicaoDoBloco(t, duracaoMs)
                    return (
                      <div
                        key={t.inicio_ms}
                        role="img"
                        aria-label={nome}
                        title={nome}
                        className="absolute inset-y-0 rounded-xs"
                        style={{ left: pct(esquerda), width: pct(largura), background: HACHURA }}
                      />
                    )
                  })}
                {faixa.chave === 'pauta' &&
                  faixa.blocos.map((b) => {
                    const { esquerda, largura } = posicaoDoBloco(b, duracaoMs)
                    if (largura / 100 < PAUTA_COM_TITULO) return null
                    return (
                      <span
                        key={b.chave}
                        aria-hidden
                        className="pointer-events-none absolute inset-y-0 truncate px-1 text-2xs leading-[14px] font-medium text-black/80"
                        style={{ left: pct(esquerda), width: pct(largura) }}
                      >
                        {b.nome.replace(/^Pauta: /, '').replace(/, [\d:]+ a [\d:]+$/, '')}
                      </span>
                    )
                  })}
                {faixa.blocos.length === 0 && faixa.vazio && (
                  <span className="absolute inset-y-0 left-1 leading-[14px] text-muted-foreground">{faixa.vazio}</span>
                )}
                {selecionado && (
                  <span
                    aria-hidden
                    data-selecionado=""
                    className="pointer-events-none absolute -inset-y-0.5 z-10 min-w-1 rounded-xs outline-2 outline-offset-1 outline-ring"
                    style={{ left: pct(posicaoDoBloco(selecionado, duracaoMs).esquerda), width: pct(posicaoDoBloco(selecionado, duracaoMs).largura) }}
                  />
                )}
                {ativo && (
                  <button
                    type="button"
                    aria-label={ativo.nome}
                    aria-pressed={ativo.chave === selecionada}
                    className="absolute inset-y-0 z-10 min-w-1 rounded-xs focus-visible:outline-2 focus-visible:outline-offset-1"
                    style={{ left: pct(posicaoDoBloco(ativo, duracaoMs).esquerda), width: pct(posicaoDoBloco(ativo, duracaoMs).largura) }}
                    onKeyDown={(e) => aoTeclarNoBloco(e, faixa, ativo.chave)}
                    // Só o Enter e o Espaço (`detail` 0): o ponteiro já selecionou no `pointerdown` da faixa.
                    onClick={(e) => e.detail === 0 && aoSelecionar(ativo.chave)}
                  />
                )}
                {comAlcas &&
                  (() => {
                    const limites = limitesDasAlcas(comAlcas, duracaoMs, duracaoMs)
                    const comum = { duracaoMs, aoMover: comAlcas.aoMover, aoSalvar: comAlcas.aoSalvar, aoDescartar: comAlcas.aoDescartar }
                    return (
                      <>
                        <AlcaDoTempo rotulo="Início do item" borda="inicio" ms={comAlcas.inicio_ms} limites={limites.inicio} {...comum} />
                        <AlcaDoTempo rotulo="Fim do item" borda="fim" ms={comAlcas.fim_ms} limites={limites.fim} {...comum} />
                      </>
                    )
                  })()}
              </div>
            </div>
          )
        })}
        <div ref={cursor} aria-hidden data-cursor="" className="pointer-events-none absolute inset-y-0 z-30 w-0.5 -translate-x-1/2 bg-foreground" />
        {dica && (
          <div
            role="tooltip"
            className={cn(
              'pointer-events-none absolute z-40 max-w-80 -translate-y-full truncate rounded-md border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-float',
              dica.direita && '-translate-x-full',
            )}
            style={{ left: dica.x, top: dica.y - 2 }}
          >
            {dica.nome}
          </div>
        )}
      </div>
    </div>
  )
}
