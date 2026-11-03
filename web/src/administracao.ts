const PERMISSOES_DE_ADMINISTRACAO = ['usuarios.gerir', 'chaves.gerir', 'lixeira.gerir', 'auditoria.ver']

/** O link "Administração" da barra só existe para quem tem alguma permissão da área. */
export function podeAdministrar(permissoes: string[]): boolean {
  return PERMISSOES_DE_ADMINISTRACAO.some((p) => permissoes.includes(p))
}
