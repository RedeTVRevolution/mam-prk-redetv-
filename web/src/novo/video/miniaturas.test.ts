import { expect, test } from 'vitest'
import { escolherMiniaturas } from './miniaturas.ts'

const ap = (inicio_ms: number, fim_ms: number, quadro?: string) => ({ inicio_ms, fim_ms, quadro })

test('a segunda pessoa pula o quadro cujo meio fica a 1 s ou menos do meio já escolhido', () => {
  const m = escolherMiniaturas([
    { id: 'a', aparicoes: [ap(0, 10_000, 'a1')] },
    { id: 'b', aparicoes: [ap(4_500, 5_500, 'b1'), ap(20_000, 22_000, 'b2')] },
  ])
  expect(m.get('a')).toBe('a1')
  expect(m.get('b')).toBe('b2')
})

test('meio a mais de 1 s do escolhido basta para ficar a primeira aparição', () => {
  const m = escolherMiniaturas([
    { id: 'a', aparicoes: [ap(0, 10_000, 'a1')] },
    { id: 'b', aparicoes: [ap(6_000, 7_000, 'b1')] },
  ])
  expect(m.get('b')).toBe('b1')
})

test('sem alternativa fica a primeira aparição com quadro; sem quadro nenhum, nada', () => {
  const m = escolherMiniaturas([
    { id: 'a', aparicoes: [ap(0, 10_000, 'a1')] },
    { id: 'b', aparicoes: [ap(1_000, 9_000), ap(4_000, 6_000, 'b2'), ap(4_200, 5_800, 'b3')] },
    { id: 'c', aparicoes: [ap(0, 1_000)] },
  ])
  expect(m.get('b')).toBe('b2')
  expect(m.get('c')).toBeUndefined()
})

test('meio a exatamente 1 s do escolhido ainda conta como perto: o limite é "mais de 1 s"', () => {
  const m = escolherMiniaturas([
    { id: 'a', aparicoes: [ap(4_000, 6_000, 'a1')] }, // meio 5 000
    { id: 'b', aparicoes: [ap(5_500, 6_500, 'b1'), ap(20_000, 22_000, 'b2')] }, // meio 6 000 = 5 000 + 1 000
    { id: 'c', aparicoes: [ap(5_501, 6_501, 'c1'), ap(20_000, 22_000, 'c2')] }, // meio 6 001, a 1 ms de passar
  ])
  expect(m.get('b')).toBe('b2')
  expect(m.get('c')).toBe('c1')
})
