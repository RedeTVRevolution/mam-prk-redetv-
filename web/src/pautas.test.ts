import { expect, test } from 'vitest'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import catalogoJson from './catalogo.fixture.json'
import type { Pauta } from './decupagem.ts'
import { cabeNaPauta, editorDeDivisao, editorDeJuncao, pautasParaJuntar } from './pautas.ts'

const catalogo = catalogoJson as CatalogoDeCorrecoes
const P = (id: string, titulo: string, inicio_ms: number, fim_ms: number): Pauta => ({ id, titulo, inicio_ms, fim_ms })
const TODAS = [P('a', 'A', 0, 10), P('b', 'B', 10, 20), P('c', 'C', 20, 30)]

test('só pautas seguidas, duas ou mais, na ordem do vídeo', () => {
  expect(pautasParaJuntar(TODAS, new Set(['a']))).toEqual({ aviso: 'Marque duas ou mais pautas para juntar (M).' })
  expect(pautasParaJuntar(TODAS, new Set(['a', 'c']))).toEqual({
    aviso: 'Só se juntam pautas seguidas: marque também a do meio.',
  })
  expect(pautasParaJuntar(TODAS, new Set(['c', 'b']))).toEqual({ pautas: [TODAS[1], TODAS[2]] })
})

test('a junção sem título não grava; o título novo vale no lugar do escolhido', () => {
  const e = editorDeJuncao(TODAS, catalogo)
  expect(e.inicial.escolha).toBe('A')
  expect(e.pedidos({ escolha: '__outro__', novo: '  ' })).toBeNull()
  expect(e.pedidos({ escolha: '__outro__', novo: ' Tudo ' })).toEqual([
    { tipo: 'pauta.juntar', item_id: 'a', valor: JSON.stringify({ ids: ['a', 'b', 'c'], titulo: 'Tudo' }) },
  ])
})

test('a divisão pede os dois títulos e só cabe dentro da pauta', () => {
  const e = editorDeDivisao(TODAS[1], 15, catalogo)
  expect(e.pedidos({ primeiro: 'B1', segundo: '' })).toBeNull()
  expect(e.pedidos({ primeiro: 'B1', segundo: 'B2' })).toEqual([
    { tipo: 'pauta.dividir', item_id: 'b', valor: JSON.stringify({ em_ms: 15, titulos: ['B1', 'B2'] }) },
  ])
  expect([cabeNaPauta(TODAS[1], 10), cabeNaPauta(TODAS[1], 15), cabeNaPauta(TODAS[1], 20)]).toEqual([false, true, false])
})
