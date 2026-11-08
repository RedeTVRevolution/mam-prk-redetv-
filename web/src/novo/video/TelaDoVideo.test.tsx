import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import type { Job } from '../../jobs.ts'
import { abrirVideo, irPara, JOB, pauseMock, playMock, REPRODUCAO, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade do player com o Visualizador.test.tsx da interface antiga.

const DECUPAGEM = {
  pautas: [
    { id: 'pa1', titulo: 'Bastidores do Miss Bumbum', inicio_ms: 724_000, fim_ms: 940_000 },
    { id: 'pa2', titulo: 'Eleição', inicio_ms: 0, fim_ms: 724_000 },
    { id: 'pa3', titulo: 'Final', inicio_ms: 940_000, fim_ms: 2_660_000 },
  ],
  pessoas: [],
  planos: [],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

let job: Partial<Job> = {}
const servidor = setupServer(...rotasDoVideo(() => job, () => DECUPAGEM))
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  job = {}
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const AGORA = new Date().toISOString()

test('a barra mostra o nome do arquivo, o programa e a data', async () => {
  await abrirVideo()

  expect(screen.getByRole('heading', { name: 'FAMA_20261021_720_BLU.mp4' })).toBeTruthy()
  expect(screen.getByText('TV Fama · 21/10/2026')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' })).toBeTruthy()
})

test('o relógio mostra o tempo do arquivo e o TC de origem do quadro atual', async () => {
  const player = await abrirVideo()
  expect(screen.getByText('00:00 / 49:19')).toBeTruthy()

  irPara(player, 61.5)

  expect(screen.getByText('01:01 / 49:19')).toBeTruthy()
  expect(screen.getByText('TC 01:01:01:15')).toBeTruthy()
})

test('acima de uma hora o relógio usa H:MM:SS', async () => {
  job = { duracao_s: 3725 }
  await abrirVideo()

  expect(screen.getByText('00:00 / 1:02:05')).toBeTruthy()
})

test('sem timecode de origem ou sem taxa de quadros, nenhum TC aparece', async () => {
  job = { timecode_origem: null }
  irPara(await abrirVideo(), 10)
  expect(screen.queryByText(/TC /)).toBeNull()
  cleanup()

  job = { taxa_de_quadros: null }
  irPara(await abrirVideo(), 10)
  expect(screen.queryByText(/TC /)).toBeNull()
})

test('clicar no TC o copia e confirma; o link no tempo também', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 1)

  await usuario.click(screen.getByRole('button', { name: /Copiar o timecode/ }))
  expect(await navigator.clipboard.readText()).toBe('01:00:01:00')
  expect(screen.getByText('Timecode copiado')).toBeTruthy()

  irPara(player, 90.4)
  await usuario.click(screen.getByRole('button', { name: 'Copiar o link neste tempo' }))
  expect(await navigator.clipboard.readText()).toBe(`${location.origin}/video/j1?t=90`)
  expect(screen.getByText('Link copiado')).toBeTruthy()
})

test('Espaço e K tocam e pausam', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()

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

test('L toca; de novo vai a 2×; de novo, a 4×; pausado, recomeça em 1×', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()

  await usuario.keyboard('l')
  expect(playMock).toHaveBeenCalledTimes(1)
  expect(player.playbackRate).toBe(1)
  await usuario.keyboard('l')
  expect(player.playbackRate).toBe(2)
  await usuario.keyboard('l')
  expect(player.playbackRate).toBe(4)
  expect(screen.getByRole('button', { name: '4×' }).getAttribute('aria-pressed')).toBe('true')

  await usuario.keyboard('k')
  await usuario.keyboard('l')
  expect(player.paused).toBe(false)
  expect(player.playbackRate).toBe(1)
})

test('J recua 5 s e não passa do início', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 12)

  await usuario.keyboard('j')
  expect(player.currentTime).toBe(7)
  await usuario.keyboard('jj')
  expect(player.currentTime).toBe(0)
})

