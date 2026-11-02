import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'

const plano = (inicio_ms: number, motivo: string, quadro: string) => ({
  tipo: 'plano',
  inicio_ms,
  fim_ms: inicio_ms + 5_000,
  motivo,
  destaques: [],
  quadro_url: quadro,
})

const RESULTADO = {
  entendida: { evidencias: ['imagem'], programa: null, desde: null, ate: null, visual: true },
  videos: [
    {
      job_id: 'v1',
      nome: 'v1.mp4',
      programa: 'TV Fama',
      data_exibicao: '2026-10-21',
      duracao_s: 2959,
      n_momentos: 2,
      momentos: [plano(724_000, 'Plano: rua molhada', 'https://q.exemplo/a.jpg'), plano(60_000, 'Plano: estúdio', 'https://q.exemplo/b.jpg')],
    },
  ],
  sem_aparicoes: [],
  plano_b: false,
  facetas: { programa: [], mes: [], pessoa: [], marca: [], tipo: [] },
}

interface Pedido {
  params: URLSearchParams
  tipo: string | null
  arquivo: File | null
}
const pedidos: Pedido[] = []
let resposta: () => Response = () => HttpResponse.json(RESULTADO)

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.ver'] })),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama', 'Leo Dias'])),
  http.get('/v1/busca', () => HttpResponse.json({ ...RESULTADO, videos: [] })),
  http.post('/v1/busca/imagem', async ({ request }) => {
    const formulario = await request.formData()
    pedidos.push({
      params: new URL(request.url).searchParams,
      tipo: request.headers.get('Content-Type'),
      arquivo: formulario.get('arquivo') as File | null,
    })
    return resposta()
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  pedidos.length = 0
  resposta = () => HttpResponse.json(RESULTADO)
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

const foto = () => new File([new Uint8Array([137, 80, 78, 71])], 'pista.png', { type: 'image/png' })

test('escolher a foto manda o arquivo em multipart e mostra a grade de planos', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca')
  const campo = await screen.findByLabelText('Foto para buscar')

  await usuario.upload(campo, foto())

  const grade = await screen.findByRole('list', { name: 'Planos' })
  expect(within(grade).getAllByRole('listitem')).toHaveLength(2)
  expect(grade.querySelector('img')?.getAttribute('src')).toBe('https://q.exemplo/a.jpg')
  expect(screen.getByText('2 planos parecidos em 1 vídeo')).toBeTruthy()
  expect(pedidos).toHaveLength(1)
  expect(pedidos[0].tipo).toMatch(/^multipart\/form-data; boundary=/)
  expect(pedidos[0].arquivo?.size).toBe(4)
  // A foto não vai para a URL da página.
  expect(location.search).toBe('')
})

test('arrastar a foto para a área também busca', async () => {
  await abrir('/busca')
  const area = (await screen.findByText(/Arraste uma foto/)).closest('div')!.parentElement!

  fireEvent.drop(area, { dataTransfer: { files: [foto()] } })

  await screen.findByRole('list', { name: 'Planos' })
  expect(pedidos).toHaveLength(1)
})

test('o programa e o período da tela vão junto, e mudar o filtro busca de novo com a mesma foto', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=pista&programa=TV+Fama&ano=2026')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())
  await screen.findByRole('list', { name: 'Planos' })
  expect(pedidos[0].params.get('programa')).toBe('TV Fama')
  expect(pedidos[0].params.get('desde')).toBe('2026-01-01')
  expect(pedidos[0].params.get('ate')).toBe('2026-12-31')
  expect(pedidos[0].params.has('q')).toBe(false)

  await usuario.click(await screen.findByRole('combobox', { name: 'Programa' }))
  await usuario.click(await screen.findByRole('option', { name: 'Leo Dias' }))

  await waitFor(() => expect(pedidos).toHaveLength(2))
  expect(pedidos[1].params.get('programa')).toBe('Leo Dias')
  // A mesma foto, sem o editor escolher de novo.
  expect(pedidos[1].arquivo?.size).toBe(4)
})

test('tipo ou tamanho errado: a mensagem da API aparece em português', async () => {
  resposta = () => HttpResponse.json({ detail: 'Envie uma imagem JPEG ou PNG válida' }, { status: 422 })
  const usuario = userEvent.setup({ applyAccept: false })
  await abrir('/busca')

  await usuario.upload(await screen.findByLabelText('Foto para buscar'), new File(['x'], 'a.gif', { type: 'image/gif' }))

  expect((await screen.findByRole('alert')).textContent).toContain('Envie uma imagem JPEG ou PNG válida')
  expect(screen.queryByRole('list', { name: 'Planos' })).toBeNull()
})

test('com o índice do quadro fora a tela diz que a busca por imagem não está disponível', async () => {
  resposta = () => HttpResponse.json({ detail: 'x' }, { status: 503 })
  const usuario = userEvent.setup()
  await abrir('/busca')

  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())

  expect((await screen.findByRole('alert')).textContent).toContain('A busca por imagem não está disponível agora')
})

test('sem planos parecidos a tela avisa, e Limpar esquece a foto', async () => {
  resposta = () => HttpResponse.json({ ...RESULTADO, videos: [] })
  const usuario = userEvent.setup()
  await abrir('/busca')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())

  expect((await screen.findByRole('status')).textContent).toContain('Nenhum plano parecido')

  await usuario.click(screen.getByRole('button', { name: 'Limpar' }))
  expect(screen.queryByText(/Nenhum plano parecido/)).toBeNull()
  expect(screen.getByText(/Arraste uma foto/)).toBeTruthy()
})
