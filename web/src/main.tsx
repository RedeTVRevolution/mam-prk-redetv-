import { AutenticadorIdentityPlatform } from './auth/identityPlatform.ts'
import { AutenticadorIndisponivel } from './auth/indisponivel.ts'
import { registrarCacheDeImagens } from './cacheDeImagens.ts'
import { mostrar } from './novo/main.tsx'

// Chave web do Identity Platform (pública por natureza), posta pelo Terraform no
// build da imagem (scripts/deploy-dev.sh). Sem ela, como no `npm run dev` e no CI,
// o login fica indisponível.
const apiKey: string | undefined = import.meta.env.VITE_IDENTITY_API_KEY
const autenticador = apiKey
  ? new AutenticadorIdentityPlatform(apiKey)
  : new AutenticadorIndisponivel()

mostrar(autenticador)

registrarCacheDeImagens()
