/** O painel do Visualizador sem React e sem DOM: itens por tipo, abas, o que é "agora" e a rolagem. */
import { assinatura } from './assinaturaDoNome.ts'
import {
  type Intervalo,
  NAO_IDENTIFICADO,
  nomeExibido,
  ocorrenciasDosObjetos,
  relogio,
  SEM_NOME,
  tomDoObjeto,
  trechosSemPauta,
} from './linhaDoTempo.ts'
import type {
  CaixaDoQuadro,
  CategoriaDeObjeto,
  CorBase,
  Decupagem,
  ObjetoDoInventario,
  Plano,
  RelacaoDoObjeto,
} from './decupagem.ts'

export { NAO_IDENTIFICADO }

export type Aba = 'agora' | 'pessoas' | 'pautas' | 'objetos' | 'comerciais' | 'textos' | 'planos' | 'transcricao'

export const ABAS: { chave: Aba; rotulo: string }[] = [
  { chave: 'agora', rotulo: 'Agora' },
  { chave: 'pessoas', rotulo: 'Pessoas' },
  { chave: 'pautas', rotulo: 'Pautas' },
  { chave: 'objetos', rotulo: 'Objetos' },
  { chave: 'comerciais', rotulo: 'Comerciais' },
  { chave: 'textos', rotulo: 'Textos na tela' },
  { chave: 'planos', rotulo: 'Planos' },
  { chave: 'transcricao', rotulo: 'Transcrição' },
]

export type TipoDoItem = 'pauta' | 'aparicao' | 'mencao' | 'objeto' | 'comercial' | 'texto' | 'plano' | 'fala'

/** A prova do nome: `inicio_ms` é o tempo onde saltar; `null` quando a fonte não tem tempo. */
export interface Selo {
  rotulo: string
  inicio_ms: number | null
  /** `nao_confirmado`: o nome é palpite, sem prova. */
  tipo?: 'nao_confirmado'
  /** A explicação, em dica. */
  dica?: string
}

const DICA_DO_NAO_CONFIRMADO =
  'O modelo sugeriu este nome, mas não achou prova: nem GC, nem fala, nem rosto conferido com as fotos de referência.'

/** O que a lista mostra de um objeto: o tipo, a cor (base e tom), o dono e a marca. */
export interface DadosDoObjeto {
  id: string
  tipo: string
  categoria: string
  coresBase: CorBase[]
  /** O tom em palavras; sem ele, a lista escreve as cores base. */
  tom: string
  /**
   * `relacao` é o verbo depois do nome ("Mel Breia calça"); `null` quando o esquema não diz.
   * `naImagem`: o dono tem aparição, e o clique no nome leva a ela na aba Pessoas.
   */
  dono: { id: string; nome: string; relacao: string | null; naImagem: boolean } | null
  marca?: string
  detalhe?: string
}

export interface ItemDoPainel extends Intervalo {
  /** A mesma chave do bloco na linha do tempo. */
  chave: string
  tipo: TipoDoItem
  titulo: string
  /** Texto de apoio, uma linha cada. */
  linhas: string[]
  /** O texto inteiro, quando o item mostra só um resumo. */
  detalhe?: string
  selos: Selo[]
  /** Aparição: o id da pessoa. */
  pessoa?: string
  /** O tom da pauta ou o tipo do texto na tela e do comercial. */
  rotulo?: string
  objeto?: DadosDoObjeto
  /** O inventário do plano; só nos itens de plano, e só se a decupagem o tem. */
  inventario?: ObjetoDoInventario[]
  /** O JPEG do momento (`null` sem quadro); só aparição, objeto e plano têm miniatura. */
  quadro?: string | null
  /** O grupo de planos recorrentes (#546); só nos itens de plano que têm par. */
  grupo?: string
}

const ABA_DO_TIPO: Record<TipoDoItem, Aba | null> = {
  pauta: 'pautas',
  aparicao: 'pessoas',
  mencao: 'pessoas',
  objeto: 'objetos',
  comercial: 'comerciais',
  texto: 'textos',
  plano: 'planos',
  fala: 'transcricao',
}

/** A aba do tipo do item. */
export function abaDaChave(chave: string): Aba | null {
  return ABA_DO_TIPO[chave.split('-')[0] as TipoDoItem] ?? null
}

const normalizar = (t: string): string =>
  t
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()

