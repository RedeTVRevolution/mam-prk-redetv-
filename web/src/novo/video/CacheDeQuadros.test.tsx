import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import type { ParDeQuadro } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { navegar } from '../../rotas.ts'
import App from '../App.tsx'
import { JOB, REPRODUCAO, simularPlayer } from './abrir-teste.tsx'

const pedidos: ParDeQuadro[] = []
const servidor = setupServer(
  http.get('/v1/eu', ({ request }) => {
    const email = request.headers.get('Authorization')?.replace('Bearer token-de-', '')
    return HttpResponse.json({ uid: email, email, permissoes: ['decupagem.ver'] })
  }),
  http.get('/v1/jobs/:id', ({ params }) => HttpResponse.json({ ...JOB, id: params.id })),
  http.get('/v1/jobs/:id/reproducao', () => HttpResponse.json(REPRODUCAO)),
  http.get('/v1/jobs/:id/passadas', () => HttpResponse.json([])),
  http.get('/v1/jobs/:id/decupagem', () =>
    HttpResponse.json({
      pautas: [], planos: [], comerciais: [], transcricao: [], textos_na_tela: [],
      pessoas: [{ id: 'p1', nome: 'Ana', na_imagem: [{ inicio_ms: 0, fim_ms: 1000, quadro: 'quadros/a.jpg' }], citada_na_fala: [], citada_no_texto: [] }],
    }),
  ),
  http.post('/v1/jobs/quadros', async ({ request }) => {
    const { quadros } = (await request.json()) as { quadros: ParDeQuadro[] }
    pedidos.push(...quadros)
    return HttpResponse.json(quadros.map((q) => ({ ...q, ...REPRODUCAO, url: `https://exemplo.test/${q.job}/a.jpg` })))
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  cleanup()
  servidor.resetHandlers()
  pedidos.length = 0
  history.replaceState(null, '', '/')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
afterAll(() => servidor.close())

const imagem = () => screen.getByRole('complementary', { name: 'Inspetor' }).querySelector('img')

test('voltar ao inspetor reaproveita os quadros vistos, separados por Job (#495)', async () => {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(<App autenticador={auth} />)

  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/j1/a.jpg'))
  act(() => navegar('/video/j2'))
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/j2/a.jpg'))
  act(() => navegar('/video/j1'))
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/j1/a.jpg'))

  expect(pedidos).toEqual([{ job: 'j1', arquivo: 'a.jpg' }, { job: 'j2', arquivo: 'a.jpg' }])
})

test('administrador vê os quadros do vídeo na lixeira pelo endpoint individual, com cache por montagem', async () => {
  const individuais: string[] = []
  servidor.use(
    http.get('/v1/eu', () => HttpResponse.json({ uid: 'ana', email: 'ana@redetv.com.br', permissoes: ['decupagem.ver', 'lixeira.gerir'] })),
    // A API omite o estado da lixeira no detalhe e só o endpoint individual entrega a URL.
    http.post('/v1/jobs/quadros', async ({ request }) => {
      const { quadros } = (await request.json()) as { quadros: ParDeQuadro[] }
      return HttpResponse.json(quadros.map((q) => ({ ...q, url: null, expira_em: null })))
    }),
    http.get('/v1/jobs/:id/quadros/:arquivo', ({ params }) => {
      individuais.push(`${params.id}/${params.arquivo}`)
      return HttpResponse.json({ ...REPRODUCAO, url: `https://exemplo.test/${params.id}/${params.arquivo}` })
    }),
  )
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(<App autenticador={auth} />)

  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/j1/a.jpg'))
  const usuario = userEvent.setup()
  await usuario.click(screen.getByRole('button', { name: 'Ana, 1 aparição' }))
  await usuario.click(screen.getByRole('button', { name: /^Ana, 00:00 a 00:01/ }))
  await waitFor(() => expect(screen.getByRole('region', { name: /^Detalhe:/ }).querySelector('img')?.getAttribute('src')).toBe('https://exemplo.test/j1/a.jpg'))
  expect(individuais).toEqual(['j1/a.jpg'])

  act(() => navegar('/video/j2'))
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/j2/a.jpg'))
  act(() => navegar('/video/j1'))
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/j1/a.jpg'))
  expect(individuais).toEqual(['j1/a.jpg', 'j2/a.jpg', 'j1/a.jpg'])
})

test.each(['cache de imagens', 'autenticador'])('descarta os quadros criados com a saída pendente no %s (#495)', async (etapa) => {
  const usuario = userEvent.setup()
  const auth = new AutenticadorFalso(['ana', 'bia'].map((nome) => ({ email: `${nome}@redetv.com.br`, senha: 'senha-forte-1', totpCadastrado: true })))
  let liberar: () => void = () => {}
  const espera = new Promise<void>((resolver) => (liberar = resolver))
  if (etapa === 'cache de imagens') {
    vi.stubGlobal('caches', { delete: () => espera })
  } else {
    const sair = auth.sair.bind(auth)
    vi.spyOn(auth, 'sair').mockImplementationOnce(async () => {
      await espera
      await sair()
    })
  }
  servidor.use(http.post('/v1/jobs/quadros', async ({ request }) => {
    const { quadros } = (await request.json()) as { quadros: ParDeQuadro[] }
    const email = request.headers.get('Authorization')?.replace('Bearer token-de-', '')
    pedidos.push(...quadros)
    return HttpResponse.json(quadros.map((q) => ({ ...q, ...REPRODUCAO, url: `https://exemplo.test/${email}/${q.job}/a.jpg` })))
  }))
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(<App autenticador={auth} />)
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/ana@redetv.com.br/j1/a.jpg'))

  await usuario.click(screen.getByRole('button', { name: 'Conta: ana@redetv.com.br' }))
  await usuario.click(screen.getByRole('menuitem', { name: 'Sair' }))
  // A tela segue montada durante os awaits e pode recriar o cache da pessoa que está saindo.
  act(() => navegar('/video/j2'))
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/ana@redetv.com.br/j2/a.jpg'))
  act(() => navegar('/video/j1'))
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/ana@redetv.com.br/j1/a.jpg'))
  await act(async () => liberar())
  await usuario.type(await screen.findByLabelText(/^E-mail/), 'bia@redetv.com.br')
  await usuario.type(screen.getByLabelText(/^Senha/), 'senha-forte-1')
  await usuario.click(screen.getByRole('button', { name: 'Entrar' }))
  await usuario.type(await screen.findByLabelText('Código do autenticador'), CODIGO_TOTP_FALSO)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))

  await screen.findByRole('button', { name: 'Conta: bia@redetv.com.br' })
  await waitFor(() => expect(imagem()?.getAttribute('src')).toBe('https://exemplo.test/bia@redetv.com.br/j1/a.jpg'))
  expect(pedidos).toEqual([
    { job: 'j1', arquivo: 'a.jpg' }, { job: 'j2', arquivo: 'a.jpg' },
    { job: 'j1', arquivo: 'a.jpg' }, { job: 'j1', arquivo: 'a.jpg' },
  ])
})
