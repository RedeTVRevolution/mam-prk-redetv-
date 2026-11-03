import { codigoDoErro, ConflitoNaApi, FalhaNaApi, PedidoInvalido } from './api.ts'

const SEM_PERMISSAO = 'Você não tem permissão para isto.'

export type Falha = { mensagem: string; codigo: string }

/**
 * A mensagem em português de uma falha da API; o código interno vai à parte. `generica` é a
 * mensagem, com a ação, para a falha que a API não explica.
 */
export function falhaDaAcao(erro: unknown, generica = 'Não foi possível concluir. Tente de novo.'): Falha {
  if (erro instanceof FalhaNaApi && erro.status === 403) return { mensagem: SEM_PERMISSAO, codigo: 'http_403' }
  if (erro instanceof ConflitoNaApi || erro instanceof PedidoInvalido) {
    return { mensagem: erro.message, codigo: codigoDoErro(erro) }
  }
  return { mensagem: generica, codigo: codigoDoErro(erro) }
}
