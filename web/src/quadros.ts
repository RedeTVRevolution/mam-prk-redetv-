import type { ClienteDaApi } from './api.ts'
import type { Reproducao } from './decupagem.ts'

/** Folga antes do vencimento: uma URL que vence em segundos já não vale. */
const MARGEM_MS = 30_000

/**
 * Busca a URL assinada do quadro de um momento e a guarda enquanto vale, para as linhas do
 * painel não pedirem de novo. `caminho` é o campo `quadro` da decupagem (`quadros/plano-0.jpg`).
 * Uma falha não fica guardada: a próxima linha a pedir tenta de novo.
 */
export function criarCacheDeQuadros(
  buscar: (arquivo: string) => Promise<Reproducao>,
): (caminho: string) => Promise<string> {
  const guardadas = new Map<string, { url: Promise<string>; venceEm: number }>()
  return (caminho) => {
    const achada = guardadas.get(caminho)
    if (achada && achada.venceEm - MARGEM_MS > Date.now()) return achada.url
    const arquivo = caminho.slice(caminho.lastIndexOf('/') + 1)
    const entrada = {
      venceEm: Number.POSITIVE_INFINITY,
      url: buscar(arquivo).then(({ url, expira_em }) => {
        entrada.venceEm = Date.parse(expira_em)
        return url
      }),
    }
    entrada.url.catch(() => {
      if (guardadas.get(caminho) === entrada) guardadas.delete(caminho)
    })
    guardadas.set(caminho, entrada)
    return entrada.url
  }
}

const dosClientes = new WeakMap<ClienteDaApi, (jobId: string, caminho: string) => Promise<string>>()

/** O cache de quadros da busca: um por cliente da API, com um cache por vídeo (a rota do quadro é do vídeo). */
export function urlDoQuadroDaBusca(api: ClienteDaApi): (jobId: string, caminho: string) => Promise<string> {
  let achado = dosClientes.get(api)
  if (!achado) {
    const porVideo = new Map<string, (caminho: string) => Promise<string>>()
    achado = (jobId, caminho) => {
      let cache = porVideo.get(jobId)
      if (!cache) {
        cache = criarCacheDeQuadros((arquivo) => api.job(jobId).quadro(arquivo))
        porVideo.set(jobId, cache)
      }
      return cache(caminho)
    }
    dosClientes.set(api, achado)
  }
  return achado
}
