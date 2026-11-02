import type { Usuario } from './App.tsx'
import type { Autenticador } from './auth/autenticador.ts'
import { consultaParaApi, type ConsultaDaBusca, type ResultadoDaBusca } from './busca.ts'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import { filtrosParaApi, type FiltrosDoAcervo, type Job, type JobCriado, type PaginaDoAcervo } from './jobs.ts'
import type { Decupagem, ItemDaFila, ItemDoHistorico, Reproducao, Sugestao } from './decupagem.ts'

/** 401 ou sessão sem token. O cliente já avisou quem o criou; quem chama só não mostra erro. */
export class SessaoExpirada extends Error {}

/** 409: o estado mudou no servidor. A mensagem é o `detail` da API. */
export class ConflitoNaApi extends Error {}

/** 422: o pedido não foi aceito. A mensagem é o `detail` da API. */
export class PedidoInvalido extends Error {}

export class NaoEncontrado extends Error {}

/** Qualquer outro status de erro. */
export class FalhaNaApi extends Error {
  readonly status: number

  constructor(status: number) {
    super(`Falha ${status}`)
    this.status = status
  }
}

/** O código para o suporte de uma falha da API. */
export function codigoDoErro(erro: unknown): string {
  if (erro instanceof FalhaNaApi) return `http_${erro.status}`
  if (erro instanceof NaoEncontrado) return 'http_404'
  if (erro instanceof ConflitoNaApi) return 'http_409'
  if (erro instanceof PedidoInvalido) return 'http_422'
  return 'api_inacessivel'
}

async function detalhe(resposta: Response): Promise<string> {
  try {
    const { detail } = (await resposta.json()) as { detail?: unknown }
    if (typeof detail === 'string') return detail
    if (detail !== undefined) return JSON.stringify(detail)
  } catch {
    // Corpo vazio ou que não é JSON: fica a mensagem padrão.
  }
  return `Falha ${resposta.status}`
}

/** Uma foto de referência de um nome: o resultado da conferência é em palavras, nunca uma porcentagem. */
export interface FotoDoNome {
  url: string
  /** Vazia quando a página de origem não é um endereço web. */
  pagina_url: string
  dominio: string
  resultado: 'confere' | 'nao_confere' | null
}

export interface FotosDoNome {
  fotos: FotoDoNome[]
  expira_em: string
}

/** Um Job visto pela API: a única porta da tela do vídeo para `/v1/jobs/{id}/...`. */
export interface ClienteDoJob {
  detalhe(): Promise<Job>
  reproducao(): Promise<Reproducao>
  /** URL assinada do JPEG `arquivo` (`plano-0.jpg`) de um momento da decupagem. */
  quadro(arquivo: string): Promise<Reproducao>
  decupagem(): Promise<Decupagem>
  /** As fotos de referência que sustentam o nome da pessoa (exige `decupagem.ver`). */
  fotosDoNome(pessoaId: string): Promise<FotosDoNome>
  catalogo(): Promise<CatalogoDeCorrecoes>
  historico(): Promise<ItemDoHistorico[]>
  fila(): Promise<ItemDaFila[]>
  corrigir(corpo: object): Promise<void>
  sugestoes(): Promise<Sugestao[]>
  /** Aceita a sugestão; `valor` é o "outro nome" (ou o título) do editor. */
  aceitarSugestao(sugestaoId: string, valor?: string): Promise<void>
  recusarSugestao(sugestaoId: string): Promise<void>
  desfazer(correcaoId: string, motivo: string): Promise<void>
  recusar(correcaoId: string, motivo: string): Promise<void>
  aprovar(correcaoId: string): Promise<void>
  reaplicar(itemId: string, candidato: string | null, motivo: string): Promise<void>
  descartar(itemId: string, motivo: string): Promise<void>
  /** `POST /v1/jobs/{id}/reprocessar` numa etapa escolhida (exige `video.reprocessar_etapa`). */
  reprocessar(etapa: string, motivo: string): Promise<Job>
}

/** Um nome do catálogo de pessoas ou de marcas, como o autocompletar o mostra. */
export interface NomeDoCatalogo {
  id: string
  nome: string
  /** "Sabrina Sato (apresentadora)": só as pessoas têm. */
  rotulo?: string
  a_revisar: boolean
}

export type CatalogoDeNomes = 'pessoas' | 'marcas'

/** O autocompletar dos campos de nome (exige `decupagem.ver`; criar exige `decupagem.editar`). */
export interface ClienteDeNomes {
  achar(catalogo: CatalogoDeNomes, q: string): Promise<NomeDoCatalogo[]>
  /** Nome novo, "a revisar"; se o nome já existe devolve o existente. */
  criar(catalogo: CatalogoDeNomes, nome: string): Promise<NomeDoCatalogo>
}

export interface ClienteDaApi {
  eu(): Promise<Usuario>
  /** Uma página do acervo; `cursor` é o `proximo` da página anterior. */
  acervo(filtros: FiltrosDoAcervo, cursor?: string | null): Promise<PaginaDoAcervo>
  criarJob(corpo: object): Promise<JobCriado>
  programas(): Promise<string[]>
  /** `GET /v1/busca`: vídeos com os momentos em que a consulta aparece. */
  buscar(consulta: ConsultaDaBusca, limite: number): Promise<ResultadoDaBusca>
  nomes: ClienteDeNomes
  job(id: string): ClienteDoJob
}

