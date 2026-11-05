import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
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
    { id: 'pa1', titulo: 'Eleição', inicio_ms: 0, fim_ms: 724_000, tom: 'informativo', resumo: 'O resumo da eleição.' },
    { id: 'pa2', titulo: 'Bastidores do Miss Bumbum', inicio_ms: 724_000, fim_ms: 940_000, tom: 'leve' },
    { id: 'pa3', titulo: 'Final', inicio_ms: 940_000, fim_ms: 2_660_000, tom: 'informativo' },
  ],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      fontes_do_nome: ['gc', 'fala'],
      na_imagem: [
        { inicio_ms: 211_000, fim_ms: 261_000, evidencia: 'rosto', papel: 'colunista', visual: 'terno preto' },
        { inicio_ms: 300_000, fim_ms: 320_000, evidencia: 'rosto' },
      ],
      citada_na_fala: [],
      citada_no_texto: [],
    },
    {
      id: 'p2',
      nome: 'Não identificado, mulher loira',
      na_imagem: [{ inicio_ms: 220_000, fim_ms: 250_000, evidencia: 'rosto' }],
      citada_na_fala: [],
      citada_no_texto: [],
    },
    {
      id: 'p3',
      nome: 'Felipe Camargo',
      na_imagem: [],
      citada_na_fala: [{ inicio_ms: 230_000, fim_ms: 235_000 }],
      citada_no_texto: [],
    },
  ],
  planos: [
    { id: 'pl1', ambiente: 'Estúdio', acao: 'apresentadora em pé', inicio_ms: 200_000, fim_ms: 400_000 },
    { id: 'pl2', ambiente: 'Externa', inicio_ms: 724_000, fim_ms: 730_000 },
  ],
  comerciais: [{ marca: 'Ultrafarma', tipo: 'merchandising', inicio_ms: 225_000, fim_ms: 240_000 }],
  transcricao: [
    { locutor: 'Ana', texto: 'Boa noite, o Leão Lobo está aqui', inicio_ms: 218_000, fim_ms: 224_000 },
    { locutor: 'Leão', texto: 'Obrigado, Ana, é um prazer', inicio_ms: 224_000, fim_ms: 300_000 },
  ],
  textos_na_tela: [{ tipo: 'GC', texto: 'LEÃO LOBO · colunista', inicio_ms: 213_000, fim_ms: 235_000 }],
  objetos: [
    {
      id: 'o1',
      categoria: 'calcado',
      tipo: 'sandália',
      cor_base: ['vermelho'],
      cor: 'vermelho vivo',
      detalhe: 'salto alto',
      marca: 'Arezzo',
      pessoa: 'p1',
      relacao: 'calca',
      ocorrencias: [
        { inicio_ms: 214_000, fim_ms: 230_000 },
        { inicio_ms: 500_000, fim_ms: 510_000 },
      ],
    },
    { id: 'o2', categoria: 'em_cena', tipo: 'troféu', cor_base: ['dourado', 'preto'], ocorrencias: [{ inicio_ms: 214_000, fim_ms: 220_000 }] },
  ],
}

const VAZIA = { ...DECUPAGEM, pautas: [], pessoas: [], planos: [], comerciais: [], transcricao: [], textos_na_tela: [], objetos: [] }

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 2959,
  programa: 'TV Fama',
  data_exibicao: '2026-10-21',
  timecode_origem: null,
  taxa_de_quadros: null,
  cortes_ms: [],
  criado_em: '2026-10-21T10:00:00Z',
}

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

async function abrir() {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={false} />
    </AtalhosProvider>,
  )
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  await waitFor(() => expect(player.getAttribute('src')).toBe('https://exemplo.test/v.mp4'))
  await screen.findByRole('tablist')
  return player
}

function irPara(player: HTMLVideoElement, segundos: number) {
  player.currentTime = segundos
  fireEvent.timeUpdate(player)
}

const painel = () => screen.getByLabelText('Painel')
const aba = (nome: string | RegExp) => screen.getByRole('tab', { name: nome })

