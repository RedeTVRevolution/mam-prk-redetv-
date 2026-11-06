import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { ReactNode } from 'react'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { consultaNova } from '../../busca.ts'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { useBusca, type PedidoDaBusca } from './useBusca.ts'

// 160 vídeos com um momento cada: 8 páginas de 20.
const videos = Array.from({ length: 160 }, (_, i) => ({
  job_id: `v${i}`,
  nome: `v${i}.mp4`,
  programa: null,
  data_exibicao: null,
  duracao_s: null,
  n_momentos: 1,
  momentos: [{ tipo: 'fala', inicio_ms: i * 1000, fim_ms: i * 1000 + 500, motivo: 'Fala: x', destaques: [], quadro_url: null, quadro: null }],
}))
const VAZIO = { programa: [], mes: [], pessoa: [], marca: [], tipo: [] }
const cursoresPedidos: (string | null)[] = []
// Os cursores que a API não aceita mais (vencidos): a resposta é 422.
let vencidos = new Set<string>()

const servidor = setupServer(
  http.get('/v1/busca', ({ request }) => {
    const p = new URL(request.url).searchParams
    const cursor = p.get('cursor')
    cursoresPedidos.push(cursor)
    if (cursor && vencidos.has(cursor)) return HttpResponse.json({ detail: 'Cursor inválido' }, { status: 422 })
    const inicio = cursor ? Number(cursor.slice(1)) + 1 : 0
    const pagina = videos.slice(inicio, inicio + Number(p.get('limite')))
    const ha = inicio + pagina.length < videos.length
    return HttpResponse.json(
      { entendida: { evidencias: ['fala'], programa: null, desde: null, ate: null }, videos: pagina, sem_aparicoes: [], plano_b: false, facetas: VAZIO },
      { headers: ha ? { 'X-Proximo-Cursor': `c${inicio + pagina.length - 1}` } : {} },
    )
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  cursoresPedidos.length = 0
  vencidos = new Set()
})
afterAll(() => servidor.close())

const TEXTO: PedidoDaBusca = { tipo: 'texto', consulta: consultaNova('x') }

async function montar(pedido: PedidoDaBusca = TEXTO) {
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
  const r = renderHook((p: PedidoDaBusca) => useBusca(p), { wrapper: envolver, initialProps: pedido })
  await waitFor(() => expect(r.result.current.quantidade).toBeGreaterThan(0))
  return { ...r, consultas }
}

async function descer(r: Awaited<ReturnType<typeof montar>>['result'], ate: number) {
  for (let p = 1; p <= ate; p++) {
    act(() => r.current.aoVer(p * 20 - 5, p * 20))
    await waitFor(() => expect(r.current.item(p * 20)).not.toBeNull())
  }
}

test('desce pelo X-Proximo-Cursor com 6 páginas na memória e sobe pelos cursores guardados', async () => {
  const { result } = await montar()
  await descer(result, 7)

  expect(result.current.item(159)?.video.job_id).toBe('v159')
  expect(result.current.haMais).toBe(false)
  // As páginas 0 e 1 saíram da memória: o lugar delas fica, sem a cena.
  expect(result.current.item(39)).toBeNull()
  expect(result.current.primeiraNaMemoria).toBe(false)
  expect(cursoresPedidos).toEqual([null, 'c19', 'c39', 'c59', 'c79', 'c99', 'c119', 'c139'])

  cursoresPedidos.length = 0
  act(() => result.current.aoVer(42, 50))
  await waitFor(() => expect(result.current.item(39)?.video.job_id).toBe('v39'))
  expect(cursoresPedidos).toEqual(['c19'])
  act(() => result.current.aoVer(22, 30))
  await waitFor(() => expect(result.current.item(0)?.video.job_id).toBe('v0'))
  expect(cursoresPedidos).toEqual(['c19', null])
  expect(result.current.primeiraNaMemoria).toBe(true)
})

test('o 422 de um cursor vencido recomeça a busca do topo, sem mostrar erro', async () => {
  const { result } = await montar()
  const doTopo = result.current.quantidade
  vencidos = new Set(['c19'])

  act(() => result.current.aoVer(15, 20))

  await waitFor(() => expect(result.current.recomecos).toBe(1))
  await waitFor(() => expect(result.current.item(0)?.video.job_id).toBe('v0'))
  expect(cursoresPedidos).toEqual([null, 'c19', null])
  expect(result.current.erro).toBeNull()
  expect(result.current.erroAoPaginar).toBeNull()
  expect(result.current.quantidade).toBe(doTopo)
})

test('o mesmo termo com outro chip mantém a lista anterior; termo novo não', async () => {
  const { result, rerender } = await montar()

  rerender({ tipo: 'texto', consulta: { ...consultaNova('x'), evidencias: ['fala'] } })
  expect(result.current.atualizando).toBe(true)
  expect(result.current.quantidade).toBe(20)
  await waitFor(() => expect(result.current.atualizando).toBe(false))

  rerender({ tipo: 'texto', consulta: consultaNova('y') })
  expect(result.current.carregando).toBe(true)
  expect(result.current.quantidade).toBe(0)
})
