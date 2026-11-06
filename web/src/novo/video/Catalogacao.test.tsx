import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { correcaoDoHistorico, DECUPAGEM } from './curadoria-teste.ts'

// A paridade do modo de catalogação (Revisar, Aprovar Revisão, Ctrl+Z e Desfazer) com o
// Catalogacao.test.tsx da interface atual. Decisão da fase 5: corrigir (F2 e Del) segue valendo
// fora do modo, como na fase 2b; o modo guarda o que só a revisão faz.

let desfeitas: { id: string; motivo: unknown }[] = []
let historico: Record<string, unknown>[] = []
let aprovacoesDaRevisao = 0
let liberarAprovacao: (() => void) | null = null

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => DECUPAGEM,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json(historico)),
  http.post('/v1/jobs/j1/revisao/aprovar', async () => {
    aprovacoesDaRevisao += 1
    if (liberarAprovacao !== null) await new Promise<void>((resolver) => (liberarAprovacao = resolver))
    return HttpResponse.json({ indexacao: 'pendente' }, { status: 202 })
  }),
  http.post('/v1/jobs/j1/correcoes/:id/desfazer', async ({ request, params }) => {
    desfeitas.push({ id: String(params.id), motivo: ((await request.json()) as { motivo: unknown }).motivo })
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  desfeitas = []
  aprovacoesDaRevisao = 0
  liberarAprovacao?.()
  liberarAprovacao = null
  historico = []
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const EDITOR = ['decupagem.editar']

async function abrir(permissoes = EDITOR) {
  await abrirVideo({ permissoes })
  ;(document.activeElement as HTMLElement).blur()
  return userEvent.setup()
}

test('E liga e desliga o modo de catalogação, só para quem edita', async () => {
  const usuario = await abrir()
  expect(screen.queryByText('Catalogando')).toBeNull()

  await usuario.keyboard('e')
  expect(screen.getByText('Catalogando')).toBeTruthy()

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()
})

test('sem decupagem.editar, E não faz nada e não está na lista do ?', async () => {
  const usuario = await abrir(['decupagem.ver'])

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).queryByText(/Revisar o vídeo/)).toBeNull()
  expect(within(lista).queryByRole('region', { name: 'Catalogação' })).toBeNull()
})

test('com decupagem.editar, a lista do ? traz os atalhos da catalogação', async () => {
  const usuario = await abrir()

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  const grupo = within(within(lista).getByRole('region', { name: 'Catalogação' }))
  for (const acao of [/Revisar o vídeo e, dentro da revisão, aprová-la/, /Desfazer a última correção/])
    expect(grupo.getByText(acao)).toBeTruthy()
})

test('Ctrl+Z desfaz a última correção do próprio editor e avisa', async () => {
  historico = [
    correcaoDoHistorico('c3', 'outro@redetv.com.br'),
    correcaoDoHistorico('c2', 'ana@redetv.com.br', 'desfeita'),
    correcaoDoHistorico('c1', 'ana@redetv.com.br'),
  ]
  const usuario = await abrir()
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  expect(await screen.findByText('Desfeito: Renomear pessoa (Leão Lobo → Não identificado)')).toBeTruthy()
  expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }])
})

test('Ctrl+Z pula a correção pendente, que a API não desfaz, e desfaz a aprovada', async () => {
  historico = [correcaoDoHistorico('c2', 'ana@redetv.com.br', 'pendente'), correcaoDoHistorico('c1', 'ana@redetv.com.br', 'aprovada')]
  const usuario = await abrir()
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  await waitFor(() => expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }]))
})

test('sem correção do editor, Ctrl+Z avisa que não há o que desfazer', async () => {
  historico = [correcaoDoHistorico('c1', 'outro@redetv.com.br')]
  const usuario = await abrir()
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  expect(await screen.findByText('Nada para desfazer neste vídeo.')).toBeTruthy()
  expect(desfeitas).toEqual([])
})