test('as abas trazem a contagem ao lado do nome', async () => {
  await abrir()

  for (const nome of ['Agora', 'Pessoas 2', 'Pautas 3', 'Objetos 2', 'Comerciais 1', 'Textos na tela 1', 'Planos 2', 'Transcrição 2']) {
    expect(aba(nome)).toBeTruthy()
  }
  expect(aba('Agora').getAttribute('aria-selected')).toBe('true')
})

test('trocar de pauta tocando muda o topo e a aba Agora sem clique', async () => {
  const player = await abrir()
  irPara(player, 100)
  expect(within(painel()).getByText('Agora · 01:40')).toBeTruthy()
  expect(within(painel()).getByText('Eleição · informativo')).toBeTruthy()
  expect(within(painel()).queryByText(/Estúdio/)).toBeNull()
  expect(within(painel()).getByText('Nada decupado neste momento.')).toBeTruthy()

  irPara(player, 232)
  expect(within(painel()).getByText('Agora · 03:52')).toBeTruthy()
  expect(within(painel()).getByText('Estúdio, apresentadora em pé')).toBeTruthy()
  const agora = within(screen.getByRole('tabpanel'))
  expect(agora.getByText('Pessoas na imagem')).toBeTruthy()
  expect(agora.getByText('Leão Lobo')).toBeTruthy()
  expect(agora.getByText('não identificado')).toBeTruthy()
  expect(agora.getByText('mulher loira')).toBeTruthy()
  expect(agora.getByText('Menções')).toBeTruthy()
  expect(agora.getByText('Ultrafarma')).toBeTruthy()
  expect(agora.getByText('LEÃO LOBO · colunista')).toBeTruthy()
  expect(agora.queryByText('Nada decupado neste momento.')).toBeNull()

  irPara(player, 727)
  expect(within(painel()).getByText('Bastidores do Miss Bumbum · leve')).toBeTruthy()
  expect(within(painel()).getByText('Externa')).toBeTruthy()
})

test('trecho sem pauta no topo diz "Sem decupagem"', async () => {
  const player = await abrir()
  irPara(player, 2_700)

  expect(within(painel()).getByText('Sem decupagem (44:20–49:19)')).toBeTruthy()
})

test('o item atual tem aria-current, a barra e o fundo, e nenhum fundo no painel é vermelho', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 800)
  await usuario.click(aba('Pautas 3'))

  const atual = within(painel()).getByRole('button', { name: /Bastidores do Miss Bumbum/ }).closest('[data-chave]') as HTMLElement
  expect(atual.getAttribute('aria-current')).toBe('true')
  expect(atual.style.boxShadow).toContain('3px')
  expect(atual.style.background).not.toBe('')
  const outro = within(painel()).getByRole('button', { name: /Eleição/ }).closest('[data-chave]') as HTMLElement
  expect(outro.getAttribute('aria-current')).toBeNull()

  const todos = [painel(), ...painel().querySelectorAll<HTMLElement>('*')]
  for (const el of todos) {
    expect(el.style.background.toLowerCase()).not.toMatch(/e03131|f4736a|red/)
  }
})

test('clicar num item salta o player, seleciona o bloco na linha do tempo e não rola a página', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  const rolar = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  const vista = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
  await usuario.click(aba('Pautas 3'))

  await usuario.click(within(painel()).getByRole('button', { name: /Bastidores do Miss Bumbum/ }))

  expect(player.currentTime).toBe(724)
  expect(
    screen.getByRole('button', { name: 'Pauta: Bastidores do Miss Bumbum, 12:04 a 15:40' }).getAttribute('aria-pressed'),
  ).toBe('true')
  expect(rolar).not.toHaveBeenCalled()
  expect(vista).not.toHaveBeenCalled()
})

test('selecionar um bloco na linha do tempo abre a aba do tipo com o item selecionado', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(screen.getByRole('button', { name: 'Comercial: Ultrafarma, 03:45 a 04:00' }))

  expect(aba('Comerciais 1').getAttribute('aria-selected')).toBe('true')
  expect(within(painel()).getByRole('button', { name: /Ultrafarma/ }).getAttribute('aria-pressed')).toBe('true')
})

