import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { guardarResultado } from '../../resultadoDaBusca.ts'
import { abrirVideo, irPara, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade do vídeo aberto pela busca (faixa "Busca", N, Shift+N e "Fechar busca") com o
// BuscaNoVisualizador.test.tsx da interface atual. O vídeo da tela é o j1; o j2 é o seguinte do resultado.

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [],
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

const momento = (inicio_ms: number, fim_ms: number, motivo: string) => ({ tipo: 'plano', inicio_ms, fim_ms, motivo, destaques: [], quadro_url: null })

const video = (id: string, momentos: ReturnType<typeof momento>[]) => ({
  job_id: id,
  nome: `${id}.mp4`,
  programa: 'TV Fama',
  data_exibicao: '2026-10-21',
  duracao_s: 120,
  n_momentos: momentos.length,
  momentos,
})

const RESULTADO = {
  entendida: { evidencias: ['imagem'], programa: null, desde: null, ate: null },
  videos: [
    video('j1', [momento(10_000, 14_000, 'Objeto: sandália vermelha'), momento(50_000, 52_000, 'Fala: sapato vermelho')]),
    video('j2', [momento(20_000, 24_000, 'Objeto: scarpin vermelho'), momento(70_000, 74_000, 'Fala: sapato')]),
  ],
  sem_aparicoes: [],
  facetas: { programa: [], mes: [], pessoa: [], marca: [], tipo: [] },
  plano_b: false,
}

const BUSCA = 'sapato vermelho'
const FAIXA = 'Busca: sapato vermelho (2)'
const buscas: URLSearchParams[] = []
let falha = false

const servidor = setupServer(
  ...rotasDoVideo(() => ({}), () => DECUPAGEM),
  http.get('/v1/busca', ({ request }) => {
    buscas.push(new URL(request.url).searchParams)
    return falha ? HttpResponse.json({ detail: 'x' }, { status: 500 }) : HttpResponse.json(RESULTADO)
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  buscas.length = 0
  falha = false
  sessionStorage.clear()
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const parametros = () => new URLSearchParams(location.search)

test('aberto pela busca, o vídeo mostra a faixa com os momentos dele, e o motivo é o nome', async () => {
  await abrirVideo({ busca: BUSCA })

  const faixa = await screen.findByRole('group', { name: FAIXA })
  expect(within(faixa).getByRole('button', { name: 'Objeto: sandália vermelha' })).toBeTruthy()
  expect(within(faixa).getByRole('button', { name: 'Fala: sapato vermelho' })).toBeTruthy()
  expect(buscas[0].get('q')).toBe(BUSCA)
})

test('com o resultado guardado na sessão, a busca não é refeita', async () => {
  guardarResultado(BUSCA, [{ job_id: 'j1', momentos: [{ inicio_ms: 5_000, fim_ms: 6_000, motivo: 'Guardado' }] }])
  await abrirVideo({ busca: BUSCA })

  expect(await screen.findByRole('button', { name: 'Guardado' })).toBeTruthy()
  expect(buscas).toHaveLength(0)
})

test('sem busca no endereço não há faixa nem chamada à busca', async () => {
  await abrirVideo()

  expect(screen.queryByRole('group', { name: /^Busca/ })).toBeNull()
  expect(buscas).toHaveLength(0)
})

test('clicar num bloco da busca salta o player ao momento', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ busca: BUSCA })

  await usuario.click(await screen.findByRole('button', { name: 'Fala: sapato vermelho' }))

  expect(player.currentTime).toBe(50)
})

test('o momento sob o player fica marcado na faixa', async () => {
  const player = await abrirVideo({ busca: BUSCA })
  const faixa = await screen.findByRole('group', { name: FAIXA })

  irPara(player, 11)
  expect(within(faixa).getByRole('button', { name: 'Objeto: sandália vermelha' }).getAttribute('aria-pressed')).toBe('true')
  expect(within(faixa).getByRole('button', { name: 'Fala: sapato vermelho' }).getAttribute('aria-pressed')).toBe('false')
})

test('N vai ao momento seguinte do mesmo vídeo', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ busca: BUSCA })
  await screen.findByRole('group', { name: FAIXA })
  irPara(player, 10)

  await usuario.keyboard('n')

  expect(player.currentTime).toBe(50)
  expect(location.pathname).toBe('/video/j1')
})

