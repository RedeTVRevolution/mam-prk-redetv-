// Porta para o SDK do Identity Platform; os testes usam uma versão falsa.

export type ResultadoDaSenha =
  | { tipo: 'logado' }
  | { tipo: 'precisa_totp' }
  | { tipo: 'precisa_cadastro_totp'; segredo: string; uri: string }

export class CredencialInvalida extends Error {}

/** Tentativas erradas demais: o Identity Platform bloqueia a conta por um tempo. */
export class ContaBloqueada extends Error {}

/** O link de senha do e-mail está vencido, já foi usado ou não é válido. */
export class CodigoDeSenhaInvalido extends Error {}

/** A senha nova não atende à política do projeto; a mensagem é a do servidor. */
export class SenhaRecusada extends Error {}

export interface Autenticador {
  /** Token da sessão atual, ou null sem sessão. */
  token(): Promise<string | null>
  entrar(email: string, senha: string): Promise<ResultadoDaSenha>
  /** Segundo fator de quem já tem autenticador. */
  confirmarTotp(codigo: string): Promise<void>
  /** Primeiro acesso: confirma o código gerado pelo autenticador recém-cadastrado. */
  cadastrarTotp(codigo: string): Promise<void>
  /** O link de senha do e-mail: confere o código e devolve o e-mail da conta. */
  verificarCodigoDeSenha(codigo: string): Promise<string>
  /** Define a senha nova com o código do link; não abre sessão. */
  redefinirSenha(codigo: string, senha: string): Promise<void>
  sair(): Promise<void>
}
