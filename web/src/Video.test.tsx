import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import Video from './Video.tsx'

// Segue o esquema 1.1 (api/decupagem.py).
const decupagem = {
  versao_esquema: '1.1',
  video: { sha256: 'a'.repeat(64), duracao_ms: 180_000 },
  programa: { resumo: 'Jornal', blocos: [] },
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', inicio_ms: 30_000, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Ana Souza',
      origem: 'modelo',
      na_imagem: [{ inicio_ms: 5_000, fim_ms: 20_000, evidencia: 'rosto' }],
      citada_na_fala: [{ inicio_ms: 65_000, fim_ms: 66_000 }],
      citada_no_texto: [{ inicio_ms: 70_000, fim_ms: 72_000, texto: '<b>Ana</b> no GC' }],
    },
  ],
  planos: [
    { id: 'pl1', ambiente: 'estúdio', plano_limpo: false, acao: null, inicio_ms: 0, fim_ms: 4_000 },
    { id: 'pl2', ambiente: 'rua', plano_limpo: true, acao: 'carro passa', inicio_ms: 140_000, fim_ms: 150_000 },
  ],
  comerciais: [
    { marca: 'Marca X', tipo: 'intervalo', evidencia: 'logo', inicio_ms: 90_000, fim_ms: 120_000 },
  ],
  transcricao: [{ locutor: 'Locutor', texto: 'Boa noite', inicio_ms: 1_000, fim_ms: 3_000 }],
}

const TOKEN = 'Bearer token-de-ana@redetv.com.br'
let statusDecupagem = 200
let links: { url: string; expira_em: string }[] = []
const servidor = setupServer(
  http.get('/v1/jobs/j1/reproducao', ({ request }) => {
    if (request.headers.get('Authorization') !== TOKEN) return new HttpResponse(null, { status: 401 })
    return HttpResponse.json(
      links.shift() ?? { url: 'https://storage.exemplo/proxy/j1', expira_em: '2999-01-01T00:00:00Z' },
    )
  }),
  http.get('/v1/jobs/j1/decupagem', ({ request }) => {
    if (request.headers.get('Authorization') !== TOKEN) return new HttpResponse(null, { status: 401 })
    return statusDecupagem === 200
      ? HttpResponse.json(decupagem)
      : new HttpResponse(null, { status: statusDecupagem })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  statusDecupagem = 200
  links = []
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(job: { estado: string; codigo_falha?: string | null }) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(
    <Video
      autenticador={auth}
      job={{ id: 'j1', nome: 'clipe.mp4', codigo_falha: null, ...job }}
      aoVoltar={() => {}}
      aoSessaoExpirada={() => {}}
    />,
  )
}

test('mostra o player com o link assinado e o painel agrupado por categoria', async () => {
  await abrir({ estado: 'concluido' })

  const player = await screen.findByLabelText('Player')
  expect(player.getAttribute('src')).toBe('https://storage.exemplo/proxy/j1')
  const imagem = within(screen.getByRole('region', { name: 'Pessoas na imagem' }))
  expect(imagem.getByText('00:05 Ana Souza')).toBeTruthy()
  const fala = within(screen.getByRole('region', { name: 'Citadas na fala' }))
  expect(fala.getByText('01:05 Ana Souza')).toBeTruthy()
  const texto = within(screen.getByRole('region', { name: 'Citadas no texto' }))
  expect(texto.getByText('01:10 Ana Souza — <b>Ana</b> no GC')).toBeTruthy()
  expect(within(screen.getByRole('region', { name: 'Pautas' })).getByText('00:30 Eleição')).toBeTruthy()
  const planos = within(screen.getByRole('region', { name: 'Planos' }))
  expect(planos.getByText('00:00 estúdio')).toBeTruthy()
  expect(planos.getByText('02:20 carro passa')).toBeTruthy()
  expect(within(screen.getByRole('region', { name: 'Comerciais' })).getByText('01:30 Marca X (intervalo)')).toBeTruthy()
  expect(within(screen.getByRole('region', { name: 'Transcrição' })).getByText('00:01 Locutor: Boa noite')).toBeTruthy()
})

test('texto da decupagem aparece escapado, nunca como HTML', async () => {
  await abrir({ estado: 'concluido' })
  await screen.findByLabelText('Player')

  expect(document.querySelector('aside b')).toBeNull()
})

test('clicar num item leva o currentTime do player ao inicio_ms', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement

  await usuario.click(screen.getByText('00:30 Eleição'))
  expect(player.currentTime).toBe(30)

  await usuario.click(screen.getByText('00:05 Ana Souza'))
  expect(player.currentTime).toBe(5)

  await usuario.click(screen.getByText('02:20 carro passa'))
  expect(player.currentTime).toBe(140)
})

test('link expirado: o player pede outro e volta ao mesmo ponto', async () => {
  links = [
    { url: 'https://storage.exemplo/proxy/j1?v=1', expira_em: '2000-01-01T00:00:00Z' },
    { url: 'https://storage.exemplo/proxy/j1?v=2', expira_em: '2999-01-01T00:00:00Z' },
  ]
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  await usuario.click(screen.getByText('00:30 Eleição'))

  fireEvent.error(player)

  await waitFor(() => expect(player.getAttribute('src')).toBe('https://storage.exemplo/proxy/j1?v=2'))
  player.currentTime = 0
  fireEvent.loadedMetadata(player)
  expect(player.currentTime).toBe(30)
})

test('erro do player com link ainda válido não pede outro link', async () => {
  let pedidos = 0
  servidor.events.on('request:start', ({ request }) => {
    if (request.url.endsWith('/reproducao')) pedidos++
  })
  await abrir({ estado: 'concluido' })
  const player = await screen.findByLabelText('Player')

  fireEvent.error(player)
  await new Promise((r) => setTimeout(r, 20))

  expect(pedidos).toBe(1)
  expect(player.getAttribute('src')).toBe('https://storage.exemplo/proxy/j1')
  servidor.events.removeAllListeners()
})

test('Job falhou mostra o código em vez do player, sem chamar a API', async () => {
  await abrir({ estado: 'falhou', codigo_falha: 'codec_nao_suportado' })

  expect((await screen.findByRole('alert')).textContent).toContain('codec_nao_suportado')
  expect(screen.queryByLabelText('Player')).toBeNull()
})

test('o botão baixa a decupagem em JSON', async () => {
  const usuario = userEvent.setup()
  const blobs: Blob[] = []
  URL.createObjectURL = (b: Blob | MediaSource) => {
    blobs.push(b as Blob)
    return 'blob:x'
  }
  URL.revokeObjectURL = () => {}
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await abrir({ estado: 'concluido' })
  await screen.findByLabelText('Player')

  await usuario.click(screen.getByText('Baixar decupagem (JSON)'))

  expect(clique).toHaveBeenCalledOnce()
  expect(JSON.parse(await blobs[0]!.text())).toEqual(decupagem)
})

test('falha ao carregar mostra aviso', async () => {
  statusDecupagem = 503
  await abrir({ estado: 'concluido' })

  expect((await screen.findByRole('alert')).textContent).toContain('Não foi possível')
})
