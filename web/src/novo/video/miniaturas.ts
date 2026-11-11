export interface AparicaoComQuadro {
  inicio_ms: number
  fim_ms: number
  quadro?: string | null
}

const DISTANCIA_MINIMA_MS = 1000

/**
 * O quadro de capa de cada pessoa: a primeira aparição com quadro cujo meio fique a mais de 1 s do
 * meio das já escolhidas para as pessoas anteriores; sem alternativa, a primeira com quadro.
 * Aproximação: o instante real do JPEG não é gravado e pode variar ±3 s.
 */
export function escolherMiniaturas(pessoas: { id: string; aparicoes: AparicaoComQuadro[] }[]): Map<string, string | undefined> {
  const escolhidos: number[] = []
  const resultado = new Map<string, string | undefined>()
  for (const { id, aparicoes } of pessoas) {
    const comQuadro = aparicoes.filter((a) => a.quadro)
    const meio = (a: AparicaoComQuadro) => (a.inicio_ms + a.fim_ms) / 2
    const escolha = comQuadro.find((a) => escolhidos.every((m) => Math.abs(meio(a) - m) > DISTANCIA_MINIMA_MS)) ?? comQuadro[0]
    if (escolha) escolhidos.push(meio(escolha))
    resultado.set(id, escolha?.quadro ?? undefined)
  }
  return resultado
}
