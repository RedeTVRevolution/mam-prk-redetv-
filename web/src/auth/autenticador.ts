// Porta para o SDK do Identity Platform; os testes usam uma versão falsa.

export type ResultadoDaSenha =
  | { tipo: 'logado' }
  | { tipo: 'precisa_totp' }
  | { tipo: 'precisa_cadastro_totp'; segredo: string; uri: string }

export class CredencialInvalida extends Error {}

export interface Autenticador {
  /** Token da sessão atual, ou null sem sessão. */
  token(): Promise<string | null>
  entrar(email: string, senha: string): Promise<ResultadoDaSenha>
  /** Segundo fator de quem já tem autenticador. */
  confirmarTotp(codigo: string): Promise<void>
  /** Primeiro acesso: confirma o código gerado pelo autenticador recém-cadastrado. */
  cadastrarTotp(codigo: string): Promise<void>
  sair(): Promise<void>
}
