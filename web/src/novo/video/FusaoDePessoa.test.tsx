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

// A paridade de "Fundir com…" com o FusaoDePessoa.test.tsx da interface antiga.

const DECUPAGEM = (nome: string, catalogoId: string) => ({ ...BASE, pessoas: [{ ...BASE.pessoas[0], nome, catalogo_id: catalogoId }] })

let decupagemAtual = DECUPAGEM('Leo Lobo', 'cat-leo')
let fundidas: { origem: string; corpo: unknown }[] = []

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => decupagemAtual,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: [] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.get('/v1/catalogo/pessoas', () => HttpResponse.json([{ id: 'cat-leao', nome: 'Leão Lobo', rotulo: 'Leão Lobo (jurado)', a_revisar: false }])),
  http.get('/v1/catalogo/pessoas/:id/fundir/impacto', () =>
    HttpResponse.json({ origem_nome: 'Leo Lobo', destino_nome: 'Leão Lobo', videos: 3, aparicoes: 5, fotos_apagadas: 2 }),
  ),
  http.post('/v1/catalogo/pessoas/:id/fundir', async ({ request, params }) => {
    fundidas.push({ origem: String(params.id), corpo: await request.json() })
    decupagemAtual = DECUPAGEM('Leão Lobo', 'cat-leao')
    return HttpResponse.json({})
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  decupagemAtual = DECUPAGEM('Leo Lobo', 'cat-leo')
  fundidas = []
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

async function abrir(permissoes: string[], consultas?: QueryClient) {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes, consultas })
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('e')
  const secao = inspetor().getByRole('button', { name: /^Pessoas \d+$/ })
  if (secao.getAttribute('aria-expanded') !== 'true') await usuario.click(secao)
  await usuario.click(inspetor().getByRole('button', { name: /^Leo Lobo, 1 aparição/ }))
  await usuario.click(await inspetor().findByRole('button', { name: /^Leo Lobo, 00:10 a 00:20/ }))
  await detalhe().findByRole('button', { name: 'Corrigir' })
  ;(document.activeElement as HTMLElement).blur()
  return usuario
}

const FUNDIDOR = ['decupagem.editar', 'catalogo.fundir']

test('Fundir com…: escolhe o destino, vê o efeito e Enter funde com o motivo; o inspetor mostra o destino', async () => {
  const usuario = await abrir(FUNDIDOR)
  await usuario.click(await detalhe().findByRole('button', { name: 'Fundir Leo Lobo com…' }))

  await usuario.type(screen.getByRole('combobox', { name: 'Fundir com' }), 'leão')
  await usuario.click(await screen.findByRole('option', { name: 'Leão Lobo (jurado)' }))
  expect(await screen.findByText(/Leo Lobo passa a ser Leão Lobo em 3 vídeos\. As fotos de referência de Leo Lobo serão apagadas\. A fusão não pode ser desfeita\. Enter confirma · Esc cancela\./)).toBeTruthy()

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(fundidas).toEqual([{ origem: 'cat-leo', corpo: { destino_id: 'cat-leao', motivo: 'nome duplicado' } }]))
  expect(await inspetor().findByRole('region', { name: /^Detalhe: Leão Lobo/ })).toBeTruthy()
  expect(screen.queryByRole('form', { name: /Fundir/ })).toBeNull()
})

test('fundir invalida a decupagem de todos os vídeos, não só a do vídeo aberto', async () => {
  const consultas = criarClienteDeConsultas()
  consultas.setQueryData(['video', 'j2', 'decupagem'], { versao_decupagem: 'v1' })
  const usuario = await abrir(FUNDIDOR, consultas)
  await usuario.click(await detalhe().findByRole('button', { name: 'Fundir Leo Lobo com…' }))
  await usuario.type(screen.getByRole('combobox', { name: 'Fundir com' }), 'leão')
  await usuario.click(await screen.findByRole('option', { name: 'Leão Lobo (jurado)' }))
  await screen.findByText(/passa a ser Leão Lobo em 3 vídeos/)
  expect(consultas.getQueryState(['video', 'j2', 'decupagem'])?.isInvalidated).toBe(false)

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(consultas.getQueryState(['video', 'j2', 'decupagem'])?.isInvalidated).toBe(true))
})

test('o campo só escolhe pessoas que já existem: sem "criar como nova"', async () => {
  const usuario = await abrir(FUNDIDOR)
  await usuario.click(await detalhe().findByRole('button', { name: 'Fundir Leo Lobo com…' }))

  await usuario.type(screen.getByRole('combobox', { name: 'Fundir com' }), 'leão')
  await screen.findByRole('option', { name: 'Leão Lobo (jurado)' })

  expect(screen.queryByRole('option', { name: /criar/ })).toBeNull()
})

test('Esc cancela a fusão sem chamar a rota', async () => {
  const usuario = await abrir(FUNDIDOR)
  await usuario.click(await detalhe().findByRole('button', { name: 'Fundir Leo Lobo com…' }))
  await screen.findByRole('form', { name: 'Fundir Leo Lobo com' })

  await usuario.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('form', { name: /Fundir/ })).toBeNull())
  expect(fundidas).toEqual([])
})

test('sem catalogo.fundir, o botão não aparece', async () => {
  await abrir(['decupagem.editar'])
  expect(screen.queryByRole('button', { name: /Fundir Leo Lobo/ })).toBeNull()
})