test('← e → andam 1 s; com Shift, 5 s; os botões do transporte andam 5 s', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 20)

  await usuario.keyboard('{ArrowRight}')
  expect(player.currentTime).toBe(21)
  await usuario.keyboard('{ArrowLeft}{ArrowLeft}')
  expect(player.currentTime).toBe(19)
  await usuario.keyboard('{Shift>}{ArrowRight}{/Shift}')
  expect(player.currentTime).toBe(24)
  await usuario.keyboard('{Shift>}{ArrowLeft}{/Shift}')
  expect(player.currentTime).toBe(19)

  await usuario.click(screen.getByRole('button', { name: 'Avançar 5 s' }))
  expect(player.currentTime).toBe(24)
  await usuario.click(screen.getByRole('button', { name: 'Recuar 5 s' }))
  expect(player.currentTime).toBe(19)
})

test('vírgula e ponto andam um quadro, só com o vídeo pausado', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
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

test('F e o botão alternam a tela cheia', async () => {
  const usuario = userEvent.setup()
  const pedir = vi.fn().mockResolvedValue(undefined)
  HTMLElement.prototype.requestFullscreen = pedir
  await abrirVideo()

  await usuario.keyboard('f')
  await usuario.click(screen.getByRole('button', { name: 'Tela cheia' }))

  expect(pedir).toHaveBeenCalledTimes(2)
  // Em tela cheia o vídeo não tem `controls`: o transporte entra junto, no mesmo elemento.
  const emTelaCheia = pedir.mock.contexts[0] as HTMLElement
  expect(emTelaCheia.contains(screen.getByLabelText('Player'))).toBe(true)
  for (const nome of ['Tocar', 'Tela cheia', 'Silenciar']) expect(emTelaCheia.contains(screen.getByRole('button', { name: nome }))).toBe(true)
  // @ts-expect-error o jsdom não define a API
  delete HTMLElement.prototype.requestFullscreen
})

test('com o foco num campo de texto, nenhum atalho age', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 20)

  await usuario.click(screen.getByLabelText('Campo'))
  await usuario.keyboard(' kljf,.]{ArrowRight}{Shift>}{ArrowLeft}{/Shift}')

  expect(playMock).not.toHaveBeenCalled()
  expect(pauseMock).not.toHaveBeenCalled()
  expect(player.currentTime).toBe(20)
  expect(player.playbackRate).toBe(1)
  expect(screen.getByRole('complementary', { name: 'Inspetor' })).toBeTruthy()
})

test('todos os atalhos do player aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()

  await usuario.keyboard('?')

  const dialogo = await screen.findByRole('dialog', { name: /Atalhos/ })
  const grupo = within(dialogo).getByRole('region', { name: 'Player' })
  expect([...grupo.querySelectorAll('dd')].map((d) => d.textContent)).toEqual(['EspaçoouK', 'L', 'J', '←→', 'Shift+←→', ',.', 'F'])
})

test('?t= posiciona o player quando o vídeo carrega', async () => {
  const player = await abrirVideo({ t: 724 })

  fireEvent.loadedMetadata(player)

  expect(player.currentTime).toBe(724)
  expect(screen.getByText('12:04 / 49:19')).toBeTruthy()
})

test('pausar e saltar atualizam o t da URL sem empilhar histórico', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
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
  servidor.use(http.get('/v1/jobs/j1/reproducao', () => (falhar ? new HttpResponse(null, { status: 503 }) : HttpResponse.json(REPRODUCAO))))
  const espera = abrirVideo({ esperarFaixas: false })

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Código para o suporte: http_503')
  falhar = false
  await usuario.click(within(aviso).getByRole('button', { name: 'Tentar de novo' }))

  // O primeiro <video> (antes da falha) saiu da tela: o novo carrega o link.
  void espera.catch(() => null)
  await waitFor(() => expect(screen.getByLabelText('Player').getAttribute('src')).toBe(REPRODUCAO.url))
})

test('com o link válido, a falha do arquivo mostra o código e não pede o link de novo', async () => {
  let pedidos = 0
  servidor.events.on('request:start', ({ request }) => {
    if (request.url.endsWith('/reproducao')) pedidos += 1
  })
  const player = await abrirVideo()
  const antes = pedidos

  fireEvent.error(player)

  expect((await screen.findByRole('alert')).textContent).toContain('Código para o suporte: midia_')
  expect(pedidos).toBe(antes)
  servidor.events.removeAllListeners()
})

