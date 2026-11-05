import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { fundoDaCelula } from './escalaDaMatriz.ts'
import { filtrosDeMarcas } from './marcas.ts'
import { render } from './render-teste.tsx'

const RELATORIO = {
  programa: null,
  desde: null,
  ate: null,
  tipo: null,
  marcas: [
    {
      marca: 'Ambev',
      insercoes: 3,
      tempo_ms: 55_000,
      videos: 2,
      por_tipo: [
        { tipo: 'merchan_apresentador', insercoes: 2, tempo_ms: 50_000, videos: 2 },
        { tipo: 'sobreposicao_grafica', insercoes: 1, tempo_ms: 5_000, videos: 1 },
      ],
      lista: [
        { job_id: 'v1', nome: 'tv-fama-01.mp4', tipo: 'merchan_apresentador', inicio_ms: 60_000, fim_ms: 90_000 },
        { job_id: 'v2', nome: null, tipo: 'sobreposicao_grafica', inicio_ms: 0, fim_ms: 5_000 },
      ],
    },
    {
      marca: 'Natura',
      insercoes: 1,
      tempo_ms: 5_000,
      videos: 1,
      por_tipo: [{ tipo: 'intervalo', insercoes: 1, tempo_ms: 5_000, videos: 1 }],
      lista: [{ job_id: 'v1', nome: 'tv-fama-01.mp4', tipo: 'intervalo', inicio_ms: 0, fim_ms: 5_000 }],
    },
  ],
}

const pedidos: URLSearchParams[] = []
let resposta: () => Response = () => HttpResponse.json(RELATORIO)

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.ver'] })),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama', 'Leo Dias'])),
  http.get('/v1/relatorios/marcas', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') {
      return new HttpResponse('marca,tipo\nAmbev,todos\n', { headers: { 'Content-Type': 'text/csv' } })
    }
    return resposta()
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  pedidos.length = 0
  resposta = () => HttpResponse.json(RELATORIO)
  cleanup()
})
afterAll(() => servidor.close())

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(<App autenticador={auth} />)
}

test('a tabela mostra inserções, tempo, vídeos e o detalhe por tipo, na ordem da API', async () => {
  await abrir('/relatorios/marcas')

  const tabela = await screen.findByRole('table', { name: 'Inserções por marca' })

  const linhas = within(tabela).getAllByRole('row').slice(1)
  expect(linhas.map((l) => within(l).getAllByRole('cell').map((c) => c.textContent))).toEqual([
    ['Ambev', '3', '55s', '2', 'Merchan com apresentador: 2 (50s) · Sobreposição gráfica: 1 (5s)'],
    ['Natura', '1', '5s', '1', 'Intervalo: 1 (5s)'],
  ])
})

test('os filtros, o tipo inclusive, vão à API e ao endereço', async () => {
  const usuario = userEvent.setup()
  await abrir('/relatorios/marcas?programa=TV+Fama&de=2026-10-01&ate=2026-10-31&tipo=intervalo')

  await screen.findByRole('table', { name: 'Inserções por marca' })

  expect(pedidos[0].get('programa')).toBe('TV Fama')
  expect(pedidos[0].get('desde')).toBe('2026-10-01')
  expect(pedidos[0].get('ate')).toBe('2026-10-31')
  expect(pedidos[0].get('tipo')).toBe('intervalo')

  fireEvent.change(screen.getByLabelText('Exibido até'), { target: { value: '2026-10-15' } })
  await waitFor(() => expect(pedidos.at(-1)?.get('ate')).toBe('2026-10-15'))
  expect(location.search).toContain('ate=2026-10-15')

  await usuario.click(screen.getByRole('combobox', { name: 'Tipo de inserção' }))
  await usuario.click(await screen.findByRole('option', { name: 'Testemunhal' }))
  await waitFor(() => expect(pedidos.at(-1)?.get('tipo')).toBe('testemunhal'))
  expect(location.search).toContain('tipo=testemunhal')
})

test('clicar numa marca abre a lista das inserções com o vídeo, o tipo e o tempo', async () => {
  const usuario = userEvent.setup()
  await abrir('/relatorios/marcas')

  await usuario.click(await screen.findByRole('button', { name: 'Ambev' }))

  const lista = screen.getByRole('table', { name: 'Inserções de Ambev' })
  const link = within(lista).getByRole('link', { name: 'tv-fama-01.mp4' })
  expect(link.getAttribute('href')).toBe('/video/v1?t=60')
  expect(within(lista).getByText('Merchan com apresentador')).toBeTruthy()
  expect(within(lista).getByText('30s')).toBeTruthy()
  // Sem nome, o vídeo aparece pelo id.
  expect(within(lista).getByRole('link', { name: 'v2' })).toBeTruthy()

  await usuario.click(screen.getByRole('button', { name: 'Ambev' }))
  expect(screen.queryByRole('table', { name: 'Inserções de Ambev' })).toBeNull()
})

