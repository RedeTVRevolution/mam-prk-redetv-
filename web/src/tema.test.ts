import { expect, test } from 'vitest'
import type { MantineTheme } from '@mantine/core'
import { deuteranopia, matiz, menorDistancia, sobre } from './cores-teste.ts'
import { contraste, CORES, CORES_DE_OBJETO, CORES_DE_OCORRENCIA, ESTADOS_DO_JOB, tema, variaveis } from './tema.ts'

const FUNDOS = { fundo: CORES.fundo, superficie: CORES.superficie, elevada: CORES.elevada }

test('o contraste segue a fórmula da WCAG', () => {
  expect(contraste('#FFFFFF', '#000000')).toBeCloseTo(21, 5)
  expect(contraste('#000000', '#FFFFFF')).toBeCloseTo(21, 5)
  // O cinza #777 sobre branco é o exemplo clássico que fica logo abaixo do AA.
  expect(contraste('#777777', '#FFFFFF')).toBeCloseTo(4.48, 2)
})

test.each(
  Object.entries({
    texto: CORES.texto,
    'texto secundário': CORES.textoSecundario,
    'texto de foco (link)': CORES.focoTexto,
    concluído: CORES.concluido,
    'em andamento': CORES.andamento,
    falhou: CORES.falhou,
  }).flatMap(([nome, cor]) => Object.entries(FUNDOS).map(([f, fundo]) => [nome, cor, f, fundo])),
)('%s (%s) passa no AA sobre %s', (_n, cor, _f, fundo) => {
  expect(contraste(cor, fundo)).toBeGreaterThanOrEqual(4.5)
})

test.each(Object.entries(ESTADOS_DO_JOB))('o selo "%s" passa no AA', (_estado, { cor }) => {
  // Variante light do Mantine: a cor a 10% atrás do texto na mesma cor.
  for (const fundo of [CORES.fundo, CORES.superficie]) {
    expect(contraste(cor, sobre(cor, 0.1, fundo))).toBeGreaterThanOrEqual(4.5)
  }
})

test('o foco aparece como anel e barra (3:1) e o botão primário tem texto legível', () => {
  for (const fundo of Object.values(FUNDOS)) {
    expect(contraste(CORES.foco, fundo)).toBeGreaterThanOrEqual(3)
  }
  expect(contraste('#FFFFFF', CORES.foco)).toBeGreaterThanOrEqual(4.5)
})

test('o texto desabilitado, isento pela WCAG, ainda se lê (3:1)', () => {
  for (const fundo of Object.values(FUNDOS)) {
    expect(contraste(CORES.textoDesabilitado, fundo)).toBeGreaterThanOrEqual(3)
  }
})

test('o mapa de ocorrências tem os sete tipos, sem planos', () => {
  expect(Object.keys(CORES_DE_OCORRENCIA).sort()).toEqual(
    ['aparicao', 'comercial', 'fala', 'mencao', 'objeto', 'pauta', 'texto_na_tela'].sort(),
  )
})

test.each(Object.entries(CORES_DE_OCORRENCIA))(
  'a cor de "%s" serve de texto sobre qualquer superfície',
  (_tipo, { cor }) => {
    for (const fundo of Object.values(FUNDOS)) {
      expect(contraste(cor, fundo)).toBeGreaterThanOrEqual(4.5)
    }
  },
)

test('as sete cores se distinguem na visão comum e na deuteranopia', () => {
  // 0,10 no Oklab é uma diferença que se vê de relance; o limiar de percepção fica perto de 0,02.
  const cores = Object.values(CORES_DE_OCORRENCIA).map(({ cor }) => cor)
  expect(menorDistancia(cores)).toBeGreaterThanOrEqual(0.1)
  expect(menorDistancia(cores, deuteranopia)).toBeGreaterThanOrEqual(0.1)
})

test('o vermelho não é cor primária nem padrão de componente', () => {
  expect(tema.primaryColor).not.toBe('red')
  expect(JSON.stringify(tema.components)).not.toMatch(/red|#e03131|#f4736a/i)
})

test('cantos de 4 a 6 px', () => {
  const raio = parseInt(tema.radius![tema.defaultRadius as 'sm'] as string)
  expect(raio).toBeGreaterThanOrEqual(4)
  expect(raio).toBeLessThanOrEqual(6)
})

test('"Decupando" é âmbar, a cor de em andamento', () => {
  expect(ESTADOS_DO_JOB.analisando).toEqual({ cor: CORES.andamento, rotulo: 'Decupando' })
  // Âmbar: matiz entre o laranja (30°) e o amarelo (60°).
  expect(matiz(CORES.andamento)).toBeGreaterThan(30)
  expect(matiz(CORES.andamento)).toBeLessThan(60)
})

test('o erro e o placeholder que o Mantine pinta nos campos passam no AA', () => {
  const { dark } = variaveis(tema as MantineTheme)
  // O campo tem fundo `superficie`; a mensagem de erro fica sobre a página ou a superfície.
  for (const variavel of ['--mantine-color-error', '--mantine-color-placeholder'] as const) {
    for (const fundo of [CORES.fundo, CORES.superficie]) {
      expect(contraste(dark[variavel], fundo)).toBeGreaterThanOrEqual(4.5)
    }
  }
})

test('toda cor base do objeto tem a sua cor no mapa', () => {
  expect(Object.keys(CORES_DE_OBJETO).sort()).toEqual(
    [
      'vermelho', 'laranja', 'amarelo', 'verde', 'azul', 'roxo', 'rosa', 'marrom',
      'bege', 'preto', 'branco', 'cinza', 'dourado', 'prateado', 'estampado',
    ].sort(),
  )
})
