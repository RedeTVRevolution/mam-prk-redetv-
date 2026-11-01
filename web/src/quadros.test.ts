import { afterEach, expect, test, vi } from 'vitest'
import { criarCacheDeQuadros } from './quadros.ts'

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
