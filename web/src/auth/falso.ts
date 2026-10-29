import {
  CredencialInvalida,
  type Autenticador,
  type ResultadoDaSenha,
} from './autenticador.ts'

export interface ContaFalsa {
  email: string
  senha: string
  /** Sem autenticador ainda: o primeiro acesso exige o cadastro. */
  totpCadastrado: boolean
}

export const CODIGO_TOTP_FALSO = '123456'

/** Identity Platform simulado, só para testes. */
export class AutenticadorFalso implements Autenticador {
  private sessao: string | null = null
  private pendente: ContaFalsa | null = null

  private readonly contas: ContaFalsa[]

  constructor(contas: ContaFalsa[]) {
    this.contas = contas
  }

  async token(): Promise<string | null> {
    return this.sessao
  }

  async entrar(email: string, senha: string): Promise<ResultadoDaSenha> {
    const conta = this.contas.find((c) => c.email === email && c.senha === senha)
    if (!conta) throw new CredencialInvalida()
    this.pendente = conta
    return conta.totpCadastrado
      ? { tipo: 'precisa_totp' }
      : { tipo: 'precisa_cadastro_totp', segredo: 'SEGREDOFALSO', uri: 'otpauth://totp/MAM' }
  }

  async confirmarTotp(codigo: string): Promise<void> {
    this.concluir(codigo)
  }

  async cadastrarTotp(codigo: string): Promise<void> {
    this.concluir(codigo)
  }

  async sair(): Promise<void> {
    this.sessao = null
  }

  private concluir(codigo: string): void {
    if (!this.pendente || codigo !== CODIGO_TOTP_FALSO) throw new CredencialInvalida()
    this.pendente.totpCadastrado = true
    this.sessao = `token-de-${this.pendente.email}`
    this.pendente = null
  }
}
