import { expect, test } from 'vitest'
import { abaDoPainel, parametrosDoPainel, programaEUsuarioJuntos, rotuloDoGrupo } from './painelDaDiretoria.ts'

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

test('o agrupamento só vai à API quando pedido', () => {
  const f = { programa: '', usuario: 'u1', de: '2026-01-01', ate: '' }
  expect(parametrosDoPainel(f)).toBe('usuario=u1&desde=2026-01-01')
  expect(parametrosDoPainel(f, { agrupar: 'auto' })).toBe('usuario=u1&desde=2026-01-01&agrupar=auto')
})

test('rotuloDoGrupo nomeia o grupo pelo primeiro dia, na tabela e no eixo', () => {
  expect(rotuloDoGrupo('2026-11-02', 'dia')).toBe('02/11/2026')
  expect(rotuloDoGrupo('2026-11-02', 'semana', true)).toBe('02/11')
  expect(rotuloDoGrupo('2026-11-01', 'mes')).toBe('11/2026')
  expect(rotuloDoGrupo('2026-11-01', 'mes', true)).toBe('11/26')
  expect(rotuloDoGrupo('2026-10-01', 'trimestre')).toBe('4º tri. 2026')
  expect(rotuloDoGrupo('2026-01-01', 'trimestre', true)).toBe('1º tri. 26')
})
