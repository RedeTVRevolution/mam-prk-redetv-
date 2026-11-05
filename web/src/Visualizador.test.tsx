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

// O selo de "finalizando" solta depois de um teto: os horários do Job são de agora.
const AGORA = new Date().toISOString()

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

async function abrir(
  job: Partial<Job> = {},
  t: number | null = null,
  podeEditar = false,
  podeReprocessar = false,
  intervaloDoAcompanhamentoMs?: number,
  podeAprovar = false,
  podeVerAuditoria = false,
) {
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
        podeAprovar={podeAprovar}
        podeReprocessar={podeReprocessar}
        podeVerAuditoria={podeVerAuditoria}
        intervaloDoAcompanhamentoMs={intervaloDoAcompanhamentoMs}
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

test('baixar a decupagem chama a rota do servidor e entrega o arquivo', async () => {
  const usuario = userEvent.setup()
  let pedidos = 0
  servidor.use(
    http.get('/v1/jobs/j1/decupagem/download', () => {
      pedidos += 1
      return HttpResponse.json(DECUPAGEM)
    }),
  )
  const entregue: { download: string }[] = []
  URL.createObjectURL = vi.fn(() => 'blob:decupagem')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    entregue.push({ download: this.download })
  })
  await abrirComFaixas()

  await usuario.click(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' }))

  await waitFor(() => expect(entregue).toEqual([{ download: 'FAMA_20261021_720_BLU.decupagem.json' }]))
  expect(pedidos).toBe(1)
})

test('falha ao baixar a decupagem mostra o código para o suporte', async () => {
  const usuario = userEvent.setup()
  servidor.use(http.get('/v1/jobs/j1/decupagem/download', () => new HttpResponse(null, { status: 409 })))
  await abrirComFaixas()

  await usuario.click(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' }))

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Código para o suporte: http_409')
})

test('baixar o vídeo chama a rota e inicia o download pela URL devolvida', async () => {
  const usuario = userEvent.setup()
  servidor.use(
    http.get('/v1/jobs/j1/download', () =>
      HttpResponse.json({ url: 'https://exemplo.test/v.mp4?baixar=1', expira_em: '2999-01-01T00:00:00Z' }),
    ),
  )
  const hrefs: string[] = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    hrefs.push(this.href)
  })
  await abrir()

  const botao = screen.getByRole('button', { name: 'Baixar vídeo' })
  await usuario.click(botao)

  await waitFor(() => expect(hrefs).toEqual(['https://exemplo.test/v.mp4?baixar=1']))
  await waitFor(() => expect(botao.hasAttribute('data-loading')).toBe(false))
})

test('o botão de baixar o vídeo fica em carregando enquanto a URL não chega', async () => {
  const usuario = userEvent.setup()
  let liberar: () => void = () => {}
  const espera = new Promise<void>((r) => (liberar = r))
  servidor.use(
    http.get('/v1/jobs/j1/download', async () => {
      await espera
      return HttpResponse.json({ url: 'https://exemplo.test/v.mp4?baixar=1', expira_em: '2999-01-01T00:00:00Z' })
    }),
  )
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await abrir()

  const botao = screen.getByRole('button', { name: 'Baixar vídeo' })
  await usuario.click(botao)
  await waitFor(() => expect(botao.hasAttribute('data-loading')).toBe(true))
  liberar()
  await waitFor(() => expect(botao.hasAttribute('data-loading')).toBe(false))
})

test('falha ao preparar o download do vídeo mostra a mensagem em português', async () => {
  const usuario = userEvent.setup()
  servidor.use(http.get('/v1/jobs/j1/download', () => new HttpResponse(null, { status: 503 })))
  await abrir()

  await usuario.click(screen.getByRole('button', { name: 'Baixar vídeo' }))

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Não foi possível preparar o download. Tente de novo.')
  expect(aviso.textContent).toContain('http_503')
})

test('"Quem acessou" só aparece com auditoria.ver e leva à Auditoria filtrada pelo vídeo', async () => {
  await abrir()
  expect(screen.queryByRole('link', { name: 'Quem acessou' })).toBeNull()
  cleanup()

  await abrir({}, null, false, false, undefined, false, true)
  const link = screen.getByRole('link', { name: 'Quem acessou' })
  expect(link.getAttribute('href')).toBe(
    '/admin/auditoria?alvo=j1&acao=video.aberto%2Cvideo.baixado%2Cdecupagem.baixada',
  )
})

test('sem a decupagem pronta, não há botão de baixar o JSON', async () => {
  await abrir({ estado: 'analisando' })

  expect(screen.queryByRole('button', { name: 'Baixar decupagem (JSON)' })).toBeNull()
})

