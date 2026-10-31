import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import type { Job } from './jobs.ts'
import { render } from './render-teste.tsx'
import Visualizador from './Visualizador.tsx'

const DECUPAGEM = {
  pautas: [
    { id: 'pa1', titulo: 'Bastidores do Miss Bumbum', inicio_ms: 724_000, fim_ms: 940_000 },
    { id: 'pa2', titulo: 'Eleição', inicio_ms: 0, fim_ms: 724_000 },
    { id: 'pa3', titulo: 'Final', inicio_ms: 940_000, fim_ms: 2_660_000 },
  ],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      na_imagem: [
        { inicio_ms: 211_000, fim_ms: 261_000, evidencia: 'rosto' },
        { inicio_ms: 300_000, fim_ms: 320_000, evidencia: 'rosto' },
      ],
      citada_na_fala: [{ inicio_ms: 10_000, fim_ms: 12_000 }],
      citada_no_texto: [],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [],
  transcricao: [{ locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [],
}

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA_20261021_720_BLU.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 2959,
  programa: 'TV Fama',
  data_exibicao: '2026-10-21',
  timecode_origem: '01:00:00:00',
  taxa_de_quadros: 30,
  cortes_ms: [60_000, 120_000],
  criado_em: '2026-10-21T10:00:00Z',
}

// O jsdom não toca vídeo: `paused` e `playbackRate` ficam por conta do teste.
const playMock = vi.fn()
const pauseMock = vi.fn()
beforeEach(() => {
  playMock.mockReset().mockImplementation(function (this: HTMLVideoElement) {
    Object.defineProperty(this, 'paused', { value: false, configurable: true })
    return Promise.resolve()
  })
  pauseMock.mockReset().mockImplementation(function (this: HTMLVideoElement) {
    Object.defineProperty(this, 'paused', { value: true, configurable: true })
  })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(playMock)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pauseMock)
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(job: Partial<Job> = {}, t: number | null = null, podeEditar = false) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <input aria-label="Campo" />
      <Visualizador
        api={criarClienteDaApi(auth, () => {})}
        job={{ ...JOB, ...job }}
        t={t}
        podeEditar={podeEditar}
      />
    </AtalhosProvider>,
  )
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  await waitFor(() => expect(player.getAttribute('src')).toBe('https://exemplo.test/v.mp4'))
  return player
}

function irPara(player: HTMLVideoElement, segundos: number) {
  player.currentTime = segundos
  fireEvent.timeUpdate(player)
}

test('o cabeçalho mostra programa, data e nome do arquivo', async () => {
  await abrir()

  expect(screen.getByText('TV Fama · 21/10/2026')).toBeTruthy()
  expect(screen.getByText(/FAMA_20261021_720_BLU\.mp4/)).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' })).toBeTruthy()
})

test('"Tela anterior" só aparece para quem edita e leva a /anterior', async () => {
  await abrir({}, null, false)
  expect(screen.queryByRole('link', { name: 'Tela anterior' })).toBeNull()
  cleanup()

  await abrir({}, null, true)
  expect(screen.getByRole('link', { name: 'Tela anterior' }).getAttribute('href')).toBe(
    '/video/j1/anterior',
  )
})

test('o relógio mostra o tempo do arquivo e o TC de origem do quadro atual', async () => {
  const player = await abrir()
  expect(screen.getByText('00:00 / 49:19')).toBeTruthy()

  irPara(player, 61.5)

  expect(screen.getByText('01:01 / 49:19')).toBeTruthy()
  expect(screen.getByText('TC 01:01:01:15')).toBeTruthy()
})

test('acima de uma hora o relógio usa H:MM:SS', async () => {
  await abrir({ duracao_s: 3725 })

  expect(screen.getByText('00:00 / 1:02:05')).toBeTruthy()
})

test('sem timecode de origem, nenhum TC aparece', async () => {
  const player = await abrir({ timecode_origem: null })
  irPara(player, 10)

  expect(screen.queryByText(/TC /)).toBeNull()
  expect(screen.queryByText(/00:00:00:00/)).toBeNull()
})

