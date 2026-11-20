import { expect, test } from 'vitest'
import { abaDoPainel, filtrosDoPainel, horasDeVideo, filtrosParaEnderecoDoPainel, parametrosDoPainel, programaEUsuarioJuntos, rotuloDoGrupo } from './painelDaDiretoria.ts'

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
  expect(parametrosDoPainel(f)).toBe('usuario=u1&desde=2026-01-01&ate=')
  expect(parametrosDoPainel(f, { agrupar: 'auto' })).toBe('usuario=u1&desde=2026-01-01&ate=&agrupar=auto')
})

test('o agrupamento vai para o endereço e volta dele; o automático fica de fora e valor inválido sai', () => {
  const base = { programa: '', usuario: '', de: '2026-01-01', ate: '2026-01-31' }
  expect(filtrosParaEnderecoDoPainel({ ...base, agrupar: 'semana' })).toBe('?de=2026-01-01&ate=2026-01-31&agrupar=semana')
  expect(filtrosParaEnderecoDoPainel({ ...base, agrupar: 'auto' })).toBe('?de=2026-01-01&ate=2026-01-31')
  expect(filtrosDoPainel('?de=2026-01-01&ate=2026-01-31&agrupar=mes').agrupar).toBe('mes')
  expect(filtrosDoPainel('?de=2026-01-01&ate=2026-01-31&agrupar=ano').agrupar).toBeUndefined()
})

test('rotuloDoGrupo nomeia o grupo pelo primeiro dia, na tabela e no eixo', () => {
  expect(rotuloDoGrupo('2026-11-02', 'dia')).toBe('02/11/2026')
  expect(rotuloDoGrupo('2026-11-02', 'semana', true)).toBe('02/11')
  expect(rotuloDoGrupo('2026-11-01', 'mes')).toBe('11/2026')
  expect(rotuloDoGrupo('2026-11-01', 'mes', true)).toBe('11/26')
  expect(rotuloDoGrupo('2026-10-01', 'trimestre')).toBe('4º tri. 2026')
  expect(rotuloDoGrupo('2026-01-01', 'trimestre', true)).toBe('1º tri. 26')
})

test('horasDeVideo nunca escreve "-0": zero sai sem sinal e o negativo de verdade fica', () => {
  expect(horasDeVideo(-0.04)).toBe('0')
  expect(horasDeVideo(-0)).toBe('0')
  expect(horasDeVideo(3.5)).toBe('3,5')
  expect(horasDeVideo(-0.06)).toBe('-0,1')
})
