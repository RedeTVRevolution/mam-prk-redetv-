import { afterEach, expect, test, vi } from 'vitest'
import {
  chaveSemAssinatura,
  ESPERA_SEM_CORS_MS,
  cuidaDoPedido,
  IDADE_MAXIMA_MS,
  limparCacheDeImagens,
  MAX_BYTES_POR_IMAGEM,
  MAX_ENTRADAS,
  NOME_DO_CACHE,
  responderImagem,
  type DependenciasDoCache,
  type PedidoDeImagem,
} from './cacheDeImagens.ts'

afterEach(() => vi.unstubAllGlobals())

const ASSINATURA =
  'X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=mam-web%40p.iam&X-Goog-Date=20261106T120000Z&X-Goog-Expires=28800&X-Goog-SignedHeaders=host&X-Goog-Signature=abc123'
const QUADRO = 'https://storage.googleapis.com/algum-bucket/job-1/quadros/plano-0.jpg'

function pedido(url: string, extra: Partial<PedidoDeImagem> & { cabecalhos?: string[] } = {}): PedidoDeImagem {
  const { cabecalhos = [], ...resto } = extra
  return { method: 'GET', url, destination: 'image', headers: { has: (n) => cabecalhos.includes(n) }, ...resto }
}

test('a chave tira os X-Goog-* e o #, e mantém o resto', () => {
  expect(chaveSemAssinatura(`${QUADRO}?${ASSINATURA}`)).toBe(QUADRO)
  // A mesma capa em outra janela de assinatura tem a mesma chave.
  expect(chaveSemAssinatura(`${QUADRO}?${ASSINATURA.replace('abc123', 'zzz').replace('120000', '130000')}`)).toBe(QUADRO)
  expect(chaveSemAssinatura(`${QUADRO}?x-goog-signature=a&v=2#parte`)).toBe(`${QUADRO}?v=2`)
  // Outro quadro, outra chave.
  expect(chaveSemAssinatura(`${QUADRO.replace('plano-0', 'plano-1')}?${ASSINATURA}`)).not.toBe(QUADRO)
})

test('só o GET de imagem com URL assinada do Storage é do service worker', () => {
  expect(cuidaDoPedido(pedido(`${QUADRO}?${ASSINATURA}`))).toBe(true)
  // Estilo de host virtual do Storage.
  expect(cuidaDoPedido(pedido(`https://b.storage.googleapis.com/job-1/quadros/plano-0.jpg?${ASSINATURA}`))).toBe(true)

  const passam = [
    pedido(`${QUADRO}?${ASSINATURA}`, { method: 'POST' }),
    pedido(`${QUADRO}?${ASSINATURA}`, { destination: 'video' }),
    pedido(`${QUADRO}?${ASSINATURA}`, { destination: '' }),
    pedido(`${QUADRO}?${ASSINATURA}`, { cabecalhos: ['authorization'] }),
    pedido(`${QUADRO}?${ASSINATURA}`, { cabecalhos: ['range'] }),
    // Sem assinatura, host de fora, host que só termina parecido, http puro.
    pedido(QUADRO),
    pedido(`https://exemplo.com/q.jpg?${ASSINATURA}`),
    pedido(`https://storage.googleapis.com.exemplo.com/q.jpg?${ASSINATURA}`),
    pedido(`http://storage.googleapis.com/b/q.jpg?${ASSINATURA}`),
    // A API e o próprio build.
    pedido('https://mam.exemplo.com/v1/jobs'),
    pedido('https://mam.exemplo.com/assets/redetv-logo.png'),
    pedido('nao é url'),
  ]
  for (const p of passam) expect(cuidaDoPedido(p), p.url).toBe(false)
})

// Um Cache em memória, na ordem de gravação como o do navegador.
function cacheFalso() {
  const guardado = new Map<string, Response>()
  const url = (chave: RequestInfo | URL) => (chave instanceof Request ? chave.url : String(chave))
  const cache: DependenciasDoCache['cache'] = {
    match: async (chave) => guardado.get(url(chave))?.clone(),
    put: async (chave, resposta) => void guardado.set(url(chave), resposta),
    delete: async (chave) => guardado.delete(url(chave)),
    keys: async () => [...guardado.keys()].map((k) => new Request(k)),
  }
  return { guardado, cache }
}

function imagem(bytes = 10, tipo = 'image/jpeg') {
  return new Response(new Uint8Array(bytes), { headers: { 'content-type': tipo } })
}

function montar(resposta: () => Response | Promise<Response>) {
  const { guardado, cache } = cacheFalso()
  let agora = 1_000_000
  const buscar = vi.fn<DependenciasDoCache['buscar']>(async () => resposta())
  const dependencias: DependenciasDoCache = { cache, buscar, agora: () => agora }
  return { guardado, cache, buscar, dependencias, passar: (ms: number) => (agora += ms) }
}