/** O nome sem acento, caixa nem espaços nas pontas, para comparar nomes. */
export const nomeNormalizado = (t: string): string => normalizar(t).trim()

const escapar = (t: string): string => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const FONTES: Record<string, string> = { gc: 'GC', fala: 'Fala', rosto: 'Rosto', referencia: 'Rosto' }

/**
 * Os selos do nome, com o tempo do primeiro GC ou fala que cita a pessoa (o rosto não tem tempo). O palpite sem prova leva só o selo "não confirmado".
 */
/** Um texto da decupagem já sem acento nem caixa, para procurar os nomes nele. */
type TextoNormalizado = { inicio_ms: number; texto: string }

const normalizados = (trechos: (Intervalo & { texto: string })[]): TextoNormalizado[] =>
  trechos.map((t) => ({ inicio_ms: t.inicio_ms, texto: normalizar(t.texto) })).sort((a, b) => a.inicio_ms - b.inicio_ms)

/**
 * Os selos do nome, com o tempo do primeiro GC ou fala que cita a pessoa (o rosto não tem tempo). O palpite sem prova
 * leva só o selo "não confirmado". `textos` e `falas` vêm normalizados e em ordem de tempo, uma vez por decupagem.
 */
function selosDoNome(nome: string, fontes: string[], textos: TextoNormalizado[], falas: TextoNormalizado[], palpite = false): Selo[] {
  if (palpite && fontes.length === 0) {
    return [{ rotulo: 'não confirmado', inicio_ms: null, tipo: 'nao_confirmado', dica: DICA_DO_NAO_CONFIRMADO }]
  }
  // O nome inteiro, entre limites de palavra: "Ana" não casa com "MARIANA".
  const procurado = normalizar(nome)
  const alvo = new RegExp(`(^|[^\\p{L}\\p{N}])${escapar(procurado)}($|[^\\p{L}\\p{N}])`, 'u')
  // O `includes` descarta de graça quase todo texto; a expressão só confere os limites da palavra.
  const prova = (trechos: TextoNormalizado[]) => trechos.find((t) => t.texto.includes(procurado) && alvo.test(t.texto))?.inicio_ms ?? null
  // `rosto` e a antiga `referencia` (ainda aceita na leitura) dão o mesmo selo "Rosto": um só.
  const unicas = fontes.filter((f, i) => fontes.findIndex((g) => (FONTES[g] ?? g) === (FONTES[f] ?? f)) === i)
  return unicas.map((f) => ({
    rotulo: FONTES[f] ?? f,
    inicio_ms: f === 'gc' ? prova(textos) : f === 'fala' ? prova(falas) : null,
  }))
}

const NOME_DA_CATEGORIA: Record<CategoriaDeObjeto, string> = {
  roupa: 'roupa',
  calcado: 'calçado',
  acessorio: 'acessório',
  na_mao: 'na mão',
  em_cena: 'em cena',
  veiculo: 'veículo',
  outro: 'outro',
  eletronico: 'eletrônico',
  produto: 'produto',
  animal: 'animal',
  alimento: 'alimento',
  movel: 'móvel',
  decoracao: 'decoração',
  instrumento_musical: 'instrumento musical',
  utensilio: 'utensílio',
  documento: 'documento',
  planta: 'planta',
  bebida: 'bebida',
}

/** O nome da categoria como a tela mostra. */
export const nomeDaCategoria = (c: CategoriaDeObjeto): string => NOME_DA_CATEGORIA[c] ?? c

const area = (c: CaixaDoQuadro): number => c.largura * c.altura

/** A maior caixa do objeto, a que o player mostra. */
export const maiorCaixa = (o: ObjetoDoInventario): CaixaDoQuadro =>
  o.caixas.reduce((a, b) => (area(b) > area(a) ? b : a))

type PlanoDoObjeto = Intervalo & { id: string; ambiente: string }

/** Quantos planos do vídeo têm o valor (uma cor ou uma marca) dentro de um tipo de objeto. */
export interface ContagemDoValor {
  valor: string
  planos: number
}

/** Uma ocorrência do objeto num plano, com o nome, a cor e a marca como foram gravados. */
export interface OcorrenciaDoObjeto {
  nome: string
  cor?: CorBase | null
  marca?: string | null
  destaque: 1 | 2 | 3
  caixa: CaixaDoQuadro
  plano: PlanoDoObjeto
}

