import { expect, test } from 'vitest'

// O dia de São Paulo vem de `fuso.ts` (#771): nenhum outro arquivo escreve o nome do fuso.
const fontes = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.*', '!./fuso.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('nenhum .ts ou .tsx de web/src fora de fuso.ts escreve o nome do fuso', () => {
  const infratores = Object.entries(fontes)
    .filter(([, texto]) => texto.includes('America/Sao_Paulo'))
    .map(([arquivo]) => arquivo)

  expect(Object.keys(fontes).length).toBeGreaterThan(10)
  expect(infratores).toEqual([])
})
