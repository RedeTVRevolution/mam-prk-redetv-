import { expect, test } from 'vitest'
import { timecodeNoInstante } from './timecode.ts'

const NTSC = 30000 / 1001
// O instante, em ms, do quadro `n` a 29,97 fps.
const noQuadro = (n: number) => (n * 1001 * 1000) / 30000

test('o TC inicial sem tempo decorrido é o próprio TC', () => {
  expect(timecodeNoInstante('01:00:00:00', 30, 0)).toBe('01:00:00:00')
})

test('61,5 s a 30 fps depois de 01:00:00:00 dão 01:01:01:15', () => {
  expect(timecodeNoInstante('01:00:00:00', 30, 61_500)).toBe('01:01:01:15')
})

test('a 25 fps o quadro vai de 0 a 24 e vira o segundo', () => {
  expect(timecodeNoInstante('00:00:00:00', 25, 960)).toBe('00:00:00:24')
  expect(timecodeNoInstante('00:00:00:00', 25, 1000)).toBe('00:00:01:00')
})

test('o TC inicial com quadros soma ao decorrido e vira o segundo', () => {
  expect(timecodeNoInstante('00:00:00:20', 25, 400)).toBe('00:00:01:05')
})

test('a 23,976 fps a base é 24 quadros por segundo', () => {
  expect(timecodeNoInstante('00:00:00:00', 24000 / 1001, 960)).toBe('00:00:00:23')
  expect(timecodeNoInstante('00:00:00:00', 24000 / 1001, 1001)).toBe('00:00:01:00')
})

test('drop-frame: o quadro 1799 ainda é 00:00:59;29', () => {
  expect(timecodeNoInstante('00:00:00;00', NTSC, noQuadro(1799))).toBe('00:00:59;29')
})

test('drop-frame: na virada de minuto pula os quadros 00 e 01', () => {
  expect(timecodeNoInstante('00:00:00;00', NTSC, noQuadro(1800))).toBe('00:01:00;02')
})

test('drop-frame: o décimo minuto não pula quadros', () => {
  expect(timecodeNoInstante('00:00:00;00', NTSC, noQuadro(17981))).toBe('00:09:59;29')
  expect(timecodeNoInstante('00:00:00;00', NTSC, noQuadro(17982))).toBe('00:10:00;00')
  expect(timecodeNoInstante('00:00:00;00', NTSC, noQuadro(17983))).toBe('00:10:00;01')
})

test('drop-frame com início em 01:00:00;00 acompanha a hora', () => {
  // Uma hora de relógio a 29,97 fps tem 107.892 quadros: o TC chega a 01:00:00;00 + 1 h menos 3,6 s.
  expect(timecodeNoInstante('01:00:00;00', NTSC, noQuadro(107_892))).toBe('02:00:00;00')
})

test('drop-frame com início no meio do minuto pula na virada', () => {
  expect(timecodeNoInstante('00:00:59;29', NTSC, noQuadro(1))).toBe('00:01:00;02')
})

test('drop-frame fora de 29,97 não dá TC', () => {
  expect(timecodeNoInstante('00:00:00;00', 60000 / 1001, 1000)).toBeNull()
})
