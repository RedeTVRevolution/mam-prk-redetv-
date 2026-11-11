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

const PASSADA: Job = {
  ...JOB,
  estado: 'concluido',
  inicio_da_passada: '2026-11-03T14:00:00Z',
  reprocessamentos: 1,
}

test('o tempo para no fim da indexação da passada, mesmo com uma etapa avulsa refeita depois e ainda rodando', () => {
  const job: Job = {
    ...PASSADA,
    etapa_atual: 'quadros',
    etapas: [
      ...(JOB.etapas ?? []),
      { nome: 'quadros', inicio: '2026-11-04T14:00:00Z', fim: null, resultado: null },
    ],
  }
  expect(tempoDaEntradaMs(job, AGORA)).toBe(409_000)
  expect(tempoDaEntradaMs(job, AGORA + 3_600_000)).toBe(409_000)
})

test('o tempo para no fim da indexação mesmo quando uma etapa refeita terminou depois dela', () => {
  const job: Job = {
    ...PASSADA,
    etapas: [
      ...(JOB.etapas ?? []),
      { nome: 'quadros', inicio: '2026-11-04T14:00:00Z', fim: '2026-11-04T14:30:00Z', resultado: 'concluida' },
    ],
  }
  expect(tempoDaEntradaMs(job, AGORA)).toBe(409_000)
})

test('a indexação de antes da passada não conta: segue o comportamento de hoje', () => {
  const job: Job = {
    ...PASSADA,
    inicio_da_passada: '2026-11-04T10:00:00Z',
    etapa_atual: 'quadros',
    etapas: [
      { nome: 'indexacao', inicio: '2026-11-03T14:05:00Z', fim: '2026-11-03T14:06:49Z', resultado: 'concluida' },
      { nome: 'quadros', inicio: '2026-11-04T10:30:00Z', fim: null, resultado: null },
    ],
  }
  expect(tempoDaEntradaMs(job, AGORA)).toBe(18_000_000)
})

test.each([
  ['em curso', null, null],
  ['com falha', '2026-11-03T14:06:49Z', 'falhou' as const],
])('indexação %s não para o relógio', (_nome, fim, resultado) => {
  const job: Job = {
    ...PASSADA,
    etapa_atual: 'quadros',
    etapas: [
      { nome: 'indexacao', inicio: '2026-11-03T14:05:00Z', fim, resultado },
      { nome: 'quadros', inicio: '2026-11-04T14:00:00Z', fim: null, resultado: null },
    ],
  }
  expect(tempoDaEntradaMs(job, AGORA)).toBe(AGORA - Date.parse('2026-11-03T14:00:00Z'))
})
