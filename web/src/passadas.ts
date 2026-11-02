// Os formatos das rotas de passada de comparação (#247) e da comparação com o Job (#249).

export interface ResumoDaPassada {
  id: string
  job_id: string
  modelo: string
  criada_em: string
}

/** `igual`; `difere` (com os motivos: nome, tipo, tempo...); `so_aqui`: o outro lado não tem o item. */
export type MarcaDoItem = 'igual' | 'difere' | 'so_aqui'

export interface ItemMarcado {
  identidade: string
  inicio_ms: number
  fim_ms: number
  detalhe: string | null
  marca: MarcaDoItem
  motivos: string[]
}

export interface RequisitoLadoALado {
  nome: string
  a: ItemMarcado[]
  b: ItemMarcado[]
}

export interface LadoDaComparacao {
  /** `null` no Job: ele não guarda os tokens que gastou. */
  custo_por_hora_usd: number | null
  tempo_total_s: number
}

export interface ComparacaoDaPassada {
  passada_id: string
  modelo: string
  modelo_do_job: string
  duracao_ms: number
  a: LadoDaComparacao
  b: LadoDaComparacao
  requisitos: RequisitoLadoALado[]
}
