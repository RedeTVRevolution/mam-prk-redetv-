import { expect, test } from 'vitest'
import { contraste, CORES, CORES_DE_OCORRENCIA } from '../cores.ts'
import { deuteranopia, matiz, menorDistancia, sobre } from '../cores-teste.ts'
import css from './index.css?raw'

// O tema.test.ts da interface nova: as mesmas regras, sobre os tokens do index.css.
const COR = Object.fromEntries(
  [...css.matchAll(/--color-([\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map(([, nome, hex]) => [nome, hex]),
)

const SUPERFICIES = ['canvas', 'background', 'card', 'popover'] as const
const TODAS = [...SUPERFICIES, 'input'] as const

// Os tipos da API e o token de cada um no design system.
const TOKEN_DO_TIPO: Record<keyof typeof CORES_DE_OCORRENCIA, string> = {
  aparicao: 'tipo-aparicao',
  comercial: 'tipo-marca',
  fala: 'tipo-fala',
  mencao: 'tipo-mencao',
  objeto: 'tipo-objeto',
  pauta: 'tipo-pauta',
  texto_na_tela: 'tipo-texto',
}

function cor(nome: string): string {
  expect(COR[nome], `--color-${nome}`).toMatch(/^#/)
  return COR[nome]
}

test.each(
  [
    ['texto', 'foreground', TODAS],
    ['texto secundário', 'muted-foreground', TODAS],
    ['link', 'link', SUPERFICIES],
    ['concluído', 'ok', SUPERFICIES],
    ['em andamento', 'andamento', SUPERFICIES],
    ['falhou', 'destructive', SUPERFICIES],
  ].flatMap(([rotulo, token, fundos]) => (fundos as readonly string[]).map((f) => [rotulo, token, f])),
)('%s (--color-%s) passa no AA sobre %s', (_r, token, fundo) => {
  expect(contraste(cor(token as string), cor(fundo as string))).toBeGreaterThanOrEqual(4.5)
})

test('o texto passa no AA sobre a linha selecionada e no botão primário', () => {
  expect(contraste(cor('foreground'), cor('selected'))).toBeGreaterThanOrEqual(4.5)
  expect(contraste(cor('muted-foreground'), cor('selected'))).toBeGreaterThanOrEqual(4.5)
  expect(contraste(cor('primary-foreground'), cor('primary'))).toBeGreaterThanOrEqual(4.5)
})

test('o foco aparece como anel e barra (3:1) sobre o painel e o elevado', () => {
  expect(cor('ring')).toBe(cor('primary'))
  for (const fundo of ['background', 'card', 'sidebar']) {
    expect(contraste(cor('ring'), cor(fundo))).toBeGreaterThanOrEqual(3)
  }
})

test('os selos de estado passam no AA: a cor sobre ela mesma a 12%', () => {
  for (const estado of ['ok', 'andamento', 'destructive']) {
    for (const fundo of ['background', 'card']) {
      expect(contraste(cor(estado), sobre(cor(estado), 0.12, cor(fundo)))).toBeGreaterThanOrEqual(4.5)
    }
  }
})

test('os sete tipos de ocorrência têm token, com os valores da interface antiga', () => {
  expect(Object.keys(TOKEN_DO_TIPO).sort()).toEqual(
    ['aparicao', 'comercial', 'fala', 'mencao', 'objeto', 'pauta', 'texto_na_tela'].sort(),
  )
  for (const [tipo, token] of Object.entries(TOKEN_DO_TIPO)) {
    expect(cor(token).toLowerCase()).toBe(CORES_DE_OCORRENCIA[tipo as keyof typeof TOKEN_DO_TIPO].cor.toLowerCase())
  }
})

test.each(Object.entries(TOKEN_DO_TIPO))('a cor de "%s" serve de texto sobre as superfícies', (_tipo, token) => {
  for (const fundo of SUPERFICIES) expect(contraste(cor(token), cor(fundo))).toBeGreaterThanOrEqual(4.5)
})

test('as sete cores se distinguem na visão comum e na deuteranopia', () => {
  const cores = Object.values(TOKEN_DO_TIPO).map(cor)
  expect(menorDistancia(cores)).toBeGreaterThanOrEqual(0.1)
  expect(menorDistancia(cores, deuteranopia)).toBeGreaterThanOrEqual(0.1)
})

test('"Decupando" é âmbar, a cor de em andamento, a mesma da interface antiga', () => {
  expect(cor('andamento').toLowerCase()).toBe(CORES.andamento.toLowerCase())
  expect(matiz(cor('andamento'))).toBeGreaterThan(30)
  expect(matiz(cor('andamento'))).toBeLessThan(60)
})

test('o vermelho da marca não é a cor primária nem a de foco', () => {
  expect(cor('primary')).not.toBe(cor('marca'))
  expect(cor('ring')).not.toBe(cor('marca'))
})

test('nenhum canto passa de 6 px', () => {
  const raios = [...css.matchAll(/--radius(?:-[\w]+)?:\s*(\d+)px/g)].map(([, px]) => Number(px))
  expect(raios.length).toBeGreaterThan(0)
  for (const r of raios) expect(r).toBeLessThanOrEqual(6)
})

test('as sombras do Tailwind saem do tema; fica só a do que flutua', () => {
  expect(css).toMatch(/--shadow-\*:\s*initial/)
  expect([...css.matchAll(/--shadow-([\w-]+):/g)].map(([, nome]) => nome)).toEqual(['float'])
})

test('as três cores de série dos gráficos existem e passam de 3:1 sobre o painel', () => {
  for (const serie of ['chart-1', 'chart-2', 'chart-3']) {
    expect(contraste(cor(serie), cor('background'))).toBeGreaterThanOrEqual(3)
  }
  expect([cor('chart-1'), cor('chart-2'), cor('chart-3')]).toEqual(['#d95926', '#c25bd6', '#199e70'])
})

test('a escala sequencial vai do mais claro (maior valor) ao mais escuro, e o texto de cada passo passa no AA', () => {
  const passos = [100, 250, 400, 500, 600].map((n) => cor(`seq-${n}`))
  const luz = passos.map((p) => contraste(p, '#000000'))
  expect(luz).toEqual([...luz].sort((a, b) => b - a))
  // O texto da célula: escuro nos três claros, branco nos dois escuros.
  const texto = [cor('background'), cor('background'), cor('background'), cor('primary-foreground'), cor('primary-foreground')]
  passos.forEach((p, i) => expect(contraste(texto[i], p)).toBeGreaterThanOrEqual(4.5))
})
