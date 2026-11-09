import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { abrirVideo, irPara, medir, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade da linha do tempo com o Visualizador.test.tsx e o Painel.test.tsx da interface antiga.

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
  comerciais: [{ marca: 'Ultrafarma', tipo: 'merchandising', inicio_ms: 225_000, fim_ms: 240_000 }],
  transcricao: [{ locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [],
}

let decupagem: object = DECUPAGEM
const servidor = setupServer(...rotasDoVideo(() => ({}), () => decupagem))
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  decupagem = DECUPAGEM
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const faixa = (nome: string) => screen.getByRole('group', { name: nome })
const chip = (nome: RegExp) => within(screen.getByRole('group', { name: 'Faixas da linha do tempo' })).getByRole('button', { name: nome })

test('os seletores de Textos e Falas podem quebrar linha sem rolagem horizontal', async () => {
  await abrirVideo()

  const seletores = screen.getByRole('group', { name: 'Faixas da linha do tempo' })
  for (const nome of [/^Textos,/, /^Falas,/]) expect(seletores.contains(chip(nome))).toBe(true)
  // O jsdom não mede layout: a barra precisa crescer quando os sete seletores não cabem.
  expect(seletores.classList.contains('flex-wrap')).toBe(true)
  expect(seletores.classList.contains('overflow-x-auto')).toBe(false)
  expect(seletores.classList.contains('h-9')).toBe(false)
})

test('os sete chips trazem a contagem; ligam e desligam a faixa; a régua tem os cortes', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()

  for (const nome of ['Pautas, 3', 'Pessoas, 2', 'Menções, 1', 'Objetos, 0', 'Comerciais, 1', 'Textos, 0', 'Falas, 1']) {
    expect(chip(new RegExp(`^${nome}$`))).toBeTruthy()
  }
  for (const nome of ['Pautas 3', 'Pessoas 2', 'Comerciais 1', 'Textos 0', 'Falas 1']) expect(faixa(nome)).toBeTruthy()
  // Menções e objetos começam desligados, como no protótipo; os planos nunca são faixa.
  expect(screen.queryByRole('group', { name: 'Menções 1' })).toBeNull()
  expect(screen.queryByRole('group', { name: /Planos/ })).toBeNull()
  expect(document.querySelector('[data-cortes]')?.getAttribute('data-cortes')).toBe('2')

  await usuario.click(chip(/^Menções/))
  expect(chip(/^Menções/).getAttribute('aria-pressed')).toBe('true')
  expect(faixa('Menções 1')).toBeTruthy()
  await usuario.click(chip(/^Pautas/))
  expect(screen.queryByRole('group', { name: 'Pautas 3' })).toBeNull()
})

test('a faixa sem objetos diz por quê', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()
  await usuario.click(chip(/^Objetos/))

  expect(within(faixa('Objetos 0')).getByText('Este vídeo não tem objetos decupados.')).toBeTruthy()
})

test('o trecho sem pauta aparece hachurado com a dica', async () => {
  await abrirVideo()

  expect(screen.getByRole('img', { name: 'Sem decupagem, 44:20–49:19' }).getAttribute('title')).toBe('Sem decupagem, 44:20–49:19')
})

test('cada faixa tem uma parada de Tab só, com o nome do bloco; a faixa vazia também é parada', async () => {
  await abrirVideo()

  const paradas = faixa('Pessoas 2').querySelectorAll('button:not([tabindex="-1"]), [tabindex="0"]')
  expect(paradas.length).toBe(1)
  expect(within(faixa('Pessoas 2')).getByRole('button').getAttribute('aria-label')).toBe('Aparição de Leão Lobo, 03:31 a 04:21')
  expect(within(faixa('Pautas 3')).getByRole('button').getAttribute('aria-label')).toBe('Pauta: Eleição, 00:00 a 12:04')
  expect(faixa('Textos 0').tabIndex).toBe(0)
  expect(faixa('Pessoas 2').hasAttribute('tabindex')).toBe(false)
})

test('com o foco numa faixa, ← e → passam de bloco e Enter salta e seleciona; o player não anda', async () => {
  const usuario = userEvent.setup()
  const player = await abrirVideo()
  irPara(player, 20)

  const bloco = within(faixa('Pessoas 2')).getByRole('button')
  bloco.focus()
  await usuario.keyboard('{ArrowRight}')

  expect(document.activeElement).toBe(within(faixa('Pessoas 2')).getByRole('button', { name: 'Aparição de Leão Lobo, 05:00 a 05:20' }))
  expect(player.currentTime).toBe(20)
  await usuario.keyboard('{Enter}')
  expect(player.currentTime).toBe(300)
  expect(within(faixa('Pessoas 2')).getByRole('button').getAttribute('aria-pressed')).toBe('true')
  await usuario.keyboard('{ArrowLeft}')
  expect((document.activeElement as HTMLElement).getAttribute('aria-label')).toBe('Aparição de Leão Lobo, 03:31 a 04:21')
})

test('clicar num bloco salta o player ao início, seleciona e abre o detalhe na seção do tipo', async () => {
  const player = await abrirVideo()
  const pautas = faixa('Pautas 3')
  medir(pautas)

  // 800 ms de 2959 s depois do x = 100: 13:00, dentro da pauta dos bastidores.
  fireEvent.pointerDown(pautas, { clientX: 100 + (780 / 2959) * 1000, pointerId: 1 })

  expect(player.currentTime).toBe(724)
  expect(within(pautas).getByRole('button').getAttribute('aria-label')).toBe('Pauta: Bastidores do Miss Bumbum, 12:04 a 15:40')
  expect(within(pautas).getByRole('button').getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('region', { name: 'Detalhe: Bastidores do Miss Bumbum' })).toBeTruthy()
})