test('Ctrl+→ e Ctrl+← trocam de aba; o player não anda', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 20)

  await usuario.keyboard('{Control>}{ArrowRight}{/Control}')
  expect(aba('Pessoas 2').getAttribute('aria-selected')).toBe('true')
  await usuario.keyboard('{Control>}{ArrowRight}{/Control}')
  expect(aba('Pautas 3').getAttribute('aria-selected')).toBe('true')
  await usuario.keyboard('{Control>}{ArrowLeft}{/Control}')
  expect(aba('Pessoas 2').getAttribute('aria-selected')).toBe('true')
  expect(player.currentTime).toBe(20)
})

test('↑ e ↓ movem a seleção na aba ativa e Enter salta o player ao item', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Pautas 3'))

  await usuario.keyboard('{ArrowDown}')
  const pressionados = () =>
    screen.getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true' && painel().contains(b))
  expect(pressionados().map((b) => b.textContent)).toEqual([expect.stringContaining('Eleição')])
  await usuario.keyboard('{ArrowDown}')
  expect(pressionados().map((b) => b.textContent)).toEqual([expect.stringContaining('Bastidores')])
  await usuario.keyboard('{Enter}')
  expect(player.currentTime).toBe(724)
  await usuario.keyboard('{ArrowUp}{ArrowUp}{ArrowUp}')
  expect(pressionados().map((b) => b.textContent)).toEqual([expect.stringContaining('Eleição')])
  // A seleção é a mesma da linha do tempo.
  expect(
    screen.getByRole('button', { name: 'Pauta: Eleição, 00:00 a 12:04' }).getAttribute('aria-pressed'),
  ).toBe('true')
})

test('Enter com o foco num item salta ao item selecionado pelas setas, não ao do foco', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Pautas 3'))
  await usuario.click(within(painel()).getByRole('button', { name: /^Eleição/ }))

  await usuario.keyboard('{ArrowDown}{Enter}')

  expect(player.currentTime).toBe(724)
  expect(within(painel()).getByRole('button', { name: /Bastidores/ }).getAttribute('aria-pressed')).toBe('true')
})

test('na aba Pessoas, ↓ segue a ordem da tela: as aparições de cada pessoa juntas, depois as menções', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(aba('Pessoas 2'))
  await usuario.click(within(painel()).getByRole('button', { name: /Leão Lobo.*aparições/ }))
  await usuario.click(within(painel()).getByRole('button', { name: /não identificado.*aparição/ }))
  // Tira o foco dos botões, para as setas não dependerem dele.
  ;(document.activeElement as HTMLElement).blur()

  const ordem: string[] = []
  for (let i = 0; i < 4; i++) {
    await usuario.keyboard('{ArrowDown}')
    ordem.push(painel().querySelector('[aria-pressed="true"]')?.getAttribute('aria-label') ?? '')
  }

  expect(ordem).toEqual([
    'Leão Lobo, 03:31 a 04:21',
    'Leão Lobo, 05:00 a 05:20',
    'não identificado, 03:40 a 04:10',
    'Felipe Camargo, 03:50 a 03:55',
  ])
})

test('a aparição selecionada na linha do tempo abre a lista da pessoa, que fecha no clique', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(screen.getByRole('button', { name: 'Aparição de Leão Lobo, 05:00 a 05:20' }))

  const linha = within(painel()).getByRole('button', { name: /Leão Lobo.*2 aparições/ })
  expect(linha.getAttribute('aria-expanded')).toBe('true')
  await usuario.click(linha)
  expect(linha.getAttribute('aria-expanded')).toBe('false')
})

test('as setas não agem com o foco num campo de texto', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(aba('Pautas 3'))
  const campo = document.createElement('input')
  document.body.append(campo)
  campo.focus()

  await usuario.keyboard('{ArrowDown}')

  expect(painel().querySelector('[aria-pressed="true"]')).toBeNull()
  campo.remove()
})

test('"Reproduzir trecho" toca do início ao fim do item e para sozinho', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Comerciais 1'))
  await usuario.click(within(painel()).getByRole('button', { name: /Ultrafarma/ }))
  playMock.mockClear()

  await usuario.click(screen.getByRole('button', { name: 'Reproduzir trecho' }))

  expect(player.currentTime).toBe(225)
  expect(playMock).toHaveBeenCalledTimes(1)
  irPara(player, 235)
  expect(pauseMock).not.toHaveBeenCalled()
  irPara(player, 240.1)
  expect(pauseMock).toHaveBeenCalledTimes(1)
  // Para no fim exato, não no instante do último `timeupdate`.
  expect(player.currentTime).toBe(240)
  // Depois de parar, tocar de novo segue até o fim do vídeo.
  irPara(player, 300)
  expect(pauseMock).toHaveBeenCalledTimes(1)
})

