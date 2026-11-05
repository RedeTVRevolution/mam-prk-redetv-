// As contas de cor dos testes de tema das duas interfaces (tema.test.ts e novo/tokens.test.ts).

/** A cor `a` com opacidade `alfa` sobre `fundo`, como o navegador compõe o `rgba()`. */
export function sobre(a: string, alfa: number, fundo: string): string {
  const canal = (cor: string, i: number) => parseInt(cor.slice(i, i + 2), 16)
  return `#${[1, 3, 5]
    .map((i) => Math.round(canal(a, i) * alfa + canal(fundo, i) * (1 - alfa)))
    .map((c) => c.toString(16).padStart(2, '0'))
    .join('')}`
}

// Simulação de Machado, Oliveira e Fernandes (2009), deuteranopia completa, no RGB linear;
// a distância entre duas cores é a euclidiana no Oklab (Ottosson, 2020).
const DEUTERANOPIA = [
  [0.367322, 0.860646, -0.227968],
  [0.280085, 0.672501, 0.047413],
  [-0.01182, 0.04294, 0.968881],
]

function linear(hex: string): number[] {
  return [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
}

function oklab([r, g, b]: number[]): number[] {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

export function deuteranopia(rgb: number[]): number[] {
  return DEUTERANOPIA.map((linha) =>
    Math.min(
      1,
      Math.max(
        0,
        linha.reduce((soma, k, i) => soma + k * rgb[i], 0),
      ),
    ),
  )
}

/** A menor distância Oklab entre duas das cores, vistas por `ver` (a visão comum é a identidade). */
export function menorDistancia(hexes: string[], ver: (rgb: number[]) => number[] = (rgb) => rgb): number {
  const cores = hexes.map((cor) => oklab(ver(linear(cor))))
  let menor = Infinity
  for (const [i, a] of cores.entries()) {
    for (const b of cores.slice(i + 1)) menor = Math.min(menor, Math.hypot(...a.map((x, k) => x - b[k])))
  }
  return menor
}

/** O matiz em graus; o âmbar fica entre o laranja (30°) e o amarelo (60°). */
export function matiz(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return (Math.atan2(Math.sqrt(3) * (g - b), 2 * r - g - b) * 180) / Math.PI
}
