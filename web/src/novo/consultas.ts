import { QueryClient } from '@tanstack/react-query'
import { createContext, useContext } from 'react'
import { SessaoExpirada, type ClienteDaApi } from '../api.ts'

/**
 * O cache do TanStack Query sobre o `api.ts`, um por sessão (sai junto no logout). A consulta que
 * sai da tela é descartada em 30 s (ADR 0014, memória), e voltar à janela não pede tudo de novo.
 * O 401 não se repete: o cliente da API já levou ao login.
 */
export function criarClienteDeConsultas() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (falhas, erro) => !(erro instanceof SessaoExpirada) && falhas < 2,
      },
    },
  })
}

export const ContextoDaApi = createContext<ClienteDaApi | null>(null)

/** O cliente da API da sessão, para o `queryFn` das telas. */
export function useApi(): ClienteDaApi {
  const api = useContext(ContextoDaApi)
  if (!api) throw new Error('Falta o ContextoDaApi.')
  return api
}
