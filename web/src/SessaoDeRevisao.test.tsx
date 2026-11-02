import { act, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { type ClienteDoJob, criarClienteDaApi } from './api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'
import { useSessaoDeRevisao } from './useSessaoDeRevisao.ts'

let eventos: string[] = []

const servidor = setupServer(
  http.post('/v1/jobs/j1/revisao/pulso', async ({ request }) => {
    eventos.push(((await request.json()) as { evento: string }).evento)
    return new HttpResponse(null, { status: 204 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  eventos = []
  // Só o relógio e os intervalos: o msw segue com os temporizadores de verdade.
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
})
afterEach(async () => {
  cleanup()
  // O aviso de saída ainda está a caminho: espera chegar antes do próximo teste.
  await new Promise((r) => setTimeout(r, 30))
  vi.useRealTimers()
  servidor.resetHandlers()
})
afterAll(() => servidor.close())

async function cliente(): Promise<ClienteDoJob> {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return criarClienteDaApi(auth, () => {}).job('j1')
}

function Tela({ api, ativo, tocando = false }: { api: ClienteDoJob; ativo: boolean; tocando?: boolean }) {
  useSessaoDeRevisao(api, ativo, tocando, 5 * 60_000, 60_000)
  return <p>tela</p>
}

const minutos = async (n: number) => {
  for (let i = 0; i < n; i++) await act(async () => vi.advanceTimersByTime(60_000))
}

test('começa avisando, segue a cada minuto com atividade e avisa ao sair', async () => {
  const api = await cliente()
  const tela = render(<Tela api={api} ativo />)
  await vi.waitFor(() => expect(eventos).toEqual(['inicio']))

  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).keyboard('x')
  await minutos(2)
  await vi.waitFor(() => expect(eventos).toEqual(['inicio', 'atividade', 'atividade']))

  tela.unmount()
  await vi.waitFor(() => expect(eventos).toEqual(['inicio', 'atividade', 'atividade', 'fim']))
})

test('sem atividade por 5 minutos os pulsos param, e a próxima atividade abre outra sessão', async () => {
  const api = await cliente()
  render(<Tela api={api} ativo />)
  await vi.waitFor(() => expect(eventos).toEqual(['inicio']))

  await minutos(10)
  await vi.waitFor(() => expect(eventos).toEqual(['inicio', 'atividade', 'atividade', 'atividade', 'atividade']))
  await minutos(3)
  expect(eventos).toHaveLength(5)

  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(document.body)
  await vi.waitFor(() => expect(eventos).toHaveLength(6))
  expect(eventos[5]).toBe('inicio')
})

test('o player tocando conta como atividade', async () => {
  const api = await cliente()
  render(<Tela api={api} ativo tocando />)
  await vi.waitFor(() => expect(eventos).toEqual(['inicio']))

  await minutos(10)

  await vi.waitFor(() => expect(eventos).toHaveLength(11))
  expect(new Set(eventos.slice(1))).toEqual(new Set(['atividade']))
})

test('fora do modo de catalogação nada é enviado', async () => {
  const api = await cliente()
  render(<Tela api={api} ativo={false} />)

  await minutos(3)

  expect(eventos).toEqual([])
})
