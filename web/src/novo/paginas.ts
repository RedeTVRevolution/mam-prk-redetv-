import { hashKey, useInfiniteQuery, useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { codigoDoErro, PedidoInvalido } from '../api.ts'

/** Páginas na memória ao mesmo tempo: no acervo, 6 × 50 = 300 vídeos; o resto sai (ADR 0014). */
export const PAGINAS_NA_MEMORIA = 6
/** Pede a página anterior antes de o esqueleto aparecer ao subir; para baixo, a folga são os 10 do fim. */
const FOLGA_PARA_CIMA = 20
const FOLGA_PARA_BAIXO = 10

/** O 422 de um cursor que a API não aceita mais (vencido ou de outra consulta): a lista recomeça. */
export class CursorVencido extends PedidoInvalido {}

/**
 * O cursor de cada página por onde a consulta passou, na ordem, e quantos itens ela tinha: a
 * página n se pede com o da posição n, e a primeira com `''` (o `null` faria o TanStack achar que
 * não há página antes). A API só tem cursor para frente; para voltar, o navegador usa o que
 * guardou (uns 100 bytes por página). Fica fora do cache: a volta do vídeo depois do `gcTime`
 * recomeça da página certa. Um mapa por prefixo da chave (`acervo`, `busca`).
 */
interface Guardados {
  cursores: string[]
  tamanhos: number[]
}
interface DoPrefixo {
  consultas: Map<string, Guardados>
  /**
   * Onde a lista estava ao sair (abrir um vídeo): o primeiro item à vista, pelo índice. Uma por
   * prefixo: acervo, vídeo, volta e volta encontra o acervo onde estava.
   */
  posicao: { chave: string; indice: number } | null
}
// Por cliente, como o cache: os cursores e a posição de outro cliente (outra sessão) não valem aqui.
const guardados = new WeakMap<QueryClient, Map<unknown, DoPrefixo>>()

function doPrefixo(cliente: QueryClient, prefixo: unknown): DoPrefixo {
  let prefixos = guardados.get(cliente)
  if (!prefixos) guardados.set(cliente, (prefixos = new Map()))
  let d = prefixos.get(prefixo)
  if (!d) prefixos.set(prefixo, (d = { consultas: new Map(), posicao: null }))
  return d
}

function guardadosDa(cliente: QueryClient, prefixo: unknown, hash: string): Guardados {
  const { consultas } = doPrefixo(cliente, prefixo)
  let g = consultas.get(hash)
  if (!g) consultas.set(hash, (g = { cursores: [''], tamanhos: [] }))
  return g
}

/** `chave` é o hash de uma consulta já na tela: ela diz o prefixo. */
export function lembrarPosicao(cliente: QueryClient, chave: string, indice: number) {
  for (const d of guardados.get(cliente)?.values() ?? []) if (d.consultas.has(chave)) d.posicao = { chave, indice }
}

/** Depois de voltar ao lugar: daqui em diante a consulta recomeça do topo (um envio novo, por exemplo). */
function esquecerPosicao(cliente: QueryClient, prefixo: unknown) {
  doPrefixo(cliente, prefixo).posicao = null
}

/** Onde começa a página `n`: a soma dos itens das de antes, todas já vistas (só se chega a ela descendo). */
const inicioDa = (tamanhos: number[], n: number) => {
  let soma = 0
  for (let i = 0; i < n; i++) soma += tamanhos[i] ?? 0
  return soma
}

/** A página onde está o item `indice`, pelos tamanhos guardados; `-1` se passa das já vistas. */
function paginaDo(tamanhos: number[], indice: number): number {
  let soma = 0
  for (let n = 0; n < tamanhos.length; n++) {
    soma += tamanhos[n]
    if (indice < soma) return n
  }
  return -1
}

/** O índice a que voltar e a página dele, se a última saída foi desta consulta e o cursor dela ainda está guardado. */
function volta(cliente: QueryClient, prefixo: unknown, hash: string, g: Guardados): { indice: number; cursor: string } {
  const p = doPrefixo(cliente, prefixo).posicao
  const n = p?.chave === hash ? paginaDo(g.tamanhos, p.indice) : -1
  return n >= 0 && g.cursores[n] !== undefined ? { indice: p!.indice, cursor: g.cursores[n] } : { indice: 0, cursor: '' }
}

export interface OpcoesDasPaginas<P, I> {
  /** O primeiro elemento é o prefixo (`acervo`, `busca`). */
  chave: QueryKey
  /** Uma página; `''` é a primeira. */
  pedir: (cursor: string) => Promise<P>
  proximo: (pagina: P) => string | null | undefined
  /** As páginas da memória numa lista só. */
  itens: (paginas: P[]) => I[]
  /** Quantos itens a página ocupa na lista: o lugar das páginas que saíram da memória. */
  tamanho: (pagina: P) => number
  staleTime?: number
  /** Quanto a consulta fica no cache depois de sair da tela; sem ele, os 30 s do cliente. */
  gcTime?: number
  /** Páginas na memória; `0`, todas (a lista da API já tem teto). */
  paginasNaMemoria?: number
  enabled?: boolean
  /** A busca não se repete sozinha: um 429 ou um 504 repetido só piora. */
  retry?: false
  /** Outra consulta com a lista na tela: a anterior fica à vista até a nova chegar (#396). */
  manterAnterior?: (chaveAnterior: QueryKey) => boolean
}

/**
 * Uma lista paginada por cursor: no máximo PAGINAS_NA_MEMORIA de cada vez, nos dois sentidos.
 * `item(i)` devolve o item se a página dele está na memória; senão `null` (a tela desenha o
 * esqueleto), e `aoVer` pede a página que falta. Um cursor recusado (422) recomeça do topo.
 */
export function usePaginas<P, I>(opcoes: OpcoesDasPaginas<P, I>) {
  const { chave, pedir, proximo, itens: juntar, tamanho, manterAnterior } = opcoes
  const cliente = useQueryClient()
  const hash = hashKey(chave)
  const g = guardadosDa(cliente, chave[0], hash)
  const lista = g.cursores
  const [recomecos, setRecomecos] = useState(0)
  // O índice da volta é o da montagem (a tela rola até ele uma vez). O cursor inicial se calcula a
  // cada vez: depois de `esquecerPosicao` (um envio refaz a lista) ou de outro filtro e volta, ele
  // é o do topo.
  const [voltaInicial, setVoltaInicial] = useState(() => volta(cliente, chave[0], hash, g).indice)
  const q = useInfiniteQuery({
    queryKey: chave,
    queryFn: async ({ pageParam }) => {
      try {
        return await pedir(pageParam)
      } catch (erro) {
        throw pageParam && erro instanceof PedidoInvalido ? new CursorVencido(erro.message) : erro
      }
    },
    // Volta do vídeo com o cache já vencido: recomeça na página do item de onde se saiu.
    initialPageParam: volta(cliente, chave[0], hash, g).cursor,
    getNextPageParam: (ultima: P, _todas, ultimoParam: string) => {
      const seguinte = proximo(ultima)
      if (!seguinte) return undefined
      const n = lista.indexOf(ultimoParam)
      if (n >= 0 && lista[n + 1] !== seguinte) {
        lista.splice(n + 1, Infinity, seguinte)
        g.tamanhos.splice(n + 1, Infinity)
      }
      return seguinte
    },
    getPreviousPageParam: (_primeira, _todas, primeiroParam: string) => {
      const n = lista.indexOf(primeiroParam)
      return n > 0 ? lista[n - 1] : undefined
    },
    maxPages: opcoes.paginasNaMemoria ?? PAGINAS_NA_MEMORIA,
    staleTime: opcoes.staleTime,
    ...(opcoes.gcTime !== undefined && { gcTime: opcoes.gcTime }),
    enabled: opcoes.enabled,
    ...(opcoes.retry === false && { retry: false }),
    // Um recomeço da mesma consulta não mostra as páginas de antes, com os cursores vencidos.
    placeholderData: manterAnterior
      ? (anterior, consulta?: { queryHash: string; queryKey: QueryKey }) =>
          consulta && consulta.queryHash !== hash && manterAnterior(consulta.queryKey) ? anterior : undefined
      : undefined,
  })

  const params = q.data?.pageParams as string[] | undefined
  const primeira = Math.max(0, params ? lista.indexOf(params[0]) : 0)
  const inicio = q.isPlaceholderData ? 0 : inicioDa(g.tamanhos, primeira)
  const itens = useMemo(() => juntar(q.data?.pages ?? []), [q.data, juntar])
  const quantidade = q.data ? inicio + itens.length + (q.hasNextPage && !q.isPlaceholderData ? 1 : 0) : 0
  const item = useCallback((i: number): I | null => itens[i - inicio] ?? null, [itens, inicio])

  const { fetchNextPage, fetchPreviousPage, hasNextPage, isFetching, isFetchNextPageError, isFetchPreviousPageError, isPlaceholderData } = q
  const aoVer = useCallback(
    (de: number, ate: number) => {
      // Uma de cada vez: pedir a outra no meio cancelaria a primeira. A grade pode chamar de novo
      // antes de este estado mudar (ela redesenha sozinha ao rolar): o pedido em curso fica.
      if (isFetching || isPlaceholderData || isFetchNextPageError || isFetchPreviousPageError) return
      if (primeira > 0 && de < inicio + FOLGA_PARA_CIMA) void fetchPreviousPage({ cancelRefetch: false })
      else if (hasNextPage && ate >= quantidade - FOLGA_PARA_BAIXO) void fetchNextPage({ cancelRefetch: false })
    },
    [primeira, inicio, quantidade, hasNextPage, isFetching, isPlaceholderData, isFetchNextPageError, isFetchPreviousPageError, fetchNextPage, fetchPreviousPage],
  )

  // O lugar de cada página, depois das mudanças locais (a lixeira tira um item): quando ela sai da
  // memória, os itens de depois não andam uma casa.
  const { data, isPlaceholderData: anterior } = q
  useEffect(() => {
    if (!data || anterior) return
    data.pages.forEach((p, i) => (g.tamanhos[primeira + i] = tamanho(p)))
  }, [data, anterior, primeira, g, tamanho])

  // Uma página pedida para cima pode trazer outro `proximo` (entrou item novo no topo): a de baixo,
  // pedida com o cursor antigo, pularia itens. As páginas da memória se pedem de novo, uma vez.
  const conferida = useRef<unknown>(null)
  useEffect(() => {
    if (!data || anterior || isFetching || conferida.current === data) return
    conferida.current = data
    const params = data.pageParams as string[]
    if (data.pages.some((p, i) => i + 1 < params.length && (proximo(p) ?? undefined) !== params[i + 1])) void q.refetch()
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [data, anterior, isFetching, proximo])

  // O teto vale por consulta: a de outro filtro ou outra ordem sai já, em vez de ficar o gcTime
  // inteiro no cache somando mais páginas. Os cursores dela saem junto.
  useEffect(() => {
    cliente.removeQueries({ queryKey: [chave[0]], type: 'inactive', predicate: (c) => c.queryHash !== hash })
    const { consultas } = doPrefixo(cliente, chave[0])
    for (const outra of consultas.keys()) if (outra !== hash) consultas.delete(outra)
    // `chave` entra pelo hash.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [cliente, hash])

  // O cursor venceu (15 min na busca) ou a lista dele sumiu: a consulta recomeça da primeira página.
  // Um 422 de novo sem ter passado da primeira página desde o recomeço seria um laço (a API recusa
  // o cursor que acabou de dar): fica o erro ao paginar, e "tentar de novo" recomeça.
  const [semAndar, setSemAndar] = useState<string | null>(null)
  // Outra consulta, ou esta de novo depois de outra (o teto apagou os cursores): vale o primeiro 422.
  if (semAndar !== null && (semAndar !== hash || (data && !anterior && (data.pageParams as string[]).some(Boolean)))) setSemAndar(null)
  const vencido = q.error instanceof CursorVencido
  const recomeca = vencido && semAndar !== hash
  const recomecar = () => {
    g.cursores.splice(0, Infinity, '')
    g.tamanhos.length = 0
    esquecerPosicao(cliente, chave[0])
    setVoltaInicial(0)
    cliente.removeQueries({ queryKey: chave, exact: true })
    setRecomecos((n) => n + 1)
    setSemAndar(hash)
  }
  useEffect(() => {
    if (recomeca) recomecar()
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [recomeca, cliente, hash])

  const prefixo = chave[0]
  const chegouNaVolta = useCallback(() => {
    esquecerPosicao(cliente, prefixo)
    // Redesenha com as opções novas: o `resetQueries` do envio usa o `initialPageParam` da última.
    setVoltaInicial(0)
  }, [cliente, prefixo])

  const falhou = q.isError && !recomeca
  return {
    chave: hash,
    /** O índice do item a que a tela volta ao montar (0: o topo). */
    voltaInicial,
    /** A tela chegou à volta: a consulta recomeça do topo daqui em diante (o envio refaz a lista). */
    chegouNaVolta,
    /** Quantas vezes a consulta recomeçou do topo por um cursor vencido. */
    recomecos,
    quantidade,
    item,
    itens,
    paginas: q.data?.pages,
    aoVer,
    // Desligada (`enabled` falso), a consulta fica pendente sem pedir nada: não está carregando.
    // Pausada sem rede, está: o esqueleto fica até a rede voltar, em vez da lista vazia.
    carregando: (q.isPending && opcoes.enabled !== false) || recomeca,
    /** A lista da consulta anterior está na tela enquanto esta não chega. */
    atualizando: isPlaceholderData,
    haMais: hasNextPage && !isPlaceholderData,
    primeiraNaMemoria: primeira === 0,
    falha: falhou && !q.data ? q.error : null,
    erro: falhou && !q.data ? codigoDoErro(q.error) : null,
    erroAoPaginar: falhou && (isFetchNextPageError || isFetchPreviousPageError) ? codigoDoErro(q.error) : null,
    tentarDeNovo: () => {
      if (vencido) recomecar()
      else if (isFetchPreviousPageError) void fetchPreviousPage()
      else if (isFetchNextPageError) void fetchNextPage()
      else void q.refetch()
    },
  }
}