test('"Reproduzir trecho" só aparece no item selecionado', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(aba('Pautas 3'))
  expect(screen.queryByRole('button', { name: 'Reproduzir trecho' })).toBeNull()

  await usuario.click(within(painel()).getByRole('button', { name: /Final/ }))

  expect(screen.getAllByRole('button', { name: 'Reproduzir trecho' })).toHaveLength(1)
})

test('Pessoas: uma linha por pessoa que abre as aparições; as menções ficam à parte', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(aba('Pessoas 2'))

  const linha = within(painel()).getByRole('button', { name: /Leão Lobo.*2 aparições/ })
  expect(linha.getAttribute('aria-expanded')).toBe('false')
  expect(within(painel()).getByRole('button', { name: /não identificado.*1 aparição/ })).toBeTruthy()
  expect(within(painel()).queryByRole('button', { name: /^Leão Lobo, 03:31/ })).toBeNull()

  await usuario.click(linha)

  expect(linha.getAttribute('aria-expanded')).toBe('true')
  const primeira = within(painel()).getByRole('button', { name: /^Leão Lobo, 03:31 a 04:21/ })
  expect(within(primeira).getByText('colunista · terno preto')).toBeTruthy()
  expect(screen.getByText('Só citadas (não contam como tempo de tela)')).toBeTruthy()
  expect(screen.getByText('Felipe Camargo')).toBeTruthy()
  expect(screen.getByText('citado na fala')).toBeTruthy()
  // Quem só foi citado não é uma linha de aparição.
  expect(within(painel()).queryByRole('button', { name: /Felipe Camargo.*aparições?/ })).toBeNull()
})

test('o selo da prova do nome salta ao tempo da prova', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 222)

  await usuario.click(screen.getByRole('button', { name: 'GC 03:33' }))
  expect(player.currentTime).toBe(213)

  await usuario.click(screen.getByRole('button', { name: 'Fala 03:38' }))
  expect(player.currentTime).toBe(218)
})

test('"não identificado" nunca ganha selos de nome', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 222)

  const linha = screen.getByText('mulher loira').closest('[data-chave]') as HTMLElement
  expect(within(linha).queryByRole('button', { name: /GC|Fala/ })).toBeNull()
  await usuario.click(aba('Pessoas 2'))
  expect(screen.queryByText(/Leão Lobo.*mulher/)).toBeNull()
})

test('Pautas, Comerciais, Textos e Planos listam o que há com os tempos', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(aba('Pautas 3'))
  const pauta = within(painel()).getByRole('button', { name: /Eleição/ })
  expect(within(pauta).getByText('informativo')).toBeTruthy()
  expect(within(pauta).getByText('00:00–12:04')).toBeTruthy()
  expect(within(pauta).getByText('O resumo da eleição.')).toBeTruthy()

  await usuario.click(aba('Comerciais 1'))
  expect(within(within(painel()).getByRole('button', { name: /Ultrafarma/ })).getByText('merchandising')).toBeTruthy()

  await usuario.click(aba('Textos na tela 1'))
  const texto = within(painel()).getByRole('button', { name: /LEÃO LOBO/ })
  expect(within(texto).getByText('GC')).toBeTruthy()
  expect(within(texto).getByText('03:33–03:55')).toBeTruthy()

  await usuario.click(aba('Planos 2'))
  expect(within(within(painel()).getByRole('button', { name: /Estúdio/ })).getByText('apresentadora em pé')).toBeTruthy()
})

