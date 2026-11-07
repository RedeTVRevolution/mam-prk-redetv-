import type { Usuario } from './sessao.ts'
import type { Autenticador } from './auth/autenticador.ts'
import { consultaDaImagemParaApi, consultaParaApi, type ConsultaDaBusca, type ResultadoDaBusca } from './busca.ts'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import { consultaDaAuditoria, type FiltrosDaAuditoria, type PaginaDeAuditoria, type RegistroDeAuditoria } from './auditoria.ts'
import { consultaDasEntradas, type FiltrosDasEntradas } from './entradas.ts'
import { filtrosParaApi, type FiltrosDoAcervo, type Job, type JobCriado, type PaginaDoAcervo } from './jobs.ts'
import type { FiltrosDeMarcas, PaginaDeInsercoes, PaginaDeMarcas, RelatorioDeMarcas } from './marcas.ts'
import type { FiltrosDoRelatorio, PaginaDeVideos, PaginaDoTempoDeTela, RelatorioDeTempoDeTela } from './tempoDeTela.ts'
import {
  parametrosDoPainel,
  type Agrupado,
  type Agrupamento,
  type FilaAgora,
  type FiltrosDoPainel,
  type OpcoesDoPainel,
  type PedidoDeAgrupamento,
  type RelatorioDeAcessos,
  type RelatorioDeApi,
  type RelatorioDeCusto,
  type RelatorioDeBuscas,
  type RelatorioDeRevisao,
  type RelatorioDeVideos,
} from './painelDaDiretoria.ts'
import { parametrosDoRelatorio, POR_PAGINA_DO_DETALHE, POR_PAGINA_DO_RANKING } from './tempoDeTela.ts'
import type { ComparacaoDaPassada, ResumoDaPassada } from './passadas.ts'
import type { Decupagem, ItemDaFila, ItemDoHistorico, Reproducao, Sugestao } from './decupagem.ts'

/** 401 ou sessão sem token. O cliente já avisou quem o criou; quem chama só não mostra erro. */
export class SessaoExpirada extends Error {}

/** 409: o estado mudou no servidor. A mensagem é o `detail` da API. */
export class ConflitoNaApi extends Error {}

/** 422: o pedido não foi aceito. A mensagem é o `detail` da API. */
export class PedidoInvalido extends Error {}

export class NaoEncontrado extends Error {}

/** 403 `login_recente_exigido`: a purga pede um login com MFA feito há poucos minutos. */
export class LoginRecenteExigido extends Error {}

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

/** Uma página da busca: o próximo cursor vem no cabeçalho e some na última (#426). */
export type PaginaDaBusca = ResultadoDaBusca & { proximo?: string | null }

function comCursor(query: string, cursor: string | null | undefined): string {
  return cursor ? `${query}&${new URLSearchParams({ cursor })}` : query
}

async function paginaDaBusca(pedido: Promise<Response>): Promise<PaginaDaBusca> {
  const resposta = await pedido
  return { ...((await resposta.json()) as ResultadoDaBusca), proximo: resposta.headers.get('X-Proximo-Cursor') }
}

/** Uma foto de referência de um nome: o resultado da conferência é em palavras, nunca uma porcentagem. */
export type EventoDeRevisao = 'inicio' | 'atividade' | 'fim'

/** Um quadro pedido em lote: o vídeo e o arquivo (`plano-0.jpg`). */
export interface ParDeQuadro {
  job: string
  arquivo: string
}

/** A resposta do lote para um par: sem `url` (e sem `expira_em`) quando o quadro não pode ser dado. */
export interface QuadroDoLote extends ParDeQuadro {
  url: string | null
  expira_em: string | null
}

