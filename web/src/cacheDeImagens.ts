// O cache de imagens (fase 6 do plano da migração; ADR 0014): os quadros e as capas chegam por
// URL assinada do Storage, e a assinatura muda a cada janela. O service worker (`sw.ts`) guarda a
// imagem sob a URL sem os parâmetros da assinatura, para a mesma capa não ser baixada de novo.
// Este módulo é só regra: o `sw.ts` e as duas interfaces (no logout) o importam, e o vitest o testa.

/** Muda se o formato do que se guarda mudar: o cache antigo fica órfão e o logout o apaga com o resto. */
export const NOME_DO_CACHE = 'mam-imagens-v1'
/** O Storage já grava `Cache-Control: max-age=86400` nos quadros (#410): o cache não vive mais que isso. */
export const IDADE_MAXIMA_MS = 24 * 60 * 60 * 1000
export const MAX_ENTRADAS = 500
/** Um quadro ou capa tem dezenas de KB; algo maior que isto não é imagem do acervo e passa direto. */
export const MAX_BYTES_POR_IMAGEM = 1024 * 1024

/** Depois de uma recusa de CORS, o worker não tenta de novo por este tempo (cada tentativa baixa a imagem à toa). */
export const ESPERA_SEM_CORS_MS = 60 * 60 * 1000

const GUARDADO_EM = 'x-mam-guardado-em'
/** Onde fica anotada a recusa de CORS: no próprio cache, que o worker (de vida curta) não guarda em memória. */
const CHAVE_SEM_CORS = 'https://sem-cors.invalid/'
const HOST_DO_STORAGE = 'storage.googleapis.com'

/** O mínimo de um `Request` que a regra lê (o `Request` do navegador a satisfaz). */
export interface PedidoDeImagem {
  method: string
  url: string
  destination: string
  headers: { has(nome: string): boolean }
}

function assinada(url: URL): boolean {
  return [...url.searchParams.keys()].some((nome) => nome.toLowerCase() === 'x-goog-signature')
}

/**
 * Só o GET de `<img>` para uma URL assinada do Storage (o host `storage.googleapis.com`, sem nome de
 * bucket aqui). A API, o vídeo, os arquivos do próprio build e qualquer pedido com `Authorization`
 * ou `Range` passam direto.
 */
export function cuidaDoPedido(pedido: PedidoDeImagem): boolean {
  if (pedido.method !== 'GET' || pedido.destination !== 'image') return false
  if (pedido.headers.has('authorization') || pedido.headers.has('range')) return false
  let url: URL
  try {
    url = new URL(pedido.url)
  } catch {
    return false
  }
  const doStorage = url.hostname === HOST_DO_STORAGE || url.hostname.endsWith(`.${HOST_DO_STORAGE}`)
  return url.protocol === 'https:' && doStorage && assinada(url)
}

/** A chave do cache: a URL sem os `X-Goog-*` da assinatura (data, validade, assinatura) e sem o `#`. */
export function chaveSemAssinatura(url: string): string {
  const u = new URL(url)
  for (const nome of [...u.searchParams.keys()]) {
    if (nome.toLowerCase().startsWith('x-goog-')) u.searchParams.delete(nome)
  }
  u.hash = ''
  return u.toString()
}

export interface DependenciasDoCache {
  cache: Pick<Cache, 'match' | 'put' | 'delete' | 'keys'>
  buscar: (entrada: PedidoDeImagem | string, init?: RequestInit) => Promise<Response>
  agora: () => number
}

/** A entrada de `chave`, se tem o carimbo e menos de `idadeMaxima` ms; sem o carimbo (ou ilegível), não vale. */
async function recentes(
  cache: DependenciasDoCache['cache'],
  chave: string,
  agora: number,
  idadeMaxima: number,
): Promise<Response | undefined> {
  const entrada = await cache.match(chave, { ignoreVary: true })
  const carimbo = entrada?.headers.get(GUARDADO_EM)
  if (!entrada || carimbo == null) return undefined
  const idade = agora - Number(carimbo)
  return idade >= 0 && idade < idadeMaxima ? entrada : undefined
}

async function guardar(
  { cache, agora }: DependenciasDoCache,
  chave: string,
  corpo: Blob,
  tipo: string,
): Promise<void> {
  const copia = new Response(corpo, {
    headers: { 'content-type': tipo, [GUARDADO_EM]: String(agora()) },
  })
  await cache.put(chave, copia)
  // `keys()` vem na ordem de gravação: o que passa do teto é o mais antigo.
  const chaves = await cache.keys()
  for (const velha of chaves.slice(0, Math.max(0, chaves.length - MAX_ENTRADAS))) {
    await cache.delete(velha)
  }
}

/**
 * A resposta de uma imagem que `cuidaDoPedido` aceitou: do cache se estiver dentro da idade, senão da
 * rede, guardando o que vier bom. O pedido refeito é `cors` e sem credencial: assim a resposta não é
 * opaca (o status e o tamanho podem ser conferidos, e um 403 de URL vencida nunca é guardado). Se o
 * bucket não liberar o CORS, o pedido original segue pela rede e nada é guardado.
 */
export async function responderImagem(
  pedido: PedidoDeImagem,
  dependencias: DependenciasDoCache,
): Promise<Response> {
  const { cache, buscar, agora } = dependencias
  if (await recentes(cache, CHAVE_SEM_CORS, agora(), ESPERA_SEM_CORS_MS)) return buscar(pedido)
  const chave = chaveSemAssinatura(pedido.url)
  const guardada = await recentes(cache, chave, agora(), IDADE_MAXIMA_MS)
  if (guardada) return guardada
  await cache.delete(chave)
  let resposta: Response
  try {
    resposta = await buscar(pedido.url, { mode: 'cors', credentials: 'omit' })
  } catch {
    // Anota a recusa (ou a falta de rede) e segue como se o worker não existisse.
    const nota = new Response(null, { headers: { [GUARDADO_EM]: String(agora()) } })
    await cache.put(CHAVE_SEM_CORS, nota).catch(() => {})
    return buscar(pedido)
  }
  const tipo = resposta.headers.get('content-type') ?? ''
  if (!resposta.ok || !tipo.startsWith('image/')) return resposta
  const corpo = await resposta.blob()
  if (corpo.size <= MAX_BYTES_POR_IMAGEM) {
    // Cota cheia ou cache indisponível: a imagem chega do mesmo jeito, só não fica guardada.
    await guardar(dependencias, chave, corpo, tipo).catch(() => {})
  }
  return new Response(corpo, { status: 200, headers: { 'content-type': tipo } })
}

/** Apaga o cache de imagens: no logout, para a próxima pessoa do mesmo navegador não herdar os quadros. */
export async function limparCacheDeImagens(): Promise<void> {
  try {
    if (typeof caches !== 'undefined') await caches.delete(NOME_DO_CACHE)
  } catch {
    // Sem o Cache Storage (navegação privativa de alguns navegadores): não há o que apagar.
  }
}

/** Liga o service worker; só no build de produção, onde o `sw.js` existe. */
export function registrarCacheDeImagens(): void {
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return
  void navigator.serviceWorker
    .register(`${import.meta.env.BASE_URL}sw.js`, { type: 'module' })
    .catch(() => {
      // Sem o service worker as imagens só perdem o cache.
    })
}