test('com o link vencido, a falha do arquivo pede outro link e volta ao mesmo ponto', async () => {
  let pedidos = 0
  servidor.use(
    http.get('/v1/jobs/j1/reproducao', () => {
      pedidos += 1
      return HttpResponse.json({
        url: pedidos === 1 ? REPRODUCAO.url : `${REPRODUCAO.url}?p=2`,
        expira_em: pedidos === 1 ? '2000-01-01T00:00:00Z' : '2999-01-01T00:00:00Z',
      })
    }),
  )
  const player = await abrirVideo()
  irPara(player, 300)

  fireEvent.error(player)

  await waitFor(() => expect(player.getAttribute('src')).toBe(`${REPRODUCAO.url}?p=2`))
  player.currentTime = 0
  fireEvent.loadedMetadata(player)
  expect(player.currentTime).toBe(300)
  expect(pedidos).toBe(2)
})

test('o vídeo que não existe avisa e leva de volta ao acervo; outra falha dá o código e tenta de novo', async () => {
  servidor.use(http.get('/v1/jobs/j1', () => new HttpResponse(null, { status: 404 })))
  const espera = abrirVideo().catch(() => null)
  expect((await screen.findByRole('alert')).textContent).toContain('Vídeo não encontrado.')
  expect(screen.getByRole('link', { name: 'Voltar ao acervo' }).getAttribute('href')).toBe('/acervo')
  cleanup()
  void espera

  let falhar = true
  servidor.use(http.get('/v1/jobs/j1', () => (falhar ? new HttpResponse(null, { status: 500 }) : HttpResponse.json(JOB))))
  const segunda = abrirVideo()
  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('http_500')
  falhar = false
  await userEvent.setup().click(within(aviso).getByRole('button', { name: 'Tentar de novo' }))
  expect(await segunda).toBeTruthy()
})

test('baixar a decupagem chama a rota do servidor e entrega o arquivo; a falha mostra o código', async () => {
  const usuario = userEvent.setup()
  let pedidos = 0
  let falhar = false
  servidor.use(
    http.get('/v1/jobs/j1/decupagem/download', () => {
      pedidos += 1
      return falhar ? new HttpResponse(null, { status: 409 }) : HttpResponse.json(DECUPAGEM)
    }),
  )
  const entregue: string[] = []
  URL.createObjectURL = vi.fn(() => 'blob:decupagem')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    entregue.push(this.download)
  })
  await abrirVideo()

  await usuario.click(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' }))
  await waitFor(() => expect(entregue).toEqual(['FAMA_20261021_720_BLU.decupagem.json']))
  expect(pedidos).toBe(1)

  falhar = true
  await usuario.click(screen.getByRole('button', { name: 'Baixar decupagem (JSON)' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Código para o suporte: http_409')
})

test('baixar o vídeo fica ocupado até a URL chegar e inicia o download por ela', async () => {
  const usuario = userEvent.setup()
  let liberar: () => void = () => {}
  const espera = new Promise<void>((r) => (liberar = r))
  servidor.use(
    http.get('/v1/jobs/j1/download', async () => {
      await espera
      return HttpResponse.json({ url: 'https://exemplo.test/v.mp4?baixar=1', expira_em: '2999-01-01T00:00:00Z' })
    }),
  )
  const hrefs: string[] = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    hrefs.push(this.href)
  })
  await abrirVideo()

  const botao = screen.getByRole('button', { name: 'Baixar vídeo' })
  await usuario.click(botao)
  await waitFor(() => expect(botao.getAttribute('aria-busy')).toBe('true'))
  liberar()
  await waitFor(() => expect(hrefs).toEqual(['https://exemplo.test/v.mp4?baixar=1']))
  await waitFor(() => expect(botao.getAttribute('aria-busy')).toBe('false'))
})

test('falha ao preparar o download do vídeo mostra a mensagem em português', async () => {
  const usuario = userEvent.setup()
  servidor.use(http.get('/v1/jobs/j1/download', () => new HttpResponse(null, { status: 503 })))
  await abrirVideo()

  await usuario.click(screen.getByRole('button', { name: 'Baixar vídeo' }))

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('Não foi possível preparar o download. Tente de novo.')
  expect(aviso.textContent).toContain('http_503')
})