test('toda aba vazia diz que está vazia', async () => {
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(VAZIA)))
  const usuario = userEvent.setup()
  await abrir()
  expect(screen.getByText('Nada decupado neste momento.')).toBeTruthy()

  const vazios: [string, string][] = [
    ['Pessoas 0', 'Nenhuma pessoa neste vídeo.'],
    ['Pautas 0', 'Nenhuma pauta neste vídeo.'],
    ['Objetos 0', 'Este vídeo não tem objetos decupados.'],
    ['Comerciais 0', 'Nenhum comercial neste vídeo.'],
    ['Textos na tela 0', 'Nenhum texto na tela neste vídeo.'],
    ['Planos 0', 'Nenhum plano neste vídeo.'],
    ['Transcrição 0', 'Este vídeo não tem transcrição.'],
  ]
  for (const [nome, frase] of vazios) {
    await usuario.click(aba(nome))
    expect(within(painel()).getByText(frase)).toBeTruthy()
  }
})

test('os atalhos do painel aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.keyboard('?')

  const tabela = await screen.findByRole('table', { name: 'Painel' })
  expect(within(tabela).getByText('No painel: mover a seleção na aba')).toBeTruthy()
  expect(within(tabela).getByText('No painel: trocar de aba')).toBeTruthy()
})

test('Transcrição: cada fala traz o início, o locutor e o texto inteiro', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(aba('Transcrição 2'))

  const fala = within(painel()).getByRole('button', { name: /Boa noite, o Leão Lobo está aqui/ })
  expect(within(fala).getByText('03:38')).toBeTruthy()
  expect(within(fala).getByText('Ana')).toBeTruthy()
  expect(within(fala).getByText('Boa noite, o Leão Lobo está aqui')).toBeTruthy()
})

test('Transcrição: a fala atual muda com o tempo, sem fundo vermelho', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Transcrição 2'))
  irPara(player, 220)

  const atual = (nome: RegExp) => within(painel()).getByRole('button', { name: nome }).closest('[data-chave]') as HTMLElement
  expect(atual(/Boa noite/).getAttribute('aria-current')).toBe('true')
  expect(atual(/Obrigado/).getAttribute('aria-current')).toBeNull()
  expect(atual(/Boa noite/).style.boxShadow).toContain('3px')

  irPara(player, 230)

  expect(atual(/Obrigado/).getAttribute('aria-current')).toBe('true')
  expect(atual(/Boa noite/).getAttribute('aria-current')).toBeNull()
  for (const el of [painel(), ...painel().querySelectorAll<HTMLElement>('*')]) {
    expect(el.style.background.toLowerCase()).not.toMatch(/e03131|f4736a|red/)
  }
})

test('Transcrição: clicar numa fala salta ao início e seleciona a ocorrência da faixa Falas, e vice-versa', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Transcrição 2'))

  await usuario.click(within(painel()).getByRole('button', { name: /Obrigado, Ana/ }))

  expect(player.currentTime).toBe(224)
  expect(within(painel()).getByRole('button', { name: 'Reproduzir trecho' })).toBeTruthy()
  const bloco = screen.getAllByRole('button', { name: /^Fala/ }).find((b) => b.getAttribute('aria-pressed') === 'true')
  expect(bloco).toBeTruthy()

  await usuario.click(aba('Agora'))
  await usuario.click(screen.getAllByRole('button', { name: /^Fala/ })[0])

  expect(aba('Transcrição 2').getAttribute('aria-selected')).toBe('true')
  expect(within(painel()).getByRole('button', { name: /Boa noite/ }).getAttribute('aria-pressed')).toBe('true')
})

test('Transcrição: ↓ e Enter funcionam como nas outras abas', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Transcrição 2'))

  await usuario.keyboard('{ArrowDown}{ArrowDown}{Enter}')

  expect(player.currentTime).toBe(224)
})

test('o agora mostra os objetos visíveis com a cor em palavras, o dono e "em cena"', async () => {
  const player = await abrir()
  irPara(player, 215)

  const secao = within(painel()).getByText('Objetos', { selector: 'p' }).parentElement as HTMLElement
  const sandalia = within(secao).getByRole('button', { name: /sandália/ }).parentElement as HTMLElement
  expect(within(sandalia).getByText('vermelho vivo')).toBeTruthy()
  expect(within(sandalia).getByText('calçado')).toBeTruthy()
  expect(within(sandalia).getByText('marca Arezzo')).toBeTruthy()
  expect(within(sandalia).getByText('salto alto')).toBeTruthy()
  expect(within(sandalia).getByText((_, el) => el?.tagName === 'P' && el.textContent === 'Leão Lobo calça')).toBeTruthy()
  expect(within(sandalia).getByRole('button', { name: 'Leão Lobo' })).toBeTruthy()
  const trofeu = within(secao).getByRole('button', { name: /troféu/ }).parentElement as HTMLElement
  expect(within(trofeu).getByText('dourado e preto')).toBeTruthy()
  // Sem dono, a categoria "em cena" não se repete na linha do dono.
  expect(within(trofeu).getAllByText('em cena').length).toBe(1)
})

