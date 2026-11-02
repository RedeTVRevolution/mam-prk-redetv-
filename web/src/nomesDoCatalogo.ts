import { createContext } from 'react'
import type { ClienteDeNomes } from './api.ts'

/** O cliente do catálogo de nomes, para os campos de nome dos formulários (o Visualizador o provê). */
export const NomesDoCatalogo = createContext<ClienteDeNomes | null>(null)