/** Um Job visto pela API: a única porta da tela do vídeo para `/v1/jobs/{id}/...`. */
export interface ClienteDoJob {
  detalhe(): Promise<Job>
  reproducao(): Promise<Reproducao>
  /** URL assinada do JPEG `arquivo` (`plano-0.jpg`) de um momento da decupagem. */
  quadro(arquivo: string): Promise<Reproducao>
  decupagem(): Promise<Decupagem>
  /** URL assinada para baixar o MP4; o download vai à auditoria (`video.baixado`). */
  baixarVideo(): Promise<Reproducao>
  /** O arquivo JSON da decupagem, pela rota do servidor que registra o download. */
  baixarDecupagem(): Promise<Blob>
  /** As passadas de comparação do Job (exige `decupagem.ver`). */
  passadas(): Promise<ResumoDaPassada[]>
  /** O Job contra uma passada, com cada item marcado (igual, difere, só de um lado). */
  comparacao(passadaId: string): Promise<ComparacaoDaPassada>
  /** As fotos de referência que sustentam o nome da pessoa (exige `decupagem.ver`). */
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
  /** `POST /v1/jobs/{id}/revisao/aprovar`: reindexa o vídeo uma vez, em segundo plano (responde 202 na hora). */
  aprovarRevisao(): Promise<void>
  reaplicar(itemId: string, candidato: string | null, motivo: string): Promise<void>
  descartar(itemId: string, motivo: string): Promise<void>
  /** `POST /v1/jobs/{id}/reprocessar` numa etapa escolhida (exige `video.reprocessar_etapa`). */
  reprocessar(etapa: string, motivo: string): Promise<Job>
  /** `POST /v1/jobs/{id}/reprocessar` sem etapa: recomeça da que falhou (exige `video.reprocessar`). */
  reprocessarOQueFalhou(motivo: string): Promise<Job>
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

/** O efeito de fundir uma pessoa do catálogo em outra (`GET /v1/catalogo/pessoas/{origem}/fundir/impacto`). */
export interface ImpactoDaFusao {
  origem_nome: string
  destino_nome: string
  videos: number
  aparicoes: number
  fotos_apagadas: number
}

/** Fundir duas pessoas do catálogo (exige `catalogo.fundir`). */
export interface ClienteDaFusao {
  impacto(origemId: string, destinoId: string): Promise<ImpactoDaFusao>
  /** A origem passa a apontar para o destino; as fotos de rosto dela são apagadas. */
  fundir(origemId: string, destinoId: string, motivo: string): Promise<void>
}

/** O efeito de renomear uma pessoa em todos os vídeos (`POST .../renomear`; com `previa` nada muda). */
export interface ImpactoDaRenomeacao {
  nome_antigo: string
  nome_novo: string
  videos: number
  momentos_afetados: number
  previa: boolean
}

/** O andamento da reindexação depois de renomear: `falhou` espera `retomar`. */
export interface AndamentoDaRenomeacao {
  estado: 'em_andamento' | 'concluida' | 'falhou'
  feitos: number
  total: number
  nome_antigo: string
  nome_novo: string
}

/** Renomear uma pessoa do catálogo em todos os vídeos (exige `correcao.aprovar`). */
export interface ClienteDaRenomeacao {
  previa(pessoaId: string, nome: string): Promise<ImpactoDaRenomeacao>
  renomear(pessoaId: string, nome: string): Promise<ImpactoDaRenomeacao>
  andamento(pessoaId: string): Promise<AndamentoDaRenomeacao>
  retomar(pessoaId: string): Promise<AndamentoDaRenomeacao>
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

/** Um tipo de correção e se ele exige a aprovação do Curador (`/v1/admin/aprovacao`). */
export interface RegraDeAprovacao {
  tipo: string
  nome: string
  exige_aprovacao: boolean
}

/** As regras de aprovação (exige `aprovacao.definir`): a lista e a mudança de um tipo por vez. */
export interface ClienteDeAprovacao {
  listar(): Promise<RegraDeAprovacao[]>
  mudar(tipo: string, exigeAprovacao: boolean): Promise<RegraDeAprovacao[]>
}

export type TipoDeItem = 'video' | 'pessoa' | 'marca'

/** Um item da lixeira (`/v1/admin/lixeira`). */
export interface ItemDaLixeira {
  tipo: string
  id: string
  nome: string
  enviado_por: string
  enviado_em: string
  motivo: string
  dias_ate_a_purga: number
}

/** O que vai junto com o vídeo, antes de confirmar. */
export interface ImpactoDoVideo {
  decupagem: number
  correcoes: number
  arquivos: { copia_limpa: number; proxy: number; quadros: number }
  /** Outros envios do mesmo arquivo: a decupagem continua para eles. */
  outros_jobs: { id: string; nome: string; enviado_por: string }[]
}

export interface ImpactoDaPessoa {
  aparicoes_que_perdem_o_nome: number
  fotos_apagadas: number
}

export interface ImpactoDaMarca {
  ocorrencias_que_perdem_o_vinculo: number
}

export interface ImpactoPorTipo {
  video: ImpactoDoVideo
  pessoa: ImpactoDaPessoa
  marca: ImpactoDaMarca
}

/** A lixeira: mandar, restaurar e purgar (enviar exige `lixeira.gerir` ou `catalogo.apagar`; o resto, `lixeira.gerir`). */
export interface ClienteDaLixeira {
  listar(): Promise<ItemDaLixeira[]>
  impacto<T extends TipoDeItem>(tipo: T, id: string): Promise<ImpactoPorTipo[T]>
  enviar(tipo: TipoDeItem, id: string, motivo: string): Promise<ItemDaLixeira>
  restaurar(tipo: TipoDeItem, id: string): Promise<void>
  /** `nome` é o nome do item, digitado: a API confere. */
  purgar(tipo: TipoDeItem, id: string, nome: string): Promise<void>
}

/** Uma pessoa no programa, com o papel que tem nele (`/v1/admin/programas`). */
export interface PessoaNoPrograma {
  pessoa_id: string
  nome: string
  apelidos: string[]
  papel: string
}

export interface ProgramaCadastrado {
  id: string
  nome: string
  perfil: string
  pessoas: PessoaNoPrograma[]
}

/** O que o formulário grava: as pessoas vão só com o id e o papel. */
export interface DadosDoPrograma {
  nome: string
  perfil: string
  pessoas: { pessoa_id: string; papel: string }[]
}

/** O cadastro de programas (exige `programas.editar`). */
export interface ClienteDoCadastroDeProgramas {
  listar(): Promise<ProgramaCadastrado[]>
  criar(dados: DadosDoPrograma): Promise<ProgramaCadastrado>
  mudar(id: string, dados: DadosDoPrograma): Promise<ProgramaCadastrado>
  /** Quantos vídeos já enviados guardam o nome do programa. */
  impacto(id: string): Promise<{ videos: number }>
  apagar(id: string): Promise<void>
  /** A pessoa que ainda não está no catálogo; se o nome já existe devolve a existente. */
  criarPessoa(nome: string, apelidos: string[]): Promise<PessoaNoPrograma>
}

export interface ClienteDaApi {
  eu(): Promise<Usuario>
  /** Uma página do acervo; `cursor` é o `proximo` da página anterior. */
  acervo(filtros: FiltrosDoAcervo, cursor?: string | null): Promise<PaginaDoAcervo>
  /** Uma página dos vídeos que entraram, de pessoas e de sistemas; a API só filtra sistema e estado. */
  entradas(filtros: FiltrosDasEntradas, cursor?: string | null): Promise<PaginaDoAcervo>
  /** `GET /v1/admin/auditoria` (exige `auditoria.ver`): só leitura; `cursor` é o `proximo` da página anterior. */
  auditoria(filtros: FiltrosDaAuditoria, limite: number, cursor?: string | null): Promise<PaginaDeAuditoria>
  /** `GET /v1/jobs/andamento`: o estado atual de até 200 vídeos num pedido só; omite os que não existem ou não se enxerga. */
  andamento(ids: string[]): Promise<Job[]>
  /** `POST /v1/jobs/quadros`: as URLs assinadas dos quadros de uma página da busca (até 100 pares); `url` vem nula se o vídeo não existe, está na lixeira ou não concluiu. */
  quadros(pares: ParDeQuadro[]): Promise<QuadroDoLote[]>
  criarJob(corpo: object): Promise<JobCriado>
  programas(): Promise<string[]>
  /**
   * `GET /v1/busca`: vídeos com os momentos em que a consulta aparece. `cursor` é o `proximo` da
   * página anterior (vale 15 min, só para a mesma consulta; vencido, a API responde 422).
   */
  buscar(consulta: ConsultaDaBusca, limite: number, cursor?: string | null): Promise<PaginaDaBusca>
  /** `POST /v1/busca/imagem`: a foto é a consulta; só programa e período da `consulta` valem. */
  buscarPorImagem(foto: File, consulta: ConsultaDaBusca, limite: number, cursor?: string | null): Promise<PaginaDaBusca>
  /** `GET /v1/relatorios/tempo-de-tela`: tempo de tela por pessoa, contando só aparições. */
  tempoDeTela(filtros: FiltrosDoRelatorio): Promise<RelatorioDeTempoDeTela>
  /** O mesmo relatório em CSV. */
  tempoDeTelaEmCsv(filtros: FiltrosDoRelatorio): Promise<Blob>
  /** Uma página do ranking do tempo de tela, com os totais do período; `cursor` é o `proximo` da página anterior. */
  rankingDoTempoDeTela(filtros: FiltrosDoRelatorio, cursor?: string): Promise<PaginaDoTempoDeTela>
  /** Os vídeos de uma pessoa no mesmo filtro, só quando a linha é aberta; uma página por vez. */
  videosDaPessoa(filtros: FiltrosDoRelatorio, pessoaId: string, cursor?: string): Promise<PaginaDeVideos>
  /** `GET /v1/painel/filtros` (exige `painel.ver`): programas e usuários que os filtros do painel oferecem. */
  opcoesDoPainel(): Promise<OpcoesDoPainel>
  /** `GET /v1/painel/fila` (exige `painel.ver`): os Jobs em andamento por estado e a idade do mais antigo, lidos na hora. */
  filaDoPainel(): Promise<FilaAgora>
  /** `GET /v1/painel/acessos`: logins por dia, usuários ativos, por usuário e no total. Sem programa. */
  acessosDoPainel(filtros: FiltrosDoPainel, agrupar?: PedidoDeAgrupamento): Promise<Agrupado<RelatorioDeAcessos>>
  /** Os mesmos acessos em CSV, uma linha por dia e pessoa. */
  acessosDoPainelEmCsv(filtros: FiltrosDoPainel): Promise<Blob>
  /** `GET /v1/painel/videos`: enviados, concluídos, falhas, horas e tempo de processamento. Programa e usuário não se combinam. */
  videosDoPainel(filtros: FiltrosDoPainel, agrupar?: PedidoDeAgrupamento): Promise<Agrupado<RelatorioDeVideos>>
  /** A base dos vídeos em CSV, uma linha por dia e pessoa (ou por dia e programa, com o filtro de programa). */
  videosDoPainelEmCsv(filtros: FiltrosDoPainel): Promise<Blob>
  /** `GET /v1/painel/buscas`: buscas, quem busca e buscas sem resultado. Programa e usuário não se combinam. */
  buscasDoPainel(filtros: FiltrosDoPainel, agrupar?: PedidoDeAgrupamento): Promise<Agrupado<RelatorioDeBuscas>>
  /** A base das buscas em CSV. */
  buscasDoPainelEmCsv(filtros: FiltrosDoPainel): Promise<Blob>
  /** `GET /v1/painel/revisao`: correções, taxa de correção e minutos de revisão. Os filtros se cruzam. */
  revisaoDoPainel(filtros: FiltrosDoPainel, agrupar?: PedidoDeAgrupamento): Promise<Agrupado<RelatorioDeRevisao>>
  /** A base da revisão em CSV, uma tabela com a coluna `indicador`. */
  revisaoDoPainelEmCsv(filtros: FiltrosDoPainel): Promise<Blob>
  /** `GET /v1/painel/api`: chamadas por sistema e rota, erros e vídeos enviados. Sem programa. */
  apiDoPainel(filtros: FiltrosDoPainel, agrupar?: PedidoDeAgrupamento): Promise<Agrupado<RelatorioDeApi>>
  /** A base da API em CSV. */
  apiDoPainelEmCsv(filtros: FiltrosDoPainel): Promise<Blob>
  /** `GET /v1/painel/custo`: custo por hora de vídeo e por mês, por usuário (ou sistema) e no total. */
  custoDoPainel(filtros: FiltrosDoPainel): Promise<RelatorioDeCusto>
  /** A base do custo em CSV. */
  custoDoPainelEmCsv(filtros: FiltrosDoPainel): Promise<Blob>
  /** `GET /v1/relatorios/marcas`: inserções, tempo e vídeos por marca e por tipo de inserção. */
  marcas(filtros: FiltrosDeMarcas): Promise<RelatorioDeMarcas>
  /** O mesmo relatório em CSV. */
  marcasEmCsv(filtros: FiltrosDeMarcas): Promise<Blob>
  /** Uma página do ranking de marcas, com os totais do período; `cursor` é o `proximo` da página anterior. */
  rankingDeMarcas(filtros: FiltrosDeMarcas, cursor?: string): Promise<PaginaDeMarcas>
  /** As inserções de uma marca no mesmo filtro (`tipo` estreita só a lista), só quando a linha é aberta. */
  insercoesDaMarca(filtros: FiltrosDeMarcas, marca: string, tipo?: string, cursor?: string): Promise<PaginaDeInsercoes>
  nomes: ClienteDeNomes
  fusao: ClienteDaFusao
  renomeacao: ClienteDaRenomeacao
  usuarios: ClienteDeUsuarios
  chaves: ClienteDeChaves
  aprovacao: ClienteDeAprovacao
  lixeira: ClienteDaLixeira
  cadastroDeProgramas: ClienteDoCadastroDeProgramas
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
    opcoes: { post?: true; put?: true; apagar?: true; corpo?: object; formulario?: FormData } = {},
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
      method: opcoes.post ? 'POST' : opcoes.put ? 'PUT' : opcoes.apagar ? 'DELETE' : undefined,
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
      if (resposta.status === 403 && (await detalhe(resposta)) === 'login_recente_exigido') throw new LoginRecenteExigido()
      throw new FalhaNaApi(resposta.status)
    }
    return resposta
  }

