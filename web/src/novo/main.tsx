import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import type { Autenticador } from '../auth/autenticador.ts'
import App from './App.tsx'
import './index.css'

/** A interface nova (ADR 0014), em Tailwind: o CSS dela só vem neste pedaço do build. */
export function mostrar(autenticador: Autenticador) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App autenticador={autenticador} />
    </StrictMode>,
  )
}
