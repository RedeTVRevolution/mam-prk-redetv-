import { ESTADOS_DO_JOB } from './tema.ts'

// O que a API mostra de um Job e os filtros do acervo, que viajam na URL e na chamada.

export interface Job {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  duracao_s?: number | null
  /** Timecode do primeiro quadro do arquivo (`HH:MM:SS:FF`, ou `;FF` no drop-frame). */
  timecode_origem?: string | null
  taxa_de_quadros?: number | null
  programa?: string | null
  data_exibicao?: string | null
  enviado_por?: { tipo: 'pessoa' | 'sistema'; nome: string | null }
  criado_em: string
}

export interface JobCriado extends Job {
  url_de_upload: string
}

export type Ordem = 'enviado' | 'exibicao'

export interface FiltrosDoAcervo {
  q: string
  programa: string
  de: string
  ate: string
  estado: string[]
  ordem: Ordem
}

export const SEM_FILTROS: FiltrosDoAcervo = {
  q: '',
  programa: '',
  de: '',
  ate: '',
  estado: [],
  ordem: 'enviado',
}

/** Uma página do acervo; `proximo` é o cursor da seguinte, ausente na última. */
export interface PaginaDoAcervo {
  jobs: Job[]
  proximo: string | null
}

export const POR_PAGINA = 50

export function haFiltro(f: FiltrosDoAcervo): boolean {
  return Boolean(f.q || f.programa || f.de || f.ate || f.estado.length)
}

/** Os filtros na query da URL do app (`/acervo?q=&programa=&de=&ate=&estado=&ordem=`). */
export function filtrosParaBusca(f: FiltrosDoAcervo): string {
  const p = new URLSearchParams()
  if (f.q) p.set('q', f.q)
  if (f.programa) p.set('programa', f.programa)
  if (f.de) p.set('de', f.de)
  if (f.ate) p.set('ate', f.ate)
  for (const e of f.estado) p.append('estado', e)
  if (f.ordem !== SEM_FILTROS.ordem) p.set('ordem', f.ordem)
  const texto = p.toString()
  return texto ? `?${texto}` : ''
}

const DATA = /^\d{4}-\d{2}-\d{2}$/

export function filtrosDaBusca(busca: string): FiltrosDoAcervo {
  const p = new URLSearchParams(busca)
  const data = (nome: string) => {
    const valor = p.get(nome) ?? ''
    return DATA.test(valor) ? valor : ''
  }
  return {
    q: p.get('q') ?? '',
    programa: p.get('programa') ?? '',
    de: data('de'),
    ate: data('ate'),
    // Estado desconhecido num link editado à mão sai do filtro, em vez de fazer a API recusar.
    estado: [...new Set(p.getAll('estado'))].filter((e) => Object.hasOwn(ESTADOS_DO_JOB, e)),
    ordem: p.get('ordem') === 'exibicao' ? 'exibicao' : 'enviado',
  }
}

/** A query de `GET /v1/jobs` para estes filtros. */
export function filtrosParaApi(f: FiltrosDoAcervo, cursor: string | null): string {
  const p = new URLSearchParams({ limite: String(POR_PAGINA), ordem: f.ordem })
  if (f.q) p.set('q', f.q)
  if (f.programa) p.set('programa', f.programa)
  if (f.de) p.set('exibicao_de', f.de)
  if (f.ate) p.set('exibicao_ate', f.ate)
  for (const e of f.estado) p.append('estado', e)
  if (cursor) p.set('cursor', cursor)
  return p.toString()
}
