// A busca sem React: o estado da tela na URL, a chamada à API e o destaque montado por posição.

export type Evidencia = 'imagem' | 'citada' | 'fala' | 'gc' | 'objeto' | 'marca'
export type OrdemDaBusca = 'relevancia' | 'data'

/** Os chips, na ordem da tela, e o tipo de ocorrência cuja cor cada um leva. */
export const EVIDENCIAS = [
  { id: 'imagem', rotulo: 'Na imagem', tipo: 'aparicao' },
  { id: 'citada', rotulo: 'Citada', tipo: 'mencao' },
  { id: 'fala', rotulo: 'Fala', tipo: 'fala' },
  { id: 'gc', rotulo: 'GC', tipo: 'texto_na_tela' },
  { id: 'objeto', rotulo: 'Objeto', tipo: 'objeto' },
  { id: 'marca', rotulo: 'Marca', tipo: 'comercial' },
] as const

/** O que a URL guarda: sem `ev`, ficam as evidências que a API entendeu da consulta. */
export interface ConsultaDaBusca {
  q: string
  evidencias: Evidencia[] | null
  /** `null`: o programa entendido; `''`: nenhum programa. */
  programa: string | null
  ano: number | null
  ordem: OrdemDaBusca
}

export interface Destaque {
  inicio: number
  fim: number
}

export interface Momento {
  inicio_ms: number
  fim_ms: number
  motivo: string
  destaques: Destaque[]
  quadro_url: string | null
}

export interface VideoDoResultado {
  job_id: string
  nome: string
  programa: string | null
  data_exibicao: string | null
  duracao_s: number | null
  n_momentos: number
  momentos: Momento[]
}

export interface SemAparicao {
  pessoa_id: string
  nome: string
  mencoes_na_fala: number
  mencoes_na_tela: number
}

export interface ResultadoDaBusca {
  entendida: { evidencias: Evidencia[]; programa: string | null; desde: string | null; ate: string | null }
  videos: VideoDoResultado[]
  sem_aparicoes: SemAparicao[]
  plano_b: boolean
}

const IDS_DE_EVIDENCIA: string[] = EVIDENCIAS.map((e) => e.id)

export function consultaDaBusca(busca: string): ConsultaDaBusca {
  const p = new URLSearchParams(busca)
  const ev = [...new Set(p.getAll('ev'))].filter((e): e is Evidencia => IDS_DE_EVIDENCIA.includes(e))
  const ano = Number(p.get('ano'))
  return {
    q: p.get('q')?.trim() ?? '',
    evidencias: ev.length ? ev : null,
    programa: p.get('programa'),
    ano: Number.isInteger(ano) && ano >= 1900 && ano <= 2999 ? ano : null,
    ordem: p.get('ordem') === 'data' ? 'data' : 'relevancia',
  }
}

/** A query da URL do app (`?q=&ev=&programa=&ano=&ordem=`). */
export function consultaParaEndereco(c: ConsultaDaBusca): string {
  const p = new URLSearchParams()
  if (c.q) p.set('q', c.q)
  for (const e of c.evidencias ?? []) p.append('ev', e)
  if (c.programa !== null) p.set('programa', c.programa)
  if (c.ano !== null) p.set('ano', String(c.ano))
  if (c.ordem !== 'relevancia') p.set('ordem', c.ordem)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

/** A query de `GET /v1/busca`. */
export function consultaParaApi(c: ConsultaDaBusca, limite: number): string {
  const p = new URLSearchParams({ q: c.q, ordem: c.ordem, limite: String(limite) })
  for (const e of c.evidencias ?? []) p.append('ev', e)
  if (c.programa !== null) p.set('programa', c.programa)
  if (c.ano !== null) {
    p.set('desde', `${c.ano}-01-01`)
    p.set('ate', `${c.ano}-12-31`)
  }
  return p.toString()
}

export interface Trecho {
  texto: string
  destacado: boolean
}

/**
 * Parte o motivo nos trechos destacados. As posições da API são em caracteres (pontos de código),
 * não em unidades UTF-16; posição fora do texto ou sobreposta é ignorada. O resultado é só texto:
 * quem desenha o põe como filho de `<mark>`, nunca como HTML.
 */
export function trechosDoMotivo(motivo: string, destaques: Destaque[]): Trecho[] {
  const letras = Array.from(motivo)
  const trechos: Trecho[] = []
  let cursor = 0
  for (const d of [...destaques].sort((a, b) => a.inicio - b.inicio)) {
    const inicio = Math.max(d.inicio, cursor)
    const fim = Math.min(d.fim, letras.length)
    if (inicio >= fim) continue
    if (inicio > cursor) trechos.push({ texto: letras.slice(cursor, inicio).join(''), destacado: false })
    trechos.push({ texto: letras.slice(inicio, fim).join(''), destacado: true })
    cursor = fim
  }
  if (cursor < letras.length) trechos.push({ texto: letras.slice(cursor).join(''), destacado: false })
  return trechos
}

/** "1 momento", "38 momentos". */
export function contagemDeMomentos(n: number): string {
  return `${n} momento${n === 1 ? '' : 's'}`
}

/** "1 vídeo", "11 vídeos". */
export function contagemDeVideos(n: number): string {
  return `${n} vídeo${n === 1 ? '' : 's'}`
}

/** "1 menção", "12 menções". */
export function contagemDeMencoes(n: number): string {
  return n === 1 ? '1 menção' : `${n} menções`
}
