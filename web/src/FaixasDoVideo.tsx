import { Box, Text, Tooltip } from '@mantine/core'
import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import {
  type FaixaDoVisualizador,
  marcasDaRegua,
  percentualDoTempo,
  posicaoDoBloco,
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

/** A linha do tempo do Visualizador: régua com cortes, uma faixa por tipo e o cursor. */
export function FaixasDoVideo({
  faixas,
  cortesMs,
  duracaoMs,
  atualMs,
  selecionada,
  aoSaltar,
  aoSelecionar,
}: {
  faixas: FaixaDoVisualizador[]
  cortesMs: number[] | null | undefined
  duracaoMs: number
  atualMs: number
  selecionada: string | null
  aoSaltar: (ms: number) => void
  aoSelecionar: (chave: string, inicioMs: number) => void
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
        {faixas.map((faixa) => (
          <Text
            key={faixa.chave}
            size="xs"
            c="dimmed"
            truncate
            aria-hidden
            style={{ lineHeight: `${ALTURA_DA_FAIXA}px` }}
          >
            {`${faixa.rotulo} ${faixa.blocos.length}`}
          </Text>
        ))}
      </Box>
      <Box style={{ flex: 1, minWidth: 0, position: 'relative', display: 'flex', flexDirection: 'column', gap: VAO }}>
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
              transform: m.percentual > 95 ? 'translateX(-100%)' : undefined,
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
      {faixas.map((faixa) => {
        const ativo =
          ativos[faixa.chave] ??
          faixa.blocos.find((b) => b.chave === selecionada)?.chave ??
          faixa.blocos[0]?.chave
        const nome = `${faixa.rotulo} ${faixa.blocos.length}`
        return (
            <Box
              key={faixa.chave}
              role="group"
              aria-label={nome}
              onKeyDown={(e) => aoTeclar(e, faixa)}
              style={{ position: 'relative', height: ALTURA_DA_FAIXA }}
            >
              {faixa.chave === 'pauta' &&
                semPauta.map((t) => {
                  const dica = `Sem decupagem, ${relogio(t.inicio_ms)}–${relogio(t.fim_ms)}`
                  const { esquerda, largura } = posicaoDoBloco(t, duracaoMs)
                  return (
                    <Tooltip key={t.inicio_ms} label={dica}>
                      <Box
                        role="img"
                        aria-label={dica}
                        style={{
                          position: 'absolute',
                          top: 0,
                          bottom: 0,
                          left: `${esquerda}%`,
                          width: `${largura}%`,
                          background: HACHURADO,
                        }}
                      />
                    </Tooltip>
                  )
                })}
              {faixa.blocos.map((b) => {
                const { esquerda, largura } = posicaoDoBloco(b, duracaoMs)
                return (
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
                        position: 'absolute',
                        top: 0,
                        bottom: 0,
                        left: `${esquerda}%`,
                        width: `${largura}%`,
                        minWidth: 2,
                        padding: 0,
                        cursor: 'pointer',
                        background: faixa.cor,
                        border: `1px solid ${CORES.fundo}`,
                        borderRadius: 2,
                        outline: selecionada === b.chave ? `2px solid ${CORES.foco}` : undefined,
                        outlineOffset: 1,
                        zIndex: selecionada === b.chave ? 1 : undefined,
                      }}
                    />
                  </Tooltip>
                )
              })}
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
            left: `${Math.min(percentualDoTempo(atualMs, duracaoMs), 100)}%`,
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
