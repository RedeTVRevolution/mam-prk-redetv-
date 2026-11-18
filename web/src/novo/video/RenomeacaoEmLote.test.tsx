import type { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { criarClienteDeConsultas } from '../consultas.ts'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { DECUPAGEM as BASE } from './curadoria-teste.ts'

// A paridade de "Renomear em todos os vídeos" com o RenomeacaoEmLote.test.tsx da interface antiga.

const DECUPAGEM = (nome: string) => ({ ...BASE, pessoas: [{ ...BASE.pessoas[0], nome, catalogo_id: 'cat-leo' }] })

let decupagemAtual = DECUPAGEM('Leo Lobo')
let pedidos: { id: string; corpo: { nome: string; previa: boolean } }[] = []
let andamentoConsultado = 0

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => decupagemAtual,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: [] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.post('/v1/catalogo/pessoas/:id/renomear', async ({ request, params }) => {
    const corpo = (await request.json()) as { nome: string; previa: boolean }
    pedidos.push({ id: String(params.id), corpo })
    if (!corpo.previa) decupagemAtual = DECUPAGEM(corpo.nome)
    return HttpResponse.json({ nome_antigo: 'Leo Lobo', nome_novo: corpo.nome, videos: 3, momentos_afetados: 7, previa: corpo.previa })
  }),
  http.get('/v1/catalogo/pessoas/:id/renomear/andamento', () => {
    andamentoConsultado += 1
    return new HttpResponse(null, { status: 404 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  decupagemAtual = DECUPAGEM('Leo Lobo')
  pedidos = []
  andamentoConsultado = 0
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const inspetor = () => within(screen.getByRole('complementary', { name: 'Inspetor' }))
const detalhe = () => within(inspetor().getByRole('region', { name: /^Detalhe:/ }))

async function abrir(permissoes: string[], revisando = true, consultas?: QueryClient) {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes, acompanhamentoMs: 5000, indexacaoMs: 2000, consultas })
  ;(document.activeElement as HTMLElement).blur()
  if (revisando) await usuario.keyboard('e')
  const secao = inspetor().getByRole('button', { name: /^Pessoas \d+$/ })
  if (secao.getAttribute('aria-expanded') !== 'true') await usuario.click(secao)
  await usuario.click(inspetor().getByRole('button', { name: /^Leo Lobo, 1 aparição/ }))
  await usuario.click(await inspetor().findByRole('button', { name: /^Leo Lobo, 00:10 a 00:20/ }))
  await detalhe().findByRole('button', { name: 'Corrigir' })
  ;(document.activeElement as HTMLElement).blur()
  return usuario
}

const APROVADOR = ['decupagem.editar', 'correcao.aprovar']

async function digitarOutroNome(usuario: ReturnType<typeof userEvent.setup>) {
  await usuario.click(await detalhe().findByRole('button', { name: 'Renomear Leo Lobo em todos os vídeos' }))
  const campo = screen.getByRole('textbox', { name: 'Novo nome' })
  await usuario.clear(campo)
  await usuario.type(campo, 'Leão Lobo')
}

test('mostra a prévia sem mudar nada e, com Enter, renomeia e fecha sem consultar andamento', async () => {
  const usuario = await abrir(APROVADOR)
  await digitarOutroNome(usuario)

  await usuario.keyboard('{Enter}')

  expect(await screen.findByText(/Leo Lobo passa a ser Leão Lobo em 3 vídeos \(7 momentos\)/)).toBeTruthy()
  expect(pedidos).toEqual([{ id: 'cat-leo', corpo: { nome: 'Leão Lobo', previa: true } }])

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(pedidos[1]).toEqual({ id: 'cat-leo', corpo: { nome: 'Leão Lobo', previa: false } }))
  expect(await inspetor().findByRole('region', { name: /^Detalhe: Leão Lobo/ })).toBeTruthy()
  await waitFor(() => expect(screen.queryByRole('form', { name: /Renomear/ })).toBeNull())
  expect(screen.queryByRole('alert')).toBeNull()
  expect(andamentoConsultado).toBe(0)
}, 20_000)

test('renomear invalida a decupagem de todos os vídeos, não só a do vídeo aberto', async () => {
  const consultas = criarClienteDeConsultas()
  consultas.setQueryData(['video', 'j2', 'decupagem'], { versao_decupagem: 'v1' })
  const usuario = await abrir(APROVADOR, true, consultas)
  await digitarOutroNome(usuario)
  await usuario.keyboard('{Enter}')
  await screen.findByText(/Leo Lobo passa a ser Leão Lobo em 3 vídeos/)
  expect(consultas.getQueryState(['video', 'j2', 'decupagem'])?.isInvalidated).toBe(false)

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(consultas.getQueryState(['video', 'j2', 'decupagem'])?.isInvalidated).toBe(true))
}, 20_000)

test('Esc cancela depois da prévia sem renomear', async () => {
  const usuario = await abrir(APROVADOR)
  await digitarOutroNome(usuario)
  await usuario.keyboard('{Enter}')
  await screen.findByText(/passa a ser Leão Lobo/)

  await usuario.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('form', { name: /Renomear/ })).toBeNull())
  expect(pedidos.map((p) => p.corpo.previa)).toEqual([true])
})

test('sem correcao.aprovar, o botão não aparece', async () => {
  await abrir(['decupagem.editar'])
  expect(screen.queryByRole('button', { name: /Renomear Leo Lobo/ })).toBeNull()
})

test('fora do modo de revisão, o botão não aparece', async () => {
  await abrir(APROVADOR, false)
  expect(screen.queryByRole('button', { name: /Renomear Leo Lobo/ })).toBeNull()
})
