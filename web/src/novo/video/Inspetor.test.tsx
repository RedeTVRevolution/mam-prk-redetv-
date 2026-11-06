import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { type ItemDoPainel, itensPorTipo } from '../../painel.ts'
import { abrirVideo, irPara, pauseMock, playMock, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade do inspetor com o Painel.test.tsx e o Miniaturas.test.tsx da interface atual.

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
        { inicio_ms: 211_000, fim_ms: 261_000, evidencia: 'rosto', papel: 'colunista', visual: 'terno preto', quadro: 'quadros/aparicao-0-0.jpg' },
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
      quadro: 'quadros/objeto-0.jpg',
      ocorrencias: [
        { inicio_ms: 214_000, fim_ms: 230_000 },
        { inicio_ms: 500_000, fim_ms: 510_000 },
      ],
    },
    { id: 'o2', categoria: 'em_cena', tipo: 'troféu', cor_base: ['dourado', 'preto'], ocorrencias: [{ inicio_ms: 214_000, fim_ms: 220_000 }] },
  ],
}

const VAZIA = { ...DECUPAGEM, pautas: [], pessoas: [], planos: [], comerciais: [], transcricao: [], textos_na_tela: [], objetos: [] }

let decupagem: object = DECUPAGEM
const quadrosPedidos: string[] = []
const servidor = setupServer(
  ...rotasDoVideo(() => ({ timecode_origem: null, taxa_de_quadros: null, cortes_ms: [] }), () => decupagem),
  http.get('/v1/jobs/j1/quadros/:arquivo', ({ params }) => {
    quadrosPedidos.push(String(params.arquivo))
    return HttpResponse.json({ url: `https://exemplo.test/${String(params.arquivo)}`, expira_em: '2999-01-01T00:00:00Z' })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  decupagem = DECUPAGEM
  quadrosPedidos.length = 0
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const inspetor = () => within(screen.getByRole('complementary', { name: 'Inspetor' }))
const agora = () => within(screen.getByRole('region', { name: 'Agora no vídeo' }))
const secao = (nome: RegExp) => inspetor().getByRole('button', { name: nome })
const lista = (nome: string) => within(inspetor().getByRole('region', { name: nome }))
const detalhe = () => within(inspetor().getByRole('region', { name: /^Detalhe:/ }))
/** Os itens selecionados na lista (o "seguir" também é um botão pressionado). */
const itensPressionados = (nome: string) => lista(nome).queryAllByRole('button', { pressed: true }).filter((b) => b.hasAttribute('data-item'))
const bloco = (faixa: string) => within(screen.getByRole('group', { name: faixa })).getByRole('button')

async function abrirSecao(nome: string) {
  const usuario = userEvent.setup()
  const botao = inspetor().getByRole('button', { name: new RegExp(`^${nome} \\d+$`) })
  if (botao.getAttribute('aria-expanded') !== 'true') await usuario.click(botao)
  return usuario
}

test('as seções trazem a contagem ao lado do nome, e Pessoas começa aberta', async () => {
  await abrirVideo()

  for (const nome of ['Pessoas 2', 'Pautas 3', 'Objetos 2', 'Comerciais 1', 'Textos na tela 1', 'Menções 1', 'Falas 2']) {
    expect(secao(new RegExp(`^${nome}$`))).toBeTruthy()
  }
  expect(secao(/^Pessoas 2$/).getAttribute('aria-expanded')).toBe('true')
  expect(secao(/^Pautas 3$/).getAttribute('aria-expanded')).toBe('false')
})

test('o Agora acompanha o vídeo: pauta, plano, pessoas, menções, objetos, comerciais, textos e fala', async () => {
  const player = await abrirVideo()
  irPara(player, 100)
  expect(agora().getByText('01:40')).toBeTruthy()
  expect(agora().getByRole('button', { name: 'Eleição · informativo' })).toBeTruthy()
  expect(agora().getByText('Ninguém na imagem')).toBeTruthy()
  expect(agora().getByText('Sem fala')).toBeTruthy()

  irPara(player, 232)
  expect(agora().getByText('03:52')).toBeTruthy()
  expect(agora().getByText('Estúdio, apresentadora em pé')).toBeTruthy()
  expect(agora().getByRole('button', { name: 'Leão Lobo' })).toBeTruthy()
  expect(agora().getByRole('button', { name: 'não identificado' })).toBeTruthy()
  expect(agora().getByRole('button', { name: 'Felipe Camargo' })).toBeTruthy()
  expect(agora().getByRole('button', { name: 'Ultrafarma merchandising' })).toBeTruthy()
  expect(agora().getByRole('button', { name: /LEÃO LOBO · colunista/ })).toBeTruthy()
  expect(agora().getByRole('button', { name: /Obrigado, Ana/ })).toBeTruthy()

  irPara(player, 727)
  expect(agora().getByRole('button', { name: 'Bastidores do Miss Bumbum · leve' })).toBeTruthy()
  expect(agora().getByText('Externa')).toBeTruthy()
})

test('trecho sem pauta no Agora diz "Sem decupagem"', async () => {
  irPara(await abrirVideo(), 2_700)

  expect(agora().getByText('Sem decupagem (44:20–49:19)')).toBeTruthy()
})

test('o Agora mostra os objetos com a cor em palavras, e clicar abre o detalhe sem saltar o player', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 215)

  await usuario.click(agora().getByRole('button', { name: /^sandália/ }))

  expect(player.currentTime).toBe(215)
  expect(detalhe().getByText('vermelho vivo')).toBeTruthy()
  expect(detalhe().getByText('calçado')).toBeTruthy()
  expect(detalhe().getByText('marca Arezzo')).toBeTruthy()
  expect(detalhe().getByText('salto alto')).toBeTruthy()
  expect(detalhe().getByText((_, el) => el?.tagName === 'P' && el.textContent === 'Leão Lobo calça')).toBeTruthy()
})

test('clicar no dono do objeto abre a pessoa', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 215)
  await usuario.click(agora().getByRole('button', { name: /^sandália/ }))

  await usuario.click(detalhe().getByRole('button', { name: 'Leão Lobo' }))

  expect(detalhe().getByRole('heading', { name: 'Leão Lobo' })).toBeTruthy()
  expect(player.currentTime).toBe(211)
  expect(bloco('Pessoas 3').getAttribute('aria-pressed')).toBe('true')
})

