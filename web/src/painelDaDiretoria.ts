// O painel da diretoria (E9): o que a API devolve, os filtros comuns (que viajam na URL e na chamada)
// e as abas. Não confundir com `painel.ts`, o painel da decupagem no Visualizador.

import { periodoDoEndereco, poePeriodoNaConsulta, poePeriodoNoEndereco } from './periodoPadrao.ts'

export type AbaDoPainel = 'acessos' | 'videos' | 'buscas' | 'revisao' | 'api' | 'custo'

export const ABAS_DO_PAINEL: { chave: AbaDoPainel; rotulo: string }[] = [
  { chave: 'acessos', rotulo: 'Acessos' },
  { chave: 'videos', rotulo: 'Vídeos' },
  { chave: 'buscas', rotulo: 'Buscas' },
  { chave: 'revisao', rotulo: 'Revisão' },
  { chave: 'api', rotulo: 'API' },
  { chave: 'custo', rotulo: 'Custo' },
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
  /** O grupo dos gráficos no endereço; ausente é o automático. */
  agrupar?: PedidoDeAgrupamento
}


/** Os filtros da query do endereço; data malformada de um link editado à mão sai. */
export function filtrosDoPainel(busca: string): FiltrosDoPainel {
  const p = new URLSearchParams(busca)
  const agrupar = p.get('agrupar') as PedidoDeAgrupamento
  return {
    programa: p.get('programa') ?? '',
    usuario: p.get('usuario') ?? '',
    ...periodoDoEndereco(p),
    ...(GRUPOS_PEDIDOS.includes(agrupar) ? { agrupar } : {}),
  }
}

/** A query do endereço da tela (o período vai sempre, vazio inclusive, para não cair no padrão). */
export function filtrosParaEnderecoDoPainel(f: FiltrosDoPainel): string {
  const p = new URLSearchParams()
  if (f.programa) p.set('programa', f.programa)
  if (f.usuario) p.set('usuario', f.usuario)
  poePeriodoNoEndereco(p, f)
  if (f.agrupar && f.agrupar !== 'auto') p.set('agrupar', f.agrupar)
  return `?${p}`
}

/** Vídeos e Buscas leem tabelas que não se cruzam: a API recusa programa e usuário juntos (422). */
export function programaEUsuarioJuntos(f: FiltrosDoPainel): boolean {
  return f.programa !== '' && f.usuario !== ''
}

/**
 * A query de `GET /v1/painel/...`. Os acessos não têm programa: a API recusa o pedido com
 * `programa`, então a aba Acessos pede sem ele (`semPrograma`).
 */
export function parametrosDoPainel(
  f: FiltrosDoPainel,
  opcoes: { csv?: boolean; semPrograma?: boolean; agrupar?: PedidoDeAgrupamento } = {},
): string {
  const p = new URLSearchParams()
  if (f.programa && !opcoes.semPrograma) p.set('programa', f.programa)
  if (f.usuario) p.set('usuario', f.usuario)
  poePeriodoNaConsulta(p, f)
  if (opcoes.csv) p.set('formato', 'csv')
  if (opcoes.agrupar) p.set('agrupar', opcoes.agrupar)
  return p.toString()
}

/**
 * O grupo dos gráficos no tempo (#428): com `agrupar`, o `por_dia` da resposta vem somado por
 * grupo e o `dia` é o primeiro dia dele; o `auto` escolhe pelo tamanho do período (até ~90 pontos).
 */
export type Agrupamento = 'dia' | 'semana' | 'mes' | 'trimestre'
export type PedidoDeAgrupamento = Agrupamento | 'auto'
const GRUPOS_PEDIDOS: readonly (string | null)[] = ['auto', 'dia', 'semana', 'mes', 'trimestre']
export type Agrupado<T> = T & { agrupamento: Agrupamento }

