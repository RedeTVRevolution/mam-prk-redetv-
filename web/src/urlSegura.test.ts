import { describe, expect, it } from 'vitest'
import { urlSegura } from './urlSegura.ts'

describe('urlSegura', () => {
  it.each(['https://storage.googleapis.com/x?sig=1', '/acervo', '/video/abc?t=3'])('aceita %s', (u) => {
    expect(urlSegura(u)).toBe(u)
  })

  it.each([
    'javascript:alert(1)',
    ' JaVaScRiPt:alert(1)',
    'java\tscript:alert(1)',
    'data:text/html,<b>x</b>',
    'http://exemplo.com/x',
    'otpauth://totp/MAM',
    '//outro.site/x',
    '/\\outro.site',
    'acervo',
    '',
  ])('recusa %j', (u) => {
    expect(urlSegura(u)).toBeNull()
  })

  it('recusa vazio', () => {
    expect(urlSegura(null)).toBeNull()
    expect(urlSegura(undefined)).toBeNull()
  })
})

const fontes = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.*'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

describe('texto de usuário na tela', () => {
  it('nenhum arquivo usa dangerouslySetInnerHTML, innerHTML ou outerHTML', () => {
    expect(Object.keys(fontes).length).toBeGreaterThan(50)
    const achados = Object.entries(fontes)
      .filter(([, texto]) => /dangerouslySetInnerHTML|\.(inner|outer)HTML|insertAdjacentHTML/.test(texto))
      .map(([caminho]) => caminho)
    expect(achados).toEqual([])
  })
})
