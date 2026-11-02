// O relatório de tempo de tela: o que a API devolve e os filtros, que viajam na URL e na chamada.

export interface VideoDaPessoa {
  job_id: string
  nome: string | null
  tempo_de_tela_ms: number
  aparicoes: number
  mencoes_na_fala: number
  mencoes_no_texto: number
}

export interface PessoaNoRelatorio {
  pessoa_id: string
  nome: string
  tempo_de_tela_ms: number
  videos: number
  aparicoes: number
  mencoes_na_fala: number
  mencoes_no_texto: number
  por_video: VideoDaPessoa[]
}

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

export const SEM_FILTROS_DO_RELATORIO: FiltrosDoRelatorio = { programa: '', de: '', ate: '' }

const DATA = /^\d{4}-\d{2}-\d{2}$/

/** Os filtros da query do endereço; data malformada de um link editado à mão sai. */
export function filtrosDoRelatorio(busca: string): FiltrosDoRelatorio {
  const p = new URLSearchParams(busca)
  const data = (nome: string) => {
    const valor = p.get(nome) ?? ''
    return DATA.test(valor) ? valor : ''
  }
  return { programa: p.get('programa') ?? '', de: data('de'), ate: data('ate') }
}

/** A query do endereço da tela (vazia sem filtros). */
export function filtrosParaEndereco(f: FiltrosDoRelatorio): string {
  const p = new URLSearchParams()
  if (f.programa) p.set('programa', f.programa)
  if (f.de) p.set('de', f.de)
  if (f.ate) p.set('ate', f.ate)
  const query = p.toString()
  return query ? `?${query}` : ''
}

/** A query de `GET /v1/relatorios/tempo-de-tela` para estes filtros. */
export function parametrosDoRelatorio(f: FiltrosDoRelatorio, formato?: 'csv'): string {
  const p = new URLSearchParams()
  if (f.programa) p.set('programa', f.programa)
  if (f.de) p.set('desde', f.de)
  if (f.ate) p.set('ate', f.ate)
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