test('com timecode mas sem taxa de quadros, nenhum TC aparece', async () => {
  const player = await abrir({ taxa_de_quadros: null })
  irPara(player, 10)

  expect(screen.queryByText(/TC /)).toBeNull()
})

test('clicar no TC o copia e confirma', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 1)

  await usuario.click(screen.getByRole('button', { name: /Copiar o timecode/ }))

  expect(await navigator.clipboard.readText()).toBe('01:00:01:00')
  expect(screen.getByText('Timecode copiado')).toBeTruthy()
})

test('Espaço e K tocam e pausam', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()

  await usuario.keyboard(' ')
  expect(playMock).toHaveBeenCalledTimes(1)
  await usuario.keyboard(' ')
  expect(pauseMock).toHaveBeenCalledTimes(1)
  await usuario.keyboard('k')
  expect(playMock).toHaveBeenCalledTimes(2)
  await usuario.keyboard('K')
  expect(pauseMock).toHaveBeenCalledTimes(2)
  expect(player.paused).toBe(true)
})

test('L toca; de novo vai a 2×; de novo, a 4×', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()

  await usuario.keyboard('l')
  expect(playMock).toHaveBeenCalledTimes(1)
  expect(player.playbackRate).toBe(1)
  await usuario.keyboard('l')
  expect(player.playbackRate).toBe(2)
  await usuario.keyboard('l')
  expect(player.playbackRate).toBe(4)
  expect(screen.getByRole('button', { name: '4×' }).getAttribute('aria-pressed')).toBe('true')
})

test('J recua 5 s e não passa do início', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 12)

  await usuario.keyboard('j')
  expect(player.currentTime).toBe(7)
  await usuario.keyboard('j')
  await usuario.keyboard('j')
  expect(player.currentTime).toBe(0)
})

test('← e → andam 1 s; com Shift, 5 s', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 20)

  await usuario.keyboard('{ArrowRight}')
  expect(player.currentTime).toBe(21)
  await usuario.keyboard('{ArrowLeft}{ArrowLeft}')
  expect(player.currentTime).toBe(19)
  await usuario.keyboard('{Shift>}{ArrowRight}{/Shift}')
  expect(player.currentTime).toBe(24)
  await usuario.keyboard('{Shift>}{ArrowLeft}{/Shift}')
  expect(player.currentTime).toBe(19)
})

test('vírgula e ponto andam um quadro, só com o vídeo pausado', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 10)

  await usuario.keyboard('.')
  expect(player.currentTime).toBeCloseTo(10 + 1 / 30, 5)
  await usuario.keyboard(',,')
  expect(player.currentTime).toBeCloseTo(10 - 1 / 30, 5)

  await usuario.keyboard('l')
  const tocando = player.currentTime
  await usuario.keyboard('.')
  expect(player.currentTime).toBe(tocando)
})

test('F alterna a tela cheia', async () => {
  const usuario = userEvent.setup()
  const pedir = vi.fn().mockResolvedValue(undefined)
  HTMLElement.prototype.requestFullscreen = pedir
  await abrir()

  await usuario.keyboard('f')

  expect(pedir).toHaveBeenCalledTimes(1)
  // @ts-expect-error o jsdom não define a API
  delete HTMLElement.prototype.requestFullscreen
})

test('com o foco num campo de texto, nenhum atalho age', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 20)

  await usuario.click(screen.getByLabelText('Campo'))
  await usuario.keyboard(' kljf,.{ArrowRight}{Shift>}{ArrowLeft}{/Shift}')

  expect(playMock).not.toHaveBeenCalled()
  expect(pauseMock).not.toHaveBeenCalled()
  expect(player.currentTime).toBe(20)
  expect(player.playbackRate).toBe(1)
})

test('todos os atalhos do player aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.keyboard('?')

  const dialogo = await screen.findByRole('dialog', { name: 'Atalhos' })
  const tabela = dialogo.querySelector('table[aria-label="Player"]') as HTMLElement
  const teclas = [...tabela.querySelectorAll('kbd')].map((k) => k.textContent)
  expect(teclas).toEqual(['Espaço ou K', 'L', 'J', '← →', 'Shift + ← →', ', .', 'F'])
})

