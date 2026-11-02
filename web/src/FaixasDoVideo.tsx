import { Box, Text, Tooltip } from '@mantine/core'
import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import {
  type Borda,
  type FaixaDoVisualizador,
  type LimitesDaAlca,
  limitesDasAlcas,
  percentualDoTempo,
  teclaDaAlca,
  type Intervalo,
  marcasDaRegua,
  posicaoDoBloco,
  posicaoDoCursor,
  relogio,
  riscosDeCorte,
  tempoDoPonteiro,
  trechosSemPauta,
  vizinhoNaFaixa,
} from './linhaDoTempo.ts'
import { CORES, HACHURADO } from './tema.ts'

const LARGURA_DO_ROTULO = 96
const ALTURA_DA_FAIXA = 20
const ALTURA_DA_REGUA = 20
const VAO = 4

/** As alças de tempo do item em correção: os tempos de agora e o que fazer quando se movem. */
export interface AlcasDaCorrecao {
  chave: string
  inicio_ms: number
  fim_ms: number
  aoMover: (borda: Borda, ms: number) => void
  /** Enter na alça grava os tempos, como no formulário da linha. */
  aoSalvar: () => void
  /** Esc na alça descarta. */
  aoDescartar: () => void
}

/** O trecho marcado com I e O: a faixa "Trecho" logo abaixo da régua, com as alças dos dois lados. */
export interface TrechoMarcado {
  inicio_ms: number
  /** Sem a saída marcada (só o `I`), a faixa mostra a entrada e as alças esperam. */
  fim_ms: number | null
  aoMover: (borda: Borda, ms: number) => void
  /** Enter na alça grava, como no formulário. */
  aoSalvar: () => void
  /** Esc na alça descarta o trecho. */
  aoDescartar: () => void
}

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
    <Box
      role="slider"
      tabIndex={0}
      aria-label={rotulo}
      aria-valuemin={limites.minMs}
      aria-valuemax={limites.maxMs}
      aria-valuenow={ms}
      aria-valuetext={relogio(ms)}
      title="Arraste, ou use ← → (0,1 s) e Shift (1 s)"
      style={{
        position: 'absolute',
        top: -3,
        width: 8,
        height: ALTURA_DA_FAIXA + 6,
        left: `${percentualDoTempo(ms, duracaoMs)}%`,
        transform: 'translateX(-50%)',
        background: CORES.texto,
        borderRadius: 2,
        cursor: 'ew-resize',
        touchAction: 'none',
        zIndex: 3,
      }}
      onPointerDown={(e: PointerEvent<HTMLElement>) => {
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
        e.preventDefault()
        // As setas movem a alça, não o player nem o foco da faixa.
        e.stopPropagation()
        aoMover(borda, novo)
      }}
    />
  )
}

