import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { AutenticadorIdentityPlatform } from './auth/identityPlatform.ts'
import { AutenticadorIndisponivel } from './auth/indisponivel.ts'

// Chave web do Identity Platform (pública por natureza), posta pelo Terraform no
// build da imagem (scripts/deploy-dev.sh). Sem ela, como no `npm run dev` e no CI,
// o login fica indisponível.
const apiKey: string | undefined = import.meta.env.VITE_IDENTITY_API_KEY
const autenticador = apiKey
  ? new AutenticadorIdentityPlatform(apiKey)
  : new AutenticadorIndisponivel()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App autenticador={autenticador} />
  </StrictMode>,
)