test('as sete faixas aparecem com a contagem, sem a faixa de planos, e os cortes na régua', async () => {
  const { container } = await abrirComFaixas()

  for (const nome of ['Pautas 3', 'Pessoas 2', 'Menções 1', 'Objetos 0', 'Comerciais 0', 'Textos 0', 'Falas 1']) {
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

test('a faixa sem ocorrências também é uma parada de Tab', async () => {
  await abrirComFaixas()

  expect(screen.getByRole('group', { name: 'Comerciais 0' }).tabIndex).toBe(0)
  expect(screen.getByRole('group', { name: 'Pessoas 2' }).hasAttribute('tabindex')).toBe(false)
})

test('a régua termina com o rótulo do fim do vídeo', async () => {
  await abrirComFaixas()

  expect(screen.getByText('49:19')).toBeTruthy()
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


test('o botão "Reprocessar…" só aparece com a permissão e com o vídeo concluído', async () => {
  await abrir({}, null, false, false)
  expect(screen.queryByRole('button', { name: /Reprocessar…/ })).toBeNull()
  cleanup()

  await abrir({ estado: 'analisando' }, null, false, true)
  expect(screen.queryByRole('button', { name: /Reprocessar…/ })).toBeNull()
  cleanup()

  await abrir({}, null, false, true)
  expect(screen.getByRole('button', { name: /Reprocessar…/ })).toBeTruthy()
})

test('escolher a etapa e o motivo reprocessa e avisa que a decupagem está sendo refeita', async () => {
  let corpo: unknown = null
  servidor.use(
    http.post('/v1/jobs/j1/reprocessar', async ({ request }) => {
      corpo = await request.json()
      return HttpResponse.json({ ...JOB, estado: 'analisando', etapa_atual: 'analise' }, { status: 202 })
    }),
  )
  await abrir({}, null, false, true)
  const usuario = userEvent.setup()

  await usuario.click(screen.getByRole('button', { name: /Reprocessar…/ }))
  expect(screen.getByRole('radio', { name: /Quadros-chave/ })).toBeTruthy()
  expect(screen.getByRole('radio', { name: /Identificação/ })).toBeTruthy()
  expect(screen.getByRole('radio', { name: /Inventário de objetos/ })).toBeTruthy()
  expect(screen.getByRole('radio', { name: /Indexação/ })).toBeTruthy()
  expect(
    screen.getByText(
      'Reprocessar a partir da análise? A Decupagem fica indisponível até a nova análise terminar, e as etapas seguintes rodam de novo.',
    ),
  ).toBeTruthy()
  // Sem motivo, o botão não age.
  expect((screen.getByRole('button', { name: 'Reprocessar' }) as HTMLButtonElement).disabled).toBe(true)
  await usuario.type(screen.getByRole('textbox', { name: /Motivo/ }), '  instrução nova ')
  await usuario.click(screen.getByRole('button', { name: 'Reprocessar' }))

  await waitFor(() => expect(corpo).toEqual({ etapa: 'analise', motivo: 'instrução nova' }))
  expect(
    await screen.findByText(/Reprocessando: Análise em andamento\. A Decupagem está sendo refeita/),
  ).toBeTruthy()
  expect(screen.queryByRole('radio', { name: /Quadros-chave/ })).toBeNull()
})

test('com outra etapa o pedido leva a etapa escolhida', async () => {
  let corpo: unknown = null
  servidor.use(
    http.post('/v1/jobs/j1/reprocessar', async ({ request }) => {
      corpo = await request.json()
      return HttpResponse.json({ ...JOB, etapa_atual: 'quadros_chave' }, { status: 202 })
    }),
  )
  await abrir({}, null, false, true)
  const usuario = userEvent.setup()

  await usuario.click(screen.getByRole('button', { name: /Reprocessar…/ }))
  await usuario.click(screen.getByRole('radio', { name: /Quadros-chave/ }))
  await usuario.type(screen.getByRole('textbox', { name: /Motivo/ }), 'miniaturas ruins')
  await usuario.click(screen.getByRole('button', { name: 'Reprocessar' }))

  await waitFor(() => expect(corpo).toEqual({ etapa: 'quadros_chave', motivo: 'miniaturas ruins' }))
  expect(await screen.findByText(/Reprocessando: Quadros-chave em andamento\./)).toBeTruthy()
})

test('um 409 mostra a mensagem do servidor e cancelar fecha a escolha', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/reprocessar', () =>
      HttpResponse.json({ detail: 'Job em analisando, não reprocessável' }, { status: 409 }),
    ),
  )
  await abrir({}, null, false, true)
  const usuario = userEvent.setup()

  await usuario.click(screen.getByRole('button', { name: /Reprocessar…/ }))
  await usuario.type(screen.getByRole('textbox', { name: /Motivo/ }), 'x')
  await usuario.click(screen.getByRole('button', { name: 'Reprocessar' }))

  expect((await screen.findByRole('alert')).textContent).toMatch(/Job em analisando, não reprocessável/)
  await usuario.click(screen.getByRole('button', { name: 'Cancelar' }))
  expect(screen.queryByRole('radio', { name: /Análise/ })).toBeNull()
  expect(screen.getByRole('button', { name: /Reprocessar…/ })).toBeTruthy()
})

test('o acompanhamento vai até a indexação terminar e então recarrega a decupagem', async () => {
  let cargas = 0
  const respostas: Partial<Job>[] = [
    // Entre a identificação e os quadros, sem etapa em andamento, mas a indexação pendente.
    { etapa_atual: null, indexacao: { estado: 'pendente', em: AGORA } },
    { etapa_atual: null, indexacao: { estado: 'indexado', em: AGORA } },
  ]
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => {
      cargas += 1
      return HttpResponse.json(DECUPAGEM)
    }),
    http.post('/v1/jobs/j1/reprocessar', () =>
      HttpResponse.json(
        { ...JOB, etapa_atual: 'identificacao', indexacao: { estado: 'pendente', em: AGORA } },
        { status: 202 },
      ),
    ),
    http.get('/v1/jobs/j1', () => HttpResponse.json({ ...JOB, ...(respostas.shift() ?? respostas.at(-1)) })),
  )
  await abrir({}, null, false, true, 20)
  await screen.findByRole('group', { name: 'Pautas 3' })
  expect(cargas).toBe(1)
  const usuario = userEvent.setup()

  await usuario.click(screen.getByRole('button', { name: /Reprocessar…/ }))
  await usuario.click(screen.getByRole('radio', { name: /Identificação/ }))
  await usuario.type(screen.getByRole('textbox', { name: /Motivo/ }), 'nomes novos')
  await usuario.click(screen.getByRole('button', { name: 'Reprocessar' }))
  expect(await screen.findByText(/Reprocessando: Identificação em andamento\./)).toBeTruthy()
  // No intervalo entre etapas o botão não volta.
  await waitFor(() => expect(screen.queryByText(/em andamento/)).toBeNull())
  expect(screen.queryByRole('button', { name: /Reprocessar…/ })).toBeNull()

  await waitFor(() => expect(cargas).toBe(2))
  expect(await screen.findByRole('button', { name: /Reprocessar…/ })).toBeTruthy()
})


