import { expect, test } from 'vitest'
import { detalhesEmFrases, FRASE_DA_ACAO, type RegistroDeAuditoria } from './auditoria.ts'

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
