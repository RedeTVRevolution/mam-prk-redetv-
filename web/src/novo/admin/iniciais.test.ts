import { expect, test } from 'vitest'
import { iniciais } from './iniciais.ts'

test.each([
  ['Marcelo de Carvalho', 'MC'],
  ['Ana', 'A'],
  ['Maria da Silva dos Santos', 'MS'],
  ['Ludwig van Beethoven', 'LB'],
  ['joana.silva@redetv.com.br', 'JS'],
  ['', '?'],
])('%s -> %s', (nome, esperado) => {
  expect(iniciais(nome)).toBe(esperado)
})
