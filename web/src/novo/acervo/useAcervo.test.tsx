import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { SEM_FILTROS, type FiltrosDoAcervo } from '../../jobs.ts'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { lembrarPosicao, useAcervo } from './useAcervo.ts'

// 400 vídeos: 8 páginas de 50.
const jobs = Array.from({ length: 400 }, (_, i) => ({
  id: `j${i}`,
  nome: `video-${i}.mp4`,
  estado: 'concluido',
  codigo_falha: null,
  criado_em: '2026-10-29T15:00:00Z',
}))
const cursoresPedidos: (string | null)[] = []

const servidor = setupServer(
  http.get('/v1/jobs', ({ request }) => {
    const p = new URL(request.url).searchParams
    const cursor = p.get('cursor')
    cursoresPedidos.push(cursor)
    const lista = p.get('estado') ? jobs.slice(0, 10) : jobs
    const inicio = cursor ? lista.findIndex((j) => j.id === cursor) + 1 : 0
    const pagina = lista.slice(inicio, inicio + Number(p.get('limite')))
    const ha = inicio + pagina.length < lista.length
    return HttpResponse.json(pagina, { headers: ha ? { 'X-Proximo-Cursor': pagina[pagina.length - 1].id } : {} })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  cursoresPedidos.length = 0
})
afterAll(() => servidor.close())

async function montar(filtros: FiltrosDoAcervo = SEM_FILTROS) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  const api = criarClienteDaApi(auth, () => {})
  const consultas = criarClienteDeConsultas()
  const envolver = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={consultas}>
      <ContextoDaApi.Provider value={api}>{children}</ContextoDaApi.Provider>
    </QueryClientProvider>
  )
  const r = renderHook((f: FiltrosDoAcervo) => useAcervo(f), { wrapper: envolver, initialProps: filtros })
  await waitFor(() => expect(r.result.current.quantidade).toBeGreaterThan(0))
  return { ...r, consultas, envolver }
}

/** Mostra o fim da lista até a página `ate` (contada do zero) estar na memória. */
async function descer(r: Awaited<ReturnType<typeof montar>>['result'], ate: number) {
  for (let p = 1; p <= ate; p++) {
    act(() => r.current.aoVer(p * 50 - 5, p * 50))
    await waitFor(() => expect(r.current.item(p * 50)).not.toBeNull())
  }
}

test('desce até o fim com 6 páginas na memória e sobe de novo pelos cursores guardados', async () => {
  const { result, consultas } = await montar()
  await descer(result, 7)

  expect(result.current.item(399)?.id).toBe('j399')
  expect(result.current.quantidade).toBe(400)
  // As páginas 0 e 1 saíram da memória: o lugar delas fica, sem o vídeo.
  expect(result.current.item(99)).toBeNull()
  expect(result.current.item(100)?.id).toBe('j100')
  const [consulta] = consultas.getQueryCache().findAll({ queryKey: ['acervo'] })
  expect((consulta.state.data as { pages: unknown[] }).pages).toHaveLength(6)

  // Subir: a página 1 vem com o cursor da página 0 (o último dela), e a 0 sem cursor.
  cursoresPedidos.length = 0
  act(() => result.current.aoVer(105, 130))
  await waitFor(() => expect(result.current.item(99)?.id).toBe('j99'))
  expect(cursoresPedidos).toEqual(['j49'])
  expect(result.current.item(399)).toBeNull()
  act(() => result.current.aoVer(55, 80))
  await waitFor(() => expect(result.current.item(0)?.id).toBe('j0'))
  expect(cursoresPedidos).toEqual(['j49', null])
  expect(result.current.quantidade).toBe(301)
})

test('trocar o filtro descarta na hora a consulta de antes', async () => {
  const { result, rerender, consultas } = await montar()
  await descer(result, 2)

  rerender({ ...SEM_FILTROS, estado: ['falhou'] })
  await waitFor(() => expect(result.current.quantidade).toBe(10))

  const chaves = consultas.getQueryCache().findAll({ queryKey: ['acervo'] }).map((c) => c.queryKey)
  expect(chaves).toEqual([['acervo', { ...SEM_FILTROS, estado: ['falhou'] }]])
})

test('voltar do vídeo com o cache vencido recomeça na página de onde se saiu', async () => {
  const primeiro = await montar()
  await descer(primeiro.result, 4)
  lembrarPosicao(primeiro.result.current.chave, 210)
  primeiro.unmount()
  // O mesmo cliente de consultas, sem a consulta (o gcTime passou).
  primeiro.consultas.removeQueries({ queryKey: ['acervo'] })
  cursoresPedidos.length = 0

  const { result } = renderHook(() => useAcervo(SEM_FILTROS), { wrapper: primeiro.envolver })
  await waitFor(() => expect(result.current.item(210)?.id).toBe('j210'))
  expect(cursoresPedidos).toEqual(['j199'])
  expect(result.current.item(199)).toBeNull()
})
