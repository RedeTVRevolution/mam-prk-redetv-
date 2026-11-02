import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'
import { duracaoLegivel, filtrosDoRelatorio } from './tempoDeTela.ts'

const video = (job_id: string, nome: string | null, tempo_de_tela_ms: number) => ({
  job_id,
  nome,
  tempo_de_tela_ms,
  aparicoes: 2,
  mencoes_na_fala: 1,
  mencoes_no_texto: 0,
})

const RELATORIO = {
  programa: null,
  desde: null,
  ate: null,
  pessoas: [
    {
      pessoa_id: 'c1',
      nome: 'Sabrina Sato',
      tempo_de_tela_ms: 725_000,
      videos: 2,
      aparicoes: 4,
      mencoes_na_fala: 2,
      mencoes_no_texto: 1,
      por_video: [video('v1', 'tv-fama-01.mp4', 600_000), video('v2', null, 125_000)],
    },
    {
      pessoa_id: 'c2',
      nome: 'Leo Dias',
      tempo_de_tela_ms: 45_000,
      videos: 1,
      aparicoes: 1,
      mencoes_na_fala: 0,
      mencoes_no_texto: 3,
      por_video: [video('v1', 'tv-fama-01.mp4', 45_000)],
    },
  ],
}

const pedidos: URLSearchParams[] = []
let resposta: () => Response = () => HttpResponse.json(RELATORIO)

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.ver'] })),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama', 'Leo Dias'])),
  http.get('/v1/relatorios/tempo-de-tela', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') {
      return new HttpResponse('pessoa_id,nome\nc1,Sabrina Sato\n', { headers: { 'Content-Type': 'text/csv' } })
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

test('a tabela mostra tempo, vídeos, aparições e menções, na ordem da API', async () => {
  await abrir('/relatorios/tempo-de-tela')

  const tabela = await screen.findByRole('table', { name: 'Tempo de tela por pessoa' })

  const linhas = within(tabela).getAllByRole('row').slice(1)
  expect(linhas.map((l) => within(l).getAllByRole('cell').map((c) => c.textContent))).toEqual([
    ['Sabrina Sato', '12min05s', '2', '4', '2', '1'],
    ['Leo Dias', '45s', '1', '1', '0', '3'],
  ])
})

test('os filtros vão à API e ao endereço; o endereço reproduz os filtros', async () => {
  await abrir('/relatorios/tempo-de-tela?programa=TV+Fama&de=2026-10-01&ate=2026-10-31')

  await screen.findByRole('table', { name: 'Tempo de tela por pessoa' })

  expect(pedidos[0].get('programa')).toBe('TV Fama')
  expect(pedidos[0].get('desde')).toBe('2026-10-01')
  expect(pedidos[0].get('ate')).toBe('2026-10-31')

  fireEvent.change(screen.getByLabelText('Exibido até'), { target: { value: '2026-10-15' } })

  await waitFor(() => expect(pedidos.at(-1)?.get('ate')).toBe('2026-10-15'))
  expect(location.search).toContain('ate=2026-10-15')
})

test('clicar numa pessoa abre a lista dos vídeos com os tempos', async () => {
  const usuario = userEvent.setup()
  await abrir('/relatorios/tempo-de-tela')

  await usuario.click(await screen.findByRole('button', { name: 'Sabrina Sato' }))

  const videos = screen.getByRole('table', { name: 'Vídeos de Sabrina Sato' })
  expect(within(videos).getByRole('link', { name: 'tv-fama-01.mp4' }).getAttribute('href')).toBe('/video/v1')
  expect(within(videos).getByText('10min00s')).toBeTruthy()
  // Sem nome, o vídeo aparece pelo id.
  expect(within(videos).getByRole('link', { name: 'v2' })).toBeTruthy()

  await usuario.click(screen.getByRole('button', { name: 'Sabrina Sato' }))
  expect(screen.queryByRole('table', { name: 'Vídeos de Sabrina Sato' })).toBeNull()
})

test('Baixar CSV pede o formato csv com os mesmos filtros e entrega o arquivo', async () => {
  const usuario = userEvent.setup()
  const criar = vi.fn(() => 'blob:csv')
  Object.assign(URL, { createObjectURL: criar, revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/relatorios/tempo-de-tela?programa=TV+Fama')
  await screen.findByRole('table', { name: 'Tempo de tela por pessoa' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  const csv = pedidos.find((p) => p.get('formato') === 'csv')
  expect(csv?.get('programa')).toBe('TV Fama')
  expect(criar).toHaveBeenCalled()
  clique.mockRestore()
})

test('sem aparição nem menção no filtro, a tela diz isso e não oferece o CSV', async () => {
  resposta = () => HttpResponse.json({ ...RELATORIO, pessoas: [] })
  await abrir('/relatorios/tempo-de-tela')

  expect(await screen.findByText('Nenhuma pessoa com aparição ou menção neste filtro.')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'Baixar CSV' }) as HTMLButtonElement).disabled).toBe(true)
})

test('erro da API mostra o alerta com o código e tenta de novo', async () => {
  const usuario = userEvent.setup()
  resposta = () => new HttpResponse(null, { status: 503 })
  await abrir('/relatorios/tempo-de-tela')

  expect(await screen.findByText(/Código para o suporte: http_503/)).toBeTruthy()

  resposta = () => HttpResponse.json(RELATORIO)
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByRole('table', { name: 'Tempo de tela por pessoa' })).toBeTruthy()
})

test('a barra leva ao relatório', async () => {
  const usuario = userEvent.setup()
  await abrir('/acervo')

  await usuario.click(await screen.findByRole('link', { name: 'Relatórios › Tempo de tela' }))

  expect(location.pathname).toBe('/relatorios/tempo-de-tela')
  expect(await screen.findByRole('table', { name: 'Tempo de tela por pessoa' })).toBeTruthy()
})

test('duração legível e filtros do endereço', () => {
  expect(duracaoLegivel(3_720_000)).toBe('1h02min')
  expect(duracaoLegivel(45_000)).toBe('45s')
  expect(filtrosDoRelatorio('de=ontem&ate=2026-10-31&programa=X')).toEqual({ programa: 'X', de: '', ate: '2026-10-31' })
})
