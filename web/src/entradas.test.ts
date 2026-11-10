import { expect, test } from 'vitest'
import { tempoDaEntradaMs } from './entradas.ts'
import type { Job } from './jobs.ts'

const JOB: Job = {
  id: 'j1',
  nome: 'clipe.mp4',
  estado: 'concluido',
  codigo_falha: null,
  criado_em: '2026-11-01T12:00:00Z',
  reprocessavel_ate: '2026-11-08T12:00:00Z',
  atualizado_em: '2026-11-04T12:00:00Z',
  etapas: [
    { nome: 'transcricao', inicio: '2026-11-01T12:01:00Z', fim: '2026-11-01T12:05:00Z', resultado: 'concluida' },
    { nome: 'indexacao', inicio: '2026-11-03T14:05:00Z', fim: '2026-11-03T14:06:49Z', resultado: 'concluida' },
    { nome: 'analise', inicio: '2026-11-03T14:00:00Z', fim: '2026-11-03T14:04:00Z', resultado: 'concluida' },
  ],
}

const AGORA = Date.parse('2026-11-04T15:00:00Z')

test('o tempo da entrada mede só a passada atual até o último fim de etapa', () => {
  expect(tempoDaEntradaMs({ ...JOB, inicio_da_passada: '2026-11-03T14:00:00Z', reprocessamentos: 1 }, AGORA)).toBe(409_000)
})

test.each([undefined, null])('legado sem reprocesso usa a criação quando o início é %s', (inicio_da_passada) => {
  expect(tempoDaEntradaMs({ ...JOB, inicio_da_passada, reprocessamentos: 0 }, AGORA)).toBe(180_409_000)
})

test.each([undefined, null])('legado reprocessado fica sem tempo quando o início é %s', (inicio_da_passada) => {
  expect(tempoDaEntradaMs({ ...JOB, inicio_da_passada, reprocessamentos: 1 }, AGORA)).toBeNull()
})

test('a coluna Tempo é o total da passada, mesmo com uma etapa em andamento', () => {
  const job: Job = {
    ...JOB,
    estado: 'analisando',
    etapa_atual: 'analise',
    inicio_da_passada: '2026-11-04T14:00:00Z',
    etapas: [
      { nome: 'transcricao', inicio: '2026-11-04T14:01:00Z', fim: null, resultado: null },
      { nome: 'analise', inicio: '2026-11-04T14:30:00Z', fim: null, resultado: null },
    ],
  }
  expect(tempoDaEntradaMs(job, AGORA)).toBe(3_600_000)
})
