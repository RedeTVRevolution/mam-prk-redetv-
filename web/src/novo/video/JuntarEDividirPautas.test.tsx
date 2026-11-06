import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, irPara, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade de juntar e dividir pautas com o JuntarEDividirPautas.test.tsx da interface antiga.

const pauta = (id: string, titulo: string, inicio_ms: number, fim_ms: number) => ({ id, titulo, resumo: 'Resumo', tom: 'informativo', inicio_ms, fim_ms })

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [pauta('pa1', 'Abertura', 0, 30_000), pauta('pa2', 'Debate', 30_000, 60_000), pauta('pa3', 'Encerramento', 60_000, 90_000)],
  pessoas: [],
  planos: [],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
  objetos: [],
}

const correcoes: Record<string, unknown>[] = []
let falhaDoPost: { status: number; detail: string } | null = null

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => DECUPAGEM,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/sugestoes', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/revisao/aprovar', () => HttpResponse.json({ indexacao: 'pendente' }, { status: 202 })),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    if (falhaDoPost) return HttpResponse.json({ detail: falhaDoPost.detail }, { status: falhaDoPost.status })
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  correcoes.length = 0
  falhaDoPost = null
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const inspetor = () => within(screen.getByRole('complementary', { name: 'Inspetor' }))

/** Abre a seção Pautas; `revisando` liga o modo de revisão (E). */
async function abrir({ revisando = true } = {}) {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ permissoes: ['decupagem.editar'] })
  ;(document.activeElement as HTMLElement).blur()
  if (revisando) await usuario.keyboard('e')
  const secao = inspetor().getByRole('button', { name: /^Pautas \d+$/ })
  if (secao.getAttribute('aria-expanded') !== 'true') await usuario.click(secao)
  return { usuario, player }
}

const linha = (titulo: string) => inspetor().findByRole('button', { name: new RegExp(`^${titulo}, `) })

test('M marca as pautas, U abre o título e Enter grava a junção com o título da primeira', async () => {
  const { usuario } = await abrir()

  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')
  await usuario.keyboard('{Escape}')
  await usuario.click(await linha('Debate'))
  await usuario.keyboard('m')
  expect(await screen.findByText('2 pautas marcadas para juntar')).toBeTruthy()
  await usuario.keyboard('u')

  const formulario = await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  const escolha = within(formulario).getByLabelText('Título') as HTMLSelectElement
  expect(Array.from(escolha.options).map((o) => o.textContent)).toEqual(['Abertura', 'Debate', 'Outro título'])
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pauta.juntar',
    item_id: 'pa1',
    versao: 'v1',
    valor: JSON.stringify({ ids: ['pa1', 'pa2'], titulo: 'Abertura' }),
  })
  await waitFor(() => expect(screen.queryByText(/pautas marcadas para juntar/)).toBeNull())
}, 15_000)

test('o título pode ser o de outra pauta ou um novo, e o botão Juntar vale como o U', async () => {
  const { usuario } = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Encerramento para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Juntar as pautas marcadas' }))

  const formulario = await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  await usuario.selectOptions(within(formulario).getByLabelText('Título'), 'Outro título')
  await usuario.type(within(formulario).getByLabelText('Novo título'), 'Fecho do programa')
  await usuario.click(within(formulario).getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pauta.juntar',
    item_id: 'pa2',
    valor: JSON.stringify({ ids: ['pa2', 'pa3'], titulo: 'Fecho do programa' }),
  })
})

test('pautas que não são seguidas, ou uma só, não abrem o formulário', async () => {
  const { usuario } = await abrir()
  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')
  await usuario.keyboard('u')
  expect(await screen.findByText('Marque duas ou mais pautas para juntar (M).')).toBeTruthy()

  await usuario.keyboard('{Escape}')
  await usuario.click(await linha('Encerramento'))
  await usuario.keyboard('m')
  await usuario.keyboard('u')

  expect(await screen.findByText('Só se juntam pautas seguidas: marque também a do meio.')).toBeTruthy()
  expect(screen.queryByRole('form', { name: /Juntar/ })).toBeNull()
  expect(correcoes).toEqual([])
})

test('M de novo desmarca a pauta, e Limpar marcas tira todas', async () => {
  const { usuario } = await abrir()
  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')
  expect(await screen.findByText('1 pauta marcada para juntar')).toBeTruthy()
  await usuario.keyboard('m')
  await waitFor(() => expect(screen.queryByText(/marcada para juntar/)).toBeNull())

  await usuario.keyboard('m')
  await usuario.click(await screen.findByRole('button', { name: 'Limpar marcas' }))
  await waitFor(() => expect(screen.queryByText(/marcada para juntar/)).toBeNull())
})

test('a linha da pauta marcada fica com o botão apertado', async () => {
  const { usuario } = await abrir()
  const botao = screen.getByRole('button', { name: 'Marcar Debate para juntar' })
  expect(botao.getAttribute('aria-pressed')).toBe('false')

  await usuario.click(botao)

  expect(screen.getByRole('button', { name: 'Marcar Debate para juntar' }).getAttribute('aria-pressed')).toBe('true')
})

test('D divide a pauta em foco no ponto do player, com os dois títulos', async () => {
  const { usuario, player } = await abrir()
  await usuario.click(await linha('Debate'))
  irPara(player, 45)
  await usuario.keyboard('d')

  const formulario = await screen.findByRole('form', { name: 'Dividir Debate em 00:45' })
  const primeiro = within(formulario).getByLabelText('Título da primeira parte')
  const segundo = within(formulario).getByLabelText('Título da segunda parte')
  expect((primeiro as HTMLInputElement).value).toBe('Debate')
  await usuario.clear(segundo)
  await usuario.type(segundo, 'Debate: réplica{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pauta.dividir',
    item_id: 'pa2',
    valor: JSON.stringify({ em_ms: 45_000, titulos: ['Debate', 'Debate: réplica'] }),
  })
})

