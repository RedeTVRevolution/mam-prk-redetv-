import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { DECUPAGEM } from './curadoria-teste.ts'

// A paridade de "Comparar com" (comparação de passadas, só leitura) com o ComparacaoDePassadas.test.tsx
// da interface antiga.

const item = (identidade: string, inicio_ms: number, marca: string, motivos: string[] = [], detalhe: string | null = null) => ({
  identidade,
  inicio_ms,
  fim_ms: inicio_ms + 10_000,
  detalhe,
  marca,
  motivos,
})

const LADO = { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 100, etapas: [] }
const COMPARACAO = {
  passada_id: 'p1',
  modelo: 'gemini-3.8-flash',
  modelo_do_job: 'gemini-3.5-flash-lite',
  duracao_ms: 3_600_000,
  // O Job não guarda os tokens: a API devolve o custo dele como `null`.
  a: { ...LADO, tempo_total_s: 125 },
  b: { ...LADO, custo_usd: 3, custo_por_hora_usd: 3, tempo_total_s: 35 },
  requisitos: [
    { nome: 'famosos', a: [], b: [] },
    { nome: 'mencoes', a: [], b: [] },
    {
      nome: 'pautas',
      a: [item('Chuva', 0, 'igual'), item('Trânsito', 20_000, 'difere', ['tempo']), item('Clima', 60_000, 'so_aqui')],
      b: [item('Chuva', 0, 'igual'), item('Trânsito', 80_000, 'difere', ['tempo']), item('Política', 300_000, 'so_aqui')],
    },
    { nome: 'broll_limpos', a: [], b: [] },
    { nome: 'broll_descricoes', a: [], b: [] },
    { nome: 'comerciais', a: [], b: [] },
  ],
}
const PASSADAS = [{ id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] }]

let pedidosDasPassadas = 0
let passadas: unknown[] | 'proibido' = PASSADAS
let comparacao: () => Response = () => HttpResponse.json(COMPARACAO)

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 3600, cortes_ms: [] }),
    () => DECUPAGEM,
  ),
  http.get('/v1/jobs/j1/passadas', () => {
    pedidosDasPassadas += 1
    return passadas === 'proibido' ? new HttpResponse(null, { status: 403 }) : HttpResponse.json(passadas)
  }),
  http.get('/v1/jobs/j1/passadas/p1/comparacao', () => comparacao()),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  pedidosDasPassadas = 0
  passadas = PASSADAS
  comparacao = () => HttpResponse.json(COMPARACAO)
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function compararComPassada() {
  const player = await abrirVideo()
  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Comparar com' }), 'p1')
  return {
    player,
    job: await screen.findByRole('region', { name: 'Decupagem do Job' }),
    passada: await screen.findByRole('region', { name: 'Decupagem da passada' }),
  }
}

test('o seletor lista as passadas pelo modelo e pela data', async () => {
  await abrirVideo()

  expect(await screen.findByRole('option', { name: /gemini-3\.8-flash.*02\/11\/2026/ })).toBeTruthy()
})

test('a lista de passadas é pedida uma vez só, não a cada render', async () => {
  await abrirVideo()
  await screen.findByRole('combobox', { name: 'Comparar com' })
  await new Promise((r) => setTimeout(r, 100))

  expect(pedidosDasPassadas).toBe(1)
})

test('o tempo de um item depois de uma hora tem as horas', async () => {
  comparacao = () => HttpResponse.json({ ...COMPARACAO, requisitos: [{ nome: 'pautas', a: [item('Fim', 4_512_000, 'so_aqui')], b: [] }] })
  const { job } = await compararComPassada()

  expect(within(job).getByText('1:15:12')).toBeTruthy()
})

test('sem passada, a tela fica como sempre', async () => {
  passadas = []
  await abrirVideo()
  await waitFor(() => expect(pedidosDasPassadas).toBe(1))

  expect(screen.queryByLabelText('Comparar com')).toBeNull()
})

test('sem permissão de ver as passadas, o seletor não aparece', async () => {
  passadas = 'proibido'
  await abrirVideo()
  await waitFor(() => expect(pedidosDasPassadas).toBe(1))

  expect(screen.queryByLabelText('Comparar com')).toBeNull()
})

test('as duas decupagens ficam lado a lado, por requisito', async () => {
  const { job, passada } = await compararComPassada()

  expect(within(job).getByText('Clima')).toBeTruthy()
  expect(within(job).queryByText('Política')).toBeNull()
  expect(within(passada).getByText('Política')).toBeTruthy()
  expect(within(job).getByText('Pautas')).toBeTruthy()
  expect(within(passada).getByText('Pautas')).toBeTruthy()
})

test('o custo por hora e o tempo de cada lado ficam no topo', async () => {
  await compararComPassada()

  const topo = screen.getByRole('region', { name: 'Custo e tempo' })
  expect(within(topo).getByText(/Job/).parentElement?.textContent).toContain('n/d')
  expect(topo.textContent).toContain('US$ 3,00 por hora')
  expect(topo.textContent).toContain('02:05')
  expect(topo.textContent).toContain('00:35')
})