test('aberto com as etapas depois da análise rodando, acompanha até o fim sem dizer "Reprocessando"', async () => {
  let cargas = 0
  // A etapa só termina depois que o teste viu o aviso. Com a consulta a cada 20 ms, um
  // "terminou" já na primeira resposta apagava o aviso antes de o `abrir` voltar.
  let terminou = false
  const rodando: Partial<Job> = { etapa_atual: 'identificacao', indexacao: { estado: 'pendente', em: AGORA } }
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => {
      cargas += 1
      return HttpResponse.json(DECUPAGEM)
    }),
    http.get('/v1/jobs/j1', () =>
      HttpResponse.json(
        terminou
          ? { ...JOB, etapa_atual: null, indexacao: { estado: 'indexado', em: AGORA } }
          : { ...JOB, ...rodando },
      ),
    ),
  )
  await abrir(rodando, null, false, true, 20)
  expect(await screen.findByText('Identificação em andamento.')).toBeTruthy()
  terminou = true

  await waitFor(() => expect(screen.queryByText(/em andamento/)).toBeNull())
  await waitFor(() => expect(cargas).toBe(2))
  expect(screen.getByRole('button', { name: /Reprocessar…/ })).toBeTruthy()
})

test('o "Reprocessar…" fica escondido entre etapas e volta num Job preso, passado o teto', async () => {
  // Entre duas etapas: sem etapa em andamento, a indexação pendente.
  await abrir({ etapa_atual: null, indexacao: { estado: 'pendente', em: AGORA } }, null, false, true, 60_000)
  await screen.findByRole('group', { name: 'Pautas 3' })
  expect(screen.queryByRole('button', { name: /Reprocessar…/ })).toBeNull()
  cleanup()

  // O Workflows morreu no meio há 7 h: a etapa ficou aberta, mas o selo solta.
  const haSeteHoras = new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString()
  await abrir(
    {
      etapa_atual: 'identificacao',
      indexacao: { estado: 'pendente', em: haSeteHoras },
      etapas: [{ nome: 'identificacao', inicio: haSeteHoras, fim: null, resultado: null }],
    },
    null,
    false,
    true,
    60_000,
  )
  expect(await screen.findByRole('button', { name: /Reprocessar…/ })).toBeTruthy()
  expect(screen.queryByText(/em andamento/)).toBeNull()
})

