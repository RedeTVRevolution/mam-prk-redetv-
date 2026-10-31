import { expect, test } from 'vitest'
import type { MantineTheme } from '@mantine/core'
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

/** A cor `a` com opacidade `alfa` sobre `fundo`, como o navegador compõe o `rgba()`. */
function sobre(a: string, alfa: number, fundo: string): string {
  const canal = (cor: string, i: number) => parseInt(cor.slice(i, i + 2), 16)
  return `#${[1, 3, 5]
    .map((i) => Math.round(canal(a, i) * alfa + canal(fundo, i) * (1 - alfa)))
    .map((c) => c.toString(16).padStart(2, '0'))
    .join('')}`
}

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

// Simulação de Machado, Oliveira e Fernandes (2009), deuteranopia completa, no RGB linear;
// a distância entre duas cores é a euclidiana no Oklab (Ottosson, 2020).
const DEUTERANOPIA = [
  [0.367322, 0.860646, -0.227968],
  [0.280085, 0.672501, 0.047413],
  [-0.01182, 0.04294, 0.968881],
]

function linear(hex: string): number[] {
  return [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
}

function oklab([r, g, b]: number[]): number[] {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function deuteranopia(rgb: number[]): number[] {
  return DEUTERANOPIA.map((linha) =>
    Math.min(
      1,
      Math.max(
        0,
        linha.reduce((soma, k, i) => soma + k * rgb[i], 0),
      ),
    ),
  )
}

function menorDistancia(ver: (rgb: number[]) => number[]): number {
  const cores = Object.values(CORES_DE_OCORRENCIA).map(({ cor }) => oklab(ver(linear(cor))))
  let menor = Infinity
  for (const [i, a] of cores.entries()) {
    for (const b of cores.slice(i + 1))
      menor = Math.min(menor, Math.hypot(...a.map((x, k) => x - b[k])))
  }
  return menor
}

test('as sete cores se distinguem na visão comum e na deuteranopia', () => {
  // 0,10 no Oklab é uma diferença que se vê de relance; o limiar de percepção fica perto de 0,02.
  expect(menorDistancia((rgb) => rgb)).toBeGreaterThanOrEqual(0.1)
  expect(menorDistancia(deuteranopia)).toBeGreaterThanOrEqual(0.1)
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
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(CORES.andamento.slice(i, i + 2), 16))
  const matiz = (Math.atan2(Math.sqrt(3) * (g - b), 2 * r - g - b) * 180) / Math.PI
  expect(matiz).toBeGreaterThan(30)
  expect(matiz).toBeLessThan(60)
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
