import { expect, test } from 'vitest'
import { finalizando, TETO_DO_FINALIZANDO_MS, type Job } from './jobs.ts'

const INICIO = '2026-11-01T12:00:00Z'
const AGORA = Date.parse(INICIO)
const job = (extra: Partial<Job>): Job => ({
  id: 'j1',
  nome: 'clipe.mp4',
  estado: 'concluido',
  codigo_falha: null,
  criado_em: INICIO,
  reprocessavel_ate: '2026-11-08T12:00:00Z',
  atualizado_em: INICIO,
  ...extra,
})
const inventario = (fim: string | null = null) => ({ nome: 'inventario_de_objetos', inicio: INICIO, fim, resultado: null })
const indexacao = (fim: string | null) => ({ nome: 'indexacao', inicio: INICIO, fim, resultado: null })

test('o selo vale logo antes do teto e some ao passar dele, com um Job parado entre etapas', () => {
  const parado = job({ etapas: [inventario('2026-11-01T12:30:00Z')], etapa_atual: null })
  expect(finalizando(parado, AGORA + TETO_DO_FINALIZANDO_MS)).toBe(true)
  expect(finalizando(parado, AGORA + TETO_DO_FINALIZANDO_MS + 1)).toBe(false)
})

test('o selo cobre uma etapa em curso até o teto', () => {
  const rodando = job({ etapas: [inventario()], etapa_atual: 'inventario_de_objetos' })
  expect(finalizando(rodando, AGORA + TETO_DO_FINALIZANDO_MS)).toBe(true)
  expect(finalizando(rodando, AGORA + TETO_DO_FINALIZANDO_MS + 1)).toBe(false)
})

test('o selo continua com a indexação pendente e some quando ela ganha fim', () => {
  const pendente = job({ indexacao: { estado: 'pendente', em: INICIO } })
  expect(finalizando(pendente, AGORA + 1000)).toBe(true)
  const pronto = job({ etapas: [indexacao('2026-11-01T12:10:00Z')], indexacao: { estado: 'indexado', em: INICIO } })
  expect(finalizando(pronto, AGORA + 1000)).toBe(false)
})

test('só um Job concluído tem o selo', () => {
  expect(finalizando(job({ estado: 'analisando', etapa_atual: 'analise' }), AGORA)).toBe(false)
})