test('o botão Dividir da linha vale como o D', async () => {
  const { usuario, player } = await abrir()
  irPara(player, 45)
  await usuario.click(screen.getByRole('button', { name: 'Dividir Debate no ponto do player' }))

  expect(await screen.findByRole('form', { name: 'Dividir Debate em 00:45' })).toBeTruthy()
})

test('dividir fora da pauta em foco avisa e não abre o formulário', async () => {
  const { usuario, player } = await abrir()
  await usuario.click(await linha('Debate'))
  irPara(player, 10)
  await usuario.keyboard('d')

  expect(await screen.findByText('Leve o vídeo para dentro da pauta em foco para dividir (D).')).toBeTruthy()
  expect(screen.queryByRole('form', { name: /Dividir/ })).toBeNull()
})

test('sem pauta em foco, D pede para selecionar uma', async () => {
  const { usuario } = await abrir()
  await usuario.keyboard('d')
  expect(await screen.findByText('Selecione a pauta que vai ser dividida (↑ ↓).')).toBeTruthy()
})

test('com o foco num campo de texto, M, U e D não fazem nada', async () => {
  const { usuario, player } = await abrir()
  await usuario.click(await linha('Debate'))
  irPara(player, 45)
  await usuario.keyboard('d')
  const formulario = await screen.findByRole('form', { name: 'Dividir Debate em 00:45' })
  const campo = within(formulario).getByLabelText('Título da primeira parte')
  await usuario.click(campo)

  await usuario.keyboard('mud')

  expect((campo as HTMLInputElement).value).toBe('Debatemud')
  expect(screen.queryByText(/marcada para juntar/)).toBeNull()
  expect(screen.getAllByRole('form')).toHaveLength(1)
})

test('os atalhos entram na lista do ?, só no modo de revisão', async () => {
  const { usuario } = await abrir()
  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  for (const acao of [/Marcar a pauta em foco para juntar/, /Juntar as pautas marcadas/, /Dividir a pauta em foco no ponto do player/])
    expect(within(lista).getByText(acao)).toBeTruthy()
})

test('fora do modo de revisão, não há botões nem atalhos de pauta', async () => {
  const { usuario } = await abrir({ revisando: false })
  expect(screen.queryByRole('button', { name: /Marcar .* para juntar/ })).toBeNull()

  await usuario.click(await linha('Debate'))
  await usuario.keyboard('m')

  expect(screen.queryByText(/marcada para juntar/)).toBeNull()
})

test('erro da API ao juntar fica no formulário', async () => {
  const { usuario } = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Abertura para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.keyboard('u')
  const formulario = await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  falhaDoPost = { status: 422, detail: 'pautas não seguidas' }

  await usuario.keyboard('{Enter}')

  expect((await within(formulario).findByRole('alert')).textContent).toBeTruthy()
  expect(screen.getByRole('form', { name: 'Juntar 2 pautas' })).toBeTruthy()
})

test('sair do modo de revisão (E) esquece as pautas marcadas e o formulário aberto', async () => {
  const { usuario } = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Abertura para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.keyboard('u')
  await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  await usuario.click(document.body)

  await usuario.keyboard('e')
  await waitFor(() => expect(screen.queryByText('Catalogando')).toBeNull())
  await usuario.keyboard('e')
  await screen.findByText('Catalogando')

  expect(screen.queryByRole('form', { name: 'Juntar 2 pautas' })).toBeNull()
  expect(screen.queryByText('2 pautas marcadas para juntar')).toBeNull()
})

test('F2 com a junção aberta troca um formulário pelo outro', async () => {
  const { usuario } = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Abertura para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.keyboard('u')
  await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  await usuario.click(await linha('Debate'))
  await inspetor().findByRole('button', { name: 'Corrigir' })

  await usuario.keyboard('{F2}')

  await waitFor(() => expect(screen.queryByRole('form', { name: 'Juntar 2 pautas' })).toBeNull())
  expect(await screen.findByRole('form', { name: /Corrigir Debate/ })).toBeTruthy()
})

test('D e U com o inspetor recolhido ou a comparação aberta trazem o inspetor com o formulário', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/passadas', () => HttpResponse.json([{ id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] }])),
    http.get('/v1/jobs/j1/passadas/p1/comparacao', () => HttpResponse.json({ passada_id: 'p1', modelo: 'm', modelo_do_job: 'n', duracao_ms: 60_000, a: { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 1, etapas: [] }, b: { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 1, etapas: [] }, requisitos: [] })),
  )
  const { usuario, player } = await abrir()
  await usuario.click(await linha('Debate'))
  irPara(player, 45)
  await usuario.keyboard('m')
  await usuario.keyboard('{Escape}')
  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')

  // Inspetor recolhido: o U abre o formulário no inspetor.
  await usuario.click(inspetor().getByRole('button', { name: 'Recolher o inspetor' }))
  await usuario.keyboard('u')
  expect(await screen.findByRole('form', { name: 'Juntar 2 pautas' })).toBeTruthy()
  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('form', { name: 'Juntar 2 pautas' })).toBeNull())

  // Comparação aberta: o U a fecha e mostra o formulário.
  await usuario.selectOptions(await screen.findByRole('combobox', { name: 'Comparar com' }), 'p1')
  await screen.findByRole('complementary', { name: 'Comparação com a passada' })
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('u')
  expect(await screen.findByRole('form', { name: 'Juntar 2 pautas' })).toBeTruthy()
  expect(screen.queryByRole('complementary', { name: 'Comparação com a passada' })).toBeNull()
})
