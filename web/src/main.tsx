import { MantineProvider } from '@mantine/core'
import '@mantine/core/styles.css'
import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { AutenticadorIdentityPlatform } from './auth/identityPlatform.ts'
import { AutenticadorIndisponivel } from './auth/indisponivel.ts'
import { tema, variaveis } from './tema.ts'

function mostrar(tela: ReactNode) {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <MantineProvider theme={tema} cssVariablesResolver={variaveis} forceColorScheme="dark">
        {tela}
      </MantineProvider>
    </StrictMode>,
  )
}

if (new URLSearchParams(location.search).has('amostra')) {
  // A amostra do sistema visual abre sem login e sem a API, num pedaço à parte do bundle.
  void import('./Amostra.tsx').then(({ default: Amostra }) => mostrar(<Amostra />))
} else {
  // Chave web do Identity Platform (pública por natureza), posta pelo Terraform no
  // build da imagem (scripts/deploy-dev.sh). Sem ela, como no `npm run dev` e no CI,
  // o login fica indisponível.
  const apiKey: string | undefined = import.meta.env.VITE_IDENTITY_API_KEY
  const autenticador = apiKey
    ? new AutenticadorIdentityPlatform(apiKey)
    : new AutenticadorIndisponivel()
  mostrar(<App autenticador={autenticador} />)
}