test('N no último momento abre o vídeo seguinte no primeiro momento dele, mantendo a busca', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ busca: BUSCA })
  await screen.findByRole('group', { name: FAIXA })
  irPara(player, 50)

  await usuario.keyboard('n')

  await waitFor(() => expect(location.pathname).toBe('/video/j2'))
  expect(parametros().get('t')).toBe('20')
  expect(parametros().get('busca')).toBe(BUSCA)
  // O resultado veio da busca feita uma vez só.
  expect(buscas).toHaveLength(1)
})

test('Shift+N no primeiro momento volta ao último do vídeo anterior', async () => {
  const usuario = userEvent.setup()
  // O j1 é o primeiro do resultado: aqui o vídeo da tela é o segundo.
  guardarResultado(BUSCA, [
    { job_id: 'j0', momentos: [{ inicio_ms: 30_000, fim_ms: 31_000, motivo: 'Anterior' }] },
    { job_id: 'j1', momentos: [{ inicio_ms: 20_000, fim_ms: 24_000, motivo: 'Daqui' }] },
  ])
  const player = await abrirVideo({ busca: BUSCA })
  await screen.findByRole('button', { name: 'Daqui' })
  irPara(player, 20)

  await usuario.keyboard('{Shift>}n{/Shift}')

  await waitFor(() => expect(location.pathname).toBe('/video/j0'))
  expect(parametros().get('t')).toBe('30')
  expect(parametros().get('busca')).toBe(BUSCA)
})

test('no último momento do resultado, N avisa e fica', async () => {
  const usuario = userEvent.setup()
  guardarResultado(BUSCA, [{ job_id: 'j1', momentos: [{ inicio_ms: 20_000, fim_ms: 24_000, motivo: 'Único' }] }])
  const player = await abrirVideo({ busca: BUSCA })
  await screen.findByRole('button', { name: 'Único' })
  irPara(player, 30)

  await usuario.keyboard('n')

  expect(await screen.findByText('Este é o último momento da busca.')).toBeTruthy()
  expect(location.pathname).toBe('/video/j1')
})

test('uma busca que não carregou faz o N avisar com o código, sem esperar para sempre', async () => {
  const usuario = userEvent.setup()
  falha = true
  await abrirVideo({ busca: BUSCA })
  await waitFor(() => expect(buscas).toHaveLength(1))

  await usuario.keyboard('n')

  expect(await screen.findByText(/A busca não carregou/)).toBeTruthy()
})

test('N não age com o foco num campo de texto', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ busca: BUSCA })
  await screen.findByRole('group', { name: FAIXA })
  irPara(player, 10)
  screen.getByLabelText('Campo').focus()

  await usuario.keyboard('n')

  expect(player.currentTime).toBe(10)
})

test('"Fechar busca" tira o busca do endereço e a faixa some', async () => {
  const usuario = userEvent.setup()
  await abrirVideo({ busca: BUSCA, t: 12 })
  history.replaceState(null, '', `/video/j1?busca=${encodeURIComponent(BUSCA)}&t=12`)
  await screen.findByRole('group', { name: FAIXA })

  await usuario.click(screen.getByRole('button', { name: 'Fechar busca' }))

  expect(parametros().has('busca')).toBe(false)
  expect(location.pathname).toBe('/video/j1')
})

test('N e Shift+N estão na lista do ?, só com busca', async () => {
  const usuario = userEvent.setup()
  await abrirVideo({ busca: BUSCA })
  await screen.findByRole('group', { name: FAIXA })

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).getByText(/momento seguinte da busca/)).toBeTruthy()
  expect(within(lista).getByText(/momento anterior da busca/)).toBeTruthy()
})
