import { expect, test } from 'vitest'
import { periodoDoEndereco, periodoPadrao } from './periodoPadrao.ts'

test('o padrão é de hoje − 6 dias até hoje, no dia de São Paulo', () => {
  // 22h de 6/11 em São Paulo já é 7/11 em UTC.
  expect(periodoPadrao(new Date('2026-11-07T01:00:00Z'))).toEqual({ de: '2026-10-31', ate: '2026-11-06' })
  expect(periodoPadrao(new Date('2026-03-03T15:00:00Z'))).toEqual({ de: '2026-02-25', ate: '2026-03-03' })
})

test('sem de nem ate o endereço vale o padrão; com algum, mesmo vazio, vale o que veio', () => {
  const agora = new Date('2026-11-07T15:00:00Z')
  expect(periodoDoEndereco(new URLSearchParams(''), agora)).toEqual({ de: '2026-11-01', ate: '2026-11-07' })
  expect(periodoDoEndereco(new URLSearchParams('de=&ate='), agora)).toEqual({ de: '', ate: '' })
  expect(periodoDoEndereco(new URLSearchParams('de=2026-10-01'), agora)).toEqual({ de: '2026-10-01', ate: '' })
  expect(periodoDoEndereco(new URLSearchParams('de=ontem&ate=2026-10-02'), agora)).toEqual({ de: '', ate: '2026-10-02' })
})
