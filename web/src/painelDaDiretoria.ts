// O painel da diretoria (E9): o que a API devolve, os filtros comuns (que viajam na URL e na chamada)
// e as abas. Não confundir com `painel.ts`, o painel da decupagem no Visualizador.

export type AbaDoPainel = 'acessos'

export const ABAS_DO_PAINEL: { chave: AbaDoPainel; rotulo: string }[] = [{ chave: 'acessos', rotulo: 'Acessos' }]

export interface FiltrosDoPainel {
  programa: string
  /** O uid de quem se quer ver. */
  usuario: string
  /** Período, em `AAAA-MM-DD` (dia de São Paulo), inclusive. */
  de: string
  ate: string
}

export const SEM_FILTROS_DO_PAINEL: FiltrosDoPainel = { programa: '', usuario: '', de: '', ate: '' }

const DATA = /^\d{4}-\d{2}-\d{2}$/

/** Os filtros da query do endereço; data malformada de um link editado à mão sai. */
export function filtrosDoPainel(busca: string): FiltrosDoPainel {
  const p = new URLSearchParams(busca)
  const data = (nome: string) => {
    const valor = p.get(nome) ?? ''
    return DATA.test(valor) ? valor : ''
  }
  return { programa: p.get('programa') ?? '', usuario: p.get('usuario') ?? '', de: data('de'), ate: data('ate') }
}

/** A query do endereço da tela (vazia sem filtros). */
export function filtrosParaEnderecoDoPainel(f: FiltrosDoPainel): string {
  const p = new URLSearchParams()
  if (f.programa) p.set('programa', f.programa)
  if (f.usuario) p.set('usuario', f.usuario)
  if (f.de) p.set('de', f.de)
  if (f.ate) p.set('ate', f.ate)
  const query = p.toString()
  return query ? `?${query}` : ''
}

/**
 * A query de `GET /v1/painel/...`. Os acessos não têm programa: a API recusa o pedido com
 * `programa`, então a aba Acessos pede sem ele (`semPrograma`).
 */
export function parametrosDoPainel(f: FiltrosDoPainel, opcoes: { csv?: boolean; semPrograma?: boolean } = {}): string {
  const p = new URLSearchParams()
  if (f.programa && !opcoes.semPrograma) p.set('programa', f.programa)
  if (f.usuario) p.set('usuario', f.usuario)
  if (f.de) p.set('desde', f.de)
  if (f.ate) p.set('ate', f.ate)
  if (opcoes.csv) p.set('formato', 'csv')
  return p.toString()
}

export function periodoInvertidoNoPainel(f: FiltrosDoPainel): boolean {
  return f.de !== '' && f.ate !== '' && f.de > f.ate
}

/** Um item de `GET /v1/painel/filtros`: quem aparece no filtro de usuário. */
export interface UsuarioDoFiltro {
  uid: string
  email: string | null
}

export interface OpcoesDoPainel {
  programas: string[]
  usuarios: UsuarioDoFiltro[]
}

export interface DiaDeAcessos {
  dia: string
  acessos: number
  usuarios_ativos: number
}

export interface UsuarioDeAcessos {
  uid: string
  email: string | null
  acessos: number
  dias_ativos: number
  ultimo_acesso: string | null
}

/** Uma semana (começa na segunda) ou um mês (começa no dia 1): `inicio` é o primeiro dia. */
export interface AtivosNoPeriodo {
  inicio: string
  usuarios_ativos: number
}

/** `GET /v1/painel/acessos`. */
export interface RelatorioDeAcessos {
  desde: string | null
  ate: string | null
  usuario: string | null
  total: { acessos: number; usuarios_ativos: number }
  por_dia: DiaDeAcessos[]
  por_semana: AtivosNoPeriodo[]
  por_mes: AtivosNoPeriodo[]
  por_usuario: UsuarioDeAcessos[]
}

/** "03/11" para `2026-11-03`. */
export function diaCurto(dia: string): string {
  const [, mes, d] = dia.split('-')
  return `${d}/${mes}`
}

/** "11/2026" para `2026-11-01`. */
export function mesCurto(dia: string): string {
  const [ano, mes] = dia.split('-')
  return `${mes}/${ano}`
}

/** "03/11/2026" para `2026-11-03`. */
export function diaCompleto(dia: string): string {
  const [ano, mes, d] = dia.split('-')
  return `${d}/${mes}/${ano}`
}
