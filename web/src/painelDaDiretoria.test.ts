import { expect, test } from 'vitest'
import { abaDoPainel, programaEUsuarioJuntos } from './painelDaDiretoria.ts'

test('abaDoPainel: vazio é Acessos, aba conhecida passa e desconhecida é null', () => {
  expect(abaDoPainel(undefined)).toBe('acessos')
  expect(abaDoPainel('videos')).toBe('videos')
  expect(abaDoPainel('buscas')).toBe('buscas')
  expect(abaDoPainel('revisao')).toBe('revisao')
  expect(abaDoPainel('api')).toBe('api')
  expect(abaDoPainel('custo')).toBe('custo')
  expect(abaDoPainel('outra')).toBeNull()
})

test('programaEUsuarioJuntos só vale com os dois', () => {
  const base = { programa: '', usuario: '', de: '', ate: '' }
  expect(programaEUsuarioJuntos({ ...base, programa: 'X' })).toBe(false)
  expect(programaEUsuarioJuntos({ ...base, programa: 'X', usuario: 'u1' })).toBe(true)
})