test('o item atual tem aria-current e a barra; nenhum fundo é vermelho', async () => {
  const player = await abrirVideo()
  irPara(player, 800)
  await abrirSecao('Pautas')

  const atual = lista('Pautas').getByRole('button', { name: /Bastidores do Miss Bumbum/ }).closest('[data-chave]') as HTMLElement
  expect(atual.getAttribute('aria-current')).toBe('true')
  expect(atual.className).toContain('before:w-[3px]')
  expect(lista('Pautas').getByRole('button', { name: /^Eleição/ }).closest('[data-chave]')?.getAttribute('aria-current')).toBeNull()
  for (const el of screen.getByRole('complementary', { name: 'Inspetor' }).querySelectorAll('*')) {
    expect(String(el.getAttribute('class'))).not.toMatch(/bg-(destructive|marca|red)/)
  }
})

test('clicar num item salta o player, seleciona o bloco na linha do tempo, abre o detalhe e não rola a página', async () => {
  const vista = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
  const rolar = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  const player = await abrirVideo()
  const usuario = await abrirSecao('Pautas')

  await usuario.click(lista('Pautas').getByRole('button', { name: /Bastidores do Miss Bumbum/ }))

  expect(player.currentTime).toBe(724)
  expect(bloco('Pautas 3').getAttribute('aria-label')).toBe('Pauta: Bastidores do Miss Bumbum, 12:04 a 15:40')
  expect(bloco('Pautas 3').getAttribute('aria-pressed')).toBe('true')
  expect(detalhe().getByRole('heading', { name: 'Bastidores do Miss Bumbum' })).toBeTruthy()
  expect(vista).not.toHaveBeenCalled()
  expect(rolar).not.toHaveBeenCalled()
})

