import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import catalogo from './catalogo.fixture.json'
import type { Job } from './jobs.ts'
import { render } from './render-teste.tsx'
import Visualizador from './Visualizador.tsx'

const pauta = (id: string, titulo: string, inicio_ms: number, fim_ms: number) => ({
  id,
  titulo,
  resumo: 'Resumo',
  tom: 'informativo',
  inicio_ms,
  fim_ms,
})

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [
    pauta('pa1', 'Abertura', 0, 30_000),
    pauta('pa2', 'Debate', 30_000, 60_000),
    pauta('pa3', 'Encerramento', 60_000, 90_000),
  ],
  pessoas: [],
  planos: [],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 120,
  criado_em: '2026-10-21T10:00:00Z',
}

const correcoes: Record<string, unknown>[] = []
let falhaDoPost: { status: number; detail: string } | null = null

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/eu', () =>
    HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
  ),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/fila', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/sugestoes', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/revisao/pulso', () => new HttpResponse(null, { status: 204 })),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    if (falhaDoPost) return HttpResponse.json({ detail: falhaDoPost.detail }, { status: falhaDoPost.status })
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  correcoes.length = 0
  falhaDoPost = null
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir({ catalogando = true } = {}) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 3' })
  const usuario = userEvent.setup()
  if (!catalogando) return usuario
  await usuario.keyboard('e')
  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  return usuario
}

const linha = (titulo: string) => screen.findByRole('button', { name: new RegExp(`^${titulo}, `) })

async function irPara(segundos: number) {
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  player.currentTime = segundos
  fireEvent.timeUpdate(player)
}

test('M marca as pautas, U abre o título e Enter grava a junção com o título da primeira', async () => {
  const usuario = await abrir()

  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')
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
  // 15 s: o render do Visualizador inteiro passou dos 5 s com o contêiner do loop ocupado.
}, 15_000)

test('o título pode ser o de outra pauta ou um novo, e o botão Juntar vale como o U', async () => {
  const usuario = await abrir()
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
  const usuario = await abrir()
  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')
  await usuario.keyboard('u')
  expect(await screen.findByText('Marque duas ou mais pautas para juntar (M).')).toBeTruthy()

  await usuario.click(await linha('Encerramento'))
  await usuario.keyboard('m')
  await usuario.keyboard('u')

  expect(await screen.findByText('Só se juntam pautas seguidas: marque também a do meio.')).toBeTruthy()
  expect(screen.queryByRole('form', { name: /Juntar/ })).toBeNull()
  expect(correcoes).toEqual([])
})

test('M de novo desmarca a pauta', async () => {
  const usuario = await abrir()
  await usuario.click(await linha('Abertura'))
  await usuario.keyboard('m')
  expect(await screen.findByText('1 pauta marcada para juntar')).toBeTruthy()
  await usuario.keyboard('m')
  await waitFor(() => expect(screen.queryByText(/marcada para juntar/)).toBeNull())
})

test('D divide a pauta em foco no ponto do player, com os dois títulos', async () => {
  const usuario = await abrir()
  await usuario.click(await linha('Debate'))
  await irPara(45)
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

test('dividir fora da pauta em foco avisa e não abre o formulário', async () => {
  const usuario = await abrir()
  await usuario.click(await linha('Debate'))
  await irPara(10)
  await usuario.keyboard('d')

  expect(await screen.findByText('Leve o vídeo para dentro da pauta em foco para dividir (D).')).toBeTruthy()
  expect(screen.queryByRole('form', { name: /Dividir/ })).toBeNull()
})

test('sem pauta em foco, D pede para selecionar uma', async () => {
  const usuario = await abrir()
  await usuario.keyboard('d')
  expect(await screen.findByText('Selecione a pauta que vai ser dividida (↑ ↓).')).toBeTruthy()
})

test('com o foco num campo de texto, M, U e D não fazem nada', async () => {
  const usuario = await abrir()
  await usuario.click(await linha('Debate'))
  await irPara(45)
  await usuario.keyboard('d')
  const formulario = await screen.findByRole('form', { name: 'Dividir Debate em 00:45' })
  const campo = within(formulario).getByLabelText('Título da primeira parte')
  await usuario.click(campo)

  await usuario.keyboard('mud')

  expect((campo as HTMLInputElement).value).toBe('Debatemud')
  expect(screen.queryByText(/marcada para juntar/)).toBeNull()
  expect(screen.getAllByRole('form')).toHaveLength(1)
})

test('os atalhos entram na lista do ?, só para quem edita', async () => {
  const usuario = await abrir()
  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  for (const acao of [
    /Marcar a pauta em foco para juntar/,
    /Juntar as pautas marcadas/,
    /Dividir a pauta em foco no ponto do player/,
  ])
    expect(within(lista).getByText(acao)).toBeTruthy()
})

test('erro da API ao juntar fica no formulário', async () => {
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Abertura para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.keyboard('u')
  await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  falhaDoPost = { status: 422, detail: 'pautas não seguidas' }

  await usuario.keyboard('{Enter}')

  expect((await screen.findByRole('alert')).textContent).toBeTruthy()
  expect(screen.getByRole('form', { name: 'Juntar 2 pautas' })).toBeTruthy()
})

test('sair do modo de catalogação (E) esquece as pautas marcadas e o formulário aberto', async () => {
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Abertura para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.keyboard('u')
  await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  await usuario.click(document.body)

  await usuario.keyboard('ee')

  expect(screen.queryByRole('form', { name: 'Juntar 2 pautas' })).toBeNull()
  expect(screen.queryByText('2 pautas marcadas para juntar')).toBeNull()
})

test('F2 com a junção aberta troca um formulário pelo outro', async () => {
  const usuario = await abrir()
  await usuario.click(screen.getByRole('button', { name: 'Marcar Abertura para juntar' }))
  await usuario.click(screen.getByRole('button', { name: 'Marcar Debate para juntar' }))
  await usuario.keyboard('u')
  await screen.findByRole('form', { name: 'Juntar 2 pautas' })
  await usuario.click(await linha('Debate'))

  await usuario.keyboard('{F2}')

  await waitFor(() => expect(screen.queryByRole('form', { name: 'Juntar 2 pautas' })).toBeNull())
})

test('Refazer à mão, fora do modo de catalogação, liga o modo e deixa marcar as pautas', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/fila', () =>
      HttpResponse.json([
        {
          id: 'f1',
          tipo: 'pauta.juntar',
          autor_email: 'bia@redetv.com.br',
          criada_em: '2026-10-30T15:00:00Z',
          motivo: 'pautas juntadas pelo editor',
          antes: null,
          depois: '{"ids":["x1","x2"],"titulo":"Abertura"}',
          antes_legivel: 'Abertura + Debate',
          depois_legivel: 'Abertura',
          candidatos: [],
        },
      ]),
    ),
  )
  const usuario = await abrir({ catalogando: false })
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  await usuario.click(await screen.findByRole('tab', { name: /Fila de revisão/ }))

  await usuario.click(await screen.findByRole('button', { name: 'Refazer à mão' }))

  await usuario.click(await screen.findByRole('button', { name: 'Marcar Abertura para juntar' }))
  expect(await screen.findByText('1 pauta marcada para juntar')).toBeTruthy()
})
