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
import { lembrarPosicao, tirarDoAcervo, useAcervo } from './useAcervo.ts'

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
  lembrarPosicao(primeiro.consultas, primeiro.result.current.chave, 210)
  primeiro.unmount()
  // O mesmo cliente de consultas, sem a consulta (o gcTime passou).
  primeiro.consultas.removeQueries({ queryKey: ['acervo'] })
  cursoresPedidos.length = 0

  const { result } = renderHook(() => useAcervo(SEM_FILTROS), { wrapper: primeiro.envolver })
  await waitFor(() => expect(result.current.item(210)?.id).toBe('j210'))
  expect(cursoresPedidos).toEqual(['j199'])
  expect(result.current.item(199)).toBeNull()
})

test('a página refeita depois de uma exclusão não repete o vídeo que avançou sobre a seguinte', async () => {
  const { result } = await montar()
  await descer(result, 7)
  // j20 vai para a lixeira: a página 0 refeita vai até o j50, e a 1 (cursor j49) ainda começa nele.
  const [tirado] = jobs.splice(20, 1)
  try {
    act(() => result.current.aoVer(105, 130))
    await waitFor(() => expect(result.current.item(99)?.id).toBe('j99'))
    act(() => result.current.aoVer(55, 80))
    await waitFor(() => expect(result.current.item(0)?.id).toBe('j0'))
    const ids = result.current.itens.map((j) => j.id)
    expect(ids).not.toContain('j20')
    expect(new Set(ids).size).toBe(ids.length)
  } finally {
    jobs.splice(20, 0, tirado)
  }
})

test('a posição de outro login, ou de uma página sem cursor guardado, não vira volta', async () => {
  const antes = await montar()
  await descer(antes.result, 5)
  lembrarPosicao(antes.consultas, antes.result.current.chave, 250)
  antes.unmount()

  // Outro login: outro cliente de consultas, sem os cursores do anterior.
  const depois = await montar()
  expect(depois.result.current.voltaInicial).toBe(0)
  // O mesmo cliente, com a posição numa página que ele nunca viu: sem cursor, volta ao topo.
  lembrarPosicao(depois.consultas, depois.result.current.chave, 250)
  depois.unmount()
  const { result } = renderHook(() => useAcervo(SEM_FILTROS), { wrapper: depois.envolver })
  expect(result.current.voltaInicial).toBe(0)
})

test('vídeos novos no topo não fazem sumir os da emenda ao subir', async () => {
  const { result } = await montar()
  await descer(result, 7)
  const novos = ['n0', 'n1', 'n2'].map((id) => ({ ...jobs[0], id }))
  jobs.unshift(...novos)
  try {
    act(() => result.current.aoVer(105, 130))
    await waitFor(() => expect(result.current.item(99)).not.toBeNull())
    act(() => result.current.aoVer(55, 80))
    await waitFor(() => expect(result.current.item(0)?.id).toBe('n0'))
    await waitFor(() => expect(result.current.itens.map((j) => j.id)).toEqual(expect.arrayContaining(['j46', 'j47', 'j48', 'j49', 'j50'])))
    const ids = result.current.itens.map((j) => j.id)
    expect(new Set(ids).size).toBe(ids.length)
  } finally {
    jobs.splice(0, novos.length)
  }
})

test('uma página menor (vídeo para a lixeira) que sai da memória não desloca os índices', async () => {
  const { result, consultas } = await montar()
  await descer(result, 5)
  act(() => tirarDoAcervo(consultas, new Set(['j20'])))
  await waitFor(() => expect(result.current.item(100)?.id).toBe('j101'))
  await descer(result, 6)
  expect(result.current.item(0)).toBeNull()
  expect(result.current.item(100)?.id).toBe('j101')
  expect(result.current.item(300)?.id).toBe('j301')
})

async function voltarA210() {
  const primeiro = await montar()
  await descer(primeiro.result, 4)
  lembrarPosicao(primeiro.consultas, primeiro.result.current.chave, 210)
  primeiro.unmount()
  primeiro.consultas.removeQueries({ queryKey: ['acervo'] })
  const r = renderHook((f: FiltrosDoAcervo) => useAcervo(f), { wrapper: primeiro.envolver, initialProps: SEM_FILTROS })
  await waitFor(() => expect(r.result.current.item(210)?.id).toBe('j210'))
  return { ...r, consultas: primeiro.consultas }
}

test('depois da volta, ir a outro filtro e voltar começa do topo', async () => {
  const { result, rerender } = await voltarA210()
  rerender({ ...SEM_FILTROS, estado: ['falhou'] })
  await waitFor(() => expect(result.current.quantidade).toBe(10))
  cursoresPedidos.length = 0
  rerender(SEM_FILTROS)
  await waitFor(() => expect(result.current.item(0)?.id).toBe('j0'))
  expect(cursoresPedidos).toEqual([null])
})

test('a lista refeita por um envio, depois da volta, começa do topo', async () => {
  const { result, consultas } = await voltarA210()
  act(() => result.current.chegouNaVolta())
  cursoresPedidos.length = 0
  await act(() => consultas.resetQueries({ queryKey: ['acervo'] }))
  await waitFor(() => expect(result.current.item(0)?.id).toBe('j0'))
  expect(cursoresPedidos[0]).toBeNull()
})

test('uma página vazia com cursor (o teto da API) é seguida sozinha até chegar um vídeo', async () => {
  servidor.use(
    http.get('/v1/jobs', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor')
      cursoresPedidos.push(cursor)
      if (!cursor) return HttpResponse.json([], { headers: { 'X-Proximo-Cursor': 'vazio-1' } })
      if (cursor === 'vazio-1') return HttpResponse.json([], { headers: { 'X-Proximo-Cursor': 'vazio-2' } })
      return HttpResponse.json(jobs.slice(0, 3))
    }),
  )
  const { result } = await montar()

  await waitFor(() => expect(result.current.itens.map((j) => j.id)).toEqual(['j0', 'j1', 'j2']))
  expect(cursoresPedidos).toEqual([null, 'vazio-1', 'vazio-2'])
})
