import { afterEach, expect, test, vi } from 'vitest'
import { anoAtual, diaDeSaoPaulo, fimDoDia, hoje, inicioDoDia } from './fuso.ts'

afterEach(() => vi.useRealTimers())

test('o dia de São Paulo do instante, não o de UTC', () => {
  expect(diaDeSaoPaulo(new Date('2026-01-01T01:30:00Z'))).toBe('2025-12-31')
  expect(diaDeSaoPaulo(new Date('2026-01-01T03:00:00Z'))).toBe('2026-01-01')
})

test('hoje e o ano seguem o relógio em São Paulo', () => {
  vi.useFakeTimers({ now: new Date('2026-01-01T02:30:00Z') })
  expect(hoje()).toBe('2025-12-31')
  expect(anoAtual()).toBe(2025)
})

test('início e fim do dia valem o -03:00 de hoje', () => {
  expect(inicioDoDia('2026-11-20')).toBe(new Date('2026-11-20T00:00:00-03:00').toISOString())
  expect(fimDoDia('2026-11-20')).toBe(new Date('2026-11-20T23:59:59.999-03:00').toISOString())
})

test('no horário de verão de 2018 o dia é o da regra de fuso', () => {
  expect(inicioDoDia('2018-11-10')).toBe('2018-11-10T02:00:00.000Z')
  expect(fimDoDia('2018-11-10')).toBe('2018-11-11T01:59:59.999Z')
  // 4/11/2018: a meia-noite não existiu, o dia começou à 1h (-02:00)
  expect(inicioDoDia('2018-11-04')).toBe('2018-11-04T03:00:00.000Z')
})

test('dia que não existe no calendário é recusado, sem travar', () => {
  for (const dia of ['2026-02-30', '2026-11-31']) {
    expect(() => inicioDoDia(dia)).toThrow()
    expect(() => fimDoDia(dia)).toThrow()
  }
})