/**
 * Um objeto de cena do vídeo, visto por tipo (#544): o mesmo tipo canônico (ou, em `outro`, o mesmo nome pela
 * assinatura e a mesma categoria) de vários planos vira um item, com os planos em que aparece. A cor e a marca são
 * atributos, contados em `cores` e `marcas`; cada ocorrência segue em `ocorrencias` com o que foi gravado. É uma
 * visão: nada do que está gravado é fundido.
 */
export interface ObjetoDoVideo {
  chave: string
  /** O tipo canônico, ou `null` em `outro`. */
  tipo: string | null
  /** O tipo canônico ou, em `outro`, o nome da primeira ocorrência. */
  nome: string
  categoria: CategoriaDeObjeto
  /** A cor, quando todas as ocorrências têm a mesma. */
  cor?: CorBase | null
  marca?: string | null
  destaque: 1 | 2 | 3
  /** A maior caixa entre as ocorrências, a que o player mostra. */
  caixa: CaixaDoQuadro
  /** O plano da maior caixa: clicar leva a ele, para o player cair na cena que o quadro mostrou. */
  planoDaCaixa: PlanoDoObjeto
  planos: PlanoDoObjeto[]
  cores: ContagemDoValor[]
  marcas: ContagemDoValor[]
  ocorrencias: OcorrenciaDoObjeto[]
}

export interface GrupoDePlanos {
  id: string
  /** "Estúdio, plano médio (rec01): 188 planos, 21 min" */
  rotulo: string
  planos: number
}

const duracaoDoGrupo = (ms: number): string => (ms < 60_000 ? `${Math.round(ms / 1000)} s` : `${Math.round(ms / 60_000)} min`)

/** Os grupos de planos recorrentes (#546), o maior primeiro: o ambiente e o enquadramento do primeiro plano, a contagem e o tempo total. */
export function gruposDePlanos(planos: Plano[]): GrupoDePlanos[] {
  const porId = new Map<string, Plano[]>()
  for (const p of planos) if (p.plano_recorrente) porId.set(p.plano_recorrente, [...(porId.get(p.plano_recorrente) ?? []), p])
  return [...porId]
    .map(([id, doGrupo]) => {
      const [primeiro] = doGrupo
      const enquadramento = primeiro.enquadramento_canonico
      const nome = [primeiro.ambiente_canonico && primeiro.ambiente_canonico !== 'outro' ? primeiro.ambiente_canonico : primeiro.ambiente, enquadramento && enquadramento !== 'indefinido' ? enquadramento : null]
        .filter(Boolean)
        .join(', ')
      const tempo = duracaoDoGrupo(doGrupo.reduce((t, p) => t + (p.fim_ms - p.inicio_ms), 0))
      return { id, planos: doGrupo.length, rotulo: `${nome.charAt(0).toUpperCase()}${nome.slice(1)} (${id}): ${doGrupo.length} planos, ${tempo}` }
    })
    .sort((a, b) => b.planos - a.planos || a.id.localeCompare(b.id))
}

/** "azul 5, branco 4": as contagens por planos, da maior para a menor. */
export const resumoDasContagens = (contagens: ContagemDoValor[], limite = 3): string => {
  const mostradas = contagens.slice(0, limite).map((c) => `${c.valor} ${c.planos}`)
  return contagens.length > limite ? `${mostradas.join(', ')}…` : mostradas.join(', ')
}

const contar = (por: Map<string, Set<string>>): ContagemDoValor[] =>
  [...por]
    .map(([valor, planos]) => ({ valor, planos: planos.size }))
    .sort((a, b) => b.planos - a.planos || a.valor.localeCompare(b.valor, 'pt-BR'))

/**
 * O inventário de todos os planos por categoria (ordem alfabética do nome mostrado), cada tipo uma vez, com o
 * destaque maior primeiro, como na aba Planos. O objeto sem caixa fica de fora: não há quadro para mostrar.
 */
