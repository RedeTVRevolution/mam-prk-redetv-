import { expect, test } from 'vitest'
import { casaComOsFiltrosDoCliente, consultaDasEntradas, filtrosDasEntradas, filtrosParaEnderecoDasEntradas, SEM_FILTROS_DAS_ENTRADAS, tempoDaEntradaMs } from './entradas.ts'
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

// 14/11 12:00 em São Paulo; e 13/11 23:00 em São Paulo (já é 14/11 em UTC).
const MEIO_DIA = new Date('2026-11-14T15:00:00Z')
const PERTO_DA_MEIA_NOITE = new Date('2026-11-14T02:00:00Z')

test('sem período no endereço, a aba abre na última semana: hoje menos 6 dias, no dia de São Paulo', () => {
  expect(filtrosDasEntradas('', MEIO_DIA)).toMatchObject({ de: '2026-11-08', ate: '' })
  expect(filtrosDasEntradas('', PERTO_DA_MEIA_NOITE)).toMatchObject({ de: '2026-11-07', ate: '' })
  expect(filtrosDasEntradas('?de=lixo&ate=2026-11-10', MEIO_DIA)).toMatchObject({ de: '2026-11-08', ate: '2026-11-10' })
})

test('de=tudo é "sem período"; um período explícito vale como está', () => {
  expect(filtrosDasEntradas('?de=tudo', MEIO_DIA)).toMatchObject({ de: '', ate: '' })
  expect(filtrosDasEntradas('?de=2026-10-01&ate=2026-10-05', MEIO_DIA)).toMatchObject({ de: '2026-10-01', ate: '2026-10-05' })
})

test('o endereço distingue o padrão (sem de) de "sem período" (de=tudo) e sobrevive a recarregar', () => {
  const tudo = filtrosParaEnderecoDasEntradas({ ...SEM_FILTROS_DAS_ENTRADAS }, MEIO_DIA)
  expect(tudo).toBe('?de=tudo')
  expect(filtrosDasEntradas(tudo, MEIO_DIA).de).toBe('')
  const periodo = filtrosParaEnderecoDasEntradas({ ...SEM_FILTROS_DAS_ENTRADAS, de: '2026-10-01', ate: '2026-10-05' }, MEIO_DIA)
  expect(periodo).toBe('?de=2026-10-01&ate=2026-10-05')
  expect(filtrosDasEntradas(periodo, MEIO_DIA)).toMatchObject({ de: '2026-10-01', ate: '2026-10-05' })
  expect(filtrosParaEnderecoDasEntradas({ ...SEM_FILTROS_DAS_ENTRADAS, ate: '2026-10-05' }, MEIO_DIA)).toBe('?de=tudo&ate=2026-10-05')
  // O padrão não vai escrito: o link de hoje não congela a semana de hoje.
  expect(filtrosParaEnderecoDasEntradas(filtrosDasEntradas('', MEIO_DIA), MEIO_DIA)).toBe('')
})

test('o período vai à API; sem período, não vai nada', () => {
  const consulta = (f: object, cursor: string | null = null) => new URLSearchParams(consultaDasEntradas({ ...SEM_FILTROS_DAS_ENTRADAS, ...f }, cursor))
  expect(consulta({ de: '2026-10-01', ate: '2026-10-05' }).get('enviado_de')).toBe('2026-10-01')
  expect(consulta({ de: '2026-10-01', ate: '2026-10-05' }).get('enviado_ate')).toBe('2026-10-05')
  expect(consulta({}).has('enviado_de')).toBe(false)
  expect(consulta({}).has('enviado_ate')).toBe(false)
})

test('o filtro do cliente não esconde mais por período, só os que não são de pessoa na lista "pessoas"', () => {
  const antigo = { ...JOB, criado_em: '2020-01-01T12:00:00Z', enviado_por: { tipo: 'pessoa' as const, nome: null } }
  expect(casaComOsFiltrosDoCliente(antigo, { ...SEM_FILTROS_DAS_ENTRADAS, de: '2026-11-01', ate: '2026-11-05' })).toBe(true)
  expect(casaComOsFiltrosDoCliente({ ...antigo, enviado_por: { tipo: 'sistema', nome: 'x' } }, { ...SEM_FILTROS_DAS_ENTRADAS, por: 'pessoas' })).toBe(false)
})
