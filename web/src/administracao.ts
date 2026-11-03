export interface Aba {
  aba: string
  rotulo: string
  permissao: string
}

// Cada ticket da área acrescenta a sua aba aqui (entradas, lixeira, auditoria).
export const ABAS: Aba[] = [
  { aba: 'usuarios', rotulo: 'Usuários', permissao: 'usuarios.gerir' },
  { aba: 'chaves', rotulo: 'Sistemas e chaves', permissao: 'chaves.gerir' },
]

/** As abas que essas permissões abrem, na ordem da área. */
export function abasPermitidas(permissoes: string[]): Aba[] {
  return ABAS.filter((a) => permissoes.includes(a.permissao))
}

/**
 * O link "Administração" da barra só existe para quem abre alguma aba da área.
 * Sai das abas, e não da lista de permissões, para o link nunca levar a uma área vazia.
 */
export function podeAdministrar(permissoes: string[]): boolean {
  return abasPermitidas(permissoes).length > 0
}