test('a segunda vez, em outra assinatura, vem do cache sem ir à rede', async () => {
  const { dependencias, buscar, guardado } = montar(() => imagem(10))

  const primeira = await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)
  expect(primeira.status).toBe(200)
  expect(buscar).toHaveBeenCalledTimes(1)
  // O pedido refeito é cors e sem credencial: a resposta não é opaca.
  expect(buscar).toHaveBeenCalledWith(`${QUADRO}?${ASSINATURA}`, { mode: 'cors', credentials: 'omit' })
  expect([...guardado.keys()]).toEqual([QUADRO])

  const outra = `${QUADRO}?${ASSINATURA.replace('abc123', 'nova')}`
  const segunda = await responderImagem(pedido(outra), dependencias)
  expect(buscar).toHaveBeenCalledTimes(1)
  expect((await segunda.arrayBuffer()).byteLength).toBe(10)
})

test('passada a idade máxima, a entrada é descartada e baixada de novo', async () => {
  const { dependencias, buscar, passar } = montar(() => imagem(10))
  await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)

  passar(IDADE_MAXIMA_MS - 1)
  await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)
  expect(buscar).toHaveBeenCalledTimes(1)

  passar(1)
  await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)
  expect(buscar).toHaveBeenCalledTimes(2)
})

test('entrada sem o carimbo de idade não vale', async () => {
  const { dependencias, buscar, guardado } = montar(() => imagem(10))
  guardado.set(QUADRO, imagem(5))

  await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)

  expect(buscar).toHaveBeenCalledTimes(1)
})

test('não guarda erro, o que não é imagem nem o que passa do teto de bytes', async () => {
  for (const resposta of [
    () => new Response('vencida', { status: 403, headers: { 'content-type': 'image/jpeg' } }),
    () => new Response('<Error/>', { headers: { 'content-type': 'application/xml' } }),
    () => imagem(MAX_BYTES_POR_IMAGEM + 1),
  ]) {
    const { dependencias, guardado } = montar(resposta)
    await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)
    expect(guardado.size).toBe(0)
  }
})

test('o 403 de uma URL vencida chega à imagem como veio', async () => {
  const { dependencias } = montar(() => new Response('x', { status: 403, headers: { 'content-type': 'image/jpeg' } }))

  expect((await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)).status).toBe(403)
})

test('sem CORS no bucket, o pedido original segue pela rede e nenhuma imagem é guardada', async () => {
  const { dependencias, buscar, guardado } = montar(() => imagem(10))
  buscar.mockRejectedValueOnce(new TypeError('Failed to fetch'))
  const original = pedido(`${QUADRO}?${ASSINATURA}`)

  const resposta = await responderImagem(original, dependencias)

  expect(buscar).toHaveBeenLastCalledWith(original)
  expect(resposta.status).toBe(200)
  expect(guardado.has(QUADRO)).toBe(false)
})

test('depois da recusa de CORS, nem tenta o pedido cors até a espera passar', async () => {
  const { dependencias, buscar, passar } = montar(() => imagem(10))
  buscar.mockRejectedValueOnce(new TypeError('Failed to fetch'))
  const original = pedido(`${QUADRO}?${ASSINATURA}`)
  await responderImagem(original, dependencias)
  buscar.mockClear()

  await responderImagem(original, dependencias)
  // Só o pedido original, sem baixar a imagem duas vezes.
  expect(buscar.mock.calls).toEqual([[original]])

  buscar.mockClear()
  passar(ESPERA_SEM_CORS_MS)
  await responderImagem(original, dependencias)
  expect(buscar).toHaveBeenCalledWith(original.url, { mode: 'cors', credentials: 'omit' })
})

test('falha ao gravar (cota cheia) não impede a imagem', async () => {
  const { dependencias, cache } = montar(() => imagem(10))
  cache.put = async () => {
    throw new DOMException('cheio', 'QuotaExceededError')
  }

  const resposta = await responderImagem(pedido(`${QUADRO}?${ASSINATURA}`), dependencias)

  expect((await resposta.arrayBuffer()).byteLength).toBe(10)
})

test('passando do teto de entradas, saem as mais antigas', async () => {
  const { dependencias, guardado } = montar(() => imagem(1))
  for (let i = 0; i < MAX_ENTRADAS + 3; i++) {
    await responderImagem(pedido(`https://storage.googleapis.com/b/${i}.jpg?${ASSINATURA}`), dependencias)
  }

  expect(guardado.size).toBe(MAX_ENTRADAS)
  expect(guardado.has('https://storage.googleapis.com/b/0.jpg')).toBe(false)
  expect(guardado.has('https://storage.googleapis.com/b/2.jpg')).toBe(false)
  expect(guardado.has('https://storage.googleapis.com/b/3.jpg')).toBe(true)
  expect(guardado.has(`https://storage.googleapis.com/b/${MAX_ENTRADAS + 2}.jpg`)).toBe(true)
})

test('o logout apaga o cache de imagens, e não quebra sem o Cache Storage', async () => {
  const apagar = vi.fn(async () => true)
  vi.stubGlobal('caches', { delete: apagar })
  await limparCacheDeImagens()
  expect(apagar).toHaveBeenCalledWith(NOME_DO_CACHE)

  vi.stubGlobal('caches', {
    delete: async () => {
      throw new Error('indisponível')
    },
  })
  await expect(limparCacheDeImagens()).resolves.toBeUndefined()

  vi.unstubAllGlobals()
  await expect(limparCacheDeImagens()).resolves.toBeUndefined()
})