/**
 * Cliente de `/v1` com o token da sessão. É o único lugar que conhece caminhos, token e
 * status HTTP; `aoSessaoExpirada` é chamado a cada 401 (ou sessão sem token); quem o liga decide
 * o que fazer com avisos repetidos.
 */
export function criarClienteDaApi(
  autenticador: Autenticador,
  aoSessaoExpirada: () => void,
): ClienteDaApi {
  async function pedir(
    caminho: string,
    opcoes: { post?: true; corpo?: object } = {},
  ): Promise<Response> {
    const token = await autenticador.token()
    if (!token) {
      aoSessaoExpirada()
      throw new SessaoExpirada()
    }
    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    }
    if (opcoes.corpo !== undefined) headers['Content-Type'] = 'application/json'
    const resposta = await fetch(caminho, {
      method: opcoes.post ? 'POST' : undefined,
      headers,
      body: opcoes.corpo === undefined ? undefined : JSON.stringify(opcoes.corpo),
    })
    if (resposta.status === 401) {
      aoSessaoExpirada()
      throw new SessaoExpirada()
    }
    if (!resposta.ok) {
      if (resposta.status === 409) throw new ConflitoNaApi(await detalhe(resposta))
      if (resposta.status === 422) throw new PedidoInvalido(await detalhe(resposta))
      if (resposta.status === 404) throw new NaoEncontrado(await detalhe(resposta))
      throw new FalhaNaApi(resposta.status)
    }
    return resposta
  }

  async function chamar<T>(
    caminho: string,
    opcoes: { post?: true; corpo?: object } = {},
  ): Promise<T> {
    return (await (await pedir(caminho, opcoes)).json()) as T
  }

  function job(id: string): ClienteDoJob {
    const base = `/v1/jobs/${id}`
    return {
      detalhe: () => chamar(base),
      reproducao: () => chamar(`${base}/reproducao`),
      quadro: (arquivo) => chamar(`${base}/quadros/${encodeURIComponent(arquivo)}`),
      decupagem: () => chamar(`${base}/decupagem`),
      fotosDoNome: (pessoaId) => chamar(`${base}/pessoas/${encodeURIComponent(pessoaId)}/referencias`),
      catalogo: () => chamar('/v1/correcoes/catalogo'),
      historico: () => chamar(`${base}/correcoes`),
      fila: () => chamar(`${base}/fila`),
      corrigir: (corpo) => chamar(`${base}/correcoes`, { post: true, corpo }),
      sugestoes: () => chamar(`${base}/sugestoes`),
      aceitarSugestao: (sugestaoId, valor) =>
        chamar(`${base}/sugestoes/${sugestaoId}/aceitar`, {
          post: true,
          corpo: valor === undefined ? undefined : { valor },
        }),
      recusarSugestao: async (sugestaoId) => {
        await pedir(`${base}/sugestoes/${sugestaoId}/recusar`, { post: true })
      },
      desfazer: (correcaoId, motivo) =>
        chamar(`${base}/correcoes/${correcaoId}/desfazer`, {
          post: true,
          corpo: { motivo },
        }),
      recusar: (correcaoId, motivo) =>
        chamar(`${base}/correcoes/${correcaoId}/recusar`, {
          post: true,
          corpo: { motivo },
        }),
      aprovar: (correcaoId) => chamar(`${base}/correcoes/${correcaoId}/aprovar`, { post: true }),
      reaplicar: (itemId, candidato, motivo) =>
        chamar(`${base}/fila/${itemId}/reaplicar`, {
          post: true,
          corpo: { item_id: candidato, motivo },
        }),
      descartar: (itemId, motivo) =>
        chamar(`${base}/fila/${itemId}/descartar`, {
          post: true,
          corpo: { motivo },
        }),
      reprocessar: (etapa, motivo) =>
        chamar(`${base}/reprocessar`, { post: true, corpo: { etapa, motivo } }),
    }
  }

  return {
    eu: () => chamar('/v1/eu'),
    acervo: async (filtros, cursor = null) => {
      const resposta = await pedir(`/v1/jobs?${filtrosParaApi(filtros, cursor)}`)
      return {
        jobs: (await resposta.json()) as Job[],
        proximo: resposta.headers.get('X-Proximo-Cursor'),
      }
    },
    criarJob: (corpo) => chamar('/v1/jobs', { post: true, corpo }),
    programas: () => chamar('/v1/programas'),
    buscar: (consulta, limite) => chamar(`/v1/busca?${consultaParaApi(consulta, limite)}`),
    nomes: {
      achar: (catalogo, q) => chamar(`/v1/catalogo/${catalogo}?q=${encodeURIComponent(q)}`),
      criar: (catalogo, nome) => chamar(`/v1/catalogo/${catalogo}`, { post: true, corpo: { nome } }),
    },
    job,
  }
}
