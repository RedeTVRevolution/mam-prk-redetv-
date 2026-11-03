import type { Usuario } from './App.tsx'
import type { Autenticador } from './auth/autenticador.ts'
import { consultaDaImagemParaApi, consultaParaApi, type ConsultaDaBusca, type ResultadoDaBusca } from './busca.ts'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import { filtrosParaApi, type FiltrosDoAcervo, type Job, type JobCriado, type PaginaDoAcervo } from './jobs.ts'
import type { FiltrosDeMarcas, RelatorioDeMarcas } from './marcas.ts'
import type { FiltrosDoRelatorio, RelatorioDeTempoDeTela } from './tempoDeTela.ts'
import { parametrosDoRelatorio } from './tempoDeTela.ts'
import type { ComparacaoDaPassada, ResumoDaPassada } from './passadas.ts'
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

export type EventoDeRevisao = 'inicio' | 'atividade' | 'fim'

/** Um Job visto pela API: a única porta da tela do vídeo para `/v1/jobs/{id}/...`. */
export interface ClienteDoJob {
  detalhe(): Promise<Job>
  reproducao(): Promise<Reproducao>
  /** URL assinada do JPEG `arquivo` (`plano-0.jpg`) de um momento da decupagem. */
  quadro(arquivo: string): Promise<Reproducao>
  decupagem(): Promise<Decupagem>
  /** As passadas de comparação do Job (exige `decupagem.ver`). */
  passadas(): Promise<ResumoDaPassada[]>
  /** O Job contra uma passada, com cada item marcado (igual, difere, só de um lado). */
  comparacao(passadaId: string): Promise<ComparacaoDaPassada>
  /** As fotos de referência que sustentam o nome da pessoa (exige `decupagem.ver`). */
  fotosDoNome(pessoaId: string): Promise<FotosDoNome>
  /** Avisa que a pessoa começou, segue ou terminou de revisar (exige `decupagem.editar`). */
  pulsoDeRevisao(evento: EventoDeRevisao): Promise<void>
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

/** Um nome do catálogo de pessoas ou de marcas (ou um tipo de objeto já visto), como o autocompletar o mostra. */
export interface NomeDoCatalogo {
  id: string
  nome: string
  /** "Sabrina Sato (apresentadora)" nas pessoas, "camiseta (3)" nos tipos de objeto. */
  rotulo?: string
  a_revisar: boolean
}

/** `tipos_de_objeto` só sugere (`GET /v1/objetos/tipos`): não há nome a criar. */
export type CatalogoDeNomes = 'pessoas' | 'marcas' | 'tipos_de_objeto'

/** O autocompletar dos campos de nome (exige `decupagem.ver`; criar exige `decupagem.editar`). */
export interface ClienteDeNomes {
  achar(catalogo: CatalogoDeNomes, q: string): Promise<NomeDoCatalogo[]>
  /** Nome novo, "a revisar"; se o nome já existe devolve o existente. */
  criar(catalogo: CatalogoDeNomes, nome: string): Promise<NomeDoCatalogo>
}

/** Uma conta da administração (`/v1/admin/usuarios`). */
export interface ContaDaLista {
  uid: string
  email: string
  nome: string
  papeis: string[]
  criada_em: string | null
  ultimo_acesso: string | null
  situacao: 'ativa' | 'desativada'
}

/** Contas e papéis (exige `usuarios.gerir`). */
export interface ClienteDeUsuarios {
  listar(): Promise<ContaDaLista[]>
  criar(corpo: { email: string; nome: string; papeis: string[] }): Promise<ContaDaLista>
  reenviarLink(uid: string): Promise<void>
  trocarPapeis(uid: string, papeis: string[]): Promise<ContaDaLista>
  desativar(uid: string): Promise<ContaDaLista>
  reativar(uid: string): Promise<ContaDaLista>
}

/** Uma chave de API da administração (`/v1/admin/chaves`); a chave em texto nunca vem na lista. */
export interface ChaveDaLista {
  id: string
  sistema: string
  escopos: string[]
  criada_em: string
  revogada_em: string | null
}

/** A resposta da emissão: a única vez em que a chave em texto sai da API. */
export interface ChaveEmitida extends ChaveDaLista {
  chave: string
}

/** Sistemas e chaves de API (exige `chaves.gerir`). */
export interface ClienteDeChaves {
  listar(): Promise<ChaveDaLista[]>
  emitir(corpo: { sistema: string; escopos: string[] }): Promise<ChaveEmitida>
  revogar(id: string): Promise<ChaveDaLista>
}

export interface ClienteDaApi {
  eu(): Promise<Usuario>
  /** Uma página do acervo; `cursor` é o `proximo` da página anterior. */
  acervo(filtros: FiltrosDoAcervo, cursor?: string | null): Promise<PaginaDoAcervo>
  criarJob(corpo: object): Promise<JobCriado>
  programas(): Promise<string[]>
  /** `GET /v1/busca`: vídeos com os momentos em que a consulta aparece. */
  buscar(consulta: ConsultaDaBusca, limite: number): Promise<ResultadoDaBusca>
  /** `POST /v1/busca/imagem`: a foto é a consulta; só programa e período da `consulta` valem. */
  buscarPorImagem(foto: File, consulta: ConsultaDaBusca, limite: number): Promise<ResultadoDaBusca>
  /** `GET /v1/busca/parecidos`: os planos mais próximos do quadro de um plano (o próprio fica fora). */
  buscarParecidos(job: string, plano: number, limite: number): Promise<ResultadoDaBusca>
  /** `GET /v1/busca/parecidos/planos`: os números dos planos do vídeo com vetor do quadro indexado. */
  planosComVetor(job: string): Promise<number[]>
  /** `GET /v1/relatorios/tempo-de-tela`: tempo de tela por pessoa, contando só aparições. */
  tempoDeTela(filtros: FiltrosDoRelatorio): Promise<RelatorioDeTempoDeTela>
  /** O mesmo relatório em CSV. */
  tempoDeTelaEmCsv(filtros: FiltrosDoRelatorio): Promise<Blob>
  /** `GET /v1/relatorios/marcas`: inserções, tempo e vídeos por marca e por tipo de inserção. */
  marcas(filtros: FiltrosDeMarcas): Promise<RelatorioDeMarcas>
  /** O mesmo relatório em CSV. */
  marcasEmCsv(filtros: FiltrosDeMarcas): Promise<Blob>
  nomes: ClienteDeNomes
  usuarios: ClienteDeUsuarios
  chaves: ClienteDeChaves
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
    opcoes: { post?: true; put?: true; corpo?: object; formulario?: FormData } = {},
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
      method: opcoes.post ? 'POST' : opcoes.put ? 'PUT' : undefined,
      headers,
      // Com `FormData` o navegador monta o Content-Type do multipart, com o limite.
      body: opcoes.formulario ?? (opcoes.corpo === undefined ? undefined : JSON.stringify(opcoes.corpo)),
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
    opcoes: { post?: true; put?: true; corpo?: object; formulario?: FormData } = {},
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
      passadas: () => chamar(`${base}/passadas`),
      comparacao: (passadaId) => chamar(`${base}/passadas/${encodeURIComponent(passadaId)}/comparacao`),
      fotosDoNome: (pessoaId) => chamar(`${base}/pessoas/${encodeURIComponent(pessoaId)}/referencias`),
      pulsoDeRevisao: async (evento) => {
        await pedir(`${base}/revisao/pulso`, { post: true, corpo: { evento } })
      },
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
    buscarPorImagem: (foto, consulta, limite) => {
      const formulario = new FormData()
      formulario.append('arquivo', foto)
      return chamar(`/v1/busca/imagem?${consultaDaImagemParaApi(consulta, limite)}`, { post: true, formulario })
    },
    buscarParecidos: (job, plano, limite) =>
      chamar(`/v1/busca/parecidos?${new URLSearchParams({ job, plano: String(plano), limite: String(limite) })}`),
    planosComVetor: async (job) =>
      (await chamar<{ planos: number[] }>(`/v1/busca/parecidos/planos?${new URLSearchParams({ job })}`)).planos,
    tempoDeTela: (filtros) => chamar(`/v1/relatorios/tempo-de-tela?${parametrosDoRelatorio(filtros)}`),
    tempoDeTelaEmCsv: async (filtros) =>
      (await pedir(`/v1/relatorios/tempo-de-tela?${parametrosDoRelatorio(filtros, 'csv')}`)).blob(),
    marcas: (filtros) => chamar(`/v1/relatorios/marcas?${parametrosDoRelatorio(filtros, undefined, { tipo: filtros.tipo })}`),
    marcasEmCsv: async (filtros) =>
      (await pedir(`/v1/relatorios/marcas?${parametrosDoRelatorio(filtros, 'csv', { tipo: filtros.tipo })}`)).blob(),
    nomes: {
      achar: async (catalogo, q) => {
        if (catalogo !== 'tipos_de_objeto') return chamar(`/v1/catalogo/${catalogo}?q=${encodeURIComponent(q)}`)
        const tipos = await chamar<{ tipo: string; ocorrencias: number }[]>(`/v1/objetos/tipos?q=${encodeURIComponent(q)}`)
        return tipos.map((t) => ({ id: t.tipo, nome: t.tipo, rotulo: `${t.tipo} (${t.ocorrencias})`, a_revisar: false }))
      },
      criar: (catalogo, nome) => {
        if (catalogo === 'tipos_de_objeto') return Promise.reject(new Error('Tipo de objeto não tem catálogo para criar.'))
        return chamar(`/v1/catalogo/${catalogo}`, { post: true, corpo: { nome } })
      },
    },
    usuarios: {
      listar: () => chamar('/v1/admin/usuarios'),
      criar: (corpo) => chamar('/v1/admin/usuarios', { post: true, corpo }),
      reenviarLink: async (uid) => {
        await pedir(`/v1/admin/usuarios/${encodeURIComponent(uid)}/link-de-senha`, { post: true })
      },
      trocarPapeis: (uid, papeis) =>
        chamar(`/v1/admin/usuarios/${encodeURIComponent(uid)}/papeis`, { put: true, corpo: { papeis } }),
      desativar: (uid) => chamar(`/v1/admin/usuarios/${encodeURIComponent(uid)}/desativar`, { post: true }),
      reativar: (uid) => chamar(`/v1/admin/usuarios/${encodeURIComponent(uid)}/reativar`, { post: true }),
    },
    chaves: {
      listar: () => chamar('/v1/admin/chaves'),
      emitir: (corpo) => chamar('/v1/admin/chaves', { post: true, corpo }),
      revogar: (id) => chamar(`/v1/admin/chaves/${encodeURIComponent(id)}/revogar`, { post: true }),
    },
    job,
  }
}