test('Esc e "Voltar à lista" voltam do detalhe à lista com o item selecionado', async () => {
  const player = await abrirVideo()
  const usuario = await abrirSecao('Comerciais')
  await usuario.click(lista('Comerciais').getByRole('button', { name: /Ultrafarma/ }))
  expect(detalhe()).toBeTruthy()

  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('{Escape}')
  expect(inspetor().queryByRole('region', { name: /^Detalhe:/ })).toBeNull()
  expect(lista('Comerciais').getByRole('button', { name: /Ultrafarma/ }).getAttribute('aria-pressed')).toBe('true')

  await usuario.click(lista('Comerciais').getByRole('button', { name: /Ultrafarma/ }))
  await usuario.click(detalhe().getByRole('button', { name: 'Voltar à lista' }))
  expect(inspetor().queryByRole('region', { name: /^Detalhe:/ })).toBeNull()
  expect(player.currentTime).toBe(225)
})

test('Ctrl+→ e Ctrl+← trocam de seção; o player não anda', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 20)

  await usuario.keyboard('{Control>}{ArrowRight}{/Control}')
  expect(secao(/^Pautas 3$/).getAttribute('aria-expanded')).toBe('true')
  await usuario.keyboard('{Control>}{ArrowRight}{/Control}')
  expect(secao(/^Objetos 2$/).getAttribute('aria-expanded')).toBe('true')
  await usuario.keyboard('{Control>}{ArrowLeft}{/Control}')
  expect(secao(/^Pautas 3$/).getAttribute('aria-expanded')).toBe('true')
  expect(player.currentTime).toBe(20)
})

test('↑ e ↓ movem a seleção na seção aberta, a mesma da linha do tempo, e Enter salta o player', async () => {
  const player = await abrirVideo()
  const usuario = await abrirSecao('Pautas')
  ;(document.activeElement as HTMLElement).blur()
  const pressionados = () => itensPressionados('Pautas').map((b) => b.getAttribute('aria-label'))

  await usuario.keyboard('{ArrowDown}')
  expect(pressionados()).toEqual(['Eleição, 00:00 a 12:04'])
  await usuario.keyboard('{ArrowDown}')
  expect(pressionados()).toEqual(['Bastidores do Miss Bumbum, 12:04 a 15:40'])
  await usuario.keyboard('{Enter}')
  expect(player.currentTime).toBe(724)
  await usuario.keyboard('{ArrowUp}{ArrowUp}{ArrowUp}')
  expect(pressionados()).toEqual(['Eleição, 00:00 a 12:04'])
  expect(bloco('Pautas 3').getAttribute('aria-label')).toBe('Pauta: Eleição, 00:00 a 12:04')
  expect(bloco('Pautas 3').getAttribute('aria-pressed')).toBe('true')
})

test('com o detalhe aberto, ↓ passa ao item seguinte no próprio detalhe', async () => {
  await abrirVideo()
  const usuario = await abrirSecao('Pautas')
  await usuario.click(lista('Pautas').getByRole('button', { name: /^Eleição/ }))
  ;(document.activeElement as HTMLElement).blur()

  await usuario.keyboard('{ArrowDown}')

  expect(detalhe().getByRole('heading', { name: 'Bastidores do Miss Bumbum' })).toBeTruthy()
})

test('na seção Pessoas, a pessoa abre as aparições, e ↓ segue a ordem da tela', async () => {
  await abrirVideo()
  const usuario = userEvent.setup()
  const pessoas = lista('Pessoas')
  const leao = pessoas.getByRole('button', { name: 'Leão Lobo, 2 aparições' })
  expect(leao.getAttribute('aria-expanded')).toBe('false')
  expect(pessoas.queryByRole('button', { name: /^Leão Lobo, 03:31/ })).toBeNull()

  await usuario.click(leao)
  await usuario.click(pessoas.getByRole('button', { name: 'não identificado, 1 aparição' }))
  expect(leao.getAttribute('aria-expanded')).toBe('true')
  expect(within(pessoas.getByRole('button', { name: /^Leão Lobo, 03:31 a 04:21/ })).getByText('colunista · terno preto')).toBeTruthy()
  expect(pessoas.getAllByText('mulher loira').length).toBeGreaterThan(0)
  // Quem só foi citado fica em Menções, não é uma pessoa na imagem.
  expect(pessoas.queryByRole('button', { name: /Felipe Camargo/ })).toBeNull()
  ;(document.activeElement as HTMLElement).blur()

  const ordem: string[] = []
  for (let i = 0; i < 3; i++) {
    await usuario.keyboard('{ArrowDown}')
    ordem.push(itensPressionados('Pessoas')[0]?.getAttribute('aria-label') ?? '')
  }
  expect(ordem).toEqual(['Leão Lobo, 03:31 a 04:21', 'Leão Lobo, 05:00 a 05:20', 'não identificado, 03:40 a 04:10'])
})

