import { MantineProvider } from '@mantine/core'
import '@mantine/charts/styles.css'
import '@mantine/core/styles.css'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import type { Autenticador } from './auth/autenticador.ts'
import { tema, variaveis } from './tema.ts'

/** A interface atual, em Mantine: o CSS dela só vem neste pedaço do build. */
export function mostrar(autenticador: Autenticador) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <MantineProvider theme={tema} cssVariablesResolver={variaveis} forceColorScheme="dark">
        <App autenticador={autenticador} />
      </MantineProvider>
    </StrictMode>,
  )
}
