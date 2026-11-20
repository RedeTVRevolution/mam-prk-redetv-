// O dia de São Paulo num lugar só: toda tela mostra e corta o dia por aqui (a API faz o mesmo em
// `api/fuso.py`). O navegador pode estar em qualquer fuso; o dia da emissora não muda.

export const FUSO = 'America/Sao_Paulo'

const DIA = new Intl.DateTimeFormat('en-CA', { timeZone: FUSO, year: 'numeric', month: '2-digit', day: '2-digit' })
const DATA = new Intl.DateTimeFormat('pt-BR', { timeZone: FUSO })
const DATA_E_HORA = new Intl.DateTimeFormat('pt-BR', { timeZone: FUSO, dateStyle: 'short', timeStyle: 'short' })

/** O dia de São Paulo do instante, em `AAAA-MM-DD`. */
export const diaDeSaoPaulo = (instante: Date): string => DIA.format(instante)

/** Hoje em São Paulo, em `AAAA-MM-DD`. */
export const hoje = (): string => diaDeSaoPaulo(new Date())

/** O ano de hoje em São Paulo. */
export const anoAtual = (): number => Number(hoje().slice(0, 4))

/** `DD/MM/AAAA`, em São Paulo. */
export const formataData = (iso: string): string => DATA.format(new Date(iso))

/** Data e hora curtas (`dd/mm/aaaa HH:mm`), em São Paulo. */
export const formataDataEHora = (iso: string): string => DATA_E_HORA.format(new Date(iso))

/** `AAAA-MM-DD` que existe no calendário (2026-02-30 não). */
export const diaValido = (dia: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(dia) && new Date(`${dia}T00:00:00Z`).toISOString().startsWith(dia)

/** O primeiro instante do dia de São Paulo (`AAAA-MM-DD`), em ISO: o que a regra de fuso diz, com ou sem horário de verão. */
export function inicioDoDia(dia: string): string {
  if (!diaValido(dia)) throw new Error(`Dia inválido: ${dia}`)
  // O fuso nunca passa de 4 h de UTC e muda em horas cheias: a primeira hora cheia que já é o dia é o começo.
  let t = Date.parse(`${dia}T00:00:00Z`)
  for (let volta = 0; diaDeSaoPaulo(new Date(t)) !== dia; volta++) {
    if (volta >= 6) throw new Error(`Sem início do dia para ${dia}`)
    t += 3_600_000
  }
  return new Date(t).toISOString()
}

/** O último milissegundo do dia de São Paulo, em ISO. */
export function fimDoDia(dia: string): string {
  const seguinte = new Date(Date.parse(`${dia}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10)
  return new Date(Date.parse(inicioDoDia(seguinte)) - 1).toISOString()
}