export function inventarioDoVideo(
  planos: Plano[],
): { categoria: CategoriaDeObjeto; nome: string; objetos: ObjetoDoVideo[] }[] {
  const porChave = new Map<string, ObjetoDoVideo>()
  const cores = new Map<string, Map<string, Set<string>>>()
  const marcas = new Map<string, Map<string, Set<string>>>()
  const somar = (por: Map<string, Map<string, Set<string>>>, chave: string, valor: string, plano: string) => {
    const dentro = por.get(chave) ?? new Map<string, Set<string>>()
    dentro.set(valor, (dentro.get(valor) ?? new Set<string>()).add(plano))
    por.set(chave, dentro)
  }
  for (const p of planos) {
    const plano = { id: p.id, ambiente: p.ambiente_canonico ?? p.ambiente, inicio_ms: p.inicio_ms, fim_ms: p.fim_ms }
    for (const o of p.inventario ?? []) {
      if (o.caixas.length === 0) continue
      const tipo = o.tipo_canonico && o.tipo_canonico !== 'outro' ? o.tipo_canonico : null
      const chave = tipo
        ? `tipo:${tipo}`
        : `nome:${o.categoria}:${assinatura(o.nome, o.cor ? [o.cor] : []) || nomeNormalizado(o.nome)}`
      const caixa = maiorCaixa(o)
      const ocorrencia = { nome: o.nome, cor: o.cor, marca: o.marca, destaque: o.destaque, caixa, plano }
      if (o.cor) somar(cores, chave, o.cor, p.id)
      if (o.marca) somar(marcas, chave, o.marca, p.id)
      const achado = porChave.get(chave)
      if (!achado) {
        const { categoria, cor, marca, destaque } = o
        porChave.set(chave, {
          chave, tipo, nome: tipo ?? o.nome, categoria, cor, marca, destaque, caixa, planoDaCaixa: plano,
          planos: [plano], cores: [], marcas: [], ocorrencias: [ocorrencia],
        })
        continue
      }
      achado.ocorrencias.push(ocorrencia)
      if (achado.planos.at(-1)?.id !== p.id) achado.planos.push(plano)
      achado.marca ||= o.marca
      if ((achado.cor ?? null) !== (o.cor ?? null)) achado.cor = null
      if (o.destaque > achado.destaque) achado.destaque = o.destaque
      if (area(caixa) > area(achado.caixa)) Object.assign(achado, { caixa, planoDaCaixa: plano })
    }
  }
  for (const [chave, o] of porChave) {
    o.cores = contar(cores.get(chave) ?? new Map())
    o.marcas = contar(marcas.get(chave) ?? new Map())
  }
  const grupos = new Map<CategoriaDeObjeto, ObjetoDoVideo[]>()
  for (const o of porChave.values()) {
    const grupo = grupos.get(o.categoria)
    if (grupo) grupo.push(o)
    else grupos.set(o.categoria, [o])
  }
  return [...grupos]
    .map(([categoria, objetos]) => ({
      categoria,
      nome: nomeDaCategoria(categoria),
      objetos: objetos.sort((a, b) => b.destaque - a.destaque),
    }))
    .sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'))
}

/** A relação do dono com o objeto, como verbo depois do nome ("Mel Breia calça"): não depende do gênero do tipo. */
const VERBO_DA_RELACAO: Record<RelacaoDoObjeto, string> = {
  veste: 'veste',
  calca: 'calça',
  usa: 'usa',
  segura: 'segura',
}

/** Um `pessoa` que não está nas pessoas da decupagem: o objeto tem dono, só não se sabe quem. */
const DONO_FORA_DA_DECUPAGEM = 'pessoa fora da decupagem'

