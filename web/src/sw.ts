// O service worker do cache de imagens (`cacheDeImagens.ts`). O Vite o publica em `/sw.js`, na raiz,
// o que dá ao worker o escopo `/` sem cabeçalho extra. Quem não passa em `cuidaDoPedido` nem chega a
// `respondWith`: o navegador segue pela rede como se o worker não existisse.
import { cuidaDoPedido, NOME_DO_CACHE, responderImagem } from './cacheDeImagens.ts'

// O `tsconfig` usa a lib DOM, que não tem os tipos de worker: só o que este arquivo usa.
interface EventoComEspera {
  waitUntil(trabalho: Promise<unknown>): void
}
interface EventoDeBusca {
  request: Request
  respondWith(resposta: Promise<Response>): void
}
const worker = self as unknown as {
  addEventListener(tipo: 'install', ouvinte: (e: EventoComEspera) => void): void
  addEventListener(tipo: 'activate', ouvinte: (e: EventoComEspera) => void): void
  addEventListener(tipo: 'fetch', ouvinte: (e: EventoDeBusca) => void): void
  skipWaiting(): Promise<void>
  clients: { claim(): Promise<void> }
}

// Assume as abas abertas já na primeira visita, para as capas dela entrarem no cache.
worker.addEventListener('install', (e) => e.waitUntil(worker.skipWaiting()))
worker.addEventListener('activate', (e) => e.waitUntil(worker.clients.claim()))

worker.addEventListener('fetch', (e) => {
  if (!cuidaDoPedido(e.request)) return
  e.respondWith(
    caches
      .open(NOME_DO_CACHE)
      .then((cache) =>
        responderImagem(e.request, {
          cache,
          buscar: (entrada, init) => fetch(entrada as Request | string, init),
          agora: Date.now,
        }),
      )
      // Sem o Cache Storage, o pedido segue pela rede.
      .catch(() => fetch(e.request)),
  )
})
