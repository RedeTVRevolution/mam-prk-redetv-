import type { InfiniteData } from '@tanstack/react-query'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import type { Job, PaginaDoAcervo } from '../../jobs.ts'
import { criarClienteDeConsultas } from '../consultas.ts'
import { abrirVideo, JOB, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// Os diálogos do menu do vídeo são os do acervo (`novo/comum/`); aqui se confere a ligação:
// o menu abre o diálogo, o pedido vai à API e o acervo em cache muda sem esperar o `staleTime`.

const DECUPAGEM = { pautas: [{ id: 'pa1', titulo: 'Eleição', inicio_ms: 0, fim_ms: 60_000 }], pessoas: [], planos: [], comerciais: [], transcricao: [], textos_na_tela: [] }
const OUTRO: Job = { ...JOB, id: 'j2', nome: 'OUTRO.mp4' }
const envios: unknown[] = []
const reprocessos: unknown[] = []

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({}),
    () => DECUPAGEM,
  ),
  http.get('/v1/admin/lixeira/videos/:id/impacto', () => HttpResponse.json({ decupagem: 1, correcoes: 0, arquivos: { copia_limpa: 1, proxy: 1, quadros: 10 }, outros_jobs: [] })),
  http.post('/v1/admin/lixeira/videos/:id', async ({ params, request }) => {
    envios.push({ id: params.id, corpo: await request.json() })
    return HttpResponse.json({}, { status: 201 })
  }),
  http.post('/v1/jobs/:id/reprocessar', async ({ request }) => {
    reprocessos.push(await request.json())
    return HttpResponse.json({ ...JOB, estado: 'analisando', etapa_atual: 'analise' })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  envios.length = 0
  reprocessos.length = 0
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

/** O acervo já visitado na sessão, em cache, com este vídeo e outro. */
function comAcervoEmCache() {
  const consultas = criarClienteDeConsultas()
  consultas.setQueryData<InfiniteData<PaginaDoAcervo>>(['acervo', {}], { pages: [{ jobs: [JOB, OUTRO], proximo: null }], pageParams: [null] })
  const acervo = () => consultas.getQueryData<InfiniteData<PaginaDoAcervo>>(['acervo', {}])!.pages[0].jobs
  return { consultas, acervo }
}

async function escolherNoMenu(item: RegExp) {
  const usuario = userEvent.setup()
  await usuario.click(screen.getByRole('button', { name: 'Mais ações' }))
  await usuario.click(await within(await screen.findByRole('menu')).findByRole('menuitem', { name: item }))
  return { usuario, dialogo: within(await screen.findByRole('dialog')) }
}

test('mandar para a lixeira pelo menu grava com o motivo, tira o vídeo do acervo em cache e volta ao acervo', async () => {
  const { consultas, acervo } = comAcervoEmCache()
  await abrirVideo({ permissoes: ['lixeira.gerir'], consultas })

  const { usuario, dialogo } = await escolherNoMenu(/Mandar para a lixeira…/)
  expect(await dialogo.findByText(/1 decupagem/)).toBeTruthy()
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'duplicado')
  await usuario.click(dialogo.getByRole('button', { name: 'Mandar para a lixeira' }))

  await waitFor(() => expect(location.pathname).toBe('/acervo'))
  expect(envios).toEqual([{ id: 'j1', corpo: { motivo: 'duplicado' } }])
  expect(acervo().map((j) => j.id)).toEqual(['j2'])
})

test('reprocessar pelo menu grava a etapa e o motivo, troca o Job no acervo em cache e acompanha na tela', async () => {
  const { consultas, acervo } = comAcervoEmCache()
  await abrirVideo({ permissoes: ['video.reprocessar_etapa'], consultas })

  const { usuario, dialogo } = await escolherNoMenu(/Reprocessar…/)
  await usuario.click(dialogo.getByRole('radio', { name: /Identificação/ }))
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'rosto trocado')
  await usuario.click(dialogo.getByRole('button', { name: 'Reprocessar' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(reprocessos).toEqual([{ etapa: 'identificacao', motivo: 'rosto trocado' }])
  expect(acervo().map((j) => [j.id, j.estado])).toEqual([
    ['j1', 'analisando'],
    ['j2', 'concluido'],
  ])
  expect(await screen.findByText(/Reprocessando:/)).toBeTruthy()
})
