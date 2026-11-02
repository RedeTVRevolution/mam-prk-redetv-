import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import type { Job } from './jobs.ts'
import { render } from './render-teste.tsx'
import Visualizador from './Visualizador.tsx'

const DECUPAGEM = {
  pautas: [],
  pessoas: [],
  planos: [],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

const item = (identidade: string, inicio_ms: number, marca: string, motivos: string[] = [], detalhe: string | null = null) => ({
  identidade,
  inicio_ms,
  fim_ms: inicio_ms + 10_000,
  detalhe,
  marca,
  motivos,
})

const LADO = { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 100, etapas: [] }
const COMPARACAO = {
  passada_id: 'p1',
  modelo: 'gemini-3.8-flash',
  modelo_do_job: 'gemini-3.5-flash-lite',
  duracao_ms: 3_600_000,
  a: { ...LADO, custo_usd: 0.5, custo_por_hora_usd: 0.5, tempo_total_s: 125 },
  b: { ...LADO, custo_usd: 3, custo_por_hora_usd: 3, tempo_total_s: 35 },
  requisitos: [
    { nome: 'famosos', a: [], b: [] },
    { nome: 'mencoes', a: [], b: [] },
    {
      nome: 'pautas',
      a: [item('Chuva', 0, 'igual'), item('Trânsito', 20_000, 'difere', ['tempo']), item('Clima', 60_000, 'so_aqui')],
      b: [item('Chuva', 0, 'igual'), item('Trânsito', 80_000, 'difere', ['tempo']), item('Política', 300_000, 'so_aqui')],
    },
    { nome: 'broll_limpos', a: [], b: [] },
    { nome: 'broll_descricoes', a: [], b: [] },
    { nome: 'comerciais', a: [], b: [] },
  ],
}

let passadas: unknown[] | 'proibido' = [
  { id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] },
]

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/jobs/j1/passadas', () =>
    passadas === 'proibido' ? new HttpResponse(null, { status: 403 }) : HttpResponse.json(passadas),
  ),
  http.get('/v1/jobs/j1/passadas/p1/comparacao', () => HttpResponse.json(COMPARACAO)),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  history.replaceState(null, '', '/')
})
afterAll(() => servidor.close())

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 3600,
  programa: 'TV Fama',
  data_exibicao: '2026-10-21',
  timecode_origem: '01:00:00:00',
  taxa_de_quadros: 30,
  cortes_ms: [],
  criado_em: '2026-10-21T10:00:00Z',
}

async function abrir() {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={false} />
    </AtalhosProvider>,
  )
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  await waitFor(() => expect(player.getAttribute('src')).toBe('https://exemplo.test/v.mp4'))
  return player
}

async function compararComPassada() {
  await userEvent.click(await screen.findByRole('combobox', { name: 'Comparar com' }))
  await userEvent.click(await screen.findByRole('option', { name: /gemini-3\.8-flash/ }))
  return { job: await screen.findByRole('region', { name: 'Decupagem do Job' }), passada: await screen.findByRole('region', { name: 'Decupagem da passada' }) }
}

test('o seletor lista as passadas pelo modelo e pela data', async () => {
  await abrir()
  await userEvent.click(await screen.findByRole('combobox', { name: 'Comparar com' }))

  expect(await screen.findByRole('option', { name: /gemini-3\.8-flash.*02\/11\/2026/ })).toBeTruthy()
})

test('sem passada, o Visualizador fica como hoje', async () => {
  passadas = []
  await abrir()
  await screen.findByLabelText('Player')

  expect(screen.queryByLabelText('Comparar com')).toBeNull()
  passadas = [{ id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] }]
})

test('sem permissão de ver as passadas, o seletor não aparece', async () => {
  passadas = 'proibido'
  await abrir()
  await screen.findByLabelText('Player')

  expect(screen.queryByLabelText('Comparar com')).toBeNull()
  passadas = [{ id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] }]
})

test('as duas decupagens ficam lado a lado, por requisito', async () => {
  await abrir()
  const { job, passada } = await compararComPassada()

  expect(within(job).getByText('Clima')).toBeTruthy()
  expect(within(job).queryByText('Política')).toBeNull()
  expect(within(passada).getByText('Política')).toBeTruthy()
  expect(within(job).getByText('Pautas')).toBeTruthy()
  expect(within(passada).getByText('Pautas')).toBeTruthy()
})

test('o custo por hora e o tempo de cada lado ficam no topo', async () => {
  await abrir()
  await compararComPassada()

  const topo = screen.getByRole('region', { name: 'Custo e tempo' })
  expect(topo.textContent).toContain('US$ 0,50 por hora')
  expect(topo.textContent).toContain('US$ 3,00 por hora')
  expect(topo.textContent).toContain('02:05')
  expect(topo.textContent).toContain('00:35')
})

test('o item que só um lado tem e o que difere ficam marcados, com palavras', async () => {
  await abrir()
  const { job, passada } = await compararComPassada()

  expect(within(within(job).getByRole('button', { name: /Clima/ })).getByText('só neste lado')).toBeTruthy()
  expect(within(within(passada).getByRole('button', { name: /Política/ })).getByText('só neste lado')).toBeTruthy()
  expect(within(within(job).getByRole('button', { name: /Trânsito/ })).getByText('difere: tempo')).toBeTruthy()
  expect(within(within(job).getByRole('button', { name: /Chuva/ })).queryByText(/difere|só neste/)).toBeNull()
})

test('clicar num item de qualquer lado leva o player ao início dele', async () => {
  const player = await abrir()
  const { job, passada } = await compararComPassada()

  fireEvent.click(within(passada).getByRole('button', { name: /Política/ }))
  expect(player.currentTime).toBe(300)

  fireEvent.click(within(job).getByRole('button', { name: /Clima/ }))
  expect(player.currentTime).toBe(60)
})

test('a passada não tem como ser corrigida nesta tela', async () => {
  await abrir()
  const { passada } = await compararComPassada()

  expect(within(passada).queryByRole('button', { name: /corrigir|remover|editar/i })).toBeNull()
})
