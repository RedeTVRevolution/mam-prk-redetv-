import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { enviarRetomavel } from './upload.ts'

const PEDACO = 256 * 1024
const URL_ASSINADA = 'https://storage.exemplo/quarentena/j1?assinatura=x'
const SESSAO = 'https://storage.exemplo/sessao/abc'

// Cloud Storage simulado: guarda os bytes recebidos e responde como o protocolo retomável.
let recebido = 0
let inicios = 0
let falhasPendentes = 0
let sessaoPerdida = false
const faixas: string[] = []

function responderPedaco(request: Request) {
  const faixa = request.headers.get('Content-Range') ?? ''
  faixas.push(faixa)
  if (sessaoPerdida) return new HttpResponse(null, { status: 404 })
  const consulta = /^bytes \*\/(\d+)$/.exec(faixa)
  if (consulta) {
    return recebido === 0
      ? new HttpResponse(null, { status: 308 })
      : new HttpResponse(null, { status: 308, headers: { Range: `bytes=0-${recebido - 1}` } })
  }
  const [, de, ate, total] = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(faixa) ?? []
  if (falhasPendentes > 0 && Number(de) > 0) {
    falhasPendentes -= 1
    return new HttpResponse(null, { status: 503 })
  }
  if (Number(de) !== recebido) return new HttpResponse(null, { status: 400 })
  recebido = Number(ate) + 1
  return recebido === Number(total)
    ? new HttpResponse(null, { status: 200 })
    : new HttpResponse(null, { status: 308, headers: { Range: `bytes=0-${recebido - 1}` } })
}

const servidor = setupServer(
  http.post(URL_ASSINADA, ({ request }) => {
    expect(request.headers.get('x-goog-resumable')).toBe('start')
    expect(request.headers.get('x-goog-if-generation-match')).toBe('0')
    expect(request.headers.get('x-upload-content-length')).toBe(String(arquivo.size))
    inicios += 1
    return new HttpResponse(null, { status: 201, headers: { Location: SESSAO } })
  }),
  http.put(SESSAO, ({ request }) => responderPedaco(request)),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  recebido = 0
  inicios = 0
  falhasPendentes = 0
  sessaoPerdida = false
  faixas.length = 0
})
afterAll(() => servidor.close())

const arquivo = new File([new Uint8Array(PEDACO * 2 + 1000)], 'clipe.mp4', { type: 'video/mp4' })

test('envia em pedaços e informa o progresso até 100%', async () => {
  const progresso: number[] = []

  await enviarRetomavel(URL_ASSINADA, arquivo, {
    tamanhoDoPedaco: PEDACO,
    aoProgresso: (p) => progresso.push(p),
  })

  expect(recebido).toBe(arquivo.size)
  expect(inicios).toBe(1)
  expect(progresso.at(-1)).toBe(1)
  expect(progresso).toEqual([...progresso].sort((a, b) => a - b))
  expect(progresso.length).toBeGreaterThan(2)
})

test('uma falha no meio continua de onde parou, sem recomeçar', async () => {
  falhasPendentes = 1

  await enviarRetomavel(URL_ASSINADA, arquivo, { tamanhoDoPedaco: PEDACO, espera: async () => {} })

  expect(recebido).toBe(arquivo.size)
  expect(inicios).toBe(1)
  expect(faixas).toContain(`bytes */${arquivo.size}`)
})

test('desiste depois de falhas seguidas demais', async () => {
  falhasPendentes = 100

  await expect(
    enviarRetomavel(URL_ASSINADA, arquivo, {
      tamanhoDoPedaco: PEDACO,
      tentativas: 3,
      espera: async () => {},
    }),
  ).rejects.toThrow()
})

test('desiste logo quando o Storage não reconhece mais a sessão', async () => {
  sessaoPerdida = true

  await expect(
    enviarRetomavel(URL_ASSINADA, arquivo, { tamanhoDoPedaco: PEDACO, espera: async () => {} }),
  ).rejects.toThrow()
  expect(faixas).toHaveLength(1)
})
