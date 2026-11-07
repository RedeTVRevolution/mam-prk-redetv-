import { useQuery, type QueryKey } from '@tanstack/react-query'
import type { PaginaDaBusca } from '../../api.ts'
import { consultaDaImagemParaApi, consultaParaApi, type ConsultaDaBusca, type Momento, type VideoDoResultado } from '../../busca.ts'
import { finalizando, SEM_FILTROS, type Job } from '../../jobs.ts'
import { useApi } from '../consultas.ts'
import { usePaginas } from '../paginas.ts'

/** Vídeos por página na busca por texto e na por foto (o padrão da API). */
const VIDEOS_POR_PAGINA = 20
/**
 * A busca fica 5 min no cache depois de sair da tela (o cursor vale 15): voltar do vídeo nesse
 * tempo não a refaz. Enquanto está no cache, não se refaz sozinha: refazer pediria de novo todas
 * as páginas da memória, contra o limite de buscas por minuto.
 */
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

function cenasDa(pagina: PaginaDaBusca): Cena[] {
  return pagina.videos.flatMap((video) => video.momentos.map((momento, i) => ({ chave: `${video.job_id}:${i}`, video, momento })))
}
const cenasDaBusca = (ps: PaginaDaBusca[]) => ps.flatMap(cenasDa)
const tamanhoNaBusca = (p: PaginaDaBusca) => cenasDa(p).length
const proximoDaBusca = (p: PaginaDaBusca) => p.proximo

const chaveDa = (pedido: PedidoDaBusca | null): QueryKey => {
  if (!pedido) return ['busca', 'nada']
  if (pedido.tipo === 'texto') return ['busca', 'texto', pedido.consulta.q, consultaParaApi(pedido.consulta, VIDEOS_POR_PAGINA)]
  return ['busca', 'imagem', pedido.id, consultaDaImagemParaApi(pedido.consulta, VIDEOS_POR_PAGINA)]
}

/**
 * A busca paginada por cursor, com as cenas numa lista só (#400, #426). O mesmo termo com outro
 * chip, filtro ou ordem mantém a lista anterior à vista até a nova chegar; termo novo ou foto nova
 * recomeçam pelo carregamento (#396).
 */
export function useBusca(pedido: PedidoDaBusca | null) {
  const api = useApi()
  const chave = chaveDa(pedido)
  const termo = pedido?.tipo === 'texto' ? pedido.consulta.q : null
  return usePaginas({
    chave,
    pedir: (cursor) => {
      if (pedido?.tipo === 'texto') return api.buscar(pedido.consulta, VIDEOS_POR_PAGINA, cursor)
      return api.buscarPorImagem(pedido!.foto, pedido!.consulta, VIDEOS_POR_PAGINA, cursor)
    },
    proximo: proximoDaBusca,
    itens: cenasDaBusca,
    tamanho: tamanhoNaBusca,
    staleTime: Infinity,
    gcTime: VALIDADE,
    // Todas as páginas ficam: a API corta em 500 vídeos (25 páginas de 20). Sem página tirada do
    // alto, subir não pede a primeira de novo, que abriria uma lista nova na API (outro cursor).
    paginasNaMemoria: 0,
    enabled: pedido !== null,
    retry: false,
    manterAnterior: (anterior) => termo !== null && anterior[0] === 'busca' && anterior[1] === 'texto' && anterior[2] === termo,
  })
}

/**
 * Quantos vídeos ainda estão entrando na busca (#404): a regra do selo "Finalizando". Confere a
 * cada `intervaloMs` enquanto houver algum (o aviso some quando a indexação termina) e a cada
 * `ociosoMs` quando não há (o vídeo que termina depois também avisa). Só confere com `ativo`
 * (há o que buscar); desligado, devolve 0.
 * ponytail: só os 50 concluídos mais recentes; um vídeo finalizando mais antigo que eles não conta.
 */
export function useEntrandoNaBusca(ativo: boolean, intervaloMs = 15_000, ociosoMs = 60_000): number {
  const api = useApi()
  const contar = (jobs: Job[] | undefined) => (jobs ?? []).filter((j) => finalizando(j)).length
  const q = useQuery({
    queryKey: ['entrando-na-busca'],
    queryFn: () => api.acervo({ ...SEM_FILTROS, estado: ['concluido'] }),
    refetchInterval: (c) => (contar(c.state.data?.jobs) > 0 ? intervaloMs : ociosoMs),
    enabled: ativo,
  })
  return ativo ? contar(q.data?.jobs) : 0
}
