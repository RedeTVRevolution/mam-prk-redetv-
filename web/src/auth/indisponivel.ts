import type { Autenticador, ResultadoDaSenha } from './autenticador.ts'

/** Provisório até o adaptador do SDK existir: nunca há sessão e entrar falha. */
export class AutenticadorIndisponivel implements Autenticador {
  async token(): Promise<string | null> {
    return null
  }

  async entrar(): Promise<ResultadoDaSenha> {
    throw new Error('SDK do Identity Platform ainda não ligado')
  }

  async confirmarTotp(): Promise<void> {
    throw new Error('SDK do Identity Platform ainda não ligado')
  }

  async cadastrarTotp(): Promise<void> {
    throw new Error('SDK do Identity Platform ainda não ligado')
  }

  async sair(): Promise<void> {}
}