  async function chamar<T>(
    caminho: string,
    opcoes: { post?: true; put?: true; apagar?: true; corpo?: object; formulario?: FormData } = {},
  ): Promise<T> {
    return (await (await pedir(caminho, opcoes)).json()) as T
  }

  /** Um relatório do painel com o grupo dos gráficos que o servidor usou (`X-Agrupamento`; sem `agrupar`, por dia). */
  async function doPainel<T>(
    aba: string,
    filtros: FiltrosDoPainel,
    opcoes: { semPrograma?: boolean; agrupar?: PedidoDeAgrupamento },
  ): Promise<Agrupado<T>> {
    const resposta = await pedir(`/v1/painel/${aba}?${parametrosDoPainel(filtros, opcoes)}`)
    const agrupamento = (resposta.headers.get('X-Agrupamento') ?? 'dia') as Agrupamento
    return { ...((await resposta.json()) as T), agrupamento }
  }

  function job(id: string): ClienteDoJob {
    const base = `/v1/jobs/${id}`
    return {
      detalhe: () => chamar(base),
      reproducao: () => chamar(`${base}/reproducao`),
      quadro: (arquivo) => chamar(`${base}/quadros/${encodeURIComponent(arquivo)}`),
      decupagem: () => chamar(`${base}/decupagem`),
      baixarVideo: () => chamar(`${base}/download`),
      baixarDecupagem: async () => (await pedir(`${base}/decupagem/download`)).blob(),
      passadas: () => chamar(`${base}/passadas`),
      comparacao: (passadaId) => chamar(`${base}/passadas/${encodeURIComponent(passadaId)}/comparacao`),
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
      aprovarRevisao: () => chamar(`${base}/revisao/aprovar`, { post: true }),
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
      reprocessarOQueFalhou: (motivo) =>
        chamar(`${base}/reprocessar`, { post: true, corpo: motivo ? { motivo } : undefined }),
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
    entradas: async (filtros, cursor = null) => {
      const resposta = await pedir(`/v1/jobs?${consultaDasEntradas(filtros, cursor)}`)
      return {
        jobs: (await resposta.json()) as Job[],
        proximo: resposta.headers.get('X-Proximo-Cursor'),
      }
    },
    auditoria: async (filtros, limite, cursor = null) => {
      const resposta = await pedir(`/v1/admin/auditoria?${consultaDaAuditoria(filtros, limite, cursor)}`)
      return {
        registros: (await resposta.json()) as RegistroDeAuditoria[],
        proximo: resposta.headers.get('X-Proximo-Cursor'),
      }
    },
    andamento: (ids) => chamar(`/v1/jobs/andamento?ids=${ids.map(encodeURIComponent).join(',')}`),
    quadros: async (pares) => (await chamar<QuadroDoLote[]>('/v1/jobs/quadros', { post: true, corpo: { quadros: pares } })),
    criarJob: (corpo) => chamar('/v1/jobs', { post: true, corpo }),
    programas: () => chamar('/v1/programas'),
    buscar: (consulta, limite, cursor) => paginaDaBusca(pedir(`/v1/busca?${comCursor(consultaParaApi(consulta, limite), cursor)}`)),
    buscarPorImagem: (foto, consulta, limite, cursor) => {
      const formulario = new FormData()
      formulario.append('arquivo', foto)
      return paginaDaBusca(pedir(`/v1/busca/imagem?${comCursor(consultaDaImagemParaApi(consulta, limite), cursor)}`, { post: true, formulario }))
    },
    tempoDeTela: (filtros) => chamar(`/v1/relatorios/tempo-de-tela?${parametrosDoRelatorio(filtros)}`),
    tempoDeTelaEmCsv: async (filtros) =>
      (await pedir(`/v1/relatorios/tempo-de-tela?${parametrosDoRelatorio(filtros, 'csv')}`)).blob(),
    rankingDoTempoDeTela: async (filtros, cursor = '') => {
      const extras = { limite: String(POR_PAGINA_DO_RANKING), cursor }
      const resposta = await pedir(`/v1/relatorios/tempo-de-tela?${parametrosDoRelatorio(filtros, undefined, extras)}`)
      return { ...(await resposta.json()), proximo: resposta.headers.get('X-Proximo-Cursor') }
    },
    videosDaPessoa: async (filtros, pessoaId, cursor = '') => {
      const extras = { pessoa_id: pessoaId, limite: String(POR_PAGINA_DO_DETALHE), cursor }
      const resposta = await pedir(`/v1/relatorios/tempo-de-tela/videos?${parametrosDoRelatorio(filtros, undefined, extras)}`)
      return { videos: await resposta.json(), proximo: resposta.headers.get('X-Proximo-Cursor') }
    },
    opcoesDoPainel: () => chamar('/v1/painel/filtros'),
    filaDoPainel: () => chamar('/v1/painel/fila'),
    acessosDoPainel: (filtros, agrupar) => doPainel('acessos', filtros, { semPrograma: true, agrupar }),
    acessosDoPainelEmCsv: async (filtros) =>
      (await pedir(`/v1/painel/acessos?${parametrosDoPainel(filtros, { csv: true, semPrograma: true })}`)).blob(),
    videosDoPainel: (filtros, agrupar) => doPainel('videos', filtros, { agrupar }),
    videosDoPainelEmCsv: async (filtros) => (await pedir(`/v1/painel/videos?${parametrosDoPainel(filtros, { csv: true })}`)).blob(),
    buscasDoPainel: (filtros, agrupar) => doPainel('buscas', filtros, { agrupar }),
    revisaoDoPainel: (filtros, agrupar) => doPainel('revisao', filtros, { agrupar }),
    revisaoDoPainelEmCsv: async (filtros) => (await pedir(`/v1/painel/revisao?${parametrosDoPainel(filtros, { csv: true })}`)).blob(),
    apiDoPainel: (filtros, agrupar) => doPainel('api', filtros, { semPrograma: true, agrupar }),
    apiDoPainelEmCsv: async (filtros) => (await pedir(`/v1/painel/api?${parametrosDoPainel(filtros, { csv: true, semPrograma: true })}`)).blob(),
    custoDoPainel: (filtros) => chamar(`/v1/painel/custo?${parametrosDoPainel(filtros)}`),
    custoDoPainelEmCsv: async (filtros) => (await pedir(`/v1/painel/custo?${parametrosDoPainel(filtros, { csv: true })}`)).blob(),
    buscasDoPainelEmCsv: async (filtros) => (await pedir(`/v1/painel/buscas?${parametrosDoPainel(filtros, { csv: true })}`)).blob(),
    marcas: (filtros) => chamar(`/v1/relatorios/marcas?${parametrosDoRelatorio(filtros, undefined, { tipo: filtros.tipo })}`),
    marcasEmCsv: async (filtros) =>
      (await pedir(`/v1/relatorios/marcas?${parametrosDoRelatorio(filtros, 'csv', { tipo: filtros.tipo })}`)).blob(),
    rankingDeMarcas: async (filtros, cursor = '') => {
      const extras = { tipo: filtros.tipo, limite: String(POR_PAGINA_DO_RANKING), cursor }
      const resposta = await pedir(`/v1/relatorios/marcas?${parametrosDoRelatorio(filtros, undefined, extras)}`)
      return { ...(await resposta.json()), proximo: resposta.headers.get('X-Proximo-Cursor') }
    },
    insercoesDaMarca: async (filtros, marca, tipo = filtros.tipo, cursor = '') => {
      const extras = { marca, tipo, limite: String(POR_PAGINA_DO_DETALHE), cursor }
      const resposta = await pedir(`/v1/relatorios/marcas/insercoes?${parametrosDoRelatorio(filtros, undefined, extras)}`)
      return { insercoes: await resposta.json(), proximo: resposta.headers.get('X-Proximo-Cursor') }
    },
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
    fusao: {
      impacto: (origemId, destinoId) =>
        chamar(`/v1/catalogo/pessoas/${encodeURIComponent(origemId)}/fundir/impacto?destino_id=${encodeURIComponent(destinoId)}`),
      fundir: async (origemId, destinoId, motivo) => {
        await chamar(`/v1/catalogo/pessoas/${encodeURIComponent(origemId)}/fundir`, {
          post: true,
          corpo: { destino_id: destinoId, motivo },
        })
      },
    },
    renomeacao: {
      previa: (pessoaId, nome) =>
        chamar(`/v1/catalogo/pessoas/${encodeURIComponent(pessoaId)}/renomear`, { post: true, corpo: { nome, previa: true } }),
      renomear: (pessoaId, nome) =>
        chamar(`/v1/catalogo/pessoas/${encodeURIComponent(pessoaId)}/renomear`, { post: true, corpo: { nome, previa: false } }),
      andamento: (pessoaId) => chamar(`/v1/catalogo/pessoas/${encodeURIComponent(pessoaId)}/renomear/andamento`),
      retomar: (pessoaId) =>
        chamar(`/v1/catalogo/pessoas/${encodeURIComponent(pessoaId)}/renomear/retomar`, { post: true }),
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
    aprovacao: {
      listar: () => chamar('/v1/admin/aprovacao'),
      mudar: (tipo, exigeAprovacao) =>
        chamar('/v1/admin/aprovacao', { put: true, corpo: { tipo, exige_aprovacao: exigeAprovacao } }),
    },
    lixeira: {
      listar: () => chamar('/v1/admin/lixeira'),
      impacto: (tipo, id) => chamar(`${caminhoDaLixeira(tipo, id)}/impacto`),
      enviar: (tipo, id, motivo) => chamar(caminhoDaLixeira(tipo, id), { post: true, corpo: { motivo } }),
      restaurar: async (tipo, id) => {
        await pedir(`${caminhoDaLixeira(tipo, id)}/restaurar`, { post: true })
      },
      purgar: async (tipo, id, nome) => {
        await pedir(`${caminhoDaLixeira(tipo, id)}/purgar`, { post: true, corpo: { nome } })
      },
    },
    cadastroDeProgramas: {
      listar: () => chamar('/v1/admin/programas'),
      criar: (corpo) => chamar('/v1/admin/programas', { post: true, corpo }),
      mudar: (id, corpo) => chamar(`/v1/admin/programas/${encodeURIComponent(id)}`, { put: true, corpo }),
      impacto: (id) => chamar(`/v1/admin/programas/${encodeURIComponent(id)}/impacto`),
      apagar: async (id) => {
        await pedir(`/v1/admin/programas/${encodeURIComponent(id)}`, { apagar: true })
      },
      criarPessoa: (nome, apelidos) => chamar('/v1/admin/programas/pessoas', { post: true, corpo: { nome, apelidos } }),
    },
    job,
  }
}

const SEGMENTO_DA_LIXEIRA: Record<TipoDeItem, string> = { video: 'videos', pessoa: 'pessoas', marca: 'marcas' }

function caminhoDaLixeira(tipo: TipoDeItem, id: string): string {
  return `/v1/admin/lixeira/${SEGMENTO_DA_LIXEIRA[tipo]}/${encodeURIComponent(id)}`
}
