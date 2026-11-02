// O relatório por marca e tipo de inserção: o que a API devolve e os filtros (os do tempo de tela mais o tipo).

import { filtrosDoRelatorio, type FiltrosDoRelatorio } from './tempoDeTela.ts'

export interface InsercaoNoRelatorio {
  job_id: string
  nome: string | null
  tipo: string
  inicio_ms: number
  fim_ms: number
}

export interface TotalPorTipo {
  tipo: string
  insercoes: number
  tempo_ms: number
  videos: number
}

export interface MarcaNoRelatorio {
  marca: string
  insercoes: number
  tempo_ms: number
  videos: number
  por_tipo: TotalPorTipo[]
  lista: InsercaoNoRelatorio[]
}

export interface RelatorioDeMarcas {
  programa: string | null
  desde: string | null
  ate: string | null
  tipo: string | null
  marcas: MarcaNoRelatorio[]
}

export interface FiltrosDeMarcas extends FiltrosDoRelatorio {
  tipo: string
}

/** Os tipos de inserção da decupagem (`Comercial.tipo`), com o nome que a tela mostra. */
export const TIPOS_DE_INSERCAO: Record<string, string> = {
  intervalo: 'Intervalo',
  merchan_apresentador: 'Merchan com apresentador',
  testemunhal: 'Testemunhal',
  produto_em_cena: 'Produto em cena',
  patrocinio_vinheta: 'Patrocínio ou vinheta',
  sobreposicao_grafica: 'Sobreposição gráfica',
  marca_incidental: 'Marca incidental',
  mencao_editorial: 'Menção editorial',
}

export function nomeDoTipo(tipo: string): string {
  return TIPOS_DE_INSERCAO[tipo] ?? tipo
}

/** Os filtros da query do endereço; tipo desconhecido de um link editado à mão sai. */
export function filtrosDeMarcas(busca: string): FiltrosDeMarcas {
  const tipo = new URLSearchParams(busca).get('tipo') ?? ''
  return { ...filtrosDoRelatorio(busca), tipo: tipo in TIPOS_DE_INSERCAO ? tipo : '' }
}
