import { createContext, useContext } from 'react'

export interface Opcao {
  valor: string
  rotulo: string
}

/** A resposta de `GET /v1/correcoes/catalogo` (api/catalogo_de_correcoes.py). */
export interface CatalogoDeCorrecoes {
  tipos: Opcao[]
  tipos_de_comercial: Opcao[]
  tipos_de_texto_na_tela: Opcao[]
  tons_da_pauta: Opcao[]
  fontes_do_nome: Opcao[]
  categorias_de_objeto: Opcao[]
  cores_base: Opcao[]
  relacoes_do_objeto: Opcao[]
  limites: { nome: number; texto: number; motivo: number }
  prefixos: { acrescentado: string; nao_identificado: string }
}

export const ContextoDoCatalogo = createContext<CatalogoDeCorrecoes | null>(null)

export function useCatalogo(): CatalogoDeCorrecoes {
  const catalogo = useContext(ContextoDoCatalogo)
  if (!catalogo) throw new Error('Sem catálogo de correções: falta o provedor')
  return catalogo
}

/** O rótulo do valor; um valor fora da lista (Decupagem gravada antes dela) sai como veio. */
export const rotuloDe = (opcoes: Opcao[], valor: string): string =>
  opcoes.find((o) => o.valor === valor)?.rotulo ?? valor

export const comoSelect = (opcoes: Opcao[]) =>
  opcoes.map((o) => ({ value: o.valor, label: o.rotulo }))

/** As pessoas que a revisão cria não existem no JSON do modelo: só se desfazem. */
export const pessoaDoModelo = (catalogo: CatalogoDeCorrecoes, p: { id: string }): boolean =>
  !p.id.startsWith(catalogo.prefixos.acrescentado) &&
  !p.id.startsWith(catalogo.prefixos.nao_identificado)
