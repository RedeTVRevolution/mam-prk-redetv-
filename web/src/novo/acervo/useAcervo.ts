import { hashKey, useInfiniteQuery, useQueryClient, type InfiniteData, type QueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { codigoDoErro, SessaoExpirada } from '../../api.ts'
import { ESTADOS_DO_JOB } from '../../cores.ts'
import { finalizando, MAXIMO_DO_ANDAMENTO, POR_PAGINA, type FiltrosDoAcervo, type Job, type PaginaDoAcervo } from '../../jobs.ts'
import { useApi } from '../consultas.ts'

/** Páginas na memória ao mesmo tempo: 6 × 50 = 300 vídeos; o resto sai (ADR 0014). */
export const PAGINAS_NA_MEMORIA = 6
/** Pede a página anterior antes de o esqueleto aparecer ao subir; para baixo, a folga são os 10 do fim. */
const FOLGA_PARA_CIMA = 20
const FOLGA_PARA_BAIXO = 10

const NAO_TERMINAIS = Object.keys(ESTADOS_DO_JOB).filter((e) => e !== 'concluido' && e !== 'falhou' && e !== 'cancelado')

export const chaveDoAcervo = (filtros: FiltrosDoAcervo) => ['acervo', filtros] as const

/**
 * O cursor de cada página por onde a consulta passou, na ordem: a página n se pede com o da
 * posição n, e a primeira com `''` (o `null` faria o TanStack achar que não há página antes).
 * A API só tem cursor para frente; para voltar, o navegador usa o que guardou (uns 100 bytes
 * por página). Fica fora do cache: a volta do vídeo depois do `gcTime` recomeça da página certa.
 */
const cursores = new WeakMap<QueryClient, Map<string, string[]>>()

function cursoresDa(cliente: QueryClient, hash: string): string[] {
  let doCliente = cursores.get(cliente)
  if (!doCliente) cursores.set(cliente, (doCliente = new Map()))
  let lista = doCliente.get(hash)
  if (!lista) doCliente.set(hash, (lista = ['']))
  return lista
}

/** Onde o acervo estava ao sair (abrir um vídeo): o primeiro vídeo à vista, pelo índice. */
let posicaoAoSair: { chave: string; indice: number } | null = null

export function lembrarPosicao(chave: string, indice: number) {
  posicaoAoSair = { chave, indice }
}

/** Depois de voltar ao lugar: daqui em diante a consulta recomeça do topo (um envio novo, por exemplo). */
export function esquecerPosicao() {
  posicaoAoSair = null
}

/** O índice a que voltar, se a última saída foi desta mesma consulta. */
export function posicaoDaVolta(chave: string): number {
  return posicaoAoSair?.chave === chave ? posicaoAoSair.indice : 0
}

/**
 * O acervo paginado: no máximo PAGINAS_NA_MEMORIA de cada vez, nos dois sentidos. `item(i)`
 * devolve o vídeo se a página dele está na memória; senão `null` (a tela desenha o esqueleto),
 * e `aoVer` pede a página que falta.
 */
export function useAcervo(filtros: FiltrosDoAcervo) {
  const api = useApi()
  const cliente = useQueryClient()
  const chave = chaveDoAcervo(filtros)
  const hash = hashKey(chave)
  const lista = cursoresDa(cliente, hash)
  const q = useInfiniteQuery({
    queryKey: chave,
    queryFn: ({ pageParam }) => api.acervo(filtros, pageParam),
    // Volta do vídeo com o cache já vencido: recomeça na página do vídeo de onde se saiu.
    initialPageParam: lista[Math.floor(posicaoDaVolta(hash) / POR_PAGINA)] ?? '',
    getNextPageParam: (ultima: PaginaDoAcervo, _todas, ultimoParam: string) => {
      if (!ultima.proximo) return undefined
      const n = lista.indexOf(ultimoParam)
      if (n >= 0 && lista[n + 1] !== ultima.proximo) lista.splice(n + 1, Infinity, ultima.proximo)
      return ultima.proximo
    },
    getPreviousPageParam: (_primeira, _todas, primeiroParam: string) => {
      const n = lista.indexOf(primeiroParam)
      return n > 0 ? lista[n - 1] : undefined
    },
    maxPages: PAGINAS_NA_MEMORIA,
    // Voltar do vídeo não repete as 6 páginas; o que está em andamento se atualiza à parte.
    staleTime: 60_000,
  })

  const params = q.data?.pageParams as string[] | undefined
  const primeira = Math.max(0, params ? lista.indexOf(params[0]) : 0)
  const inicio = primeira * POR_PAGINA
  // As páginas da memória numa lista só: a do andamento e a da lixeira podem ter perdido um vídeo.
  const itens = useMemo(() => q.data?.pages.flatMap((p) => p.jobs) ?? [], [q.data])
  const quantidade = q.data ? inicio + itens.length + (q.hasNextPage ? 1 : 0) : 0
  const item = useCallback((i: number): Job | null => itens[i - inicio] ?? null, [itens, inicio])

  const { fetchNextPage, fetchPreviousPage, hasNextPage, isFetching, isFetchNextPageError, isFetchPreviousPageError } = q
  const aoVer = useCallback(
    (de: number, ate: number) => {
      // Uma de cada vez: pedir a outra no meio cancelaria a primeira.
      if (isFetching || isFetchNextPageError || isFetchPreviousPageError) return
      if (primeira > 0 && de < inicio + FOLGA_PARA_CIMA) void fetchPreviousPage()
      else if (hasNextPage && ate >= quantidade - FOLGA_PARA_BAIXO) void fetchNextPage()
    },
    [primeira, inicio, quantidade, hasNextPage, isFetching, isFetchNextPageError, isFetchPreviousPageError, fetchNextPage, fetchPreviousPage],
  )

  // O teto vale por consulta: a de outro filtro ou outra ordem sai já, em vez de ficar o gcTime
  // inteiro no cache somando mais 300 vídeos. Os cursores dela saem junto.
  useEffect(() => {
    cliente.removeQueries({ queryKey: ['acervo'], type: 'inactive', predicate: (c) => c.queryHash !== hash })
    const doCliente = cursores.get(cliente)
    for (const outra of doCliente?.keys() ?? []) if (outra !== hash) doCliente!.delete(outra)
  }, [cliente, hash])

  return {
    chave: hash,
    quantidade,
    item,
    itens,
    aoVer,
    carregando: q.isPending,
    erro: q.isError && !q.data ? codigoDoErro(q.error) : null,
    erroAoPaginar: isFetchNextPageError || isFetchPreviousPageError ? codigoDoErro(q.error) : null,
    tentarDeNovo: () => {
      if (isFetchPreviousPageError) void fetchPreviousPage()
      else if (isFetchNextPageError) void fetchNextPage()
      else void q.refetch()
    },
  }
}

/** Põe o Job que a API devolveu (um reprocessamento) no lugar do da lista, com a capa da lista. */
export function trocarNoAcervo(cliente: QueryClient, novo: Job) {
  cliente.setQueriesData<InfiniteData<PaginaDoAcervo>>({ queryKey: ['acervo'] }, (d) =>
    d && { ...d, pages: d.pages.map((p) => ({ ...p, jobs: p.jobs.map((j) => (j.id === novo.id ? { ...novo, capa_url: j.capa_url } : j)) })) },
  )
}

/** Tira um vídeo das páginas da memória (foi para a lixeira ou sumiu), sem pedir a lista de novo. */
export function tirarDoAcervo(cliente: QueryClient, ids: Set<string>) {
  cliente.setQueriesData<InfiniteData<PaginaDoAcervo>>({ queryKey: ['acervo'] }, (d) =>
    d && { ...d, pages: d.pages.map((p) => ({ ...p, jobs: p.jobs.filter((j) => !ids.has(j.id)) })) },
  )
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
        // O andamento não traz a capa (só a listagem assina a URL): fica a da lista. Quem a rota
        // omite (foi para a lixeira ou sumiu) sai.
        const atualiza = (j: Job): Job[] => {
          if (!pedidos.has(j.id)) return [j]
          const novo = novos.get(j.id)
          return novo ? [{ ...novo, capa_url: j.capa_url }] : []
        }
        cliente.setQueryData<InfiniteData<PaginaDoAcervo>>(chave, (d) => d && { ...d, pages: d.pages.map((p) => ({ ...p, jobs: p.jobs.flatMap(atualiza) })) })
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
