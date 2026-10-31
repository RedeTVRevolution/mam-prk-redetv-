/** O painel do Visualizador sem React e sem DOM: itens por tipo, abas, o que é "agora" e a rolagem. */
import { type Intervalo, relogio, trechosSemPauta } from './linhaDoTempo.ts'
import type { Decupagem } from './Video.tsx'

export type Aba = 'agora' | 'pessoas' | 'pautas' | 'comerciais' | 'textos' | 'planos'

export const ABAS: { chave: Aba; rotulo: string }[] = [
  { chave: 'agora', rotulo: 'Agora' },
  { chave: 'pessoas', rotulo: 'Pessoas' },
  { chave: 'pautas', rotulo: 'Pautas' },
  { chave: 'comerciais', rotulo: 'Comerciais' },
  { chave: 'textos', rotulo: 'Textos na tela' },
  { chave: 'planos', rotulo: 'Planos' },
]

export type TipoDoItem = 'pauta' | 'aparicao' | 'mencao' | 'comercial' | 'texto' | 'plano' | 'fala'

/** A prova do nome: `inicio_ms` é o tempo onde saltar; `null` quando a fonte não tem tempo. */
export interface Selo {
  rotulo: string
  inicio_ms: number | null
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
}

const ABA_DO_TIPO: Record<TipoDoItem, Aba | null> = {
  pauta: 'pautas',
  aparicao: 'pessoas',
  mencao: 'pessoas',
  comercial: 'comerciais',
  texto: 'textos',
  plano: 'planos',
  fala: null,
}

/** A aba do tipo do bloco (`fala` ainda não tem aba: é a Transcrição do #160). */
export function abaDaChave(chave: string): Aba | null {
  return ABA_DO_TIPO[chave.split('-')[0] as TipoDoItem] ?? null
}

const normalizar = (t: string): string =>
  t
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()

const SEM_NOME = /^n[ãa]o identificado\s*[,:\-–—]?\s*/i

const FONTES: Record<string, string> = { gc: 'GC', fala: 'Fala', rosto: 'Rosto', referencia: 'Referência' }

/** Os selos do nome, com o tempo do primeiro GC ou fala que cita a pessoa (os rostos não têm tempo). */
function selosDoNome(nome: string, fontes: string[], d: Decupagem): Selo[] {
  const alvo = normalizar(nome)
  const prova = (trechos: (Intervalo & { texto: string })[]) =>
    trechos.filter((t) => normalizar(t.texto).includes(alvo)).sort((a, b) => a.inicio_ms - b.inicio_ms)[0]
      ?.inicio_ms ?? null
  return fontes.map((f) => ({
    rotulo: FONTES[f] ?? f,
    inicio_ms: f === 'gc' ? prova(d.textos_na_tela ?? []) : f === 'fala' ? prova(d.transcricao) : null,
  }))
}

/** Todos os itens da decupagem, com as chaves que a linha do tempo usa. */
export function itensDoPainel(d: Decupagem): ItemDoPainel[] {
  const itens: ItemDoPainel[] = []
  const nome = (n: string) => (SEM_NOME.test(n) ? 'não identificado' : n)
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
  for (const p of d.pessoas) {
    const sem = SEM_NOME.test(p.nome)
    const selos = sem ? [] : selosDoNome(p.nome, p.fontes_do_nome ?? [], d)
    for (const x of p.na_imagem) {
      const apoio = [x.papel, x.visual].filter(Boolean).join(' · ')
      itens.push({
        chave: `aparicao-${a++}`,
        tipo: 'aparicao',
        titulo: nome(p.nome),
        linhas: [...(sem ? [p.nome.replace(SEM_NOME, '')].filter(Boolean) : []), ...(apoio ? [apoio] : [])],
        selos,
        pessoa: p.id,
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
      titulo: p.ambiente,
      linhas: p.acao ? [p.acao] : [],
      selos: [],
      inicio_ms: p.inicio_ms,
      fim_ms: p.fim_ms,
    }),
  )
  d.transcricao.forEach((f, i) =>
    itens.push({
      chave: `fala-${i}`,
      tipo: 'fala',
      titulo: f.texto,
      linhas: [f.locutor],
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
export const TIPOS_DO_AGORA: TipoDoItem[] = ['aparicao', 'mencao', 'comercial', 'texto']

/** O que está no tempo atual, agrupado por tipo. */
export function agora(itens: ItemDoPainel[], ms: number): ItemDoPainel[] {
  return TIPOS_DO_AGORA.flatMap((t) => itens.filter((i) => i.tipo === t && contem(i, ms)))
}

const TIPOS_DA_ABA: Record<Exclude<Aba, 'agora'>, TipoDoItem[]> = {
  pessoas: ['aparicao', 'mencao'],
  pautas: ['pauta'],
  comerciais: ['comercial'],
  textos: ['texto'],
  planos: ['plano'],
}

/** Os itens de uma aba, em ordem de início (pessoas: aparições, depois menções). */
export function itensDaAba(itens: ItemDoPainel[], aba: Exclude<Aba, 'agora'>): ItemDoPainel[] {
  const ordem = (a: ItemDoPainel, b: ItemDoPainel) => a.inicio_ms - b.inicio_ms || a.fim_ms - b.fim_ms
  return TIPOS_DA_ABA[aba].flatMap((t) => itens.filter((i) => i.tipo === t).sort(ordem))
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