/** Os Jobs em andamento num estado, lidos na hora (`GET /v1/painel/fila`, #420). */
export interface EstadoNaFila {
  estado: 'aguardando_upload' | 'validando' | 'analisando'
  quantidade: number
  /** Desde a criação do Job; 0 sem Job no estado. */
  idade_do_mais_antigo_s: number
}

export interface FilaAgora {
  por_estado: EstadoNaFila[]
  esperando_gpu?: { quantidade: number; idade_do_mais_antigo_s: number }
}

/** Um item de `GET /v1/painel/filtros`: quem aparece no filtro de usuário. */
export interface UsuarioDoFiltro {
  uid: string
  email: string | null
}

export interface OpcoesDoPainel {
  programas: string[]
  usuarios: UsuarioDoFiltro[]
  /** Os sistemas (chaves de API) com eventos; só a aba API os oferece (#524). */
  sistemas: string[]
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
  /** `null` é a linha "Sem programa". */
  programa: string | null
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

export interface NumerosDeCusto {
  custo: number
  videos: number
  horas_de_video: number
  custo_por_hora: number | null
}

export interface TotalDeCusto extends NumerosDeCusto {
  custo_dos_jobs: number
  custo_sem_dono: number
}

export interface MesDeCusto extends TotalDeCusto {
  mes: string
}

export interface QuemDeCusto extends NumerosDeCusto {
  quem_tipo: 'usuario' | 'sistema'
  quem_id: string
  email: string | null
}

/** `GET /v1/painel/custo`. `custo` é o líquido dos créditos, na `moeda` da exportação (`null` sem linha). */
export interface RelatorioDeCusto {
  desde: string | null
  ate: string | null
  programa: string | null
  usuario: string | null
  moeda: string | null
  /** O dia (AAAA-MM-DD) da última linha do faturamento no período; `null` sem linha. */
  faturamento_ate: string | null
  total: TotalDeCusto
  por_mes: MesDeCusto[]
  por_quem: QuemDeCusto[]
  por_etapa: { etapa: string; custo: number }[]
  sem_dono_por_servico: { servico: string | null; custo: number }[]
}

/** O custo em centavos, sem sinal no zero: abaixo de meio centavo, em módulo, vira 0 (nunca −0). Gráfico e texto passam por aqui. */
export function emCentavos(valor: number): number {
  return Math.round(valor * 100) / 100 + 0
}

/** O custo com duas casas e a moeda da exportação: "R$ 12,50" (BRL) ou "12,50 USD". */
export function custoLegivel(bruto: number, moeda: string | null): string {
  const valor = emCentavos(bruto)
  if (moeda === 'BRL') return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
  const numero = valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return moeda ? `${numero} ${moeda}` : numero
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

/** O nome do grupo depois de "por": "Logins por semana". */
export const NOME_DO_GRUPO: Record<Agrupamento, string> = { dia: 'dia', semana: 'semana', mes: 'mês', trimestre: 'trimestre' }

/** A coluna do grupo na tabela: o grupo é nomeado pelo primeiro dia dele. */
export const COLUNA_DO_GRUPO: Record<Agrupamento, string> = { dia: 'Dia', semana: 'Semana de', mes: 'Mês', trimestre: 'Trimestre' }

/** O grupo que começa em `inicio` (`AAAA-MM-DD`), na tabela ("02/11/2026", "11/2026", "4º tri. 2026") ou, curto, no eixo do gráfico. */
export function rotuloDoGrupo(inicio: string, grupo: Agrupamento, curto = false): string {
  const [ano, mes, dia] = inicio.split('-')
  if (grupo === 'mes') return curto ? `${mes}/${ano.slice(2)}` : `${mes}/${ano}`
  if (grupo === 'trimestre') return `${Math.floor((Number(mes) - 1) / 3) + 1}º tri. ${curto ? ano.slice(2) : ano}`
  return curto ? `${dia}/${mes}` : `${dia}/${mes}/${ano}`
}