test('a aparição selecionada na linha do tempo abre a pessoa, que fecha no clique', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()
  bloco('Pessoas 3').focus()
  // 03:31 Leão Lobo, 03:40 não identificado, 05:00 Leão Lobo.
  await usuario.keyboard('{ArrowRight}{ArrowRight}{Enter}')
  await usuario.click(detalhe().getByRole('button', { name: 'Voltar à lista' }))

  const linha = lista('Pessoas').getByRole('button', { name: 'Leão Lobo, 2 aparições' })
  expect(linha.getAttribute('aria-expanded')).toBe('true')
  await usuario.click(linha)
  expect(linha.getAttribute('aria-expanded')).toBe('false')
})

test('as setas não agem com o foco num campo de texto, e o filtro filtra a lista', async () => {
  await abrirVideo()
  const usuario = await abrirSecao('Pautas')
  const filtro = inspetor().getByRole('textbox', { name: 'Filtrar pautas' })
  await usuario.click(filtro)

  await usuario.keyboard('{ArrowDown}')
  expect(itensPressionados('Pautas')).toEqual([])

  await usuario.type(filtro, 'bastidor')
  expect(lista('Pautas').getAllByRole('button', { pressed: false }).map((b) => b.getAttribute('aria-label'))).toEqual([
    'Bastidores do Miss Bumbum, 12:04 a 15:40',
  ])
  await usuario.clear(filtro)
  await usuario.type(filtro, 'xyz')
  expect(lista('Pautas').getByText('Nada com “xyz” em pautas.')).toBeTruthy()
})

test('"Tocar o trecho" toca do início ao fim do item e para sozinho', async () => {
  const player = await abrirVideo()
  const usuario = await abrirSecao('Comerciais')
  await usuario.click(lista('Comerciais').getByRole('button', { name: /Ultrafarma/ }))
  playMock.mockClear()

  await usuario.click(detalhe().getByRole('button', { name: 'Tocar o trecho' }))

  expect(player.currentTime).toBe(225)
  expect(playMock).toHaveBeenCalledTimes(1)
  irPara(player, 235)
  expect(pauseMock).not.toHaveBeenCalled()
  irPara(player, 240.1)
  expect(pauseMock).toHaveBeenCalledTimes(1)
  expect(player.currentTime).toBe(240)
  irPara(player, 300)
  expect(pauseMock).toHaveBeenCalledTimes(1)
})

test('o selo da prova do nome, no detalhe da aparição, salta ao tempo da prova; o não identificado não tem selo', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 222)
  await usuario.click(agora().getByRole('button', { name: 'Leão Lobo' }))

  await usuario.click(detalhe().getByRole('button', { name: 'GC 03:33' }))
  expect(player.currentTime).toBe(213)
  await usuario.click(detalhe().getByRole('button', { name: 'Fala 03:38' }))
  expect(player.currentTime).toBe(218)

  irPara(player, 222)
  await usuario.click(agora().getByRole('button', { name: 'não identificado' }))
  expect(detalhe().queryByRole('button', { name: /GC|Fala/ })).toBeNull()
  expect(detalhe().getByText('mulher loira')).toBeTruthy()
})

test('Pautas, Comerciais e Textos listam o que há com os tempos', async () => {
  await abrirVideo()
  await abrirSecao('Pautas')
  const pauta = lista('Pautas').getByRole('button', { name: /^Eleição/ })
  expect(within(pauta).getByText('informativo')).toBeTruthy()
  expect(within(pauta).getByText('00:00–12:04')).toBeTruthy()
  expect(within(pauta).getByText('O resumo da eleição.')).toBeTruthy()

  await abrirSecao('Comerciais')
  expect(within(lista('Comerciais').getByRole('button', { name: /Ultrafarma/ })).getByText('merchandising')).toBeTruthy()

  await abrirSecao('Textos na tela')
  const texto = lista('Textos na tela').getByRole('button', { name: /LEÃO LOBO/ })
  expect(within(texto).getByText('GC')).toBeTruthy()
  expect(within(texto).getByText('03:33–03:55')).toBeTruthy()
})

