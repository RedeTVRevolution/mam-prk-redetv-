import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import {
  ConflitoNaApi,
  criarClienteDaApi,
  FalhaNaApi,
  NaoEncontrado,
  PedidoInvalido,
  SessaoExpirada,
} from './api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { SEM_FILTROS } from './jobs.ts'

const servidor = setupServer()
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => servidor.resetHandlers())
afterAll(() => servidor.close())

async function autenticadorComSessao() {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

async function cliente() {
  const aoSessaoExpirada = vi.fn()
  const api = criarClienteDaApi(await autenticadorComSessao(), aoSessaoExpirada)
  return { api, aoSessaoExpirada }
}

test('manda o token da sessão e devolve o corpo', async () => {
  let autorizacao: string | null = null
  servidor.use(
    http.get('/v1/eu', ({ request }) => {
      autorizacao = request.headers.get('Authorization')
      return HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: [] })
    }),
  )
  const { api, aoSessaoExpirada } = await cliente()

  expect((await api.eu()).email).toBe('ana@redetv.com.br')
  expect(autorizacao).toMatch(/^Bearer .+/)
  expect(aoSessaoExpirada).not.toHaveBeenCalled()
})

test('401 vira SessaoExpirada e avisa uma vez', async () => {
  servidor.use(http.get('/v1/jobs', () => new HttpResponse(null, { status: 401 })))
  const { api, aoSessaoExpirada } = await cliente()

  await expect(api.acervo(SEM_FILTROS)).rejects.toBeInstanceOf(SessaoExpirada)
  expect(aoSessaoExpirada).toHaveBeenCalledTimes(1)
})

test('sem token nem chama a API: SessaoExpirada', async () => {
  let chamou = false
  servidor.use(
    http.get('/v1/jobs', () => {
      chamou = true
      return HttpResponse.json([])
    }),
  )
  const aoSessaoExpirada = vi.fn()
  const api = criarClienteDaApi(new AutenticadorFalso([]), aoSessaoExpirada)

  await expect(api.acervo(SEM_FILTROS)).rejects.toBeInstanceOf(SessaoExpirada)
  expect(aoSessaoExpirada).toHaveBeenCalledTimes(1)
  expect(chamou).toBe(false)
})

test('404 vira NaoEncontrado', async () => {
  servidor.use(
    http.get('/v1/jobs/x/decupagem', () => HttpResponse.json({ detail: 'sumiu' }, { status: 404 })),
  )
  const { api, aoSessaoExpirada } = await cliente()

  await expect(api.job('x').decupagem()).rejects.toBeInstanceOf(NaoEncontrado)
  expect(aoSessaoExpirada).not.toHaveBeenCalled()
})

test('409 vira ConflitoNaApi com a mensagem do servidor', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/correcoes', () =>
      HttpResponse.json({ detail: 'A decupagem mudou' }, { status: 409 }),
    ),
  )
  const { api } = await cliente()

  const erro = await api
    .job('j1')
    .corrigir({ tipo: 'pessoa.renomear' })
    .catch((e: unknown) => e)
  expect(erro).toBeInstanceOf(ConflitoNaApi)
  expect((erro as Error).message).toBe('A decupagem mudou')
})

test('422 vira PedidoInvalido com a mensagem do servidor', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/correcoes', () =>
      HttpResponse.json({ detail: 'Tempos além da duração' }, { status: 422 }),
    ),
  )
  const { api } = await cliente()

  const erro = await api
    .job('j1')
    .corrigir({})
    .catch((e: unknown) => e)
  expect(erro).toBeInstanceOf(PedidoInvalido)
  expect((erro as Error).message).toBe('Tempos além da duração')
})

test('500 vira FalhaNaApi com o status', async () => {
  servidor.use(http.get('/v1/programas', () => new HttpResponse('quebrou', { status: 500 })))
  const { api, aoSessaoExpirada } = await cliente()

  const erro = await api.programas().catch((e: unknown) => e)
  expect(erro).toBeInstanceOf(FalhaNaApi)
  expect((erro as FalhaNaApi).status).toBe(500)
  expect(aoSessaoExpirada).not.toHaveBeenCalled()
})

test('as operações do Job montam o caminho e o corpo', async () => {
  const pedidos: string[] = []
  servidor.use(
    http.post('/v1/jobs/j1/correcoes/c1/desfazer', async ({ request }) => {
      pedidos.push(`desfazer ${JSON.stringify(await request.json())}`)
      return HttpResponse.json({})
    }),
    http.post('/v1/jobs/j1/fila/f1/reaplicar', async ({ request }) => {
      pedidos.push(`reaplicar ${JSON.stringify(await request.json())}`)
      return HttpResponse.json({})
    }),
  )
  const { api } = await cliente()

  await api.job('j1').desfazer('c1', 'engano')
  await api.job('j1').reaplicar('f1', 'p2', 'certo')

  expect(pedidos).toEqual([
    'desfazer {"motivo":"engano"}',
    'reaplicar {"item_id":"p2","motivo":"certo"}',
  ])
})
