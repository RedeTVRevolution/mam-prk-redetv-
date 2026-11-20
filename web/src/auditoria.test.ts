import { expect, test } from 'vitest'
import { consultaDaAuditoria, detalhesEmFrases, FRASE_DA_ACAO, type RegistroDeAuditoria } from './auditoria.ts'

function registro(acao: string, detalhes: Record<string, unknown>): RegistroDeAuditoria {
  return { id: '1', quando: '2026-11-17T00:00:00Z', acao, alvo_tipo: 'marca', alvo_id: 'm1', detalhes } as RegistroDeAuditoria
}

test('as ações do cadastro de marcas têm frase e detalhes legíveis', () => {
  expect(FRASE_DA_ACAO['marca.juntada']).toBe('Juntou outra marca nesta')
  expect(detalhesEmFrases(registro('marca.criada', { apelidos: ['UniAefel'] }))).toEqual(['Apelidos: UniAefel'])
  expect(detalhesEmFrases(registro('marca.alterada', { apelidos_antes: [], apelidos_depois: ['Uni Fael'] }))).toEqual([
    'Antes: nenhum',
    'Depois: Uni Fael',
  ])
  expect(
    detalhesEmFrases(registro('marca.juntada', { outra_id: 'm2', outra_nome: 'UniAefel', apelidos_depois: ['UniAefel'] })),
  ).toEqual(['Juntou: UniAefel', 'Apelidos depois: UniAefel'])
})

test('a consulta da auditoria corta o dia de São Paulo, com horário de verão (2018) e o fim inclusivo', () => {
  const p = new URLSearchParams(consultaDaAuditoria({ pessoa: '', alvo: '', acao: '', de: '2018-11-10', ate: '2018-11-10' }, 50, null))
  expect(new Date(p.get('de')!).getTime()).toBe(Date.parse('2018-11-10T00:00:00-02:00'))
  expect(new Date(p.get('ate')!).getTime()).toBe(Date.parse('2018-11-10T23:59:59.999-02:00'))
})
