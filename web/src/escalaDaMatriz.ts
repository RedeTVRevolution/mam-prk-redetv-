// A escala de cor da matriz de calor dos relatórios.

/** O fundo de uma célula: `foco` com 0 a 60% de opacidade, numa escala só para a matriz inteira. */
export function fundoDaCelula(valor: number, maximo: number): string {
  if (valor <= 0 || maximo <= 0) return 'transparent'
  return `rgba(56, 113, 220, ${(0.6 * valor) / maximo})`
}
