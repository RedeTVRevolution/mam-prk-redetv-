import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { correcaoDoHistorico, DECUPAGEM } from './curadoria-teste.ts'

// A gaveta dentro da tela do vídeo: o botão Histórico, o salto ao item e o "Refazer à mão".

let historico: object[] = []
let fila: object[] = []
const pedidos = { historico: 0, fila: 0 }

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => DECUPAGEM,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => {
    pedidos.historico += 1
    return HttpResponse.json(historico)
  }),
  http.get('/v1/jobs/j1/fila', () => {
    pedidos.fila += 1
    return HttpResponse.json(fila)
  }),
  http.get('/v1/jobs/j1/sugestoes', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/revisao/aprovar', () => HttpResponse.json({ indexacao: 'pendente' }, { status: 202 })),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
  historico = []
  fila = []
  pedidos.historico = 0
  pedidos.fila = 0
})
afterAll(() => servidor.close())

const gaveta = () => within(screen.getByRole('complementary', { name: 'Correções do vídeo' }))

const FILA_ESTRUTURAL = {
  id: 'f1',
  tipo: 'pauta.juntar',
  autor_email: 'bia@redetv.com.br',
  criada_em: '2026-10-30T15:00:00Z',
  motivo: 'pautas juntadas pelo editor',
  antes: null,
  depois: '{"ids":["x1","x2"],"titulo":"Eleição"}',
  antes_legivel: 'Eleição + Clima',
  depois_legivel: 'Eleição',
  candidatos: [],
}

async function abrir(permissoes = ['decupagem.editar']) {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ permissoes })
  ;(document.activeElement as HTMLElement).blur()
  return { usuario, player }
}

test('o botão Histórico abre a gaveta no lugar do inspetor, e a contagem vem da fila e das pendentes', async () => {
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br', 'pendente')]
  const { usuario } = await abrir(['decupagem.editar', 'correcao.aprovar'])

  const botao = await screen.findByRole('button', { name: 'Histórico' })
  expect((await within(botao).findByRole('img', { name: '1 a resolver' })).textContent).toBe('1')
  await usuario.click(botao)

  expect(botao.getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()
  expect(screen.getByLabelText('Player')).toBeTruthy()
  expect(await gaveta().findByRole('tab', { name: 'Aprovação (1)' })).toBeTruthy()

  await usuario.click(gaveta().getByRole('button', { name: 'Fechar' }))
  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
  expect(screen.getByRole('complementary', { name: 'Inspetor' })).toBeTruthy()
})

test('clicar numa correção da gaveta salta o player ao item', async () => {
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br')]
  const { usuario, player } = await abrir()

  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  await usuario.click(await gaveta().findByRole('button', { name: /^Saltar ao item/ }))

  expect(player.currentTime).toBe(10)
})

test('sem decupagem.editar não há botão Histórico nem pedido de histórico ou fila', async () => {
  await abrir(['decupagem.ver'])

  expect(screen.queryByRole('button', { name: 'Histórico' })).toBeNull()
  expect(pedidos).toEqual({ historico: 0, fila: 0 })
})

test('com a gaveta aberta, as setas e o Enter são dela', async () => {
  const comercial = { ...correcaoDoHistorico('c2', 'bia@redetv.com.br', 'ativa', 'comercial.marca'), item_id: 'c1', ancora: { versao: 'v1', tipo_do_item: 'comercial' } }
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br'), comercial]
  const { usuario, player } = await abrir()
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  await gaveta().findAllByRole('button', { name: /^Saltar ao item/ })

  // O foco no corpo da página: o Enter não é de nenhum botão.
  await usuario.click(document.body)
  await usuario.keyboard('{ArrowDown}{Enter}')

  // Um só salto, ao item da segunda correção (o comercial, em 40 s).
  await waitFor(() => expect(player.currentTime).toBe(40))
})

test('Refazer à mão, fora do modo de revisão, liga o modo e deixa marcar as pautas', async () => {
  fila = [FILA_ESTRUTURAL]
  const { usuario } = await abrir()
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  await usuario.click(await gaveta().findByRole('tab', { name: /Fila de revisão/ }))

  await usuario.click(await gaveta().findByRole('button', { name: 'Refazer à mão' }))

  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
  expect(await screen.findByText('Marque as pautas (M) e junte (U), ou divida (D).')).toBeTruthy()
  await usuario.click(await screen.findByRole('button', { name: 'Marcar Eleição para juntar' }))
  expect(await screen.findByText('1 pauta marcada para juntar')).toBeTruthy()
})

test('o F2 com a gaveta aberta traz o formulário de volta ao inspetor', async () => {
  const { usuario } = await abrir()
  await usuario.keyboard('e')
  const secao = within(screen.getByRole('complementary', { name: 'Inspetor' })).getByRole('button', { name: /^Pautas \d+$/ })
  if (secao.getAttribute('aria-expanded') !== 'true') await usuario.click(secao)
  await usuario.click(await screen.findByRole('button', { name: /^Eleição, / }))
  await usuario.keyboard('{Escape}')
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()
  ;(document.activeElement as HTMLElement).blur()

  await usuario.keyboard('{F2}')

  expect(await screen.findByRole('form', { name: 'Corrigir Eleição' })).toBeTruthy()
  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
})