/** Todos os itens da decupagem, com as chaves que a linha do tempo usa. */
export function itensDoPainel(d: Decupagem): ItemDoPainel[] {
  const itens: ItemDoPainel[] = []
  const nome = nomeExibido
  d.pautas.forEach((p, i) =>
    itens.push({
      chave: `pauta-${i}`,
      tipo: 'pauta',
      titulo: p.titulo,
      linhas: p.resumo ? [p.resumo] : [],
      detalhe: p.resumo,
      selos: [],
      inicio_ms: p.inicio_ms,
      fim_ms: p.fim_ms,
      rotulo: p.tom ?? undefined,
    }),
  )
  let a = 0
  let m = 0
  // Os textos e as falas se normalizam uma vez para todas as pessoas, não uma vez por pessoa.
  let textos: TextoNormalizado[] | null = null
  let falas: TextoNormalizado[] | null = null
  for (const p of d.pessoas) {
    const sem = SEM_NOME.test(p.nome)
    textos ??= normalizados(d.textos_na_tela ?? [])
    falas ??= normalizados(d.transcricao)
    const selos = sem ? [] : selosDoNome(p.nome, p.fontes_do_nome ?? [], textos, falas, p.estado_do_nome === 'palpite')
    for (const x of p.na_imagem) {
      const apoio = [x.papel, x.visual].filter(Boolean).join(' · ')
      itens.push({
        chave: `aparicao-${a++}`,
        tipo: 'aparicao',
        titulo: nome(p.nome),
        linhas: [...(sem ? [p.nome.replace(SEM_NOME, '')].filter(Boolean) : []), ...(apoio ? [apoio] : [])],
        selos,
        pessoa: p.id,
        quadro: x.quadro ?? null,
        inicio_ms: x.inicio_ms,
        fim_ms: x.fim_ms,
      })
    }
  }
  const mencao = (nomeDaPessoa: string, x: Intervalo, linha: string) =>
    itens.push({
      chave: `mencao-${m++}`,
      tipo: 'mencao',
      titulo: nome(nomeDaPessoa),
      linhas: [linha],
      selos: [],
      inicio_ms: x.inicio_ms,
      fim_ms: x.fim_ms,
    })
  for (const p of d.pessoas) for (const x of p.citada_na_fala) mencao(p.nome, x, 'citado na fala')
  for (const p of d.pessoas)
    for (const x of p.citada_no_texto) mencao(p.nome, x, `citado no texto: ${x.texto}`)
  const donos = new Map(d.pessoas.map((p) => [p.id, p]))
  ocorrenciasDosObjetos(d).forEach((o, i) => {
    const { objeto } = o
    const dono = objeto.pessoa ? donos.get(objeto.pessoa) : undefined
    itens.push({
      chave: `objeto-${i}`,
      tipo: 'objeto',
      quadro: objeto.quadro ?? null,
      titulo: objeto.tipo,
      linhas: [],
      selos: [],
      inicio_ms: o.inicio_ms,
      fim_ms: o.fim_ms,
      objeto: {
        id: objeto.id,
        tipo: objeto.tipo,
        categoria: nomeDaCategoria(objeto.categoria),
        coresBase: objeto.cor_base,
        tom: tomDoObjeto(objeto) ?? '',
        dono: objeto.pessoa
          ? {
              id: objeto.pessoa,
              nome: dono ? nomeExibido(dono.nome) : DONO_FORA_DA_DECUPAGEM,
              relacao: objeto.relacao ? VERBO_DA_RELACAO[objeto.relacao] : null,
              naImagem: (dono?.na_imagem.length ?? 0) > 0,
            }
          : null,
        marca: objeto.marca || undefined,
        detalhe: objeto.detalhe || undefined,
      },
    })
  })
  d.comerciais.forEach((c, i) =>
    itens.push({
      chave: `comercial-${i}`,
      tipo: 'comercial',
      titulo: c.marca,
      linhas: [c.tipo],
      selos: [],
      inicio_ms: c.inicio_ms,
      fim_ms: c.fim_ms,
    }),
  )
  ;(d.textos_na_tela ?? []).forEach((t, i) =>
    itens.push({
      chave: `texto-${i}`,
      tipo: 'texto',
      titulo: t.texto,
      linhas: [],
      selos: [],
      inicio_ms: t.inicio_ms,
      fim_ms: t.fim_ms,
      rotulo: t.tipo,
    }),
  )
  d.planos.forEach((p, i) =>
    itens.push({
      chave: `plano-${i}`,
      tipo: 'plano',
      titulo: p.ambiente_canonico ?? p.ambiente,
      quadro: p.quadro ?? null,
      linhas: [p.enquadramento_canonico, p.acao].filter((l): l is string => !!l && l !== 'indefinido'),
      selos: [],
      inicio_ms: p.inicio_ms,
      fim_ms: p.fim_ms,
      ...(p.inventario?.length ? { inventario: p.inventario } : {}),
      ...(p.plano_recorrente ? { grupo: p.plano_recorrente } : {}),
    }),
  )
  d.transcricao.forEach((f, i) =>
    itens.push({
      chave: `fala-${i}`,
      tipo: 'fala',
      titulo: f.texto,
      linhas: f.locutor ? [f.locutor] : [],
      selos: [],
      inicio_ms: f.inicio_ms,
      fim_ms: f.fim_ms,
    }),
  )
  return itens
}