test('toda seção vazia diz que está vazia', async () => {
  decupagem = VAZIA
  await abrirVideo()

  const vazios: [string, string][] = [
    ['Pessoas', 'Nenhuma pessoa na imagem neste vídeo.'],
    ['Pautas', 'Nenhuma pauta neste vídeo.'],
    ['Objetos', 'Este vídeo não tem objetos decupados.'],
    ['Comerciais', 'Nenhum comercial neste vídeo.'],
    ['Textos na tela', 'Nenhum texto na tela neste vídeo.'],
    ['Menções', 'Nenhuma menção neste vídeo.'],
    ['Falas', 'Este vídeo não tem transcrição.'],
  ]
  for (const [nome, frase] of vazios) {
    await abrirSecao(nome)
    expect(lista(nome).getByText(frase)).toBeTruthy()
  }
})

test('os atalhos do inspetor aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()

  await usuario.keyboard('?')

  const grupo = within(await screen.findByRole('region', { name: 'Inspetor' }))
  for (const acao of ['No inspetor: mover a seleção na seção aberta', 'No inspetor: trocar de seção', 'No inspetor: voltar do detalhe à lista', 'Recolher e abrir o inspetor']) {
    expect(grupo.getByText(acao)).toBeTruthy()
  }
})

test('] recolhe o inspetor, e de novo o abre', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()

  await usuario.keyboard(']')
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()
  await usuario.keyboard(']')
  expect(screen.getByRole('complementary', { name: 'Inspetor' })).toBeTruthy()
  await usuario.click(inspetor().getByRole('button', { name: 'Recolher o inspetor' }))
  await usuario.click(screen.getByRole('button', { name: 'Abrir o inspetor' }))
  expect(screen.getByRole('complementary', { name: 'Inspetor' })).toBeTruthy()
})

test('Falas: cada fala traz o início, o locutor e o texto; a atual muda com o tempo', async () => {
  const player = await abrirVideo()
  await abrirSecao('Falas')
  irPara(player, 220)

  const fala = (nome: RegExp) => lista('Falas').getByRole('button', { name: nome })
  expect(within(fala(/Boa noite/)).getByText('03:38')).toBeTruthy()
  expect(within(fala(/Boa noite/)).getByText('Ana')).toBeTruthy()
  expect(fala(/Boa noite/).closest('[data-chave]')?.getAttribute('aria-current')).toBe('true')

  irPara(player, 230)
  expect(fala(/Obrigado/).closest('[data-chave]')?.getAttribute('aria-current')).toBe('true')
  expect(fala(/Boa noite/).closest('[data-chave]')?.getAttribute('aria-current')).toBeNull()
})

test('Falas: clicar numa fala salta ao início e seleciona o bloco da faixa Falas', async () => {
  const player = await abrirVideo()
  const usuario = await abrirSecao('Falas')

  await usuario.click(lista('Falas').getByRole('button', { name: /Obrigado, Ana/ }))

  expect(player.currentTime).toBe(224)
  expect(bloco('Falas 2').getAttribute('aria-pressed')).toBe('true')
  expect(bloco('Falas 2').getAttribute('aria-label')).toBe('Fala de Leão: Obrigado, Ana, é um prazer, 03:44 a 05:00')
})

test('Objetos: cada objeto traz as ocorrências, a cor em palavras ao lado do quadradinho, e abre as ocorrências', async () => {
  await abrirVideo()
  const usuario = await abrirSecao('Objetos')
  const objetos = lista('Objetos')

  const sandalia = objetos.getByRole('button', { name: 'sandália, 2 ocorrências' })
  expect(objetos.getByRole('button', { name: 'troféu, 1 ocorrência' })).toBeTruthy()
  expect(within(sandalia).getByText('calçado · de Leão Lobo · marca Arezzo')).toBeTruthy()
  for (const q of objetos.getAllByRole('button').flatMap((b) => [...b.querySelectorAll('[data-cor-base]')])) {
    expect(q.getAttribute('aria-hidden')).toBe('true')
  }
  expect(within(objetos.getByRole('button', { name: 'troféu, 1 ocorrência' })).getByText('dourado e preto')).toBeTruthy()
  expect(objetos.queryByRole('button', { name: 'sandália, 08:20 a 08:30' })).toBeNull()

  await usuario.click(sandalia)
  expect(objetos.getByRole('button', { name: 'sandália, 08:20 a 08:30' })).toBeTruthy()
})

