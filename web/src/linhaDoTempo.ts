/** A linha do tempo da Decupagem sem React e sem DOM: tempos, faixas, alças e arrasto. */
import type { MantineColor } from '@mantine/core'
import { pessoaDoModelo, type CatalogoDeCorrecoes } from './catalogo.ts'
import { CORES_DE_OCORRENCIA } from './tema.ts'
import type { Decupagem } from './Video.tsx'

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

/** "mm:ss" em milissegundos; `null` se não for um tempo. */
export function lerTempo(texto: string): number | null {
  const achado = /^(\d{1,3}):([0-5]\d)$/.exec(texto.trim())
  return achado ? (Number(achado[1]) * 60 + Number(achado[2])) * 1000 : null
}

/** O campo em mm:ss, em ms: o valor original, com os milissegundos, se o Editor não o mudou. */
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
  cor: MantineColor
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
