// O painel da diretoria (E9): o que a API devolve, os filtros comuns (que viajam na URL e na chamada)
// e as abas. Não confundir com `painel.ts`, o painel da decupagem no Visualizador.

export type AbaDoPainel = 'acessos' | 'videos' | 'buscas' | 'revisao' | 'api'

export const ABAS_DO_PAINEL: { chave: AbaDoPainel; rotulo: string }[] = [
  { chave: 'acessos', rotulo: 'Acessos' },
  { chave: 'videos', rotulo: 'Vídeos' },
  { chave: 'buscas', rotulo: 'Buscas' },
  { chave: 'revisao', rotulo: 'Revisão' },
  { chave: 'api', rotulo: 'API' },
]

/** A aba do endereço (`/painel/<aba>`); vazia é Acessos, e `null` é aba que não existe. */
export function abaDoPainel(parte: string | undefined): AbaDoPainel | null {
  if (parte === undefined) return 'acessos'
  return ABAS_DO_PAINEL.find((a) => a.chave === parte)?.chave ?? null
}

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

/** Vídeos e Buscas leem tabelas que não se cruzam: a API recusa programa e usuário juntos (422). */
export function programaEUsuarioJuntos(f: FiltrosDoPainel): boolean {
  return f.programa !== '' && f.usuario !== ''
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

/** Os números de vídeos de um recorte. O tempo médio é o de processamento dos concluídos, vazio sem nenhum. */
export interface NumerosDeVideos {
  enviados: number
  concluidos: number
  falhos: number
  horas_concluidas: number
  tempo_medio_s: number | null
}

export interface DiaDeVideos extends NumerosDeVideos {
  dia: string
}

export interface ProgramaDeVideos extends NumerosDeVideos {
  programa: string
}

export interface QuemDeVideos extends NumerosDeVideos {
  quem_tipo: 'usuario' | 'sistema'
  quem_id: string
  email: string | null
}

/** `GET /v1/painel/videos`. `por_programa` vem vazio com filtro de usuário e `por_usuario` com filtro de programa. */
export interface RelatorioDeVideos {
  desde: string | null
  ate: string | null
  programa: string | null
  usuario: string | null
  total: NumerosDeVideos
  por_dia: DiaDeVideos[]
  por_programa: ProgramaDeVideos[]
  por_usuario: QuemDeVideos[]
}

export interface NumerosDeBuscas {
  buscas: number
  sem_resultado: number
}

/** `usuarios_que_buscam` é `null` com filtro de programa: a tabela por programa não sabe quem buscou. */
export interface DiaDeBuscas extends NumerosDeBuscas {
  dia: string
  usuarios_que_buscam: number | null
}

export interface QuemDeBuscas extends NumerosDeBuscas {
  quem_tipo: 'usuario' | 'sistema'
  quem_id: string
  email: string | null
}

/** `GET /v1/painel/buscas`. */
export interface RelatorioDeBuscas {
  desde: string | null
  ate: string | null
  programa: string | null
  usuario: string | null
  total: NumerosDeBuscas & { usuarios_que_buscam: number | null }
  por_dia: DiaDeBuscas[]
  por_usuario: QuemDeBuscas[]
}

/** As horas de vídeo com uma casa e vírgula: "3,5". */
export function horasDeVideo(horas: number): string {
  return horas.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 1 })
}

export interface DiaDeCorrecoes {
  dia: string
  correcoes: number
}

/** `tipo` é `null` no evento que não trouxe o tipo da correção. */
export interface TipoDeCorrecoes {
  tipo: string | null
  correcoes: number
}

export interface QuemDeCorrecoes {
  quem_tipo: 'usuario' | 'sistema'
  quem_id: string
  email: string | null
  correcoes: number
}

export interface TaxaDoTipo {
  tipo: string
  correcoes: number
  itens: number
  taxa: number | null
}

export interface TaxaDoPrograma {
  programa: string | null
  correcoes: number
  itens: number
  taxa: number | null
}

/** O tempo ativo de revisão; `minutos_por_hora_de_video` vem `null` sem vídeo de duração conhecida. */
export interface NumerosDeRevisao {
  minutos: number
  videos: number
  horas_de_video: number
  minutos_por_hora_de_video: number | null
}

export interface PessoaNaRevisao extends NumerosDeRevisao {
  uid: string
  email: string
}

export interface ProgramaNaRevisao extends NumerosDeRevisao {
  programa: string | null
}

/** `GET /v1/painel/revisao`. A taxa vem vazia com filtro de usuário (ela não tem pessoa). */
export interface RelatorioDeRevisao {
  desde: string | null
  ate: string | null
  programa: string | null
  usuario: string | null
  correcoes: {
    total: number
    por_dia: DiaDeCorrecoes[]
    por_tipo: TipoDeCorrecoes[]
    por_usuario: QuemDeCorrecoes[]
  }
  taxa_de_correcao: { por_tipo: TaxaDoTipo[]; por_programa: TaxaDoPrograma[] }
  tempo_de_revisao: {
    total: NumerosDeRevisao
    por_pessoa: PessoaNaRevisao[]
    por_programa: ProgramaNaRevisao[]
  }
}

export interface NumerosDeChamadas {
  chamadas: number
  erros_do_cliente: number
  erros_do_servidor: number
}

export interface DiaDeApi extends NumerosDeChamadas {
  dia: string
  videos_enviados: number
}

export interface SistemaDeApi extends NumerosDeChamadas {
  quem_tipo: 'usuario' | 'sistema'
  quem_id: string
  videos_enviados: number
}

export interface RotaDeApi extends NumerosDeChamadas {
  metodo: string | null
  rota: string | null
}

/** `GET /v1/painel/api`. `videos_enviados` são só os enviados por sistema. */
export interface RelatorioDeApi {
  desde: string | null
  ate: string | null
  usuario: string | null
  total: NumerosDeChamadas & { sistemas: number; videos_enviados: number }
  por_dia: DiaDeApi[]
  por_sistema: SistemaDeApi[]
  por_rota: RotaDeApi[]
}

/** A taxa em porcentagem com uma casa: "12,5%"; sem taxa, um traço. */
export function taxaLegivel(taxa: number | null): string {
  if (taxa === null) return '—'
  return `${(taxa * 100).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 1 })}%`
}

/** Minutos com uma casa e vírgula: "12,5". */
export function minutosLegiveis(minutos: number): string {
  return minutos.toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 1 })
}
