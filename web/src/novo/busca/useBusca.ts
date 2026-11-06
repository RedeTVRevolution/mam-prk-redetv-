import { useQuery, type QueryKey } from '@tanstack/react-query'
import type { PaginaDaBusca } from '../../api.ts'
import { consultaDaImagemParaApi, consultaParaApi, type ConsultaDaBusca, type Momento, type VideoDoResultado } from '../../busca.ts'
import { finalizando, SEM_FILTROS, type Job } from '../../jobs.ts'
import { useApi } from '../consultas.ts'
import { usePaginas } from '../paginas.ts'

/** Vídeos por página na busca por texto (o padrão da API) e planos na por imagem e nos parecidos. */
const VIDEOS_POR_PAGINA = 20
const PLANOS_POR_PAGINA = 50
/** O cursor da busca vale 15 min: voltar do vídeo dentro de 5 não refaz a busca. */
const VALIDADE = 5 * 60_000

/** Uma cena da grade: um momento, com o vídeo dele. */
export interface Cena {
  chave: string
  video: VideoDoResultado
  momento: Momento
}

export type PedidoDaBusca =
  | { tipo: 'texto'; consulta: ConsultaDaBusca }
  /** `id` muda a cada foto escolhida: o arquivo não entra na chave. */
  | { tipo: 'imagem'; foto: File; id: number; consulta: ConsultaDaBusca }
  | { tipo: 'parecidos'; job: string; plano: number }

function cenasDa(pagina: PaginaDaBusca, soPlanos: boolean): Cena[] {
  return pagina.videos.flatMap((video) =>
    video.momentos.flatMap((momento, i) => (soPlanos && momento.tipo !== 'plano' ? [] : [{ chave: `${video.job_id}:${i}`, video, momento }])),
  )
}
// Na busca visual com o vetor do quadro, só os planos; a por imagem e os parecidos são só de planos.
const soPlanosNa = (p: PaginaDaBusca) => p.entendida.visual === true
const cenasDaBusca = (ps: PaginaDaBusca[]) => ps.flatMap((p) => cenasDa(p, soPlanosNa(p)))
const tamanhoNaBusca = (p: PaginaDaBusca) => cenasDa(p, soPlanosNa(p)).length
const cenasDosPlanos = (ps: PaginaDaBusca[]) => ps.flatMap((p) => cenasDa(p, true))
const tamanhoNosPlanos = (p: PaginaDaBusca) => cenasDa(p, true).length
const proximoDaBusca = (p: PaginaDaBusca) => p.proximo

const chaveDa = (pedido: PedidoDaBusca | null): QueryKey => {
  if (!pedido) return ['busca', 'nada']
  if (pedido.tipo === 'texto') return ['busca', 'texto', pedido.consulta.q, consultaParaApi(pedido.consulta, VIDEOS_POR_PAGINA)]
  if (pedido.tipo === 'imagem') return ['busca', 'imagem', pedido.id, consultaDaImagemParaApi(pedido.consulta, PLANOS_POR_PAGINA)]
  return ['busca', 'parecidos', pedido.job, pedido.plano]
}

/**
 * A busca paginada por cursor, com as cenas numa lista só (#400, #426). O mesmo termo com outro
 * chip, filtro ou ordem mantém a lista anterior à vista até a nova chegar; termo novo, foto nova ou
 * outro plano recomeçam pelo carregamento (#396).
 */
export function useBusca(pedido: PedidoDaBusca | null) {
  const api = useApi()
  const chave = chaveDa(pedido)
  const termo = pedido?.tipo === 'texto' ? pedido.consulta.q : null
  return usePaginas({
    chave,
    pedir: (cursor) => {
      if (pedido?.tipo === 'texto') return api.buscar(pedido.consulta, VIDEOS_POR_PAGINA, cursor)
      if (pedido?.tipo === 'imagem') return api.buscarPorImagem(pedido.foto, pedido.consulta, PLANOS_POR_PAGINA, cursor)
      return api.buscarParecidos(pedido!.job, pedido!.plano, PLANOS_POR_PAGINA, cursor)
    },
    proximo: proximoDaBusca,
    itens: pedido?.tipo === 'texto' ? cenasDaBusca : cenasDosPlanos,
    tamanho: pedido?.tipo === 'texto' ? tamanhoNaBusca : tamanhoNosPlanos,
    staleTime: VALIDADE,
    enabled: pedido !== null,
    retry: false,
    manterAnterior: (anterior) => termo !== null && anterior[1] === 'texto' && anterior[2] === termo,
  })
}

/**
 * Quantos vídeos ainda estão entrando na busca (#404): a regra do selo "Finalizando". Atualiza
 * sozinho enquanto houver algum, para o aviso sumir quando a indexação terminar.
 * ponytail: só os 50 concluídos mais recentes; um vídeo finalizando mais antigo que eles não conta.
 */
export function useEntrandoNaBusca(intervaloMs = 15_000): number {
  const api = useApi()
  const contar = (jobs: Job[] | undefined) => (jobs ?? []).filter((j) => finalizando(j)).length
  const q = useQuery({
    queryKey: ['entrando-na-busca'],
    queryFn: () => api.acervo({ ...SEM_FILTROS, estado: ['concluido'] }),
    refetchInterval: (c) => (contar(c.state.data?.jobs) > 0 ? intervaloMs : false),
  })
  return contar(q.data?.jobs)
}