/** A linha do tempo do Visualizador: régua com cortes, uma faixa por tipo e o cursor. */
export function FaixasDoVideo({
  faixas,
  cortesMs,
  duracaoMs,
  atualMs,
  selecionada,
  aoSaltar,
  aoSelecionar,
  alcas,
  trecho,
}: {
  faixas: FaixaDoVisualizador[]
  cortesMs: number[] | null | undefined
  duracaoMs: number
  atualMs: number
  selecionada: string | null
  aoSaltar: (ms: number) => void
  aoSelecionar: (chave: string, inicioMs: number) => void
  /** Com a correção de tempos aberta, as alças aparecem na faixa do item. */
  alcas?: AlcasDaCorrecao | null
  /** O trecho marcado no modo de catalogação. */
  trecho?: TrechoMarcado | null
}) {
  const trilha = useRef<HTMLDivElement>(null)
  const arrastando = useRef(false)
  // O bloco que tem a parada de Tab em cada faixa.
  const [ativos, setAtivos] = useState<Record<string, string>>({})

  function saltarNoPonteiro(e: PointerEvent) {
    const caixa = trilha.current?.getBoundingClientRect()
    if (!caixa) return
    const ms = tempoDoPonteiro(
      e.clientX,
      { esquerda: caixa.left, largura: caixa.width },
      duracaoMs,
      { minMs: 0, maxMs: duracaoMs },
    )
    if (ms !== null) aoSaltar(ms)
  }

  function aoTeclar(e: KeyboardEvent<HTMLElement>, faixa: FaixaDoVisualizador) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    // Com o foco na faixa, as setas não movem o player.
    e.preventDefault()
    const atual = (e.target as HTMLElement).dataset.chave
    if (!atual) return
    const proximo = vizinhoNaFaixa(faixa.blocos, atual, e.key === 'ArrowRight' ? 1 : -1)
    e.currentTarget.querySelector<HTMLElement>(`[data-chave="${proximo}"]`)?.focus()
  }

  const semPauta = trechosSemPauta(
    faixas.find((f) => f.chave === 'pauta')?.blocos ?? [],
    duracaoMs,
  )

  return (
    <Box style={{ display: 'flex', gap: VAO * 2 }}>
      <Box style={{ width: LARGURA_DO_ROTULO, display: 'flex', flexDirection: 'column', gap: VAO }}>
        <Box style={{ height: ALTURA_DA_REGUA }} />
        {trecho && (
          <Text size="xs" fw={600} aria-hidden style={{ lineHeight: `${ALTURA_DA_FAIXA}px`, color: CORES.foco }}>
            Trecho
          </Text>
        )}
        {faixas.map((faixa) => (
          <Text
            key={faixa.chave}
            size="xs"
            c="dimmed"
            truncate
            aria-hidden
            style={{ lineHeight: `${ALTURA_DA_FAIXA}px` }}
          >
            {rotuloDaFaixa(faixa)}
          </Text>
        ))}
      </Box>
      <Box
        style={{
          flex: 1,
          minWidth: 0,
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          gap: VAO,
        }}
      >
        <Box
          ref={trilha}
          role="presentation"
          style={{
            position: 'relative',
            height: ALTURA_DA_REGUA,
            cursor: 'pointer',
            touchAction: 'none',
            borderBottom: `1px solid ${CORES.borda}`,
          }}
          onPointerDown={(e) => {
            arrastando.current = true
            e.currentTarget.setPointerCapture?.(e.pointerId)
            saltarNoPonteiro(e)
          }}
          onPointerMove={(e) => {
            if (arrastando.current) saltarNoPonteiro(e)
          }}
          onPointerUp={() => {
            arrastando.current = false
          }}
          onPointerCancel={() => {
            arrastando.current = false
          }}
        >
          {marcasDaRegua(duracaoMs).map((m) => (
            <Text
              key={m.ms}
              size="xs"
              c="dimmed"
              style={{
                position: 'absolute',
                left: `${m.percentual}%`,
                fontVariantNumeric: 'tabular-nums',
                transform: m.noFim ? 'translateX(-100%)' : undefined,
                pointerEvents: 'none',
              }}
            >
              {m.rotulo}
            </Text>
          ))}
          {riscosDeCorte(cortesMs, duracaoMs).map((p) => (
            <Box
              key={p}
              data-corte=""
              style={{
                position: 'absolute',
                left: `${p}%`,
                bottom: 0,
                width: 1,
                height: 6,
                background: CORES.textoSecundario,
                pointerEvents: 'none',
              }}
            />
          ))}
        </Box>
        {trecho && <FaixaDoTrecho trecho={trecho} duracaoMs={duracaoMs} />}
        {faixas.map((faixa) => {
          const ativo =
            ativos[faixa.chave] ??
            faixa.blocos.find((b) => b.chave === selecionada)?.chave ??
            faixa.blocos[0]?.chave
          return (
            <Box
              key={faixa.chave}
              role="group"
              aria-label={rotuloDaFaixa(faixa)}
              // A faixa sem blocos ainda é uma parada de Tab.
              tabIndex={faixa.blocos.length === 0 ? 0 : undefined}
              onKeyDown={(e) => aoTeclar(e, faixa)}
              style={{ position: 'relative', height: ALTURA_DA_FAIXA }}
            >
              {faixa.chave === 'pauta' &&
                semPauta.map((t) => {
                  const dica = `Sem decupagem, ${relogio(t.inicio_ms)}–${relogio(t.fim_ms)}`
                  return (
                    <Tooltip key={t.inicio_ms} label={dica}>
                      <Box
                        role="img"
                        aria-label={dica}
                        style={{ ...estiloDoTrecho(t, duracaoMs), background: HACHURADO }}
                      />
                    </Tooltip>
                  )
                })}
              {faixa.blocos.length === 0 && faixa.vazio && (
                <Text size="xs" c="dimmed" style={{ position: 'absolute', top: 0, left: 0, lineHeight: `${ALTURA_DA_FAIXA}px` }}>
                  {faixa.vazio}
                </Text>
              )}
              {alcas && faixa.blocos.some((b) => b.chave === alcas.chave) && (() => {
                const limites = limitesDasAlcas(alcas, duracaoMs, duracaoMs)
                return (
                  <>
                    <AlcaDoTempo rotulo="Início do item" borda="inicio" ms={alcas.inicio_ms} limites={limites.inicio} duracaoMs={duracaoMs} aoMover={alcas.aoMover} aoSalvar={alcas.aoSalvar} aoDescartar={alcas.aoDescartar} />
                    <AlcaDoTempo rotulo="Fim do item" borda="fim" ms={alcas.fim_ms} limites={limites.fim} duracaoMs={duracaoMs} aoMover={alcas.aoMover} aoSalvar={alcas.aoSalvar} aoDescartar={alcas.aoDescartar} />
                  </>
                )
              })()}
              {faixa.blocos.map((b) => (
                <Tooltip key={b.chave} label={b.nome}>
                  <Box
                    component="button"
                    type="button"
                    data-chave={b.chave}
                    aria-label={b.nome}
                    aria-pressed={selecionada === b.chave}
                    tabIndex={b.chave === ativo ? 0 : -1}
                    onFocus={() => setAtivos((a) => ({ ...a, [faixa.chave]: b.chave }))}
                    onClick={() => aoSelecionar(b.chave, b.inicio_ms)}
                    style={{
                      ...estiloDoTrecho(b, duracaoMs),
                      minWidth: 2,
                      padding: 0,
                      cursor: 'pointer',
                      background: faixa.cor,
                      border: `1px solid ${CORES.fundo}`,
                      borderRadius: 'var(--mantine-radius-xs)',
                      outline: selecionada === b.chave ? `2px solid ${CORES.foco}` : undefined,
                      outlineOffset: 1,
                      zIndex: selecionada === b.chave ? 1 : undefined,
                    }}
                  />
                </Tooltip>
              ))}
            </Box>
          )
        })}
        <Box
          aria-hidden
          data-cursor=""
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${posicaoDoCursor(atualMs, duracaoMs)}%`,
            width: 2,
            background: CORES.texto,
            pointerEvents: 'none',
            zIndex: 2,
          }}
        />
      </Box>
    </Box>
  )
}

const rotuloDaFaixa = (f: FaixaDoVisualizador): string => `${f.rotulo} ${f.blocos.length}`

/** O estilo de um trecho de tempo dentro da faixa, com a posição do módulo da linha do tempo. */
function estiloDoTrecho(t: Intervalo, duracaoMs: number): CSSProperties {
  const { esquerda, largura } = posicaoDoBloco(t, duracaoMs)
  return { position: 'absolute', top: 0, bottom: 0, left: `${esquerda}%`, width: `${largura}%` }
}

const TEMPOS_DO_TRECHO = (t: TrechoMarcado) =>
  `${relogio(t.inicio_ms)}–${t.fim_ms === null ? '…' : relogio(t.fim_ms)}`

function FaixaDoTrecho({ trecho, duracaoMs }: { trecho: TrechoMarcado; duracaoMs: number }) {
  const completo = trecho.fim_ms !== null
  const limites = limitesDasAlcas(
    { inicio_ms: trecho.inicio_ms, fim_ms: trecho.fim_ms ?? trecho.inicio_ms },
    duracaoMs,
    duracaoMs,
  )
  return (
    <Box role="group" aria-label="Trecho" style={{ position: 'relative', height: ALTURA_DA_FAIXA }}>
      {completo && (
        <Box
          data-trecho=""
          style={{ ...estiloDoTrecho({ inicio_ms: trecho.inicio_ms, fim_ms: trecho.fim_ms as number }, duracaoMs), background: `${CORES.foco}29`, border: `1px solid ${CORES.foco}`, borderRadius: 'var(--mantine-radius-xs)' }}
        />
      )}
      <Text
        size="xs"
        aria-label={`Trecho ${TEMPOS_DO_TRECHO(trecho)}`}
        style={{
          position: 'absolute',
          top: 0,
          left: `${percentualDoTempo(trecho.inicio_ms, duracaoMs)}%`,
          marginLeft: 8,
          lineHeight: `${ALTURA_DA_FAIXA}px`,
          fontVariantNumeric: 'tabular-nums',
          pointerEvents: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        {TEMPOS_DO_TRECHO(trecho)}
      </Text>
      <AlcaDoTempo rotulo="Início do trecho" borda="inicio" ms={trecho.inicio_ms} limites={limites.inicio} duracaoMs={duracaoMs} aoMover={trecho.aoMover} aoSalvar={trecho.aoSalvar} aoDescartar={trecho.aoDescartar} />
      {trecho.fim_ms !== null && (
        <AlcaDoTempo rotulo="Fim do trecho" borda="fim" ms={trecho.fim_ms} limites={limites.fim} duracaoMs={duracaoMs} aoMover={trecho.aoMover} aoSalvar={trecho.aoSalvar} aoDescartar={trecho.aoDescartar} />
      )}
    </Box>
  )
}