const CORRECAO = {
  id: 'c1',
  tipo: 'pessoa.renomear',
  item_id: 'p1',
  ancora: { versao: 'v1', tipo_do_item: 'pessoa' },
  autor_email: 'bia@redetv.com.br',
  criada_em: '2026-10-30T15:00:00Z',
  motivo: 'sobrenome completo',
  antes: 'Leão',
  depois: 'Leão Lobo',
  antes_legivel: 'Leão',
  depois_legivel: 'Leão Lobo',
  estado: 'pendente',
}

function comGaveta() {
  const pedidos = { historico: 0, fila: 0 }
  servidor.use(
    http.get('/v1/jobs/j1/correcoes', () => {
      pedidos.historico += 1
      return HttpResponse.json([CORRECAO])
    }),
    http.get('/v1/jobs/j1/fila', () => {
      pedidos.fila += 1
      return HttpResponse.json([])
    }),
  )
  return pedidos
}

test('o botão Histórico abre a gaveta com o player à vista, e a contagem vem da fila e das pendentes', async () => {
  comGaveta()
  const usuario = userEvent.setup()
  await abrir({}, null, true, false, undefined, true)

  const botao = await screen.findByRole('button', { name: 'Histórico' })
  await waitFor(() => expect(document.querySelector('.mantine-Indicator-indicator')?.textContent).toBe('1'))
  await usuario.click(botao)

  expect(await screen.findByRole('dialog', { name: 'Correções do vídeo' })).toBeTruthy()
  expect(screen.getByLabelText('Player')).toBeTruthy()
  expect(await screen.findByRole('tab', { name: 'Aprovação (1)' })).toBeTruthy()

  await usuario.click(screen.getByRole('button', { name: 'Fechar' }))
  expect(screen.queryByRole('dialog', { name: 'Correções do vídeo' })).toBeNull()
})

test('clicar numa correção da gaveta salta o player ao item e abre a aba dele', async () => {
  comGaveta()
  const usuario = userEvent.setup()
  const player = await abrir({}, null, true)

  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  await usuario.click(await screen.findByRole('button', { name: /^Saltar ao item/ }))

  expect(player.currentTime).toBe(211)
})

test('sem decupagem.editar não há botão Histórico nem pedido de histórico ou fila', async () => {
  const pedidos = comGaveta()
  await abrir({}, null, false)
  await screen.findByLabelText('Painel')

  expect(screen.queryByRole('button', { name: 'Histórico' })).toBeNull()
  expect(pedidos).toEqual({ historico: 0, fila: 0 })
})

test('com a gaveta aberta, as setas e o Enter são dela e o painel não os trata', async () => {
  comGaveta()
  const usuario = userEvent.setup()
  const player = await abrir({}, null, true)
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  await screen.findByRole('button', { name: /^Saltar ao item/ })

  // O foco no corpo da página: o Enter não é de nenhum botão.
  await usuario.click(document.body)
  await usuario.keyboard('{ArrowDown}{Enter}')

  // Um só salto (o da gaveta, ao item da correção): o Enter do painel não saltou a outro item.
  expect(player.currentTime).toBe(211)
})

test('decupagem sem os campos novos (1.1) abre o painel, e sem catálogo a catalogação não corrige nada', async () => {
  servidor.use(http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 503 })))
  const usuario = userEvent.setup()
  await abrir({}, null, true)

  expect((await screen.findAllByText('Eleição')).length).toBeGreaterThan(0)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))
  await usuario.keyboard('{F2}')

  expect(screen.queryByRole('textbox', { name: 'Motivo' })).toBeNull()
  expect(screen.queryByRole('button', { name: /^Corrigir / })).toBeNull()
})

test('o detalhe do vídeo mostra a versão do pipeline da decupagem', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json({
        ...DECUPAGEM,
        versao_pipeline: '2026.11.1',
        manifesto_do_pipeline: { modelos: { analise: 'gemini-3.5-flash-lite' } },
      })),
  )
  await abrirComFaixas()

  const selo = await screen.findByText('Pipeline 2026.11.1')
  // O manifesto aparece também pelo teclado, não só com o mouse.
  selo.focus()
  expect(await screen.findByText(/gemini-3\.5-flash-lite/)).toBeTruthy()
})

test('a decupagem sem versão do pipeline aparece como anterior à versão', async () => {
  await abrirComFaixas()

  expect(await screen.findByText('Pipeline anterior à versão')).toBeTruthy()
})
