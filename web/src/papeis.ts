/** Os papéis do `api/papeis.py`, com o que cada um pode, na ordem em que a API os devolve. */
export const PAPEIS = [
  { valor: 'consulta', nome: 'Consulta', pode: 'vê a decupagem' },
  { valor: 'operador', nome: 'Operador', pode: 'envia vídeos e reprocessa' },
  { valor: 'editor', nome: 'Editor', pode: 'vê e corrige a decupagem' },
  { valor: 'curador', nome: 'Curador', pode: 'aprova correções, reprocessa etapas e cuida do catálogo' },
  { valor: 'administrador', nome: 'Administrador', pode: 'gere contas, chaves, lixeira e auditoria' },
]

export const NOME_DO_PAPEL: Record<string, string> = Object.fromEntries(PAPEIS.map((p) => [p.valor, p.nome]))
