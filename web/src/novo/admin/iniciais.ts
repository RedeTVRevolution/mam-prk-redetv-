const PARTICULAS = new Set(['de', 'da', 'do', 'das', 'dos', 'e', 'di', 'del', 'van', 'von'])

/** As iniciais do nome (primeira e última palavra, sem partículas) ou, num e-mail, do que vem antes do `@`. */
export function iniciais(nome: string): string {
  const base = nome.includes('@') ? nome.split('@')[0] : nome
  const partes = base.trim().split(/[\s.@_-]+/).filter((p) => p && !PARTICULAS.has(p.toLowerCase()))
  const primeira = partes[0]?.[0] ?? ''
  const ultima = partes.length > 1 ? (partes[partes.length - 1][0] ?? '') : ''
  return (primeira + ultima).toUpperCase() || '?'
}