test('toda cor de objeto tem a palavra ao lado', async () => {
  const player = await abrir()
  irPara(player, 215)

  const quadradinhos = painel().querySelectorAll('[data-cor-base]')
  expect(quadradinhos.length).toBe(3)
  for (const q of quadradinhos) {
    expect(q.getAttribute('aria-hidden')).toBe('true')
    // A palavra ao lado nomeia a própria cor ("vermelho vivo" ao lado do vermelho).
    expect(q.parentElement?.textContent).toContain(q.getAttribute('data-cor-base'))
  }
})

test('clicar no dono salta para a pessoa na aba Pessoas', async () => {
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 215)

  await usuario.click(within(painel()).getByRole('button', { name: 'Leão Lobo' }))

  expect(aba('Pessoas 2').getAttribute('aria-selected')).toBe('true')
  expect(within(painel()).getByRole('button', { name: /^Leão Lobo, 03:31 a 04:21/ }).getAttribute('aria-pressed')).toBe('true')
})

test('a aba Objetos lista cada objeto com o número de ocorrências e abre as ocorrências', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(aba('Objetos 2'))
  expect(within(painel()).getByText('2 ocorrências')).toBeTruthy()
  expect(within(painel()).getByText('1 ocorrência')).toBeTruthy()
  expect(within(painel()).queryByRole('button', { name: /sandália, 08:20/ })).toBeNull()

  await usuario.click(within(painel()).getByRole('button', { name: 'sandália, 2 ocorrências' }))
  expect(within(painel()).getByRole('button', { name: 'sandália, 08:20 a 08:30' })).toBeTruthy()
})

test('o bloco do objeto na faixa leva à aba Objetos com a ocorrência selecionada', async () => {
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(
    await screen.findByRole('button', { name: 'Objeto: sandália (vermelho vivo) de Leão Lobo, 08:20 a 08:30' }),
  )

  expect(aba('Objetos 2').getAttribute('aria-selected')).toBe('true')
  expect(within(painel()).getByRole('button', { name: 'sandália, 08:20 a 08:30' }).getAttribute('aria-pressed')).toBe('true')
})

test('uma Decupagem sem objetos mostra o aviso na faixa', async () => {
  const { objetos: _, ...antiga } = DECUPAGEM
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(antiga)))
  await abrir()

  expect(await screen.findByText('Este vídeo não tem objetos decupados.')).toBeTruthy()
})

test('uma Decupagem sem objetos mostra o aviso na aba Objetos', async () => {
  const { objetos: _, ...antiga } = DECUPAGEM
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(antiga)))
  const usuario = userEvent.setup()
  await abrir()

  await usuario.click(aba('Objetos 0'))
  expect(within(painel()).getByText('Este vídeo não tem objetos decupados.')).toBeTruthy()
})

function comPessoas(pessoas: object[]) {
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json({ ...DECUPAGEM, pessoas })))
}

const PESSOA_PELO_ROSTO = {
  id: 'p1',
  nome: 'Leão Lobo',
  fontes_do_nome: ['rosto'],
  estado_do_nome: 'confirmado',
  na_imagem: [{ inicio_ms: 211_000, fim_ms: 261_000, evidencia: 'rosto', quadro: 'quadros/aparicao-0-0.jpg' }],
  citada_na_fala: [],
  citada_no_texto: [],
}

test('o selo "Rosto" é só texto: não abre nada', async () => {
  comPessoas([PESSOA_PELO_ROSTO])
  const player = await abrir()
  irPara(player, 222)

  expect(screen.getAllByText('Rosto').length).toBeGreaterThan(0)
  expect(screen.queryByRole('button', { name: /^Rosto/ })).toBeNull()
})

