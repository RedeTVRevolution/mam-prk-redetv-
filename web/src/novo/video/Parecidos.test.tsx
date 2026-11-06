import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import type { Job } from '../../jobs.ts'
import { abrirVideo, irPara, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { criarClienteDeConsultas } from '../consultas.ts'
import { chaveDoVideo } from './tipos.ts'

// A paridade do botão "Planos parecidos" com o ParecidosNoVisualizador.test.tsx da interface antiga.
// A grade que ele abre (/busca/parecidos) é testada em busca/Busca.test.tsx.

const plano = (id: string, inicio_ms: number) => ({ id, ambiente: `ambiente ${id}`, plano_limpo: false, inicio_ms, fim_ms: inicio_ms + 5_000 })

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [],
  planos: [plano('pl0', 0), plano('pl1', 10_000)],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

let comVetor: number[] = [1]
let consultas = 0
let job: Partial<Job> = {}

const servidor = setupServer(
  ...rotasDoVideo(() => job, () => DECUPAGEM),
  http.get('/v1/busca/parecidos/planos', () => {
    consultas += 1
    return HttpResponse.json({ planos: comVetor })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  comVetor = [1]
  consultas = 0
  job = { indexacao: { estado: 'indexado', em: '2026-10-21T10:00:00Z' } }
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const BOTAO = 'Planos parecidos com este'

/** O botão fica no plano de agora, no Agora do inspetor: o player é posto no meio do plano. */
async function abrirNoPlano(segundos: number) {
  irPara(await abrirVideo(), segundos)
  const agora = within(screen.getByRole('region', { name: 'Agora no vídeo' }))
  await agora.findByText(/ambiente pl\d/)
  return agora
}

test('o botão aparece só no plano com vetor e leva à grade dos parecidos', async () => {
  const agora = await abrirNoPlano(11)

  await userEvent.setup().click(await agora.findByRole('button', { name: BOTAO }))

  expect(location.pathname + location.search).toBe('/busca/parecidos?job=j1&plano=1')
})

test('o plano sem vetor não mostra o botão', async () => {
  const agora = await abrirNoPlano(2)

  expect(agora.queryByRole('button', { name: BOTAO })).toBeNull()
})

test('vídeo sem vetor nos planos não mostra o botão', async () => {
  comVetor = []
  const agora = await abrirNoPlano(11)

  await waitFor(() => expect(consultas).toBe(1))
  expect(agora.queryByRole('button', { name: BOTAO })).toBeNull()
})

test('vídeo ainda não indexado não mostra o botão nem consulta os vetores', async () => {
  job = { indexacao: { estado: 'pendente', em: '2026-10-21T10:00:00Z' } }
  const agora = await abrirNoPlano(11)

  expect(agora.queryByRole('button', { name: BOTAO })).toBeNull()
  expect(consultas).toBe(0)
})

test('depois de reprocessar, a nova indexação refaz a lista dos planos com vetor', async () => {
  // O cliente de consultas sobrevive: o job volta indexado em outro instante, com outros vetores.
  const consultasDoApp = criarClienteDeConsultas()
  irPara(await abrirVideo({ consultas: consultasDoApp }), 11)
  await within(screen.getByRole('region', { name: 'Agora no vídeo' })).findByRole('button', { name: BOTAO })
  cleanup()

  // O reprocessamento termina: o job vem de novo da API, indexado em outro instante.
  consultasDoApp.removeQueries({ queryKey: chaveDoVideo('j1', 'job') })
  job = { indexacao: { estado: 'indexado', em: '2026-10-22T10:00:00Z' } }
  comVetor = [0]
  irPara(await abrirVideo({ consultas: consultasDoApp }), 11)
  await waitFor(() => expect(consultas).toBe(2))
  const agora = within(screen.getByRole('region', { name: 'Agora no vídeo' }))
  await agora.findByText(/ambiente pl1/)
  expect(agora.queryByRole('button', { name: BOTAO })).toBeNull()
})

test('pelo detalhe de cada plano na seção Planos, o botão também aparece só no que tem vetor', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()
  const inspetor = within(screen.getByRole('complementary', { name: 'Inspetor' }))
  await usuario.click(inspetor.getByRole('button', { name: /^Planos \d+$/ }))

  await usuario.click(await inspetor.findByRole('button', { name: /^ambiente pl0/ }))
  await inspetor.findByRole('region', { name: 'Detalhe: ambiente pl0' })
  expect(inspetor.queryByRole('button', { name: BOTAO })).toBeNull()
  await usuario.keyboard('{Escape}')

  await usuario.click(await inspetor.findByRole('button', { name: /^ambiente pl1/ }))
  const detalhe = within(await inspetor.findByRole('region', { name: 'Detalhe: ambiente pl1' }))
  await usuario.click(detalhe.getByRole('button', { name: BOTAO }))
  expect(location.pathname + location.search).toBe('/busca/parecidos?job=j1&plano=1')
})
