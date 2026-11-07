import type { ClienteDaApi, ParDeQuadro } from './api.ts'
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

/** O teto de pares por pedido em lote da API. */
const PARES_POR_PEDIDO = 100

const dosClientes = new WeakMap<ClienteDaApi, (jobId: string, caminho: string) => Promise<string>>()

/**
 * O cache de quadros da busca: um por cliente da API, por (vídeo, arquivo). Os quadros pedidos no
 * mesmo instante (as cenas de uma página montam juntas) saem num `POST /v1/jobs/quadros` só, em
 * pedaços de 100. Um quadro sem URL (vídeo na lixeira, não concluído) ou uma falha não ficam guardados.
 */
export function urlDoQuadroDaBusca(api: ClienteDaApi): (jobId: string, caminho: string) => Promise<string> {
  let achado = dosClientes.get(api)
  if (!achado) {
    type Espera = { par: ParDeQuadro; resolver: (r: Reproducao) => void; recusar: (e: unknown) => void }
    let fila: Espera[] = []
    const enviar = async () => {
      const lote = fila
      fila = []
      for (let i = 0; i < lote.length; i += PARES_POR_PEDIDO) {
        const pedaco = lote.slice(i, i + PARES_POR_PEDIDO)
        try {
          const respostas = await api.quadros(pedaco.map((e) => e.par))
          for (const espera of pedaco) {
            const r = respostas.find((q) => q.job === espera.par.job && q.arquivo === espera.par.arquivo)
            if (r?.url && r.expira_em) espera.resolver({ url: r.url, expira_em: r.expira_em })
            else espera.recusar(new Error('Quadro indisponível'))
          }
        } catch (erro) {
          for (const espera of pedaco) espera.recusar(erro)
        }
      }
    }
    const caches = new Map<string, (caminho: string) => Promise<string>>()
    achado = (jobId, caminho) => {
      const arquivo = caminho.slice(caminho.lastIndexOf('/') + 1)
      const chave = `${jobId}/${arquivo}`
      let cache = caches.get(chave)
      if (!cache) {
        cache = criarCacheDeQuadros(
          (nome) =>
            new Promise<Reproducao>((resolver, recusar) => {
              if (fila.length === 0) setTimeout(() => void enviar(), 0)
              fila.push({ par: { job: jobId, arquivo: nome }, resolver, recusar })
            }),
        )
        caches.set(chave, cache)
      }
      return cache(caminho)
    }
    dosClientes.set(api, achado)
  }
  return achado
}