test('o palpite não confirmado leva o selo em texto, com a dica, e nenhuma porcentagem', async () => {
  comPessoas([
    { ...PESSOA_PELO_ROSTO, fontes_do_nome: [], estado_do_nome: 'palpite', nome: 'Leão Lobo' },
  ])
  const usuario = userEvent.setup()
  const player = await abrir()
  irPara(player, 222)

  const selo = screen.getByText('não confirmado')
  expect(selo.closest('button')).toBeNull()
  expect(painel().textContent).not.toMatch(/\d\s*%/)
  await usuario.hover(selo)
  expect(await screen.findByText(/não achou prova/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: /^Rosto/ })).toBeNull()
})

const CAIXA_PEQUENA = { quadro: 'quadros/plano-0-0.jpg', x: 0.5, y: 0.5, largura: 0.1, altura: 0.1 }
const CAIXA_GRANDE = { quadro: 'quadros/plano-0-1.jpg', x: 0.1, y: 0.2, largura: 0.3, altura: 0.4 }
const INVENTARIO = [
  { nome: 'caneca', categoria: 'utensilio', caixas: [CAIXA_PEQUENA], destaque: 1 },
  { nome: 'carro azul', categoria: 'veiculo', cor: 'azul', marca: 'BYD', caixas: [CAIXA_PEQUENA, CAIXA_GRANDE], destaque: 3 },
  { nome: 'blazer preto', categoria: 'roupa', caixas: [CAIXA_PEQUENA], destaque: 2 },
  { nome: 'camisa', categoria: 'roupa', caixas: [CAIXA_PEQUENA], destaque: 3 },
]

async function abrirComInventario() {
  const planos = [{ ...DECUPAGEM.planos[0], inventario: INVENTARIO }, DECUPAGEM.planos[1]]
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json({ ...DECUPAGEM, planos })),
    http.get('/v1/jobs/j1/quadros/:arquivo', ({ params }) =>
      HttpResponse.json({ url: `https://quadros.test/${params.arquivo}`, expira_em: '2999-01-01T00:00:00Z' }),
    ),
  )
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(aba(/^Planos/))
  return usuario
}

test('o plano mostra só os objetos de destaque e o "ver todos" abre o inventário por categoria', async () => {
  const usuario = await abrirComInventario()

  const destaque = within(painel()).getByRole('group', { name: 'Objetos de destaque do plano Estúdio' })
  expect(within(destaque).getAllByRole('button').map((b) => b.textContent)).toEqual([
    'carro azul (azul · BYD)',
    'camisa',
  ])
  expect(within(painel()).queryByText('caneca')).toBeNull()

  await usuario.click(within(painel()).getByRole('button', { name: 'Ver todos os objetos do plano (4)' }))

  const titulos = within(painel()).getAllByRole('heading', { level: 4 }).map((h) => h.textContent)
  expect(titulos).toEqual(['roupa', 'utensílio', 'veículo'])
  const roupas = within(painel()).getByRole('region', { name: 'roupa do plano Estúdio' })
  // O destaque maior vem primeiro dentro da categoria.
  expect(within(roupas).getAllByRole('button').map((b) => b.textContent)).toEqual(['camisa', 'blazer preto'])
  expect(within(painel()).getByText('caneca')).toBeTruthy()
})

test('o plano sem inventário não tem o "ver todos"', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(aba(/^Planos/))

  expect(within(painel()).getByText('Estúdio')).toBeTruthy()
  expect(within(painel()).queryByRole('button', { name: /Ver todos os objetos/ })).toBeNull()
})

