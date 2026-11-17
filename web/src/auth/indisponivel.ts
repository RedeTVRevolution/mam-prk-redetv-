import type { Autenticador, ResultadoDaSenha } from './autenticador.ts'

/** Sem a configuração do Identity Platform: nunca há sessão e entrar falha. */
export class AutenticadorIndisponivel implements Autenticador {
  async token(): Promise<string | null> {
    return null
  }

  async entrar(): Promise<ResultadoDaSenha> {
    throw new Error('Identity Platform não configurado neste build')
  }

  async confirmarTotp(): Promise<void> {
    throw new Error('Identity Platform não configurado neste build')
  }

  async cadastrarTotp(): Promise<void> {
    throw new Error('Identity Platform não configurado neste build')
  }

  async sair(): Promise<void> {}
}