test('Baixar CSV pede o formato csv com os mesmos filtros e entrega o arquivo', async () => {
  const usuario = userEvent.setup()
  const criar = vi.fn(() => 'blob:csv')
  Object.assign(URL, { createObjectURL: criar, revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/relatorios/marcas?programa=TV+Fama&tipo=intervalo')
  await screen.findByRole('table', { name: 'Inserções por marca' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  const csv = pedidos.find((p) => p.get('formato') === 'csv')
  expect(csv?.get('programa')).toBe('TV Fama')
  expect(csv?.get('tipo')).toBe('intervalo')
  expect(criar).toHaveBeenCalled()
  clique.mockRestore()
})

test('sem inserção no filtro, a tela diz isso, não oferece o CSV e não há gráfico', async () => {
  resposta = () => HttpResponse.json({ ...RELATORIO, marcas: [] })
  await abrir('/relatorios/marcas')

  expect(await screen.findByText('Nenhuma inserção de marca neste filtro.')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Baixar CSV' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByRole('img', { name: 'Marcas com mais tempo' })).toBeNull()
  expect(screen.queryByRole('table', { name: 'Tempo por marca e tipo de inserção' })).toBeNull()
})

test('erro da API mostra o alerta com o código e tenta de novo', async () => {
  const usuario = userEvent.setup()
  resposta = () => new HttpResponse(null, { status: 503 })
  await abrir('/relatorios/marcas')

  expect(await screen.findByText(/Código para o suporte: http_503/)).toBeTruthy()

  resposta = () => HttpResponse.json(RELATORIO)
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByRole('table', { name: 'Inserções por marca' })).toBeTruthy()
})

test('a barra leva ao relatório', async () => {
  const usuario = userEvent.setup()
  await abrir('/acervo')

  await usuario.click(await screen.findByRole('link', { name: 'Relatórios › Marcas' }))

  expect(location.pathname).toBe('/relatorios/marcas')
  expect(await screen.findByRole('table', { name: 'Inserções por marca' })).toBeTruthy()
})

test('tipo desconhecido no endereço sai dos filtros', () => {
  expect(filtrosDeMarcas('tipo=outdoor&programa=X')).toEqual({ programa: 'X', de: '', ate: '', tipo: '' })
  expect(filtrosDeMarcas('tipo=testemunhal').tipo).toBe('testemunhal')
  expect(filtrosDeMarcas('tipo=toString').tipo).toBe('')
})

test('o ranking e o resumo vêm acima da tabela; clicar na barra abre a linha da marca', async () => {
  await abrir('/relatorios/marcas')

  const ranking = await screen.findByRole('img', { name: 'Marcas com mais tempo' })
  expect(within(ranking).getByText('Ambev')).toBeTruthy()
  expect(within(ranking).getByText('55s')).toBeTruthy()
  // Os vídeos do resumo são os distintos: v1 e v2.
  expect(screen.getByText('4 inserções · 1min00s · 2 vídeos')).toBeTruthy()

  const barras = ranking.querySelectorAll('.recharts-bar-rectangle')
  fireEvent.click(barras[0].firstElementChild ?? barras[0])
  expect(await screen.findByRole('table', { name: 'Inserções de Ambev' })).toBeTruthy()
})

test('a matriz tem uma coluna por tipo com inserção; clicar na célula abre a marca filtrada pelo tipo', async () => {
  const usuario = userEvent.setup()
  await abrir('/relatorios/marcas')

  const matriz = await screen.findByRole('table', { name: 'Tempo por marca e tipo de inserção' })
  const colunas = within(matriz).getAllByRole('columnheader').map((c) => c.textContent)
  // Só os tipos com inserção no filtro, na ordem da lista de tipos.
  expect(colunas).toEqual(['Marca', 'Intervalo', 'Merchan com apresentador', 'Sobreposição gráfica'])

  await usuario.click(within(matriz).getByRole('button', { name: 'Ambev, Sobreposição gráfica: 5s' }))

  const lista = screen.getByRole('table', { name: 'Inserções de Ambev' })
  expect(within(lista).getByRole('link', { name: 'v2' })).toBeTruthy()
  expect(within(lista).queryByRole('link', { name: 'tv-fama-01.mp4' })).toBeNull()
  expect(screen.getByText('Só Sobreposição gráfica')).toBeTruthy()
})

test('a escala da matriz vai de 0 a 60% de opacidade', () => {
  expect(fundoDaCelula(0, 100)).toBe('transparent')
  expect(fundoDaCelula(100, 100)).toBe('rgba(56, 113, 220, 0.6)')
  expect(fundoDaCelula(50, 100)).toBe('rgba(56, 113, 220, 0.3)')
})
