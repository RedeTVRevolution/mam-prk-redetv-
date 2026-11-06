import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { DECUPAGEM as BASE } from './curadoria-teste.ts'

// A paridade de "Renomear em todos os vídeos" com o RenomeacaoEmLote.test.tsx da interface atual.

const DECUPAGEM = (nome: string) => ({ ...BASE, pessoas: [{ ...BASE.pessoas[0], nome, catalogo_id: 'cat-leo' }] })

let decupagemAtual = DECUPAGEM('Leo Lobo')
let pedidos: { id: string; corpo: { nome: string; previa: boolean } }[] = []
let consultas = 0
let retomadas = 0
let estadoFinal: 'concluida' | 'falhou' = 'concluida'

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
    consultas += 1
    const feito = consultas > 1
    return HttpResponse.json({
      estado: feito ? estadoFinal : 'em_andamento',
      feitos: feito && estadoFinal === 'concluida' ? 3 : 1,
      total: 3,
      nome_antigo: 'Leo Lobo',
      nome_novo: 'Leão Lobo',
    })
  }),
  http.post('/v1/catalogo/pessoas/:id/renomear/retomar', () => {
    retomadas += 1
    estadoFinal = 'concluida'
    consultas = 0
    return HttpResponse.json({ estado: 'em_andamento', feitos: 1, total: 3, nome_antigo: 'Leo Lobo', nome_novo: 'Leão Lobo' })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  decupagemAtual = DECUPAGEM('Leo Lobo')
  pedidos = []
  consultas = 0
  retomadas = 0
  estadoFinal = 'concluida'
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

async function abrir(permissoes: string[], revisando = true) {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes, intervalos: { acompanhamentoMs: 5000, indexacaoMs: 2000 } })
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

test('mostra a prévia sem mudar nada e, com Enter, renomeia e acompanha a busca até terminar', async () => {
  const usuario = await abrir(APROVADOR)
  await digitarOutroNome(usuario)

  await usuario.keyboard('{Enter}')

  expect(await screen.findByText(/Leo Lobo passa a ser Leão Lobo em 3 vídeos \(7 momentos\)/)).toBeTruthy()
  expect(pedidos).toEqual([{ id: 'cat-leo', corpo: { nome: 'Leão Lobo', previa: true } }])

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(pedidos[1]).toEqual({ id: 'cat-leo', corpo: { nome: 'Leão Lobo', previa: false } }))
  expect(await screen.findByText('Atualizando a busca: 1 de 3 vídeos.')).toBeTruthy()
  expect(await inspetor().findByRole('region', { name: /^Detalhe: Leão Lobo/ })).toBeTruthy()
  expect(await screen.findByText(/Pronto: Leão Lobo em 3 vídeos/, undefined, { timeout: 4000 })).toBeTruthy()
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

test('se a busca não termina, "Tentar de novo" retoma', async () => {
  estadoFinal = 'falhou'
  const usuario = await abrir(APROVADOR)
  await digitarOutroNome(usuario)
  await usuario.keyboard('{Enter}')
  await screen.findByText(/passa a ser/)
  await usuario.keyboard('{Enter}')

  const retomar = await screen.findByRole('button', { name: 'Tentar de novo' }, { timeout: 4000 })
  expect(screen.getByText(/O nome novo já vale nas decupagens/)).toBeTruthy()
  await usuario.click(retomar)

  await waitFor(() => expect(retomadas).toBe(1))
  expect(await screen.findByText(/Pronto: Leão Lobo/, undefined, { timeout: 4000 })).toBeTruthy()
}, 20_000)

test('sem correcao.aprovar, o botão não aparece', async () => {
  await abrir(['decupagem.editar'])
  expect(screen.queryByRole('button', { name: /Renomear Leo Lobo/ })).toBeNull()
})

test('fora do modo de revisão, o botão não aparece', async () => {
  await abrir(APROVADOR, false)
  expect(screen.queryByRole('button', { name: /Renomear Leo Lobo/ })).toBeNull()
})
