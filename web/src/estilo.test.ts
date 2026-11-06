import { expect, test } from 'vitest'

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
  expect(arquivos.map((a) => a.nome)).toContain('./main.tsx')
  expect(arquivos.map((a) => a.nome)).toContain('./novo/index.css')
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

// O mesmo, nas classes do Tailwind: gradiente (`bg-linear-to-r`), desfoque de
// fundo e as sombras do Tailwind (de 3 a 50 px de desfoque). Fica a `shadow-float` do tema.
test.each(arquivos.map((a) => [a.nome, a.codigo]))('%s não usa gradiente, vidro nem sombra grande do Tailwind', (_nome, codigo) => {
  expect(codigo).not.toMatch(/\bbg-(linear|radial|conic|gradient)-/)
  expect(codigo).not.toMatch(/\bbackdrop-blur/)
  expect(codigo).not.toMatch(/\bshadow-(2xs|xs|sm|md|lg|xl|2xl)\b/)
  for (const [, valor] of codigo.matchAll(/\bshadow-\[([^\]]+)\]/g)) {
    for (const d of desfoques(valor.replaceAll('_', ' '))) expect(d).toBeLessThanOrEqual(MAIOR_DESFOQUE_PX)
  }
  for (const [, valor] of codigo.matchAll(/--shadow-[\w-]+:\s*([^;]+)/g)) {
    for (const d of desfoques(valor)) expect(d).toBeLessThanOrEqual(MAIOR_DESFOQUE_PX)
  }
})

test.each(arquivos.map((a) => [a.nome, a.codigo]))(
  '%s não usa emoji nem símbolo tipográfico como ícone',
  (_nome, codigo) => {
    // Pictogramas, formas geométricas (▦ ◫ ◈ ●), símbolos diversos e dingbats (♙ ♫ ✨).
    expect(codigo).not.toMatch(/\p{Extended_Pictographic}|[■-◿☀-➿]/u)
  },
)
