import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { AutenticadorIndisponivel } from './auth/indisponivel.ts'

// TODO: trocar pelo adaptador do SDK do Identity Platform quando houver projeto no dev.
const autenticador = new AutenticadorIndisponivel()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App autenticador={autenticador} />
  </StrictMode>,
)
