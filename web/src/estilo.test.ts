import { expect, test } from 'vitest'
import { tema } from './tema.ts'

// O que o docs/design/principios.md proíbe, procurado no código do front (fora dos testes).
const fontes = import.meta.glob<string>(['./**/*.{ts,tsx,css}', '!./**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
})
const arquivos = Object.entries(fontes).map(([nome, codigo]) => ({ nome, codigo }))

const MAIOR_DESFOQUE_PX = 8

/** O desfoque (terceiro comprimento) de cada sombra de um valor de `box-shadow`. */
function desfoques(valor: string): number[] {
  return valor.split(/,(?![^(]*\))/).map((sombra) => {
    const comprimentos = sombra.replace(/rgba?\([^)]*\)/g, '').match(/-?\d+(\.\d+)?(px)?/g) ?? []
    return parseFloat(comprimentos[2] ?? '0')
  })
}

test('a varredura acha os arquivos do front', () => {
  expect(arquivos.map((a) => a.nome)).toContain('./tema.ts')
})

test.each(arquivos.map((a) => [a.nome, a.codigo]))('%s não usa gradiente', (_nome, codigo) => {
  // O hachurado (repeating-linear-gradient) desenha listras, não uma transição de cor.
  expect(codigo).not.toMatch(/(?<!repeating-)(linear|radial|conic)-gradient/)
})

test.each(arquivos.map((a) => [a.nome, a.codigo]))('%s não tem sombra grande', (_nome, codigo) => {
  for (const [, valor] of codigo.matchAll(/(?:box-shadow|boxShadow)\s*:\s*['"`]?([^;'"`}]+)/g)) {
    for (const d of desfoques(valor)) expect(d).toBeLessThanOrEqual(MAIOR_DESFOQUE_PX)
  }
})

test('as sombras do tema são pequenas', () => {
  for (const valor of Object.values(tema.shadows ?? {})) {
    for (const d of desfoques(valor ?? '')) expect(d).toBeLessThanOrEqual(MAIOR_DESFOQUE_PX)
  }
})

test.each(arquivos.map((a) => [a.nome, a.codigo]))(
  '%s não usa emoji nem símbolo tipográfico como ícone',
  (_nome, codigo) => {
    // Pictogramas, formas geométricas (▦ ◫ ◈ ●), símbolos diversos e dingbats (♙ ♫ ✨).
    expect(codigo).not.toMatch(/\p{Extended_Pictographic}|[■-◿☀-➿]/u)
  },
)