test('?t= posiciona o player quando o vídeo carrega', async () => {
  const player = await abrir({}, 724)

  fireEvent.loadedMetadata(player)

  expect(player.currentTime).toBe(724)
})

test('pausar e saltar atualizam o t da URL sem empilhar histórico', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  const entradas = history.length

  irPara(player, 90.8)
  fireEvent.pause(player)
  expect(location.pathname + location.search).toBe('/video/j1?t=90')

  await usuario.keyboard('{ArrowRight}')
  fireEvent.seeked(player)
  expect(location.search).toBe('?t=91')
  expect(history.length).toBe(entradas)
})

test('falha ao carregar o vídeo mostra o código e tenta de novo', async () => {
  const usuario = userEvent.setup()
  let falhar = true
  servidor.use(
    http.get('/v1/jobs/j1/reproducao', () =>
      falhar
        ? new HttpResponse(null, { status: 503 })
        : HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
    ),
  )
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={false} />
    </AtalhosProvider>,
  )

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Código para o suporte: http_503')
  falhar = false
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByLabelText('Player')).toBeTruthy()
})

test('L com o vídeo pausado recomeça o ciclo em 1×', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()

  await usuario.keyboard('lll')
  expect(player.playbackRate).toBe(4)
  await usuario.keyboard('k')
  await usuario.keyboard('l')

  expect(player.paused).toBe(false)
  expect(player.playbackRate).toBe(1)
})

test('com o link válido, a falha do arquivo mostra o código e não pede o link de novo', async () => {
  let pedidos = 0
  servidor.events.on('request:start', ({ request }) => {
    if (request.url.endsWith('/reproducao')) pedidos += 1
  })
  const player = await abrir()
  const antes = pedidos

  fireEvent.error(player)

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Código para o suporte: midia_')
  expect(pedidos).toBe(antes)
  servidor.events.removeAllListeners()
})

test('com o link vencido, a falha do arquivo pede outro link e volta ao mesmo ponto', async () => {
  let pedidos = 0
  servidor.use(
    http.get('/v1/jobs/j1/reproducao', () => {
      pedidos += 1
      return HttpResponse.json({
        url: `https://exemplo.test/v.mp4?p=${pedidos}`,
        expira_em: pedidos === 1 ? '2000-01-01T00:00:00Z' : '2999-01-01T00:00:00Z',
      })
    }),
  )
  history.replaceState(null, '', '/video/j1')
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={false} />
    </AtalhosProvider>,
  )
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  await waitFor(() => expect(player.getAttribute('src')).toBe('https://exemplo.test/v.mp4?p=1'))
  irPara(player, 300)

  fireEvent.error(player)

  await waitFor(() => expect(player.getAttribute('src')).toBe('https://exemplo.test/v.mp4?p=2'))
  player.currentTime = 0
  fireEvent.loadedMetadata(player)
  expect(player.currentTime).toBe(300)
  expect(pedidos).toBe(2)
})

test('falha ao baixar a decupagem mostra o código para o suporte', async () => {
  const usuario = userEvent.setup()
  // A primeira leitura é a da linha do tempo; a do botão é a segunda.
  let leituras = 0
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      ++leituras === 1 ? HttpResponse.json(DECUPAGEM) : new HttpResponse(null, { status: 409 }),
    ),
  )
  await abrirComFaixas()

  await usuario.click(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' }))

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Código para o suporte: http_409')
})

test('sem a decupagem pronta, não há botão de baixar o JSON', async () => {
  await abrir({ estado: 'analisando' })

  expect(screen.queryByRole('button', { name: 'Baixar decupagem (JSON)' })).toBeNull()
})

test('as seis faixas aparecem com a contagem, sem a faixa de planos, e os cortes na régua', async () => {
  const { container } = await abrirComFaixas()

  for (const nome of ['Pautas 3', 'Pessoas 2', 'Menções 1', 'Comerciais 0', 'Textos 0', 'Falas 1']) {
    expect(screen.getByRole('group', { name: nome })).toBeTruthy()
  }
  expect(screen.queryByRole('group', { name: /Planos/ })).toBeNull()
  expect(container.querySelectorAll('[data-corte]').length).toBe(2)
})

