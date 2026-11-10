import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { abrirVideo, JOB, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

const DECUPAGEM = { pautas: [], pessoas: [], planos: [], comerciais: [], transcricao: [], textos_na_tela: [] }

let corpos: unknown[] = []
let status = 200
const servidor = setupServer(
  ...rotasDoVideo(
    () => ({}),
    () => DECUPAGEM,
  ),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama', 'Hoje em Dia'])),
  http.patch('/v1/jobs/j1', async ({ request }) => {
    corpos.push(await request.json())
    if (status !== 200) return HttpResponse.json({ detail: 'Data de exibição no futuro' }, { status })
    return HttpResponse.json({ ...JOB, programa: 'Hoje em Dia', data_exibicao: '2026-01-02' })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  corpos = []
  status = 200
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

test('sem decupagem.editar não há botão Editar', async () => {
  await abrirVideo({ permissoes: ['decupagem.ver'] })

  expect(screen.queryByRole('button', { name: 'Editar data e programa' })).toBeNull()
})

test('edita a data e o programa, manda só o que mudou e mostra o novo título', async () => {
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  const usuario = userEvent.setup()

  await usuario.click(screen.getByRole('button', { name: 'Editar data e programa' }))
  fireEvent.change(await screen.findByLabelText('Data de exibição'), { target: { value: '2026-01-02' } })
  await usuario.selectOptions(screen.getByLabelText('Programa'), 'Hoje em Dia')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(corpos).toEqual([{ data_exibicao: '2026-01-02', programa: 'Hoje em Dia' }]))
  expect(await screen.findByText('Hoje em Dia · 02/01/2026')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('mostra o motivo da recusa e mantém o diálogo aberto', async () => {
  status = 422
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  const usuario = userEvent.setup()

  await usuario.click(screen.getByRole('button', { name: 'Editar data e programa' }))
  fireEvent.change(await screen.findByLabelText('Data de exibição'), { target: { value: '2026-01-02' } })
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  expect(await screen.findByText('Data de exibição no futuro')).toBeTruthy()
  expect(screen.getByRole('dialog')).toBeTruthy()
})
