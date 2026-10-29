import { initializeApp } from '@firebase/app'
import {
  AuthErrorCodes,
  getAuth,
  getMultiFactorResolver,
  multiFactor,
  signInWithEmailAndPassword,
  signOut,
  TotpMultiFactorGenerator,
  type Auth,
  type MultiFactorError,
  type MultiFactorResolver,
  type TotpSecret,
} from '@firebase/auth'
import {
  ContaBloqueada,
  CredencialInvalida,
  type Autenticador,
  type ResultadoDaSenha,
} from './autenticador.ts'

const ERROS_DE_CREDENCIAL: string[] = [
  AuthErrorCodes.INVALID_LOGIN_CREDENTIALS,
  AuthErrorCodes.INVALID_PASSWORD,
  AuthErrorCodes.INVALID_EMAIL,
  AuthErrorCodes.USER_DELETED,
  AuthErrorCodes.USER_DISABLED,
  AuthErrorCodes.INVALID_CODE,
]

function codigoDoErro(erro: unknown): string | undefined {
  return (erro as { code?: string }).code
}

function traduzir(erro: unknown): unknown {
  const codigo = codigoDoErro(erro)
  // O bloqueio após tentativas erradas é do próprio Identity Platform.
  if (codigo === AuthErrorCodes.TOO_MANY_ATTEMPTS_TRY_LATER) return new ContaBloqueada()
  if (codigo && ERROS_DE_CREDENCIAL.includes(codigo)) return new CredencialInvalida()
  return erro
}

/** Adaptador do SDK do Identity Platform (o mesmo do Firebase Auth), com MFA por TOTP. */
export class AutenticadorIdentityPlatform implements Autenticador {
  private resolver: MultiFactorResolver | null = null
  private segredo: TotpSecret | null = null

  private readonly auth: Auth

  // Sem authDomain: ele só serve ao login por popup ou redirecionamento.
  constructor(apiKey: string) {
    this.auth = getAuth(initializeApp({ apiKey }))
  }

  async token(): Promise<string | null> {
    await this.auth.authStateReady()
    return (await this.auth.currentUser?.getIdToken()) ?? null
  }

  async entrar(email: string, senha: string): Promise<ResultadoDaSenha> {
    this.resolver = null
    this.segredo = null
    try {
      const { user } = await signInWithEmailAndPassword(this.auth, email, senha)
      // Entrou só com a senha: ainda não há autenticador. A API recusa este token até o cadastro.
      this.segredo = await TotpMultiFactorGenerator.generateSecret(
        await multiFactor(user).getSession(),
      )
      return {
        tipo: 'precisa_cadastro_totp',
        segredo: this.segredo.secretKey,
        uri: this.segredo.generateQrCodeUrl(email, 'MAM RedeTV'),
      }
    } catch (erro) {
      if (codigoDoErro(erro) !== AuthErrorCodes.MFA_REQUIRED) throw traduzir(erro)
      this.resolver = getMultiFactorResolver(this.auth, erro as MultiFactorError)
      return { tipo: 'precisa_totp' }
    }
  }

  async confirmarTotp(codigo: string): Promise<void> {
    const dica = this.resolver?.hints.find(
      (h) => h.factorId === TotpMultiFactorGenerator.FACTOR_ID,
    )
    if (!this.resolver || !dica) throw new Error('etapa de TOTP fora de ordem')
    try {
      await this.resolver.resolveSignIn(
        TotpMultiFactorGenerator.assertionForSignIn(dica.uid, codigo),
      )
    } catch (erro) {
      throw traduzir(erro)
    }
    this.resolver = null
  }

  async cadastrarTotp(codigo: string): Promise<void> {
    const usuario = this.auth.currentUser
    if (!this.segredo || !usuario) throw new Error('etapa de TOTP fora de ordem')
    try {
      await multiFactor(usuario).enroll(
        TotpMultiFactorGenerator.assertionForEnrollment(this.segredo, codigo),
        'Autenticador',
      )
    } catch (erro) {
      throw traduzir(erro)
    }
    this.segredo = null
    // Token novo, para a API ver o segundo fator. Se ainda faltar, o 401 leva de volta ao login.
    await usuario.getIdToken(true)
  }

  async sair(): Promise<void> {
    this.resolver = null
    this.segredo = null
    await signOut(this.auth)
  }
}