test('o trecho sem pauta aparece hachurado com a dica', async () => {
  await abrirComFaixas()

  expect(screen.getByRole('img', { name: 'Sem decupagem, 44:20–49:19' })).toBeTruthy()
})

test('os blocos têm nome acessível com quem ou o quê e os tempos', async () => {
  await abrirComFaixas()

  expect(screen.getByRole('button', { name: 'Aparição de Leão Lobo, 03:31 a 04:21' })).toBeTruthy()
  expect(
    screen.getByRole('button', { name: 'Pauta: Bastidores do Miss Bumbum, 12:04 a 15:40' }),
  ).toBeTruthy()
})

test('clicar num bloco salta o player ao início e o seleciona', async () => {
  const usuario = userEvent.setup()
  const player = await abrirComFaixas()

  const bloco = screen.getByRole('button', { name: 'Pauta: Bastidores do Miss Bumbum, 12:04 a 15:40' })
  await usuario.click(bloco)

  expect(player.currentTime).toBe(724)
  expect(bloco.getAttribute('aria-pressed')).toBe('true')
})

test('com o foco numa faixa, ← e → passam de bloco e Enter salta; o player não anda', async () => {
  const usuario = userEvent.setup()
  const player = await abrirComFaixas()
  irPara(player, 20)

  await usuario.tab()
  // Os atalhos do cabeçalho e do player vêm antes: caminha até a faixa das pessoas.
  const primeiro = screen.getByRole('button', { name: 'Aparição de Leão Lobo, 03:31 a 04:21' })
  primeiro.focus()
  await usuario.keyboard('{ArrowRight}')

  const segundo = screen.getByRole('button', { name: 'Aparição de Leão Lobo, 05:00 a 05:20' })
  expect(document.activeElement).toBe(segundo)
  expect(player.currentTime).toBe(20)
  await usuario.keyboard('{Enter}')
  expect(player.currentTime).toBe(300)
  await usuario.keyboard('{ArrowLeft}')
  expect(document.activeElement).toBe(primeiro)
})

test('cada faixa tem uma parada de Tab só', async () => {
  await abrirComFaixas()

  const paradas = screen
    .getByRole('group', { name: 'Pessoas 2' })
    .querySelectorAll('button:not([tabindex="-1"])')
  expect(paradas.length).toBe(1)
})

test('clicar na régua salta o player para o tempo do ponteiro', async () => {
  const { container } = await abrirComFaixas()
  const regua = container.querySelector('[data-corte]')?.parentElement as HTMLElement
  regua.getBoundingClientRect = () => ({ left: 100, width: 1000 }) as DOMRect

  fireEvent.pointerDown(regua, { clientX: 600, pointerId: 1 })

  expect(player(container).currentTime).toBeCloseTo(2959 / 2, 1)
})

test('as teclas da faixa aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrirComFaixas()

  await usuario.keyboard('?')

  const dialogo = await screen.findByRole('dialog', { name: 'Atalhos' })
  const tabela = dialogo.querySelector('table[aria-label="Linha do tempo"]') as HTMLElement
  expect([...tabela.querySelectorAll('kbd')].map((k) => k.textContent)).toEqual(['← →', 'Enter'])
})

test('falha ao carregar a decupagem mostra o código e tenta de novo', async () => {
  const usuario = userEvent.setup()
  let falhar = true
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      falhar ? new HttpResponse(null, { status: 503 }) : HttpResponse.json(DECUPAGEM),
    ),
  )
  await abrir()

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('http_503')
  falhar = false
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByRole('group', { name: 'Pautas 3' })).toBeTruthy()
})

test('sem a decupagem pronta, a linha do tempo não aparece', async () => {
  await abrir({ estado: 'analisando' })

  expect(screen.queryByRole('group', { name: /Pautas/ })).toBeNull()
})

function player(raiz: HTMLElement): HTMLVideoElement {
  return raiz.querySelector('video') as HTMLVideoElement
}

async function abrirComFaixas() {
  const p = await abrir()
  await screen.findByRole('group', { name: 'Pautas 3' })
  return Object.assign(p, { container: document.body })
}