test('o bloco do objeto na faixa leva à seção Objetos com a ocorrência selecionada', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()
  await usuario.click(within(screen.getByRole('group', { name: 'Faixas da linha do tempo' })).getByRole('button', { name: /^Objetos/ }))
  bloco('Objetos 3').focus()
  await usuario.keyboard('{ArrowRight}{ArrowRight}{Enter}')
  await usuario.click(detalhe().getByRole('button', { name: 'Voltar à lista' }))

  expect(secao(/^Objetos 2$/).getAttribute('aria-expanded')).toBe('true')
  expect(lista('Objetos').getByRole('button', { name: 'sandália, 08:20 a 08:30' }).getAttribute('aria-pressed')).toBe('true')
})

test('rolar a lista à mão deixa de seguir a reprodução e mostra "Voltar ao tempo atual"', async () => {
  const player = await abrirVideo()
  const usuario = await abrirSecao('Falas')
  irPara(player, 220)
  const seguir = inspetor().getByRole('button', { name: 'Seguindo a reprodução' })
  expect(seguir.getAttribute('aria-pressed')).toBe('true')

  fireEvent.wheel(lista('Falas').getByRole('list').parentElement as HTMLElement)

  expect(inspetor().getByRole('button', { name: 'Seguir a reprodução' }).getAttribute('aria-pressed')).toBe('false')
  await usuario.click(inspetor().getByRole('button', { name: 'Voltar ao tempo atual' }))
  expect(inspetor().getByRole('button', { name: 'Seguindo a reprodução' })).toBeTruthy()
})

test('as linhas pedem a URL do quadro delas; a sem quadro não pede nada; o detalhe reaproveita a URL', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()
  await usuario.click(lista('Pessoas').getByRole('button', { name: 'Leão Lobo, 2 aparições' }))

  await waitFor(() => expect(quadrosPedidos).toEqual(['aparicao-0-0.jpg']))
  await waitFor(() =>
    expect(lista('Pessoas').getByRole('button', { name: 'Leão Lobo, 2 aparições' }).querySelector('img')?.getAttribute('src')).toBe(
      'https://exemplo.test/aparicao-0-0.jpg',
    ),
  )
  await usuario.click(lista('Pessoas').getByRole('button', { name: /^Leão Lobo, 03:31/ }))
  await waitFor(() => expect(screen.getByRole('region', { name: /^Detalhe:/ }).querySelector('img')).toBeTruthy())
  expect(quadrosPedidos).toEqual(['aparicao-0-0.jpg'])

  await usuario.click(detalhe().getByRole('button', { name: 'Voltar à lista' }))
  await abrirSecao('Objetos')
  await waitFor(() => expect(quadrosPedidos).toContain('objeto-0.jpg'))
})

test('o agrupamento por tipo é linear: 30 mil itens em pouco tempo, cada lista em ordem de tempo', () => {
  const itens = Array.from({ length: 30_000 }, (_, i) => ({ tipo: i % 3 ? 'fala' : 'texto', chave: `x${i}`, inicio_ms: 30_000 - i, fim_ms: 30_001 - i }) as ItemDoPainel)
  const inicio = performance.now()
  const mapa = itensPorTipo(itens)
  // Com a cópia da lista a cada item, eram 1,4 s; linear, uns poucos milissegundos.
  expect(performance.now() - inicio).toBeLessThan(250)
  expect(mapa.get('fala')?.length).toBe(20_000)
  const falas = mapa.get('fala') ?? []
  expect(falas.every((f, i) => i === 0 || falas[i - 1].inicio_ms <= f.inicio_ms)).toBe(true)
})
