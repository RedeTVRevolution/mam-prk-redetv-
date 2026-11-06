/** A linha do tempo da Decupagem sem React e sem DOM: tempos, faixas, alças e arrasto. */
import { pessoaDoModelo, type CatalogoDeCorrecoes } from './catalogo.ts'
import { CORES_DE_OCORRENCIA } from './cores.ts'
import type { Decupagem, Objeto } from './decupagem.ts'

/** `ms` em `MM:SS`: trunca os segundos e os minutos passam de 59, sem horas (ADR 0003). */
export function tempo(ms: number): string {
  const total = Math.floor(ms / 1000)
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

/** O relógio do player: `MM:SS`, e `H:MM:SS` a partir de uma hora. */
export function relogio(ms: number): string {
  const total = Math.floor(Math.max(ms, 0) / 1000)
  if (total < 3600) return tempo(ms)
  const hh = Math.floor(total / 3600)
  return `${hh}:${tempo((total % 3600) * 1000)}`
}

/** "mm:ss.mmm": o modal dos tempos arrastados mostra os milissegundos. */
export function tempoPreciso(ms: number): string {
  return `${tempo(ms)}.${String(ms % 1000).padStart(3, '0')}`
}

/** "mm:ss" ou "H:MM:SS" em milissegundos; `null` se não for um tempo. */
export function lerTempo(texto: string): number | null {
  const t = texto.trim()
  const horas = /^(\d{1,2}):([0-5]\d):([0-5]\d)$/.exec(t)
  if (horas) return (Number(horas[1]) * 3600 + Number(horas[2]) * 60 + Number(horas[3])) * 1000
  const achado = /^(\d{1,3}):([0-5]\d)$/.exec(t)
  return achado ? (Number(achado[1]) * 60 + Number(achado[2])) * 1000 : null
}

/** O campo em mm:ss ou H:MM:SS, em ms: o valor original, com os milissegundos, se o Editor não o mudou. */
export function tempoDoCampo(texto: string, originalMs: number): number | null {
  const ms = lerTempo(texto)
  return ms !== null && ms === lerTempo(tempo(originalMs)) ? originalMs : ms
}

export interface Intervalo {
  inicio_ms: number
  fim_ms: number
}

export type ListaDePessoa = 'na_imagem' | 'citada_na_fala' | 'citada_no_texto'

/** O que a correção `item.tempos` precisa para achar a ocorrência no servidor. */
export type Alvo =
  | { tipo: 'pauta'; id: string }
  | { tipo: 'comercial'; id: string }
  | { tipo: 'pessoa'; id: string; lista: ListaDePessoa }

export interface Ocorrencia extends Intervalo {
  chave: string
  /** Só as ocorrências de tipos com correção de tempo têm alvo. */
  alvo?: Alvo
}

export interface Faixa {
  nome: string
  cor: string
  ocorrencias: Ocorrencia[]
}

export type Borda = 'inicio' | 'fim'

/** Quanto as setas movem uma alça: 100 ms, ou 1 s com Shift. */
const PASSO_DA_ALCA_MS = 100
const PASSO_GRANDE_DA_ALCA_MS = 1000

// Menor largura de uma ocorrência na linha do tempo, para não sumir.
const LARGURA_MINIMA_MS = 1500

export function faixasDe(d: Decupagem, catalogo: CatalogoDeCorrecoes): Faixa[] {
  const de = <T extends Intervalo>(
    prefixo: string,
    lista: T[],
    alvo?: (x: T) => Alvo | undefined,
  ): Ocorrencia[] =>
    lista.map((x, i) => ({
      chave: `${prefixo}-${i}`,
      inicio_ms: x.inicio_ms,
      fim_ms: x.fim_ms,
      alvo: alvo?.(x),
    }))
  const daPessoa = (lista: ListaDePessoa) =>
    d.pessoas.flatMap((p) =>
      p[lista].map((x) => ({
        ...x,
        alvo: pessoaDoModelo(catalogo, p) ? { pessoa: p.id, lista } : null,
      })),
    )
  const alvoDaPessoa = (x: { alvo: { pessoa: string; lista: ListaDePessoa } | null }) =>
    x.alvo ? ({ tipo: 'pessoa', id: x.alvo.pessoa, lista: x.alvo.lista } as const) : undefined
  return [
    {
      nome: 'Pautas',
      cor: CORES_DE_OCORRENCIA.pauta.cor,
      ocorrencias: de('pauta', d.pautas, (p) => ({ tipo: 'pauta', id: p.id })),
    },
    {
      nome: 'Aparições',
      cor: CORES_DE_OCORRENCIA.aparicao.cor,
      ocorrencias: de('img', daPessoa('na_imagem'), alvoDaPessoa),
    },
    {
      nome: 'Menções',
      cor: CORES_DE_OCORRENCIA.mencao.cor,
      ocorrencias: de(
        'mencao',
        [...daPessoa('citada_na_fala'), ...daPessoa('citada_no_texto')],
        alvoDaPessoa,
      ),
    },
    {
      nome: 'Comerciais',
      cor: CORES_DE_OCORRENCIA.comercial.cor,
      ocorrencias: de('com', d.comerciais, (c) =>
        c.id && !c.acrescentado ? { tipo: 'comercial', id: c.id } : undefined,
      ),
    },
    {
      nome: 'Planos',
      // Fora do mapa de tipos: os planos saem da linha do tempo no redesenho do Visualizador.
      cor: 'dark.3',
      ocorrencias: de('plano', d.planos),
    },
    {
      nome: 'Fala',
      cor: CORES_DE_OCORRENCIA.fala.cor,
      ocorrencias: de('fala', d.transcricao),
    },
    {
      nome: 'Texto na tela',
      cor: CORES_DE_OCORRENCIA.texto_na_tela.cor,
      ocorrencias: de('texto', d.textos_na_tela ?? []),
    },
  ]
}

export function maiorFim(faixas: Faixa[]): number {
  return Math.max(0, ...faixas.flatMap((f) => f.ocorrencias.map((o) => o.fim_ms)))
}

/** Uma seção desenhada da faixa, em `percentual` da largura: uma ocorrência ou o vão antes dela. */
export type Secao =
  | { chave: string; percentual: number; ocorrencia: Ocorrencia }
  | { chave: string; percentual: number; ocorrencia: null }

/**
 * As seções de uma faixa, que é uma fileira só: o trecho que se sobrepõe ao anterior não é
 * desenhado de novo. Cada ocorrência fica no seu tempo, sem empurrar as seguintes.
 */
export function secoesDaFaixa(ocorrencias: Ocorrencia[], duracaoMs: number): Secao[] {
  const ordenadas = [...ocorrencias].sort((a, b) => a.inicio_ms - b.inicio_ms)
  const secoes: Secao[] = []
  let cursor = 0
  for (const o of ordenadas) {
    // A largura mínima cresce para a esquerda quando a ocorrência encosta no fim.
    const fim = Math.min(Math.max(o.fim_ms, o.inicio_ms + LARGURA_MINIMA_MS), duracaoMs)
    const inicio = Math.max(cursor, Math.min(o.inicio_ms, fim - LARGURA_MINIMA_MS))
    if (fim <= inicio) continue
    if (inicio > cursor) {
      secoes.push({
        chave: `vao-${o.chave}`,
        percentual: ((inicio - cursor) / duracaoMs) * 100,
        ocorrencia: null,
      })
    }
    secoes.push({ chave: o.chave, percentual: ((fim - inicio) / duracaoMs) * 100, ocorrencia: o })
    cursor = fim
  }
  return secoes
}

/** A posição de um tempo na trilha, em % da largura. */
export const percentualDoTempo = (ms: number, duracaoMs: number): number => (ms / duracaoMs) * 100

/** Os limites de cada alça da ocorrência selecionada. */
export interface LimitesDaAlca {
  minMs: number
  maxMs: number
}

/**
 * A alça de início vai de 0 ao fim da ocorrência; a de fim, do início até a duração da linha
 * do tempo e, no máximo, `limiteMs`: a duração do vídeo na decupagem, que a API confere.
 */
export function limitesDasAlcas(
  o: Intervalo,
  duracaoMs: number,
  limiteMs: number,
): Record<Borda, LimitesDaAlca> {
  return {
    inicio: { minMs: 0, maxMs: o.fim_ms },
    fim: { minMs: o.inicio_ms, maxMs: Math.min(duracaoMs, limiteMs) },
  }
}

/** O tempo da alça dentro dos limites, em milissegundos inteiros. */
export const limitarAlca = (valor: number, { minMs, maxMs }: LimitesDaAlca): number =>
  Math.round(Math.min(maxMs, Math.max(minMs, valor)))

/** O tempo da alça depois de uma tecla: setas movem 100 ms, Shift 1 s; outra tecla, `null`. */
export function teclaDaAlca(
  tecla: string,
  shift: boolean,
  ms: number,
  limites: LimitesDaAlca,
): number | null {
  const sentido = tecla === 'ArrowRight' ? 1 : tecla === 'ArrowLeft' ? -1 : 0
  if (sentido === 0) return null
  return limitarAlca(ms + sentido * (shift ? PASSO_GRANDE_DA_ALCA_MS : PASSO_DA_ALCA_MS), limites)
}

/** O tempo sob o ponteiro, dada a trilha (`esquerda` e `largura` em px); `null` sem largura. */
export function tempoDoPonteiro(
  x: number,
  trilha: { esquerda: number; largura: number },
  duracaoMs: number,
  limites: LimitesDaAlca,
): number | null {
  if (trilha.largura === 0) return null
  return limitarAlca(((x - trilha.esquerda) / trilha.largura) * duracaoMs, limites)
}

/** A ocorrência selecionada, com o intervalo de antes da correção. */
export interface Selecao {
  /** A decupagem em que a ocorrência foi selecionada: a chave é um índice e só vale nela. */
  decupagem: Decupagem
  chave: string
  alvo: Alvo
  original: Intervalo
}

/** A seleção, o intervalo arrastado (`null` = sem mudança) e se o modal de confirmação abre. */
export interface EstadoDaLinha {
  selecao: Selecao | null
  arrastado: Intervalo | null
  confirmando: boolean
}

export const LINHA_LIVRE: EstadoDaLinha = { selecao: null, arrastado: null, confirmando: false }

export type AcaoDaLinha =
  | { tipo: 'selecionar'; decupagem: Decupagem; ocorrencia: Ocorrencia }
  | { tipo: 'mover'; decupagem: Decupagem; borda: Borda; ms: number }
  | { tipo: 'soltar'; decupagem: Decupagem }
  | { tipo: 'cancelar' }
  | { tipo: 'enviado' }

/** Depois de recarregar a decupagem, a seleção antiga não vale mais: os índices podem ter mudado. */
export const selecaoValida = (e: EstadoDaLinha, decupagem: Decupagem): Selecao | null =>
  e.selecao?.decupagem === decupagem ? e.selecao : null

export function reduzirLinha(e: EstadoDaLinha, a: AcaoDaLinha): EstadoDaLinha {
  switch (a.tipo) {
    case 'selecionar': {
      const { ocorrencia: o } = a
      if (!o.alvo || o.chave === selecaoValida(e, a.decupagem)?.chave) return e
      return {
        ...e,
        arrastado: null,
        selecao: {
          decupagem: a.decupagem,
          chave: o.chave,
          alvo: o.alvo,
          original: { inicio_ms: o.inicio_ms, fim_ms: o.fim_ms },
        },
      }
    }
    case 'mover': {
      const selecao = selecaoValida(e, a.decupagem)
      if (!selecao) return e
      const base = e.arrastado ?? selecao.original
      return { ...e, arrastado: { ...base, [a.borda === 'inicio' ? 'inicio_ms' : 'fim_ms']: a.ms } }
    }
    case 'soltar': {
      const selecao = selecaoValida(e, a.decupagem)
      if (!selecao) return e
      const mudou =
        e.arrastado !== null &&
        (e.arrastado.inicio_ms !== selecao.original.inicio_ms ||
          e.arrastado.fim_ms !== selecao.original.fim_ms)
      return mudou ? { ...e, confirmando: true } : { ...e, arrastado: null }
    }
    // Cancelar devolve a ocorrência ao intervalo anterior.
    case 'cancelar':
      return { ...e, confirmando: false, arrastado: null }
    // O intervalo arrastado fica na linha do tempo até a decupagem recarregada chegar; aí a
    // seleção antiga deixa de valer e as alças somem.
    case 'enviado':
      return { ...e, confirmando: false }
  }
}

/** As faixas com a ocorrência selecionada no intervalo arrastado. */
export function faixasComArrasto(
  faixas: Faixa[],
  selecao: Selecao | null,
  arrastado: Intervalo | null,
): Faixa[] {
  if (!selecao || !arrastado) return faixas
  return faixas.map((f) => ({
    ...f,
    ocorrencias: f.ocorrencias.map((o) => (o.chave === selecao.chave ? { ...o, ...arrastado } : o)),
  }))
}

/** Um bloco de uma faixa do Visualizador; `nome` é o nome acessível e a dica. */
export interface BlocoDaFaixa extends Intervalo {
  chave: string
  nome: string
}

export const NAO_IDENTIFICADO = 'não identificado'

export const SEM_NOME = /^n[ãa]o identificado\s*[,:\-–—]?\s*/i

/** O nome da pessoa como a tela o diz: "Não identificado, mulher loira" vira "não identificado". */
export const nomeExibido = (nome: string): string => (SEM_NOME.test(nome) ? NAO_IDENTIFICADO : nome)

export interface FaixaDoVisualizador {
  chave: string
  rotulo: string
  cor: string
  /** O que a faixa diz quando não tem nenhum bloco, se tiver o que dizer. */
  vazio?: string
  /** Em ordem de início. */
  blocos: BlocoDaFaixa[]
}

const TAMANHO_DO_TRECHO = 60

const resumo = (texto: string): string =>
  texto.length > TAMANHO_DO_TRECHO ? `${texto.slice(0, TAMANHO_DO_TRECHO).trimEnd()}…` : texto

export const SEM_OBJETOS = 'Este vídeo não tem objetos decupados.'

/** O tom em palavras ("vermelho vivo"); sem ele, as cores base ("dourado e preto"); `null` sem nenhum dos dois. */
export function tomDoObjeto(o: Objeto): string | null {
  return o.cor || (o.cor_base.length > 0 ? o.cor_base.join(' e ') : null)
}

/** "sandália (vermelho vivo) de Mel Breia": o tipo, o tom e o dono, quando houver. */
export function descricaoDoObjeto(o: Objeto, dono: string | null): string {
  const tom = tomDoObjeto(o)
  return `${o.tipo}${tom ? ` (${tom})` : ''}${dono ? ` de ${dono}` : ''}`
}

/** Uma ocorrência por intervalo de cada objeto, na ordem da decupagem: a chave é `objeto-i`. */
export function ocorrenciasDosObjetos(
  d: Decupagem,
): (Intervalo & { objeto: Objeto; dono: string | null })[] {
  const nomes = new Map(d.pessoas.map((p) => [p.id, nomeExibido(p.nome)]))
  return (d.objetos ?? []).flatMap((objeto) =>
    objeto.ocorrencias.map((x) => ({
      inicio_ms: x.inicio_ms,
      fim_ms: x.fim_ms,
      objeto,
      dono: (objeto.pessoa && nomes.get(objeto.pessoa)) || null,
    })),
  )
}

/**
 * As sete faixas do Visualizador: pautas, pessoas na imagem, menções, objetos, comerciais, textos na tela
 * e falas. Os planos não são faixa; os cortes viram riscos da régua.
 */
export function faixasDoVisualizador(d: Decupagem): FaixaDoVisualizador[] {
  const faixa = (
    chave: string,
    rotulo: string,
    cor: string,
    itens: (Intervalo & { nome: string })[],
    vazio?: string,
  ): FaixaDoVisualizador => ({
    chave,
    rotulo,
    cor,
    vazio,
    blocos: itens
      .map((x, i) => ({
        chave: `${chave}-${i}`,
        inicio_ms: x.inicio_ms,
        fim_ms: x.fim_ms,
        nome: `${x.nome}, ${relogio(x.inicio_ms)} a ${relogio(x.fim_ms)}`,
      }))
      .sort((a, b) => a.inicio_ms - b.inicio_ms || a.fim_ms - b.fim_ms),
  })
  const daPessoa = (
    lista: ListaDePessoa,
    nome: (pessoa: string) => string,
  ): (Intervalo & { nome: string })[] =>
    d.pessoas.flatMap((p) => p[lista].map((x) => ({ ...x, nome: nome(p.nome) })))
  return [
    faixa(
      'pauta',
      'Pautas',
      CORES_DE_OCORRENCIA.pauta.cor,
      d.pautas.map((p) => ({ ...p, nome: `Pauta: ${p.titulo}` })),
    ),
    faixa(
      'aparicao',
      'Pessoas',
      CORES_DE_OCORRENCIA.aparicao.cor,
      daPessoa('na_imagem', (n) => `Aparição de ${n}`),
    ),
    faixa('mencao', 'Menções', CORES_DE_OCORRENCIA.mencao.cor, [
      ...daPessoa('citada_na_fala', (n) => `Menção a ${n} na fala`),
      ...daPessoa('citada_no_texto', (n) => `Menção a ${n} no texto`),
    ]),
    faixa(
      'objeto',
      'Objetos',
      CORES_DE_OCORRENCIA.objeto.cor,
      ocorrenciasDosObjetos(d).map((o) => ({ ...o, nome: `Objeto: ${descricaoDoObjeto(o.objeto, o.dono)}` })),
      SEM_OBJETOS,
    ),
    faixa(
      'comercial',
      'Comerciais',
      CORES_DE_OCORRENCIA.comercial.cor,
      d.comerciais.map((c) => ({ ...c, nome: `Comercial: ${c.marca}` })),
    ),
    faixa(
      'texto',
      'Textos',
      CORES_DE_OCORRENCIA.texto_na_tela.cor,
      (d.textos_na_tela ?? []).map((t) => ({ ...t, nome: `Texto na tela: ${resumo(t.texto)}` })),
    ),
    faixa(
      'fala',
      'Falas',
      CORES_DE_OCORRENCIA.fala.cor,
      d.transcricao.map((f) => ({ ...f, nome: f.locutor ? `Fala de ${f.locutor}: ${resumo(f.texto)}` : `Fala: ${resumo(f.texto)}` })),
    ),
  ]
}

export interface MarcaDaRegua {
  ms: number
  percentual: number
  rotulo: string
  /** A marca do fim do vídeo: o rótulo fica à esquerda dela, para não sair da régua. */
  noFim: boolean
}

/**
 * As marcas da régua: a cada 1 minuto até 10, a cada 5 até 30 e a cada 10 acima disso, mais a
 * do fim do vídeo; a marca redonda a menos de meio passo do fim sai, para os rótulos não se
 * encostarem.
 */
export function marcasDaRegua(duracaoMs: number): MarcaDaRegua[] {
  if (duracaoMs <= 0) return []
  const minutos = duracaoMs / 60_000
  const passoMs = (minutos <= 10 ? 1 : minutos <= 30 ? 5 : 10) * 60_000
  const tempos: number[] = []
  for (let ms = 0; ms < duracaoMs; ms += passoMs) tempos.push(ms)
  if (tempos.length > 1 && duracaoMs - tempos[tempos.length - 1] < passoMs / 2) tempos.pop()
  tempos.push(duracaoMs)
  return tempos.map((ms) => ({
    ms,
    percentual: percentualDoTempo(ms, duracaoMs),
    rotulo: relogio(ms),
    noFim: ms === duracaoMs,
  }))
}

/** Os cortes de câmera dentro do vídeo, em % da largura, sem repetição. */
export function riscosDeCorte(cortesMs: number[] | null | undefined, duracaoMs: number): number[] {
  return [...new Set(cortesMs ?? [])]
    .filter((ms) => ms > 0 && ms < duracaoMs)
    .map((ms) => percentualDoTempo(ms, duracaoMs))
}

/** A posição do cursor de reprodução, em % da largura, dentro da trilha. */
export const posicaoDoCursor = (atualMs: number, duracaoMs: number): number =>
  Math.min(Math.max(percentualDoTempo(atualMs, duracaoMs), 0), 100)

/** A duração da linha do tempo: a do player ou, se um bloco passa dela, o fim do último bloco. */
export function duracaoDaLinha(duracaoMs: number, faixas: FaixaDoVisualizador[]): number {
  let maior = Math.max(duracaoMs, 1)
  for (const f of faixas) for (const b of f.blocos) maior = Math.max(maior, b.fim_ms)
  return maior
}

/** Menor vão sem pauta que vale mostrar. */
const VAO_MINIMO_MS = 1000

/** Os trechos do vídeo que nenhuma pauta cobre. */
export function trechosSemPauta(pautas: Intervalo[], duracaoMs: number): Intervalo[] {
  const trechos: Intervalo[] = []
  let coberto = 0
  const soma = (inicio_ms: number, fim_ms: number) => {
    if (fim_ms - inicio_ms >= VAO_MINIMO_MS) trechos.push({ inicio_ms, fim_ms })
  }
  for (const p of [...pautas].sort((a, b) => a.inicio_ms - b.inicio_ms)) {
    soma(coberto, Math.min(p.inicio_ms, duracaoMs))
    coberto = Math.max(coberto, p.fim_ms)
  }
  soma(coberto, duracaoMs)
  return trechos
}

/** Onde o bloco começa e quanto ocupa, em % da largura, sem passar do fim. */
export function posicaoDoBloco(
  b: Intervalo,
  duracaoMs: number,
): { esquerda: number; largura: number } {
  const esquerda = Math.min(percentualDoTempo(b.inicio_ms, duracaoMs), 100)
  const fim = Math.min(percentualDoTempo(b.fim_ms, duracaoMs), 100)
  return { esquerda, largura: Math.max(fim - esquerda, 0) }
}

/** O bloco ao lado de `chave` (−1 anterior, 1 seguinte); nas pontas, o próprio. */
export function vizinhoNaFaixa(
  blocos: { chave: string }[],
  chave: string,
  sentido: -1 | 1,
): string {
  const i = blocos.findIndex((b) => b.chave === chave)
  if (i < 0) return chave
  return blocos[Math.min(Math.max(i + sentido, 0), blocos.length - 1)].chave
}
