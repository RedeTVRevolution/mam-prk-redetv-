// O resultado da busca que o Visualizador percorre com N e Shift+N, guardado na sessão do navegador.

import type { VideoDoResultado } from './busca.ts'

export interface MomentoGuardado {
  inicio_ms: number
  fim_ms: number
  motivo: string
}

export interface VideoGuardado {
  job_id: string
  momentos: MomentoGuardado[]
}

const CHAVE = 'mam:busca'
// Dois momentos a menos de 0,1 s um do outro contam como o mesmo: o N não fica preso no que acabou de abrir.
const FOLGA_MS = 100

/** Só o que a navegação usa: um vídeo sem momentos fica de fora. */
export function guardado(videos: VideoDoResultado[]): VideoGuardado[] {
  return videos
    .filter((v) => v.momentos.length > 0)
    .map((v) => ({
      job_id: v.job_id,
      momentos: v.momentos.map((m) => ({ inicio_ms: m.inicio_ms, fim_ms: m.fim_ms, motivo: m.motivo })),
    }))
}

export function guardarResultado(q: string, videos: VideoGuardado[]) {
  try {
    sessionStorage.setItem(CHAVE, JSON.stringify({ q, videos }))
  } catch {
    // Sem armazenamento (modo privado, cota cheia): a tela refaz a busca.
  }
}

/** O resultado guardado para esta consulta; `null` se não há ou é de outra. */
export function lerResultado(q: string): VideoGuardado[] | null {
  try {
    const bruto = sessionStorage.getItem(CHAVE)
    const lido: unknown = bruto ? JSON.parse(bruto) : null
    if (typeof lido !== 'object' || lido === null) return null
    const { q: guardada, videos } = lido as { q?: unknown; videos?: unknown }
    return guardada === q && Array.isArray(videos) ? (videos as VideoGuardado[]) : null
  } catch {
    return null
  }
}

/** "Busca: sapato vermelho (4)": os momentos do resultado neste vídeo. */
export const rotuloDaBusca = (q: string, momentos: number): string => `Busca: ${q} (${momentos})`

/** O momento que o instante `atualMs` está dentro, ou o último que já começou. */
export function momentoAtual(momentos: MomentoGuardado[], atualMs: number): number | null {
  let achado: number | null = null
  momentos.forEach((m, i) => {
    if (m.inicio_ms <= atualMs + FOLGA_MS && (achado === null || m.inicio_ms >= momentos[achado].inicio_ms)) achado = i
  })
  return achado !== null && atualMs <= momentos[achado].fim_ms + FOLGA_MS ? achado : null
}

export interface Destino {
  job_id: string
  inicio_ms: number
}

/**
 * O momento seguinte (`passo` 1) ou anterior (-1) ao instante `atualMs` do vídeo `jobId`, também
 * entre vídeos: no último momento do vídeo vai ao primeiro do vídeo seguinte do resultado, no primeiro
 * volta ao último do anterior. `null` no fim e no começo do resultado, ou se o vídeo não está nele.
 */
export function passoNoResultado(
  videos: VideoGuardado[],
  jobId: string,
  atualMs: number,
  passo: 1 | -1,
): Destino | null {
  const v = videos.findIndex((x) => x.job_id === jobId)
  if (v < 0) return null
  const doVideo = videos[v].momentos
  const daqui =
    passo === 1
      ? doVideo.find((m) => m.inicio_ms > atualMs + FOLGA_MS)
      : [...doVideo].reverse().find((m) => m.inicio_ms < atualMs - FOLGA_MS)
  if (daqui) return { job_id: jobId, inicio_ms: daqui.inicio_ms }
  const outro = videos[v + passo]
  if (!outro) return null
  const m = passo === 1 ? outro.momentos[0] : outro.momentos[outro.momentos.length - 1]
  return { job_id: outro.job_id, inicio_ms: m.inicio_ms }
}
