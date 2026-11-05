/** Os papéis do `api/papeis.py`, com o que cada um pode, na ordem em que a API os devolve. */
export const PAPEIS = [
  { valor: 'consulta', nome: 'Consulta', pode: 'vê e baixa a decupagem' },
  { valor: 'operador', nome: 'Operador', pode: 'vê e baixa a decupagem (como a Consulta)' },
  { valor: 'editor', nome: 'Editor', pode: 'envia vídeos, reprocessa o que falhou e corrige a decupagem' },
  { valor: 'curador', nome: 'Curador', pode: 'o que o Editor faz, mais aprovar correções, reprocessar etapas e cuidar do catálogo' },
  { valor: 'diretoria', nome: 'Diretoria', pode: 'vê a decupagem e o painel de indicadores' },
  { valor: 'administrador', nome: 'Administrador', pode: 'gere contas, chaves, lixeira e auditoria' },
]

export const NOME_DO_PAPEL: Record<string, string> = Object.fromEntries(PAPEIS.map((p) => [p.valor, p.nome]))
