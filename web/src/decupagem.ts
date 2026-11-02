import type { Intervalo } from './linhaDoTempo.ts'
import type { CORES_DE_OBJETO } from './tema.ts'

// Os formatos que a API devolve: a Decupagem, o histórico de correções e a fila de revisão.

export type Aparicao = Intervalo & {
  evidencia: string
  papel?: string | null
  visual?: string | null
  /** O JPEG do meio da aparição, relativo à pasta do Job (`quadros/aparicao-0-1.jpg`). */
  quadro?: string | null
}

export interface Pessoa {
  id: string
  nome: string
  origem?: 'modelo' | 'revisao'
  /** 1.2: de onde veio o nome; falta em 1.1 e em pessoa acrescentada pela revisão. */
  fontes_do_nome?: string[]
  /** 1.3: `palpite` é o nome que o modelo deu sem achar prova; falta onde a identificação não rodou. */
  estado_do_nome?: 'confirmado' | 'palpite' | null
  na_imagem: Aparicao[]
  citada_na_fala: Intervalo[]
  citada_no_texto: (Intervalo & { texto: string })[]
}

export interface Pauta extends Intervalo {
  id: string
  titulo: string
  resumo?: string
  tom?: string | null
  origem?: 'modelo' | 'revisao'
}

/** Onde o objeto está num quadro do plano, em fração da largura e da altura (0 a 1). */
export interface CaixaDoQuadro {
  /** O JPEG do quadro, relativo à pasta do Job (`quadros/plano-0-1.jpg`). */
  quadro: string
  x: number
  y: number
  largura: number
  altura: number
}

/** Um objeto do inventário do plano (#244), em português; `destaque` vai de 1 a 3. */
export interface ObjetoDoInventario {
  nome: string
  categoria: CategoriaDeObjeto
  cor?: CorBase | null
  marca?: string | null
  caixas: CaixaDoQuadro[]
  destaque: 1 | 2 | 3
}

export interface Plano extends Intervalo {
  id: string
  ambiente: string
  acao?: string | null
  objetos?: string[]
  /** Ausente em decupagem antiga ou quando a etapa de inventário falhou. */
  inventario?: ObjetoDoInventario[]
  plano_limpo?: boolean
  /** O JPEG do meio do plano. */
  quadro?: string | null
  origem?: 'modelo' | 'revisao'
}

export interface Fala extends Intervalo {
  id?: string
  locutor: string
  texto: string
  origem?: 'modelo' | 'revisao'
}

export interface Comercial extends Intervalo {
  id?: string
  marca: string
  tipo: string
  /** 1.2; decupagens 1.1 trazem só `evidencia` (texto). */
  evidencias?: Evidencia[]
  evidencia?: string
  origem?: 'modelo' | 'revisao'
  acrescentado?: boolean
}

type Evidencia = 'fala' | 'logo' | 'texto_na_tela' | 'produto'

export interface TextoNaTela extends Intervalo {
  id?: string
  origem?: 'modelo' | 'revisao'
  acrescentado?: boolean
  tipo: string
  texto: string
}

export type CorBase = keyof typeof CORES_DE_OBJETO

export type CategoriaDeObjeto =
  | 'roupa'
  | 'calcado'
  | 'acessorio'
  | 'na_mao'
  | 'em_cena'
  | 'veiculo'
  | 'outro'
  | 'eletronico'
  | 'produto'
  | 'animal'
  | 'alimento'
  | 'movel'
  | 'decoracao'
  | 'instrumento_musical'
  | 'utensilio'
  | 'documento'
  | 'planta'
  | 'bebida'
export type RelacaoDoObjeto = 'veste' | 'calca' | 'usa' | 'segura'

/** 1.3: roupa, calçado, acessório ou objeto em cena, com a cor e o dono; 1.4 acrescenta eletrônico, produto, animal e alimento. */
export interface Objeto {
  id: string
  categoria: CategoriaDeObjeto
  tipo: string
  cor_base: CorBase[]
  /** O tom em palavras ("vermelho vivo"). */
  cor?: string | null
  detalhe?: string | null
  marca?: string | null
  /** O id de uma pessoa da mesma decupagem; `null` para objeto em cena. */
  pessoa?: string | null
  relacao?: RelacaoDoObjeto | null
  /** O JPEG da primeira ocorrência. */
  quadro?: string | null
  ocorrencias: Intervalo[]
}

export interface Decupagem {
  versao_decupagem?: string
  /** A versão do pipeline que fez a decupagem; ausente na anterior à versão (#250). */
  versao_pipeline?: string | null
  manifesto_do_pipeline?: Record<string, unknown> | null
  video?: { duracao_ms: number }
  pautas: Pauta[]
  pessoas: Pessoa[]
  planos: Plano[]
  comerciais: Comercial[]
  transcricao: Fala[]
  /** 1.2; falta nas decupagens 1.1. */
  textos_na_tela?: TextoNaTela[]
  /** 1.3; falta nas decupagens anteriores. */
  objetos?: Objeto[]
}

export interface Reproducao {
  url: string
  expira_em: string
}

/** Onde uma correção está no índice da busca. */
export type EstadoNaBusca = 'salva' | 'indexando' | 'na_busca'

export interface ItemDoHistorico {
  id: string
  tipo:
    | 'pessoa.renomear'
    | 'pauta.titulo'
    | 'pauta.resumo'
    | 'item.tempos'
    | 'comercial.marca'
    | 'comercial.tipo'
    | 'comercial.acrescentar'
    | 'pessoa.nao_e'
    | 'pessoa.aparicao_para_mencao'
    | 'pessoa.mencao_para_aparicao'
    | 'pessoa.acrescentar_aparicao'
    | 'plano.descricao'
    | 'plano.limpo'
    | 'fala.texto'
    | 'pauta.tom'
    | 'pessoa.fontes_do_nome'
    | 'aparicao.papel_visual'
    | 'texto_na_tela.texto'
    | 'texto_na_tela.acrescentar'
    | 'pauta.acrescentar'
    | 'pauta.juntar'
    | 'pauta.dividir'
    | 'objeto.atributos'
    | 'desfazer'
    | 'descartar'
    | 'aprovar'
    | 'recusar'
  item_id: string
  ancora: { versao: string; tipo_do_item: string }
  autor_email: string
  criada_em: string
  motivo: string
  antes: string
  depois: string
  antes_legivel: string
  depois_legivel: string
  na_busca: EstadoNaBusca
  estado: 'ativa' | 'desfeita' | 'reaplicada' | 'descartada' | 'pendente' | 'aprovada' | 'recusada'
  reaplica?: string | null
  desfaz?: string | null
  aprova?: string | null
  recusa?: string | null
}

export interface ItemDaFila {
  id: string
  tipo: ItemDoHistorico['tipo']
  autor_email: string
  criada_em: string
  motivo: string
  antes: string
  depois: string
  antes_legivel: string
  depois_legivel: string
  candidatos: {
    item_id: string
    nome: string
    inicio_ms: number
    fim_ms: number
  }[]
}

/** Uma correção proposta por uma sugestão, no formato do `POST /v1/jobs/{id}/correcoes`. */
export interface PropostaDaSugestao {
  tipo: string
  item_id: string
  valor: string
  catalogo_id?: string | null
}

/** Uma sugestão que o editor confirma (`GET /v1/jobs/{id}/sugestoes`); a tela a trata pelo formato, sem conhecer o tipo. */
export interface Sugestao {
  id: string
  tipo: string
  inicio_ms: number
  fim_ms: number
  pergunta: string
  contexto: string
  correcao: PropostaDaSugestao
  depois: PropostaDaSugestao[]
}