test('Ctrl+Shift+Z não desfaz', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir()
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}{Shift>}z{/Shift}{/Control}')

  expect(desfeitas).toEqual([])
})

test('Ctrl+Z fora do modo de catalogação não desfaz nada', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir()

  await usuario.keyboard('{Control>}z{/Control}')

  expect(desfeitas).toEqual([])
})

test('um segundo Ctrl+Z enquanto o primeiro anda não manda outro pedido', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir()
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}zz{/Control}')

  await waitFor(() => expect(desfeitas).toHaveLength(1))
  await new Promise((r) => setTimeout(r, 50))
  expect(desfeitas).toHaveLength(1)
})

test('o botão mostra Revisar fora da revisão e Aprovar Revisão dentro, como o E', async () => {
  const usuario = await abrir()
  const botao = screen.getByRole('button', { name: 'Revisar' })

  await usuario.hover(botao)
  expect(within(await screen.findByRole('tooltip')).getByText('E')).toBeTruthy()

  await usuario.click(botao)
  expect(screen.getByText('Catalogando')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Revisar' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Aprovar Revisão' })).toBeTruthy()

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()
  expect(screen.getByRole('button', { name: 'Revisar' })).toBeTruthy()
  await waitFor(() => expect(aprovacoesDaRevisao).toBe(1))
})

test('Aprovar Revisão sai do modo na hora, sem esperar a reindexação, e pede uma só', async () => {
  liberarAprovacao = () => {}
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Revisar' }))

  await usuario.click(screen.getByRole('button', { name: 'Aprovar Revisão' }))

  expect(screen.queryByText('Catalogando')).toBeNull()
  expect((screen.getByRole('button', { name: 'Revisar' }) as HTMLButtonElement).disabled).toBe(false)
  await waitFor(() => expect(aprovacoesDaRevisao).toBe(1))
  liberarAprovacao?.()
})

test('se a aprovação falha, a tela avisa para aprovar de novo', async () => {
  servidor.use(http.post('/v1/jobs/j1/revisao/aprovar', () => HttpResponse.json({ codigo: 'x' }, { status: 500 })))
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Revisar' }))

  await usuario.click(screen.getByRole('button', { name: 'Aprovar Revisão' }))

  expect(await screen.findByText('Não foi possível atualizar o índice: aprove a revisão de novo.')).toBeTruthy()
})

test('depois de aprovar, a tela mostra que o índice está sendo atualizado', async () => {
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Revisar' }))
  historico = [{ ...correcaoDoHistorico('c1', 'ana@redetv.com.br'), na_busca: 'indexando' }]

  await usuario.click(screen.getByRole('button', { name: 'Aprovar Revisão' }))

  expect(await screen.findByText('Atualizando o índice…')).toBeTruthy()
})

test('sem decupagem.editar, o botão Revisar não aparece', async () => {
  await abrir(['decupagem.ver'])
  expect(screen.queryByRole('button', { name: 'Revisar' })).toBeNull()
})

test('o botão Desfazer faz o mesmo que o Ctrl+Z, com a dica Ctrl+Z', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Revisar' }))

  const botao = screen.getByRole('button', { name: 'Desfazer' })
  await waitFor(() => expect((botao as HTMLButtonElement).disabled).toBe(false))
  await usuario.hover(botao)
  expect(within(await screen.findByRole('tooltip')).getByText('Ctrl+Z')).toBeTruthy()

  await usuario.click(botao)

  expect(await screen.findByText('Desfeito: Renomear pessoa (Leão Lobo → Não identificado)')).toBeTruthy()
  expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }])
})

test('o botão Desfazer fica desabilitado sem correção do editor para desfazer', async () => {
  historico = [correcaoDoHistorico('c1', 'outro@redetv.com.br')]
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Revisar' }))

  const botao = screen.getByRole('button', { name: 'Desfazer' })
  await waitFor(() => expect((botao as HTMLButtonElement).disabled).toBe(true))
})