/** O tempo está dentro do item; o fim é aberto, para dois itens seguidos não valerem juntos. */
export const contem = (i: Intervalo, ms: number): boolean => ms >= i.inicio_ms && ms < i.fim_ms

/** Os tipos que a aba Agora mostra, na ordem dos grupos. */
export const TIPOS_DO_AGORA: TipoDoItem[] = ['aparicao', 'mencao', 'objeto', 'comercial', 'texto']

/** O que está no tempo atual, agrupado por tipo. */
export function agora(itens: ItemDoPainel[], ms: number): ItemDoPainel[] {
  return TIPOS_DO_AGORA.flatMap((t) => itens.filter((i) => i.tipo === t && contem(i, ms)))
}

const TIPOS_DA_ABA: Record<Exclude<Aba, 'agora'>, TipoDoItem[]> = {
  pessoas: ['aparicao', 'mencao'],
  pautas: ['pauta'],
  objetos: ['objeto'],
  comerciais: ['comercial'],
  textos: ['texto'],
  planos: ['plano'],
  transcricao: ['fala'],
}

/** Os itens de uma aba, em ordem de início (pessoas: aparições, depois menções). */
export function itensDaAba(itens: ItemDoPainel[], aba: Exclude<Aba, 'agora'>): ItemDoPainel[] {
  const ordem = (a: ItemDoPainel, b: ItemDoPainel) => a.inicio_ms - b.inicio_ms || a.fim_ms - b.fim_ms
  return TIPOS_DA_ABA[aba].flatMap((t) => itens.filter((i) => i.tipo === t).sort(ordem))
}

/** Os itens por tipo, cada lista em ordem de tempo. */
export function itensPorTipo(itens: ItemDoPainel[]): Map<string, ItemDoPainel[]> {
  const mapa = new Map<string, ItemDoPainel[]>()
  for (const i of itens) {
    const lista = mapa.get(i.tipo)
    if (lista) lista.push(i)
    else mapa.set(i.tipo, [i])
  }
  for (const lista of mapa.values()) lista.sort((a, b) => a.inicio_ms - b.inicio_ms || a.fim_ms - b.fim_ms)
  return mapa
}

/** Os objetos da aba, em ordem do primeiro tempo, cada um com as suas ocorrências em ordem de tempo. */
export function objetosDaAba(itens: ItemDoPainel[]): { dados: DadosDoObjeto; ocorrencias: ItemDoPainel[] }[] {
  const porId = new Map<string, { dados: DadosDoObjeto; ocorrencias: ItemDoPainel[] }>()
  for (const i of itensDaAba(itens, 'objetos')) {
    if (!i.objeto) continue
    const achado = porId.get(i.objeto.id)
    if (achado) achado.ocorrencias.push(i)
    else porId.set(i.objeto.id, { dados: i.objeto, ocorrencias: [i] })
  }
  return [...porId.values()]
}

/** A chave ao lado da selecionada na aba; sem seleção (ou fora da aba), a primeira. */
export function vizinhoNoPainel(chaves: string[], atual: string | null, sentido: -1 | 1): string | null {
  if (chaves.length === 0) return null
  const i = atual === null ? -1 : chaves.indexOf(atual)
  if (i < 0) return chaves[0]
  return chaves[Math.min(Math.max(i + sentido, 0), chaves.length - 1)]
}

/** O trecho sem pauta que contém o tempo, se houver. */
export function semDecupagemEm(pautas: Intervalo[], duracaoMs: number, ms: number): Intervalo | null {
  return trechosSemPauta(pautas, duracaoMs).find((t) => contem(t, ms)) ?? null
}

export const textoDoSemDecupagem = (t: Intervalo): string =>
  `Sem decupagem (${relogio(t.inicio_ms)}–${relogio(t.fim_ms)})`

/** Quanto rolar o painel (positivo = para baixo) para o item entrar na vista; 0 se já está. */
export function deltaDeRolagem(
  painel: { topo: number; base: number },
  item: { topo: number; base: number },
): number {
  if (item.topo < painel.topo) return item.topo - painel.topo
  if (item.base > painel.base) return item.base - painel.base
  return 0
}

/** Quanto rolar o painel para o item ficar a um terço do topo (a transcrição acompanha a fala assim). */
export function deltaParaUmTerco(
  painel: { topo: number; base: number },
  item: { topo: number; base: number },
): number {
  return item.topo - (painel.topo + (painel.base - painel.topo) / 3)
}
