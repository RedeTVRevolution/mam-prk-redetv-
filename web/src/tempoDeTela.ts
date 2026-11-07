// O relatório de tempo de tela: o que a API devolve e os filtros, que viajam na URL e na chamada.

import { periodoDoEndereco, poePeriodoNaConsulta, poePeriodoNoEndereco } from './periodoPadrao.ts'

export interface VideoDaPessoa {
  job_id: string
  nome: string | null
  tempo_de_tela_ms: number
  aparicoes: number
  mencoes_na_fala: number
  mencoes_no_texto: number
}

export interface PessoaResumida {
  pessoa_id: string
  nome: string
  tempo_de_tela_ms: number
  videos: number
  aparicoes: number
  mencoes_na_fala: number
  mencoes_no_texto: number
}

export interface PessoaNoRelatorio extends PessoaResumida {
  por_video: VideoDaPessoa[]
}

/** O período inteiro, não só a página: os números dos cartões. */
export interface TotalDoTempoDeTela {
  pessoas: number
  tempo_de_tela_ms: number
  videos: number
  aparicoes: number
  mencoes_na_fala: number
  mencoes_no_texto: number
}

/** Uma página do ranking (`limite` na API), sem os vídeos; `proximo` é o cursor da seguinte. */
export interface PaginaDoTempoDeTela {
  programa: string | null
  desde: string | null
  ate: string | null
  total: TotalDoTempoDeTela
  pessoas: PessoaResumida[]
  proximo: string | null
}

/** Uma página dos vídeos de uma pessoa. */
export interface PaginaDeVideos {
  videos: VideoDaPessoa[]
  proximo: string | null
}

/** Pessoas por página do ranking e vídeos por página do detalhe (o teto da API é 100). */
export const POR_PAGINA_DO_RANKING = 50
export const POR_PAGINA_DO_DETALHE = 25

export interface RelatorioDeTempoDeTela {
  programa: string | null
  desde: string | null
  ate: string | null
  pessoas: PessoaNoRelatorio[]
}

export interface FiltrosDoRelatorio {
  programa: string
  de: string
  ate: string
}


/** Os filtros da query do endereço; data malformada de um link editado à mão sai. */
export function filtrosDoRelatorio(busca: string): FiltrosDoRelatorio {
  const p = new URLSearchParams(busca)
  return { programa: p.get('programa') ?? '', ...periodoDoEndereco(p) }
}

/** A query do endereço da tela (o período vai sempre, vazio inclusive, para não cair no padrão); `extras` são os filtros próprios de cada relatório. */
export function filtrosParaEndereco(f: FiltrosDoRelatorio, extras: Record<string, string> = {}): string {
  const p = new URLSearchParams()
  if (f.programa) p.set('programa', f.programa)
  poePeriodoNoEndereco(p, f)
  for (const [nome, valor] of Object.entries(extras)) if (valor) p.set(nome, valor)
  return `?${p}`
}

/** A query de `GET /v1/relatorios/...` para estes filtros (`extras`: os próprios de cada relatório). */
export function parametrosDoRelatorio(
  f: FiltrosDoRelatorio,
  formato?: 'csv',
  extras: Record<string, string> = {},
): string {
  const p = new URLSearchParams()
  if (f.programa) p.set('programa', f.programa)
  poePeriodoNaConsulta(p, f)
  for (const [nome, valor] of Object.entries(extras)) if (valor) p.set(nome, valor)
  if (formato) p.set('formato', formato)
  return p.toString()
}

/** "1h02min", "12min05s" ou "45s": o tempo de tela legível. */
export function duracaoLegivel(ms: number): string {
  const total = Math.round(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}min`
  if (m > 0) return `${m}min${String(s).padStart(2, '0')}s`
  return `${s}s`
}
