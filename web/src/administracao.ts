export interface Aba {
  aba: string
  rotulo: string
  /** Basta uma delas para a aba abrir. */
  permissoes: string[]
}

// Cada ticket da área acrescenta a sua aba aqui (entradas, lixeira, auditoria).
export const ABAS: Aba[] = [
  { aba: 'entradas', rotulo: 'Entradas', permissoes: ['video.reprocessar', 'video.reprocessar_etapa'] },
  { aba: 'usuarios', rotulo: 'Usuários', permissoes: ['usuarios.gerir'] },
  { aba: 'chaves', rotulo: 'Sistemas e chaves', permissoes: ['chaves.gerir'] },
  { aba: 'lixeira', rotulo: 'Lixeira', permissoes: ['lixeira.gerir'] },
]

/** As abas que essas permissões abrem, na ordem da área. */
export function abasPermitidas(permissoes: string[]): Aba[] {
  return ABAS.filter((a) => a.permissoes.some((p) => permissoes.includes(p)))
}

/**
 * O link "Administração" da barra só existe para quem abre alguma aba da área.
 * Sai das abas, e não da lista de permissões, para o link nunca levar a uma área vazia.
 */
export function podeAdministrar(permissoes: string[]): boolean {
  return abasPermitidas(permissoes).length > 0
}