test('com aparições sobrepostas, o clique no bloco ativo abre a que está sob o ponteiro, como a dica', async () => {
  decupagem = {
    ...DECUPAGEM,
    pessoas: [
      { id: 'pA', nome: 'Ana Longa', na_imagem: [{ inicio_ms: 0, fim_ms: 60_000, evidencia: 'rosto' }], citada_na_fala: [], citada_no_texto: [] },
      { id: 'pB', nome: 'Bia Curta', na_imagem: [{ inicio_ms: 20_000, fim_ms: 30_000, evidencia: 'rosto' }], citada_na_fala: [], citada_no_texto: [] },
    ],
  }
  const player = await abrirVideo()
  const pessoas = faixa('Pessoas 2')
  medir(pessoas)
  const x = (s: number) => 100 + (s / 2959) * 1000

  // Em 50 s só há a Ana: o bloco ativo passa a ser o dela, de 0 a 60 s, e cobre o da Bia.
  fireEvent.pointerDown(pessoas, { clientX: x(50), pointerId: 1 })
  const ativo = within(pessoas).getByRole('button')
  expect(ativo.getAttribute('aria-label')).toBe('Aparição de Ana Longa, 00:00 a 01:00')

  fireEvent.pointerMove(ativo, { clientX: x(25) })
  expect(screen.getByRole('tooltip').textContent).toBe('Aparição de Bia Curta, 00:20 a 00:30')
  fireEvent.pointerDown(ativo, { clientX: x(25), pointerId: 1 })
  fireEvent.click(ativo, { clientX: x(25), detail: 1 })

  expect(player.currentTime).toBe(20)
  expect(within(pessoas).getByRole('button').getAttribute('aria-label')).toBe('Aparição de Bia Curta, 00:20 a 00:30')
  expect(within(pessoas).getByRole('button').getAttribute('aria-pressed')).toBe('true')
})

test('clicar fora dos blocos salta o player ao ponteiro, sem selecionar', async () => {
  const player = await abrirVideo()
  const comerciais = faixa('Comerciais 1')
  medir(comerciais)

  fireEvent.pointerDown(comerciais, { clientX: 600, pointerId: 1 })

  expect(player.currentTime).toBeCloseTo(2959 / 2, 1)
  expect(within(comerciais).getByRole('button').getAttribute('aria-pressed')).toBe('false')
})

test('o botão direito e o do meio não saltam nem selecionam, na faixa e na régua', async () => {
  const player = await abrirVideo()
  const pautas = faixa('Pautas 3')
  medir(pautas)
  const regua = document.querySelector('[data-regua]') as HTMLElement
  medir(regua)
  const antes = player.currentTime

  fireEvent.pointerDown(pautas, { clientX: 100 + (780 / 2959) * 1000, pointerId: 1, button: 2 })
  fireEvent.pointerDown(regua, { clientX: 600, pointerId: 1, button: 1 })

  expect(player.currentTime).toBe(antes)
  expect(within(pautas).getByRole('button').getAttribute('aria-pressed')).toBe('false')
})

test('clicar e arrastar na régua salta o player ao tempo do ponteiro', async () => {
  const player = await abrirVideo()
  const regua = document.querySelector('[data-regua]') as HTMLElement
  medir(regua)

  fireEvent.pointerDown(regua, { clientX: 600, pointerId: 1 })
  expect(player.currentTime).toBeCloseTo(2959 / 2, 1)
  fireEvent.pointerMove(regua, { clientX: 350, pointerId: 1 })
  expect(player.currentTime).toBeCloseTo(2959 / 4, 1)
})

test('passar o ponteiro num bloco mostra o nome dele numa dica', async () => {
  await abrirVideo()
  const comerciais = faixa('Comerciais 1')
  medir(comerciais)

  fireEvent.pointerMove(comerciais, { clientX: 100 + (230 / 2959) * 1000 })
  expect(screen.getByRole('tooltip').textContent).toBe('Comercial: Ultrafarma, 03:45 a 04:00')
  fireEvent.pointerLeave(comerciais)
  expect(screen.queryByRole('tooltip')).toBeNull()
})

test('a régua termina com o rótulo do fim do vídeo, e o cursor acompanha o tempo', async () => {
  const player = await abrirVideo()

  expect(screen.getByText('49:19')).toBeTruthy()
  irPara(player, 2959 / 4)
  expect((document.querySelector('[data-cursor]') as HTMLElement).style.left).toBe('25%')
})

test('as teclas da faixa aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()

  await usuario.keyboard('?')

  const dialogo = await screen.findByRole('dialog', { name: /Atalhos/ })
  const grupo = within(dialogo).getByRole('region', { name: 'Linha do tempo' })
  expect([...grupo.querySelectorAll('dd')].map((d) => d.textContent)).toEqual(['←→', 'Enter'])
})

test('milhares de ocorrências viram um path por faixa, sem um elemento por bloco', async () => {
  const falas = Array.from({ length: 3000 }, (_, i) => ({ locutor: 'Ana', texto: `fala ${i}`, inicio_ms: i * 900, fim_ms: i * 900 + 800 }))
  decupagem = { ...DECUPAGEM, transcricao: falas }
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagem)))
  await abrirVideo()

  const falasNaFaixa = faixa('Falas 3000')
  expect(falasNaFaixa.querySelectorAll('*').length).toBeLessThan(10)
  expect(falasNaFaixa.querySelector('path')?.getAttribute('d')?.match(/M/g)?.length).toBe(3000)
})