test('"Quem acessou" só aparece com auditoria.ver e leva à Auditoria filtrada pelo vídeo', async () => {
  await abrirVideo()
  expect(screen.queryByRole('link', { name: 'Quem acessou' })).toBeNull()
  cleanup()

  await abrirVideo({ permissoes: ['auditoria.ver'] })
  expect(screen.getByRole('link', { name: 'Quem acessou' }).getAttribute('href')).toBe(
    '/admin/auditoria?alvo=j1&acao=video.aberto%2Cvideo.baixado%2Cdecupagem.baixada&de=&ate=',
  )
})

test('sem a decupagem pronta, não há baixar, linha do tempo nem itens', async () => {
  job = { estado: 'analisando' }
  await abrirVideo({ esperarFaixas: false })

  expect(screen.queryByRole('button', { name: 'Baixar decupagem (JSON)' })).toBeNull()
  expect(screen.queryByRole('group', { name: /Pautas/ })).toBeNull()
  expect(screen.getByText('O inspetor aparece quando a decupagem estiver pronta.')).toBeTruthy()
})

test.each(['analisando', 'concluido'])('mostra e atualiza a posição na GPU com o Job %s até obter a vaga', async (estado) => {
  let posicao: number | null = 3
  servidor.use(http.get('/v1/jobs/j1', () => HttpResponse.json({
    ...JOB,
    estado,
    etapa_atual: estado === 'concluido' ? 'inventario_de_objetos' : 'transcricao',
    posicao_na_fila_gpu: posicao,
  })))
  await abrirVideo({ acompanhamentoMs: 20, esperarFaixas: false })

  expect(await screen.findByText('Na fila da GPU · posição 3')).toBeTruthy()
  expect(screen.queryByText(/em andamento\./)).toBeNull()
  posicao = 1
  expect(await screen.findByText('Na fila da GPU · posição 1')).toBeTruthy()
  posicao = null
  expect(await screen.findByText(/em andamento\./)).toBeTruthy()
  expect(screen.queryByText(/Na fila da GPU/)).toBeNull()
})

test.each(['analisando', 'concluido'])('atualiza a posição na GPU após seis horas com o Job %s', async (estado) => {
  job = {
    estado,
    etapa_atual: estado === 'concluido' ? 'inventario_de_objetos' : 'transcricao',
    etapas: [{ nome: 'transcricao', inicio: new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString(), fim: null, resultado: null }],
    posicao_na_fila_gpu: 3,
  }
  await abrirVideo({ acompanhamentoMs: 20, esperarFaixas: false })

  expect(await screen.findByText('Na fila da GPU · posição 3')).toBeTruthy()
  job.posicao_na_fila_gpu = 1
  expect(await screen.findByText('Na fila da GPU · posição 1')).toBeTruthy()
  job.posicao_na_fila_gpu = null
  await waitFor(() => expect(screen.queryByText(/Na fila da GPU/)).toBeNull())
})

test('falha ao carregar a decupagem mostra o código e tenta de novo', async () => {
  const usuario = userEvent.setup()
  let falhar = true
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => (falhar ? new HttpResponse(null, { status: 503 }) : HttpResponse.json(DECUPAGEM))))
  await abrirVideo({ esperarFaixas: false })

  const aviso = await screen.findByRole('alert')
  expect(aviso.textContent).toContain('http_503')
  falhar = false
  await usuario.click(within(aviso).getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByRole('group', { name: 'Pautas 3' })).toBeTruthy()
})

test('a versão do pipeline aparece, com o manifesto também pelo teclado; sem ela, "anterior à versão"', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({ ...DECUPAGEM, versao_pipeline: '2026.11.1', manifesto_do_pipeline: { modelos: { analise: 'gemini-3.5-flash-lite' } } }),
    ),
  )
  await abrirVideo()
  const selo = await screen.findByText('Pipeline 2026.11.1')
  selo.focus()
  expect((await screen.findAllByText(/gemini-3\.5-flash-lite/)).length).toBeGreaterThan(0)
  cleanup()

  servidor.resetHandlers()
  await abrirVideo()
  expect(await screen.findByText('Pipeline anterior à versão')).toBeTruthy()
})

