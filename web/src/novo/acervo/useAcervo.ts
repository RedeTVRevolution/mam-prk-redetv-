import { hashKey, useQueryClient, type InfiniteData, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { codigoDoErro, SessaoExpirada, type PaginaDaBusca } from '../../api.ts'
import type { VideoDoResultado } from '../../busca.ts'
import { ESTADOS_DO_JOB } from '../../cores.ts'
import { finalizando, MAXIMO_DO_ANDAMENTO, type FiltrosDoAcervo, type Job, type PaginaDoAcervo } from '../../jobs.ts'
import { useApi } from '../consultas.ts'
import { usePaginas } from '../paginas.ts'

export { lembrarPosicao, PAGINAS_NA_MEMORIA } from '../paginas.ts'

const NAO_TERMINAIS = Object.keys(ESTADOS_DO_JOB).filter((e) => e !== 'concluido' && e !== 'falhou' && e !== 'cancelado')

export const chaveDoAcervo = (filtros: FiltrosDoAcervo) => ['acervo', filtros] as const

// As páginas da memória numa lista só: a do andamento e a da lixeira podem ter perdido um vídeo.
// Sem repetir: uma página refeita depois de uma exclusão avança um vídeo sobre a seguinte,
// que ainda começa pelo cursor antigo.
function semRepetir(paginas: PaginaDoAcervo[]): Job[] {
  const vistos = new Set<string>()
  return paginas.flatMap((p) => p.jobs).filter((j) => !vistos.has(j.id) && Boolean(vistos.add(j.id)))
}
const proximoDoAcervo = (p: PaginaDoAcervo) => p.proximo
// O lugar de uma página é o dos vídeos que ficaram nela: a que perdeu um para a lixeira ocupa 49.
const tamanhoDoAcervo = (p: PaginaDoAcervo) => p.jobs.length

/**
 * O acervo paginado: no máximo PAGINAS_NA_MEMORIA de cada vez, nos dois sentidos. `item(i)`
 * devolve o vídeo se a página dele está na memória; senão `null` (a tela desenha o esqueleto),
 * e `aoVer` pede a página que falta.
 */
export function useAcervo(filtros: FiltrosDoAcervo) {
  const api = useApi()
  return usePaginas({
    chave: chaveDoAcervo(filtros),
    pedir: (cursor) => api.acervo(filtros, cursor),
    proximo: proximoDoAcervo,
    itens: semRepetir,
    tamanho: tamanhoDoAcervo,
    // Voltar do vídeo não repete as 6 páginas; o que está em andamento se atualiza à parte.
    staleTime: 60_000,
  })
}

/** Muda os vídeos das páginas da busca na memória. */
function nasBuscas(cliente: QueryClient, mudar: (videos: VideoDoResultado[]) => VideoDoResultado[]) {
  cliente.setQueriesData<InfiniteData<PaginaDaBusca>>({ queryKey: ['busca'] }, (d) => d && { ...d, pages: d.pages.map((p) => ({ ...p, videos: mudar(p.videos) })) })
}

/** Muda os Jobs de cada página do acervo na memória. */
function nasPaginas(d: InfiniteData<PaginaDoAcervo> | undefined, mudar: (jobs: Job[]) => Job[]) {
  return d && { ...d, pages: d.pages.map((p) => ({ ...p, jobs: mudar(p.jobs) })) }
}

/**
 * Põe o Job que a API devolveu (um reprocessamento) no lugar do da lista, com a capa da lista. Na
 * busca, o vídeo leva os dados novos e fica com os momentos que a busca achou.
 */
export function trocarNoAcervo(cliente: QueryClient, novo: Job) {
  cliente.setQueriesData<InfiniteData<PaginaDoAcervo>>({ queryKey: ['acervo'] }, (d) =>
    nasPaginas(d, (jobs) => jobs.map((j) => (j.id === novo.id ? { ...novo, capa_url: j.capa_url } : j))),
  )
  const { nome, programa = null, data_exibicao = null, duracao_s = null } = novo
  nasBuscas(cliente, (videos) => videos.map((v) => (v.job_id === novo.id ? { ...v, nome, programa, data_exibicao, duracao_s } : v)))
}

/** Tira um vídeo das páginas da memória (foi para a lixeira ou sumiu), sem pedir a lista de novo; da busca também. */
export function tirarDoAcervo(cliente: QueryClient, ids: Set<string>) {
  cliente.setQueriesData<InfiniteData<PaginaDoAcervo>>({ queryKey: ['acervo'] }, (d) => nasPaginas(d, (jobs) => jobs.filter((j) => !ids.has(j.id))))
  nasBuscas(cliente, (videos) => videos.filter((v) => !ids.has(v.job_id)))
}

/**
 * Os vídeos em andamento na memória são consultados de novo a cada `intervaloMs`, só com a aba
 * à vista e um pedido por vez; o resto da lista não é pedido de novo. Devolve o código da falha
 * da última rodada, ou `null`.
 */
export function useAndamento(filtros: FiltrosDoAcervo, itens: Job[], intervaloMs: number): string | null {
  const api = useApi()
  const cliente = useQueryClient()
  const [falha, setFalha] = useState<string | null>(null)
  // Os vídeos cujo detalhe já foi pedido por terminarem sem capa na lista: um pedido só por vídeo.
  const capaPedida = useRef(new Set<string>())
  const ids = itens
    .filter((j) => NAO_TERMINAIS.includes(j.estado) || finalizando(j))
    .slice(0, MAXIMO_DO_ANDAMENTO)
    .map((j) => j.id)
    .join(',')
  const hash = hashKey(chaveDoAcervo(filtros))

  useEffect(() => {
    if (!ids) return
    let ativo = true
    let rodando = false
    const chave = chaveDoAcervo(filtros)
    async function atualizar() {
      if (document.visibilityState !== 'visible' || rodando) return
      rodando = true
      try {
        const pedidos = new Set(ids.split(','))
        const novos = new Map((await api.andamento([...pedidos])).map((n) => [n.id, n]))
        if (!ativo) return
        setFalha(null)
        // O andamento não traz a capa (só a listagem e o detalhe assinam a URL): fica a da lista.
        // Quem a rota omite (foi para a lixeira ou sumiu) sai.
        const atualiza = (j: Job): Job[] => {
          if (!pedidos.has(j.id)) return [j]
          const novo = novos.get(j.id)
          return novo ? [{ ...novo, capa_url: j.capa_url }] : []
        }
        const antes = cliente.getQueryData<InfiniteData<PaginaDoAcervo>>(chave)
        const semCapa = new Set(antes?.pages.flatMap((p) => p.jobs).filter((j) => !j.capa_url).map((j) => j.id))
        cliente.setQueryData<InfiniteData<PaginaDoAcervo>>(chave, (d) => nasPaginas(d, (jobs) => jobs.flatMap(atualiza)))
        // Saiu do andamento sem capa na lista: ela nasce durante o processamento, então o detalhe, que a traz, é pedido uma vez.
        for (const n of novos.values()) {
          if (NAO_TERMINAIS.includes(n.estado) || finalizando(n) || !semCapa.has(n.id) || capaPedida.current.has(n.id)) continue
          // Sem olhar `ativo`: o vídeo sair do andamento muda os ids e desmonta este efeito antes da resposta.
          capaPedida.current.add(n.id)
          void api.job(n.id).detalhe().then(
            ({ id, capa_url }) => {
              if (!capa_url) return
              cliente.setQueryData<InfiniteData<PaginaDoAcervo>>(chave, (d) => nasPaginas(d, (jobs) => jobs.map((j) => (j.id === id && !j.capa_url ? { ...j, capa_url } : j))))
            },
            () => {},
          )
        }
      } catch (erro) {
        if (ativo && !(erro instanceof SessaoExpirada)) setFalha(codigoDoErro(erro))
      } finally {
        rodando = false
      }
    }
    const relogio = setInterval(() => void atualizar(), intervaloMs)
    document.addEventListener('visibilitychange', atualizar)
    return () => {
      ativo = false
      clearInterval(relogio)
      document.removeEventListener('visibilitychange', atualizar)
    }
    // `filtros` entra pelo hash: o objeto da rota muda a cada navegação.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [api, cliente, hash, ids, intervaloMs])

  return ids ? falha : null
}
