import { afterEach, expect, test, vi } from 'vitest'
import type { ClienteDaApi } from './api.ts'
import { criarCacheDeQuadros, urlDoQuadroDaBusca } from './quadros.ts'

afterEach(() => vi.useRealTimers())

const resposta = (url: string, expira_em: string) => Promise.resolve({ url, expira_em })

test('pede o arquivo do caminho e guarda a URL enquanto ela vale', async () => {
  const buscar = vi.fn((arquivo: string) => resposta(`u/${arquivo}`, '2999-01-01T00:00:00Z'))
  const url = criarCacheDeQuadros(buscar)

  expect(await url('quadros/plano-0.jpg')).toBe('u/plano-0.jpg')
  expect(await url('quadros/plano-0.jpg')).toBe('u/plano-0.jpg')
  expect(buscar).toHaveBeenCalledTimes(1)
  expect(buscar).toHaveBeenCalledWith('plano-0.jpg')
})

test('pede de novo a URL que está para vencer', async () => {
  vi.useFakeTimers({ now: Date.parse('2026-10-31T12:00:00Z') })
  const buscar = vi.fn(() => resposta('u', '2026-10-31T12:10:00Z'))
  const url = criarCacheDeQuadros(buscar)

  await url('quadros/a.jpg')
  vi.setSystemTime(Date.parse('2026-10-31T12:09:45Z'))
  await url('quadros/a.jpg')

  expect(buscar).toHaveBeenCalledTimes(2)
})

test('uma falha não fica guardada', async () => {
  const buscar = vi
    .fn<(a: string) => Promise<{ url: string; expira_em: string }>>()
    .mockRejectedValueOnce(new Error('fora do ar'))
    .mockImplementation(() => resposta('u', '2999-01-01T00:00:00Z'))
  const url = criarCacheDeQuadros(buscar)

  await expect(url('quadros/a.jpg')).rejects.toThrow('fora do ar')
  expect(await url('quadros/a.jpg')).toBe('u')
})

test('os quadros pedidos juntos saem num pedido em lote só, e um já guardado não volta a ser pedido (#481)', async () => {
  const quadros = vi.fn((pares: { job: string; arquivo: string }[]) =>
    Promise.resolve(pares.map((p) => ({ ...p, url: `u/${p.job}/${p.arquivo}`, expira_em: '2999-01-01T00:00:00Z' }))),
  )
  const url = urlDoQuadroDaBusca({ quadros } as unknown as ClienteDaApi)

  const urls = await Promise.all([url('v1', 'quadros/a.jpg'), url('v2', 'quadros/a.jpg'), url('v1', 'quadros/b.jpg')])
  await url('v1', 'quadros/a.jpg')

  expect(urls).toEqual(['u/v1/a.jpg', 'u/v2/a.jpg', 'u/v1/b.jpg'])
  expect(quadros).toHaveBeenCalledTimes(1)
})

test('mais de 100 quadros viram pedidos de 100, e o que veio sem URL recusa só o seu (#481)', async () => {
  const quadros = vi.fn((pares: { job: string; arquivo: string }[]) =>
    Promise.resolve(pares.map((p) => ({ ...p, url: p.job === 'lixo' ? null : 'u', expira_em: p.job === 'lixo' ? null : '2999-01-01T00:00:00Z' }))),
  )
  const url = urlDoQuadroDaBusca({ quadros } as unknown as ClienteDaApi)

  const todos = await Promise.allSettled([
    ...Array.from({ length: 100 }, (_, n) => url(`v${n}`, 'quadros/a.jpg')),
    url('lixo', 'quadros/a.jpg'),
  ])

  expect(quadros.mock.calls.map(([p]) => p.length)).toEqual([100, 1])
  expect(todos.slice(0, 100).every((r) => r.status === 'fulfilled')).toBe(true)
  expect(todos[100]!.status).toBe('rejected')
})
