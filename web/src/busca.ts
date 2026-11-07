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
  /** `null`: o período entendido; `'todos'`: nenhum período. */
  ano: number | 'todos' | null
  /** Faceta de mês (`2024-05`): vale sobre o ano. */
  mes: string | null
  /** Facetas de pessoa (id do catálogo), marca e tipo de momento: `null`, sem filtro. */
  pessoa: string | null
  marca: string | null
  tipo: TipoDeMomento | null
  ordem: OrdemDaBusca
}

export type TipoDeMomento = 'plano' | 'fala' | 'texto_na_tela' | 'objeto'
const TIPOS_DE_MOMENTO: string[] = ['plano', 'fala', 'texto_na_tela', 'objeto']
const MES = /^(\d{4})-(0[1-9]|1[0-2])$/

export interface Destaque {
  inicio: number
  fim: number
}

export interface Momento {
  tipo: TipoDeMomento
  inicio_ms: number
  fim_ms: number
  motivo: string
  destaques: Destaque[]
  /** URL assinada: só chave de sistema a recebe; a web a pede pela rota do quadro (`quadro`). */
  quadro_url: string | null
  /** Caminho do quadro no vídeo (`quadros/plano-6.jpg`). */
  quadro: string | null
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
  /** `null`: o nome que o catálogo não resolve. */
  pessoa_id: string | null
  nome: string
  mencoes_na_fala: number
  mencoes_na_tela: number
}

/** Um valor de faceta e em quantos vídeos dos candidatos da busca ele aparece. */
export interface ValorDaFaceta {
  valor: string
  rotulo: string
  videos: number
}

export type NomeDaFaceta = 'programa' | 'mes' | 'pessoa' | 'marca' | 'tipo'
export type Facetas = Record<NomeDaFaceta, ValorDaFaceta[]>

export interface ResultadoDaBusca {
  entendida: {
    evidencias: Evidencia[]
    programa: string | null
    desde: string | null
    ate: string | null
    /** Só na busca por foto: o termo que o modelo deu para o objeto e que a busca usou. */
    termo_da_foto?: string | null
  }
  videos: VideoDoResultado[]
  sem_aparicoes: SemAparicao[]
  plano_b: boolean
  facetas: Facetas
}

const IDS_DE_EVIDENCIA: string[] = EVIDENCIAS.map((e) => e.id)

/** O teto do texto da busca: a API dá 422 com mais que isso (#372). */
export const TAMANHO_DA_CONSULTA = 300

/** A busca de um texto novo: chips e filtros voltam ao que a API entender. */
export function consultaNova(q: string): ConsultaDaBusca {
  return {
    q,
    evidencias: null,
    programa: null,
    ano: null,
    mes: null,
    pessoa: null,
    marca: null,
    tipo: null,
    ordem: 'relevancia',
  }
}

export function consultaDaBusca(busca: string): ConsultaDaBusca {
  const p = new URLSearchParams(busca)
  const ev = [...new Set(p.getAll('ev'))].filter((e): e is Evidencia => IDS_DE_EVIDENCIA.includes(e))
  const ano = p.get('ano') === 'todos' ? 'todos' : Number(p.get('ano'))
  return {
    q: p.get('q')?.trim() ?? '',
    evidencias: ev.length ? ev : null,
    programa: p.get('programa'),
    ano: ano === 'todos' || (Number.isInteger(ano) && ano >= 1900 && ano <= 2999) ? ano : null,
    mes: MES.test(p.get('mes') ?? '') ? p.get('mes') : null,
    pessoa: p.get('pessoa') || null,
    marca: p.get('marca') || null,
    tipo: TIPOS_DE_MOMENTO.includes(p.get('tipo') ?? '') ? (p.get('tipo') as TipoDeMomento) : null,
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
  if (c.mes !== null) p.set('mes', c.mes)
  if (c.pessoa !== null) p.set('pessoa', c.pessoa)
  if (c.marca !== null) p.set('marca', c.marca)
  if (c.tipo !== null) p.set('tipo', c.tipo)
  if (c.ordem !== 'relevancia') p.set('ordem', c.ordem)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

/** O programa e o período da consulta, como a API os recebe (a busca por texto e a por imagem). */
function filtrosParaApi(p: URLSearchParams, c: ConsultaDaBusca) {
  if (c.programa !== null) p.set('programa', c.programa)
  const mes = MES.exec(c.mes ?? '')
  if (mes) {
    // O dia 0 do mês seguinte é o último deste.
    const ultimo = new Date(Date.UTC(Number(mes[1]), Number(mes[2]), 0)).getUTCDate()
    p.set('desde', `${c.mes}-01`)
    p.set('ate', `${c.mes}-${String(ultimo).padStart(2, '0')}`)
  } else if (c.ano === 'todos') p.set('sem_periodo', 'true')
  else if (c.ano !== null) {
    p.set('desde', `${c.ano}-01-01`)
    p.set('ate', `${c.ano}-12-31`)
  }
}

/** A query de `POST /v1/busca/imagem`: só programa e período valem (a foto é a consulta). */
export function consultaDaImagemParaApi(c: ConsultaDaBusca, limite: number): string {
  const p = new URLSearchParams({ limite: String(limite) })
  filtrosParaApi(p, c)
  return p.toString()
}

/** A query de `GET /v1/busca`. */
export function consultaParaApi(c: ConsultaDaBusca, limite: number): string {
  const p = new URLSearchParams({ q: c.q, ordem: c.ordem, limite: String(limite) })
  for (const e of c.evidencias ?? []) p.append('ev', e)
  filtrosParaApi(p, c)
  if (c.pessoa !== null) p.set('pessoa', c.pessoa)
  if (c.marca !== null) p.set('marca', c.marca)
  if (c.tipo !== null) p.set('tipo', c.tipo)
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
