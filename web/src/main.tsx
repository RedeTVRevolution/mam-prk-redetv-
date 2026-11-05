import { AutenticadorIdentityPlatform } from './auth/identityPlatform.ts'
import { AutenticadorIndisponivel } from './auth/indisponivel.ts'
import { escolherInterface } from './interface.ts'

// Chave web do Identity Platform (pública por natureza), posta pelo Terraform no
// build da imagem (scripts/deploy-dev.sh). Sem ela, como no `npm run dev` e no CI,
// o login fica indisponível.
const apiKey: string | undefined = import.meta.env.VITE_IDENTITY_API_KEY
const autenticador = apiKey
  ? new AutenticadorIdentityPlatform(apiKey)
  : new AutenticadorIndisponivel()

// Cada interface vem num pedaço próprio, com o próprio CSS: o reset do Tailwind da nova nunca
// divide a página com o CSS do Mantine (ADR 0014).
const escolhida = escolherInterface() === 'nova' ? import('./novo/main.tsx') : import('./atual.tsx')
void escolhida.then(({ mostrar }) => mostrar(autenticador))