test('o item que só um lado tem e o que difere ficam marcados, com palavras', async () => {
  const { job, passada } = await compararComPassada()

  expect(within(within(job).getByRole('button', { name: /Clima/ })).getByText('só neste lado')).toBeTruthy()
  expect(within(within(passada).getByRole('button', { name: /Política/ })).getByText('só neste lado')).toBeTruthy()
  expect(within(within(job).getByRole('button', { name: /Trânsito/ })).getByText('difere: tempo')).toBeTruthy()
  expect(within(within(job).getByRole('button', { name: /Chuva/ })).queryByText(/difere|só neste/)).toBeNull()
})

test('clicar num item de qualquer lado leva o player ao início dele', async () => {
  const { player, job, passada } = await compararComPassada()

  fireEvent.click(within(passada).getByRole('button', { name: /Política/ }))
  expect(player.currentTime).toBe(300)

  fireEvent.click(within(job).getByRole('button', { name: /Clima/ }))
  expect(player.currentTime).toBe(60)
})

test('a passada não tem como ser corrigida nesta tela', async () => {
  const { passada } = await compararComPassada()

  expect(within(passada).queryByRole('button', { name: /corrigir|remover|editar/i })).toBeNull()
})

test('a comparação toma o lugar do inspetor; "Fechar a comparação" o devolve', async () => {
  const { player } = await compararComPassada()
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()
  expect(player).toBeTruthy()

  await userEvent.click(screen.getByRole('button', { name: 'Fechar a comparação' }))

  expect(screen.getByRole('complementary', { name: 'Inspetor' })).toBeTruthy()
  expect((screen.getByRole('combobox', { name: 'Comparar com' }) as HTMLSelectElement).value).toBe('')
})

test('"Fechar a comparação" devolve o foco ao seletor "Comparar com"', async () => {
  await compararComPassada()

  await userEvent.click(screen.getByRole('button', { name: 'Fechar a comparação' }))

  expect(document.activeElement).toBe(screen.getByRole('combobox', { name: 'Comparar com' }))
})

test('a falha ao carregar a comparação mostra o código e "Tentar de novo"', async () => {
  comparacao = () => new HttpResponse(null, { status: 500 })
  await abrirVideo()
  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Comparar com' }), 'p1')

  const alerta = await screen.findByRole('alert')
  expect(alerta.textContent).toContain('Não foi possível carregar a comparação')
  comparacao = () => HttpResponse.json(COMPARACAO)
  await userEvent.click(within(alerta).getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByRole('region', { name: 'Decupagem da passada' })).toBeTruthy()
})

test('uma lista longa mostra 30 itens por lado, e "Mostrar mais" acrescenta o resto', async () => {
  const muitos = Array.from({ length: 40 }, (_, i) => item(`Item ${i}`, i * 20_000, 'igual'))
  comparacao = () => HttpResponse.json({ ...COMPARACAO, requisitos: [{ nome: 'pautas', a: muitos, b: [] }] })
  const { job } = await compararComPassada()

  expect(within(job).getAllByRole('button', { name: /^Job: Item/ })).toHaveLength(30)
  await userEvent.click(within(job).getByRole('button', { name: 'Mostrar mais 10' }))

  expect(within(job).getAllByRole('button', { name: /^Job: Item/ })).toHaveLength(40)
  expect(within(job).queryByRole('button', { name: /^Mostrar mais/ })).toBeNull()
})

test('de 1024 a 1279 px a comparação abre embaixo do vídeo e de 1280 px em diante ao lado', async () => {
  const { player } = await compararComPassada()

  const comparacao = screen.getByRole('complementary', { name: 'Comparação com a passada' })
  const coluna = comparacao.parentElement!
  // O jsdom não aplica CSS: confere-se a regra dos breakpoints. A coluna só vira linha em `xl`.
  expect(coluna.className).toContain('xl:flex-row')
  expect(coluna.className).not.toMatch(/(^|\s)lg:flex-row/)
  expect(comparacao.className).toContain('lg:h-[45%]')
  expect(comparacao.className).toContain('xl:w-[62%]')
  expect(comparacao.className).not.toContain('lg:w-[62%]')
  // O vídeo e o cabeçalho ficam na coluna do vídeo, que a comparação não cobre.
  const video = screen.getByRole('region', { name: 'Vídeo' })
  expect(video.contains(comparacao)).toBe(false)
  expect(video.contains(player)).toBe(true)
})

test('sem a comparação, a coluna do vídeo e o inspetor ficam lado a lado a partir de 1024 px', async () => {
  await abrirVideo()

  const video = screen.getByRole('region', { name: 'Vídeo' })
  expect(video.parentElement!.className).toMatch(/(^|\s)lg:flex-row/)
})