async function menu() {
  const usuario = userEvent.setup()
  await usuario.click(screen.getByRole('button', { name: 'Mais ações' }))
  return screen.findByRole('menu')
}

test('o menu leva a "Reprocessar…" só com a permissão e o vídeo concluído fora das etapas', async () => {
  await abrirVideo()
  expect(screen.queryByRole('button', { name: 'Mais ações' })).toBeNull()
  cleanup()

  await abrirVideo({ permissoes: ['video.reprocessar_etapa'] })
  expect(within(await menu()).getByRole('menuitem', { name: /Reprocessar…/ })).toBeTruthy()
  cleanup()

  job = { etapa_atual: null, indexacao: { estado: 'pendente', em: AGORA } }
  await abrirVideo({ permissoes: ['video.reprocessar_etapa'] })
  expect(screen.queryByRole('button', { name: 'Mais ações' })).toBeNull()
})

test('"Mandar para a lixeira…" só com lixeira.gerir e com o vídeo fora do processamento', async () => {
  await abrirVideo({ permissoes: ['lixeira.gerir'] })
  expect(within(await menu()).getByRole('menuitem', { name: /Mandar para a lixeira/ })).toBeTruthy()
  cleanup()

  job = { estado: 'analisando' }
  await abrirVideo({ permissoes: ['lixeira.gerir'], esperarFaixas: false })
  expect(screen.queryByRole('button', { name: 'Mais ações' })).toBeNull()
})

test('sem Reprocessar nem lixeira, não há menu "Mais ações"', async () => {
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  expect(screen.queryByRole('button', { name: 'Mais ações' })).toBeNull()
})

test('aberto com as etapas depois da análise rodando, acompanha até o fim e recarrega a decupagem', async () => {
  let cargas = 0
  let terminou = false
  const rodando: Partial<Job> = { etapa_atual: 'identificacao', indexacao: { estado: 'pendente', em: AGORA } }
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => {
      cargas += 1
      return HttpResponse.json(DECUPAGEM)
    }),
    http.get('/v1/jobs/j1', () =>
      HttpResponse.json(terminou ? { ...JOB, etapa_atual: null, indexacao: { estado: 'indexado', em: AGORA } } : { ...JOB, ...rodando }),
    ),
  )
  await abrirVideo({ permissoes: ['video.reprocessar_etapa'], acompanhamentoMs: 20 })
  expect(await screen.findByText('Identificação em andamento.')).toBeTruthy()
  terminou = true

  await waitFor(() => expect(screen.queryByText(/em andamento/)).toBeNull())
  await waitFor(() => expect(cargas).toBe(2))
  expect(within(await menu()).getByRole('menuitem', { name: /Reprocessar…/ })).toBeTruthy()
})

test('aberto com a análise rodando, acompanha até o fim e mostra a decupagem', async () => {
  let terminou = false
  servidor.use(http.get('/v1/jobs/j1', () => HttpResponse.json(terminou ? JOB : { ...JOB, estado: 'analisando', etapa_atual: 'analise' })))
  await abrirVideo({ acompanhamentoMs: 20, esperarFaixas: false })
  expect(await screen.findByText(/Análise em andamento/)).toBeTruthy()
  terminou = true

  expect(await screen.findByRole('group', { name: /^Pautas \d+$/ })).toBeTruthy()
  expect(screen.queryByText(/em andamento/)).toBeNull()
})

test('um Job preso há horas volta a oferecer "Reprocessar…", sem dizer que está em andamento', async () => {
  const haSeteHoras = new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString()
  job = {
    etapa_atual: 'identificacao',
    indexacao: { estado: 'pendente', em: haSeteHoras },
    etapas: [{ nome: 'identificacao', inicio: haSeteHoras, fim: null, resultado: null }],
  }
  await abrirVideo({ permissoes: ['video.reprocessar_etapa'] })

  expect(within(await menu()).getByRole('menuitem', { name: /Reprocessar…/ })).toBeTruthy()
  expect(screen.queryByText(/em andamento/)).toBeNull()
})
