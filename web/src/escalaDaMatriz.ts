// A escala de cor da matriz de calor dos relatórios.

import { CORES } from './tema.ts'

/** O `foco` do tema em vermelho, verde e azul, para a opacidade da célula. */
const FOCO_RGB = [1, 3, 5].map((i) => parseInt(CORES.foco.slice(i, i + 2), 16)).join(', ')

/** O fundo de uma célula: `foco` com 0 a 60% de opacidade, numa escala só para a matriz inteira. */
export function fundoDaCelula(valor: number, maximo: number): string {
  if (valor <= 0 || maximo <= 0) return 'transparent'
  return `rgba(${FOCO_RGB}, ${(0.6 * valor) / maximo})`
}
