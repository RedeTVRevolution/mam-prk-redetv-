import { expect, test } from 'vitest'
import { baixarPelaUrl } from './baixar.ts'
import { urlSegura } from './urlSegura.ts'

test.each(['https://storage.googleapis.com/x?sig=1', '/acervo', '/video/abc?t=3'])('urlSegura aceita %s', (u) => {
  expect(urlSegura(u)).toBe(u)
})

test.each([
  'javascript:alert(1)',
  ' JaVaScRiPt:alert(1)',
  'java\tscript:alert(1)',
  'data:text/html,<b>x</b>',
  'http://exemplo.com/x',
  'otpauth://totp/MAM',
  '//outro.site/x',
  '/\\outro.site',
  '/\t/outro.site',
  'acervo',
  '',
  null,
  undefined,
])('urlSegura recusa %j', (u) => {
  expect(urlSegura(u)).toBeNull()
})

test('o download com endereço recusado vira erro, para a tela mostrar a falha', () => {
  expect(() => baixarPelaUrl('javascript:alert(1)')).toThrow()
})