test('passar o mouse num objeto mostra o quadro com a caixa, e sair volta ao vídeo', async () => {
  const usuario = await abrirComInventario()

  await usuario.hover(within(painel()).getByRole('button', { name: /^carro azul/ }))

  const quadro = await screen.findByRole('img', { name: 'Quadro com a caixa de carro azul' })
  // A maior caixa: a do segundo quadro.
  expect(quadro.querySelector('image')?.getAttribute('href')).toBe('https://quadros.test/plano-0-1.jpg')
  const caixa = quadro.querySelector('rect')!
  const altura = 1000 / (16 / 9)
  expect(Number(caixa.getAttribute('x'))).toBeCloseTo(100)
  expect(Number(caixa.getAttribute('y'))).toBeCloseTo(0.2 * altura)
  expect(Number(caixa.getAttribute('width'))).toBeCloseTo(300)
  expect(Number(caixa.getAttribute('height'))).toBeCloseTo(0.4 * altura)
  expect(screen.getByLabelText('Player')).toBeTruthy()

  await usuario.unhover(within(painel()).getByRole('button', { name: /^carro azul/ }))
  expect(screen.queryByRole('img', { name: /Quadro com a caixa/ })).toBeNull()
})

test('focar num objeto mostra o quadro com a caixa, e tirar o foco volta ao vídeo', async () => {
  await abrirComInventario()

  const objeto = within(painel()).getByRole('button', { name: 'camisa' })
  act(() => objeto.focus())
  expect(await screen.findByRole('img', { name: 'Quadro com a caixa de camisa' })).toBeTruthy()

  act(() => objeto.blur())
  expect(screen.queryByRole('img', { name: /Quadro com a caixa/ })).toBeNull()
})

test('o objeto que some apontado (a lista fechada) não deixa o quadro sobre o player', async () => {
  const usuario = await abrirComInventario()
  await usuario.click(within(painel()).getByRole('button', { name: 'Ver todos os objetos do plano (4)' }))

  act(() => within(painel()).getByRole('button', { name: 'caneca' }).focus())
  expect(await screen.findByRole('img', { name: 'Quadro com a caixa de caneca' })).toBeTruthy()

  // Clique sem mover o foco, como um atalho de teclado: o botão some sem blur.
  fireEvent.click(within(painel()).getByRole('button', { name: 'Ocultar os objetos do plano' }))
  expect(within(painel()).queryByText('caneca')).toBeNull()
  expect(screen.queryByRole('img', { name: /Quadro com a caixa/ })).toBeNull()
})

async function abrirObjetosComInventario() {
  // O mesmo carro em outro plano: um item só, com os dois planos.
  const planos = [
    { ...DECUPAGEM.planos[0], inventario: INVENTARIO },
    { ...DECUPAGEM.planos[1], inventario: [INVENTARIO[1]] },
  ]
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json({ ...DECUPAGEM, planos })),
    http.get('/v1/jobs/j1/quadros/:arquivo', ({ params }) =>
      HttpResponse.json({ url: `https://quadros.test/${params.arquivo}`, expira_em: '2999-01-01T00:00:00Z' }),
    ),
  )
  const usuario = userEvent.setup()
  const player = await abrir()
  await usuario.click(aba('Objetos 6'))
  return { usuario, player }
}

test('a aba Objetos lista o inventário dos planos por categoria, sem repetir, e a contagem o inclui', async () => {
  await abrirObjetosComInventario()

  const veiculos = within(painel()).getByRole('region', { name: 'veículo do vídeo' })
  expect(within(veiculos).getAllByRole('button').map((b) => b.textContent)).toEqual(['carro azul (azul · BYD)2 planos'])
  const roupas = within(painel()).getByRole('region', { name: 'roupa do vídeo' })
  expect(within(roupas).getAllByRole('button').map((b) => b.textContent)).toEqual(['blazer preto1 plano', 'camisa1 plano'])
  // Os objetos ligados às pessoas continuam como estão.
  expect(within(painel()).getByRole('button', { name: /^sandália, 2 ocorrências/ })).toBeTruthy()
})

test('apontar um objeto do inventário na aba Objetos mostra a caixa, e clicar leva o player ao plano', async () => {
  const { usuario, player } = await abrirObjetosComInventario()

  const carro = within(painel()).getByRole('button', { name: /^carro azul/ })
  await usuario.hover(carro)
  const quadro = await screen.findByRole('img', { name: 'Quadro com a caixa de carro azul' })
  expect(quadro.querySelector('image')?.getAttribute('href')).toBe('https://quadros.test/plano-0-1.jpg')
  await usuario.unhover(carro)
  expect(screen.queryByRole('img', { name: /Quadro com a caixa/ })).toBeNull()

  await usuario.click(carro)
  expect(player.currentTime).toBe(200)
})
