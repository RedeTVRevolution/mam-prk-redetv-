import { expect, test } from 'vitest'
import catalogo from './catalogo.fixture.json'
import {
  faixasComArrasto,
  faixasDe,
  faixasDoVisualizador,
  LINHA_LIVRE,
  lerTempo,
  limitarAlca,
  limitesDasAlcas,
  maiorFim,
  duracaoDaLinha,
  marcasDaRegua,
  posicaoDoBloco,
  posicaoDoCursor,
  riscosDeCorte,
  trechosSemPauta,
  vizinhoNaFaixa,
  reduzirLinha,
  secoesDaFaixa,
  selecaoValida,
  tempo,
  tempoDoCampo,
  tempoDoPonteiro,
  tempoPreciso,
  teclaDaAlca,
  type EstadoDaLinha,
  type Ocorrencia,
} from './linhaDoTempo.ts'
import type { Decupagem } from './Video.tsx'

const decupagem: Decupagem = {
  video: { duracao_ms: 180_000 },
  pautas: [{ id: 'pa1', titulo: 'Eleição', inicio_ms: 30_000, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Ana',
      na_imagem: [{ inicio_ms: 5_000, fim_ms: 20_000, evidencia: 'rosto' }],
      citada_na_fala: [{ inicio_ms: 65_000, fim_ms: 66_000 }],
      citada_no_texto: [{ inicio_ms: 70_000, fim_ms: 72_000, texto: 'Ana' }],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', inicio_ms: 0, fim_ms: 4_000 }],
  comerciais: [
    { id: 'com000', marca: 'X', tipo: 'intervalo', inicio_ms: 90_000, fim_ms: 120_000 },
    { id: 'novo', marca: 'Y', tipo: 'intervalo', acrescentado: true, inicio_ms: 1, fim_ms: 2 },
  ],
  transcricao: [{ locutor: 'L', texto: 'Boa noite', inicio_ms: 1_000, fim_ms: 3_000 }],
}

test('o tempo trunca os segundos e os minutos passam de 59, sem horas', () => {
  expect(tempo(0)).toBe('00:00')
  expect(tempo(59_600)).toBe('00:59')
  expect(tempo(3_750_000)).toBe('62:30')
})

test('o tempo preciso traz os milissegundos', () => {
  expect(tempoPreciso(62_005)).toBe('01:02.005')
})

test('lê mm:ss em milissegundos, com minutos acima de 59', () => {
  expect(lerTempo('01:24')).toBe(84_000)
  expect(lerTempo(' 62:30 ')).toBe(3_750_000)
  expect(lerTempo('1:60')).toBeNull()
  expect(lerTempo('abc')).toBeNull()
})

test('o campo que o Editor não mudou volta com os milissegundos originais', () => {
  expect(tempoDoCampo('00:01', 1_234)).toBe(1_234)
  expect(tempoDoCampo('00:02', 1_234)).toBe(2_000)
  expect(tempoDoCampo('x', 1_234)).toBeNull()
})

test('as faixas saem da Decupagem, com alvo só no que tem correção de tempo', () => {
  const faixas = faixasDe(decupagem, catalogo)
  expect(faixas.map((f) => [f.nome, f.ocorrencias.length])).toEqual([
    ['Pautas', 1],
    ['Aparições', 1],
    ['Menções', 2],
    ['Comerciais', 2],
    ['Planos', 1],
    ['Fala', 1],
    ['Texto na tela', 0],
  ])
  expect(faixas[0].ocorrencias[0]).toMatchObject({
    chave: 'pauta-0',
    alvo: { tipo: 'pauta', id: 'pa1' },
  })
  expect(faixas[1].ocorrencias[0].alvo).toEqual({ tipo: 'pessoa', id: 'p1', lista: 'na_imagem' })
  expect(faixas[3].ocorrencias.map((o) => o.alvo)).toEqual([
    { tipo: 'comercial', id: 'com000' },
    undefined,
  ])
  expect(faixas[5].ocorrencias[0].alvo).toBeUndefined()
  expect(maiorFim(faixas)).toBe(120_000)
})

test('as seções da faixa têm vãos, largura mínima e não redesenham a sobreposição', () => {
  const o = (chave: string, inicio_ms: number, fim_ms: number): Ocorrencia => ({
    chave,
    inicio_ms,
    fim_ms,
  })
  // 100 s: a ocorrência de 10 a 20 s, um vão de 10 s, outra sobreposta a ela.
  const a = o('a', 10_000, 20_000)
  expect(secoesDaFaixa([a], 100_000)).toEqual([
    { chave: 'vao-a', percentual: 10, ocorrencia: null },
    { chave: 'a', percentual: 10, ocorrencia: a },
  ])
  const sobrepostas = secoesDaFaixa([o('a', 0, 20_000), o('b', 10_000, 30_000)], 100_000)
  expect(sobrepostas.map((s) => [s.chave, s.percentual])).toEqual([
    ['a', 20],
    ['b', 10],
  ])
  // Uma ocorrência curta ganha 1,5 s; colada no fim, a largura cresce para a esquerda.
  expect(secoesDaFaixa([o('c', 10_000, 10_000)], 100_000)[1].percentual).toBe(1.5)
  const noFim = secoesDaFaixa([o('d', 99_900, 100_000)], 100_000)
  expect(noFim.map((s) => [s.chave, s.percentual])).toEqual([
    ['vao-d', 98.5],
    ['d', 1.5],
  ])
})

test('os limites das alças: início até o fim da ocorrência, fim até a duração do vídeo', () => {
  const pauta = { inicio_ms: 30_000, fim_ms: 60_000 }
  const limites = limitesDasAlcas(pauta, 150_000, 180_000)
  expect(limites.inicio).toEqual({ minMs: 0, maxMs: 60_000 })
  expect(limites.fim).toEqual({ minMs: 30_000, maxMs: 150_000 })
  // A decupagem limita mais que a linha do tempo.
  expect(limitesDasAlcas(pauta, 150_000, 100_000).fim.maxMs).toBe(100_000)
  expect(limitesDasAlcas(pauta, 150_000, Infinity).fim.maxMs).toBe(150_000)
})

test('as setas movem 100 ms, Shift 1 s, e as alças não passam do limite', () => {
  const { inicio, fim } = limitesDasAlcas({ inicio_ms: 30_000, fim_ms: 60_000 }, 150_000, 180_000)
  expect(teclaDaAlca('ArrowRight', false, 30_000, inicio)).toBe(30_100)
  expect(teclaDaAlca('ArrowRight', true, 30_000, inicio)).toBe(31_000)
  expect(teclaDaAlca('ArrowLeft', false, 30_000, inicio)).toBe(29_900)
  expect(teclaDaAlca('Tab', false, 30_000, inicio)).toBeNull()
  // 31 passos grandes a partir de 30 s: o início para no fim da ocorrência.
  let ms = 30_000
  for (let i = 0; i < 31; i++) ms = teclaDaAlca('ArrowRight', true, ms, inicio) ?? ms
  expect(ms).toBe(60_000)
  // 91 passos: o fim para na duração da linha do tempo.
  ms = 60_000
  for (let i = 0; i < 91; i++) ms = teclaDaAlca('ArrowRight', true, ms, fim) ?? ms
  expect(ms).toBe(150_000)
  // 61 passos para trás: o início para em zero.
  ms = 60_000
  for (let i = 0; i < 61; i++) ms = teclaDaAlca('ArrowLeft', true, ms, inicio) ?? ms
  expect(ms).toBe(0)
})

test('a alça fica em milissegundos inteiros', () => {
  expect(limitarAlca(1234.6, { minMs: 0, maxMs: 5_000 })).toBe(1235)
})

test('a posição do ponteiro vira milissegundos, dentro dos limites', () => {
  // 150 s em 1500 px: 10 px por segundo.
  const trilha = { esquerda: 100, largura: 1500 }
  const limites = { minMs: 0, maxMs: 150_000 }
  expect(tempoDoPonteiro(550, trilha, 150_000, limites)).toBe(45_000)
  expect(tempoDoPonteiro(0, trilha, 150_000, limites)).toBe(0)
  expect(tempoDoPonteiro(9_999, trilha, 150_000, limites)).toBe(150_000)
  expect(tempoDoPonteiro(550, { esquerda: 0, largura: 0 }, 150_000, limites)).toBeNull()
})

const pauta: Ocorrencia = {
  chave: 'pauta-0',
  inicio_ms: 30_000,
  fim_ms: 60_000,
  alvo: { tipo: 'pauta', id: 'pa1' },
}
const selecionada = (): EstadoDaLinha =>
  reduzirLinha(LINHA_LIVRE, { tipo: 'selecionar', decupagem, ocorrencia: pauta })

test('selecionar guarda o intervalo original; ocorrência sem alvo não seleciona', () => {
  const e = selecionada()
  expect(e.selecao).toMatchObject({
    chave: 'pauta-0',
    original: { inicio_ms: 30_000, fim_ms: 60_000 },
  })
  const semAlvo = { chave: 'fala-0', inicio_ms: 0, fim_ms: 1 }
  expect(reduzirLinha(LINHA_LIVRE, { tipo: 'selecionar', decupagem, ocorrencia: semAlvo })).toBe(
    LINHA_LIVRE,
  )
})

test('mover uma borda e soltar pede a confirmação; soltar sem mudar não', () => {
  const movida = reduzirLinha(selecionada(), { tipo: 'mover', decupagem, borda: 'inicio', ms: 31_100 })
  expect(movida.arrastado).toEqual({ inicio_ms: 31_100, fim_ms: 60_000 })
  const duas = reduzirLinha(movida, { tipo: 'mover', decupagem, borda: 'fim', ms: 59_000 })
  expect(duas.arrastado).toEqual({ inicio_ms: 31_100, fim_ms: 59_000 })
  expect(reduzirLinha(duas, { tipo: 'soltar', decupagem }).confirmando).toBe(true)

  const igual = reduzirLinha(selecionada(), { tipo: 'mover', decupagem, borda: 'fim', ms: 60_000 })
  const solta = reduzirLinha(igual, { tipo: 'soltar', decupagem })
  expect(solta.confirmando).toBe(false)
  expect(solta.arrastado).toBeNull()
})

test('cancelar devolve o intervalo anterior; enviado mantém o arrastado até recarregar', () => {
  const pronta = reduzirLinha(
    reduzirLinha(selecionada(), { tipo: 'mover', decupagem, borda: 'fim', ms: 59_000 }),
    { tipo: 'soltar', decupagem },
  )
  expect(reduzirLinha(pronta, { tipo: 'cancelar' })).toMatchObject({
    confirmando: false,
    arrastado: null,
  })
  expect(reduzirLinha(pronta, { tipo: 'enviado' })).toMatchObject({
    confirmando: false,
    arrastado: { inicio_ms: 30_000, fim_ms: 59_000 },
  })
})

test('a seleção não vale numa decupagem recarregada', () => {
  const e = selecionada()
  const recarregada = { ...decupagem }
  expect(selecaoValida(e, decupagem)).not.toBeNull()
  expect(selecaoValida(e, recarregada)).toBeNull()
  expect(reduzirLinha(e, { tipo: 'mover', decupagem: recarregada, borda: 'fim', ms: 1 })).toBe(e)
})

test('as faixas mostram a ocorrência selecionada no intervalo arrastado', () => {
  const e = reduzirLinha(selecionada(), { tipo: 'mover', decupagem, borda: 'inicio', ms: 40_000 })
  const faixas = faixasComArrasto(faixasDe(decupagem, catalogo), e.selecao, e.arrastado)
  expect(faixas[0].ocorrencias[0]).toMatchObject({ inicio_ms: 40_000, fim_ms: 60_000 })
  const sem = faixasDe(decupagem, catalogo)
  expect(faixasComArrasto(sem, e.selecao, null)).toBe(sem)
})

const noVisualizador: Decupagem = {
  pautas: [
    { id: 'pa2', titulo: 'Segunda', inicio_ms: 1_000_000, fim_ms: 2_000_000 },
    { id: 'pa1', titulo: 'Bastidores do Miss Bumbum', inicio_ms: 724_000, fim_ms: 900_000 },
  ],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      na_imagem: [{ inicio_ms: 211_000, fim_ms: 261_000, evidencia: 'rosto' }],
      citada_na_fala: [{ inicio_ms: 10_000, fim_ms: 12_000 }],
      citada_no_texto: [{ inicio_ms: 20_000, fim_ms: 22_000, texto: 'Leão' }],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [{ marca: 'Marca X', tipo: 'merchan', inicio_ms: 3_700_000, fim_ms: 3_760_000 }],
  transcricao: [{ locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [{ tipo: 'gc', texto: 'AO VIVO', inicio_ms: 5_000, fim_ms: 8_000 }],
}

test('o Visualizador tem seis faixas com contagem e sem planos', () => {
  const faixas = faixasDoVisualizador(noVisualizador)

  expect(faixas.map((f) => [f.rotulo, f.blocos.length])).toEqual([
    ['Pautas', 2],
    ['Pessoas', 1],
    ['Menções', 2],
    ['Comerciais', 1],
    ['Textos', 1],
    ['Falas', 1],
  ])
})

test('o nome do bloco diz quem ou o quê e os tempos; os blocos vão em ordem de início', () => {
  const faixas = faixasDoVisualizador(noVisualizador)
  const nomes = (r: string) => faixas.find((f) => f.rotulo === r)?.blocos.map((b) => b.nome)

  expect(nomes('Pautas')).toEqual([
    'Pauta: Bastidores do Miss Bumbum, 12:04 a 15:00',
    'Pauta: Segunda, 16:40 a 33:20',
  ])
  expect(nomes('Pessoas')).toEqual(['Aparição de Leão Lobo, 03:31 a 04:21'])
  expect(nomes('Menções')).toEqual([
    'Menção a Leão Lobo na fala, 00:10 a 00:12',
    'Menção a Leão Lobo no texto, 00:20 a 00:22',
  ])
  expect(nomes('Comerciais')).toEqual(['Comercial: Marca X, 1:01:40 a 1:02:40'])
  expect(nomes('Textos')).toEqual(['Texto na tela: AO VIVO, 00:05 a 00:08'])
  expect(nomes('Falas')).toEqual(['Fala de Ana: Boa noite, 00:00 a 00:03'])
})

test('as chaves dos blocos são únicas entre as faixas', () => {
  const chaves = faixasDoVisualizador(noVisualizador).flatMap((f) => f.blocos.map((b) => b.chave))

  expect(new Set(chaves).size).toBe(chaves.length)
})

test('a régua marca de 1, 5 ou 10 em 10 minutos conforme a duração, e o fim', () => {
  expect(marcasDaRegua(8 * 60_000).map((m) => m.rotulo)).toEqual([
    '00:00', '01:00', '02:00', '03:00', '04:00', '05:00', '06:00', '07:00', '08:00',
  ])
  expect(marcasDaRegua(20 * 60_000).map((m) => m.rotulo)).toEqual([
    '00:00', '05:00', '10:00', '15:00', '20:00',
  ])
  const longa = marcasDaRegua(2_959_000)
  expect(longa.map((m) => m.rotulo)).toEqual([
    '00:00', '10:00', '20:00', '30:00', '40:00', '49:19',
  ])
  expect(longa[1].percentual).toBeCloseTo((600_000 / 2_959_000) * 100, 6)
  expect(longa.map((m) => m.noFim)).toEqual([false, false, false, false, false, true])
  expect(marcasDaRegua(0)).toEqual([])
})

test('a marca redonda a menos de meio passo do fim dá lugar à do fim', () => {
  expect(marcasDaRegua(2_520_000).map((m) => m.rotulo)).toEqual([
    '00:00', '10:00', '20:00', '30:00', '42:00',
  ])
})

test('os riscos de corte ficam em percentual, sem repetição, e ignoram o que está fora do vídeo', () => {
  expect(riscosDeCorte([0, 25_000, 25_000, 50_000, 100_000, 200_000], 100_000)).toEqual([25, 50])
  expect(riscosDeCorte(null, 100_000)).toEqual([])
})

test('o cursor fica dentro da trilha', () => {
  expect(posicaoDoCursor(25_000, 100_000)).toBe(25)
  expect(posicaoDoCursor(150_000, 100_000)).toBe(100)
  expect(posicaoDoCursor(-1, 100_000)).toBe(0)
})

test('a duração da linha do tempo é a do player, ou o fim do último bloco se passar dela', () => {
  const faixas = [
    { chave: 'pauta', rotulo: 'Pautas', cor: '', blocos: [{ chave: 'p', nome: '', inicio_ms: 0, fim_ms: 90_000 }] },
  ]
  expect(duracaoDaLinha(100_000, faixas)).toBe(100_000)
  expect(duracaoDaLinha(0, faixas)).toBe(90_000)
  expect(duracaoDaLinha(0, [])).toBe(1)
})

test('o trecho sem pauta vai do fim da última pauta ao fim do vídeo', () => {
  const pautas = [
    { inicio_ms: 0, fim_ms: 1_000_000 },
    { inicio_ms: 900_000, fim_ms: 2_660_000 },
  ]

  expect(trechosSemPauta(pautas, 2_959_000)).toEqual([{ inicio_ms: 2_660_000, fim_ms: 2_959_000 }])
})

test('o trecho sem pauta também aparece no começo e no meio; vão menor que 1 s some', () => {
  const pautas = [
    { inicio_ms: 10_000, fim_ms: 20_000 },
    { inicio_ms: 20_500, fim_ms: 30_000 },
    { inicio_ms: 40_000, fim_ms: 60_000 },
  ]

  expect(trechosSemPauta(pautas, 60_000)).toEqual([
    { inicio_ms: 0, fim_ms: 10_000 },
    { inicio_ms: 30_000, fim_ms: 40_000 },
  ])
  expect(trechosSemPauta([], 60_000)).toEqual([{ inicio_ms: 0, fim_ms: 60_000 }])
})

test('o bloco ocupa seu trecho em percentual, sem passar do fim', () => {
  expect(posicaoDoBloco({ inicio_ms: 25_000, fim_ms: 50_000 }, 100_000)).toEqual({
    esquerda: 25,
    largura: 25,
  })
  expect(posicaoDoBloco({ inicio_ms: 90_000, fim_ms: 130_000 }, 100_000)).toEqual({
    esquerda: 90,
    largura: 10,
  })
})

test('← e → passam de bloco em bloco e param nas pontas', () => {
  const blocos = [{ chave: 'a' }, { chave: 'b' }, { chave: 'c' }]

  expect(vizinhoNaFaixa(blocos, 'a', 1)).toBe('b')
  expect(vizinhoNaFaixa(blocos, 'b', -1)).toBe('a')
  expect(vizinhoNaFaixa(blocos, 'c', 1)).toBe('c')
  expect(vizinhoNaFaixa(blocos, 'a', -1)).toBe('a')
})

test('a fala sem locutor não leva "de" no nome', () => {
  const d = { ...noVisualizador, transcricao: [{ locutor: '', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }] }
  const falas = faixasDoVisualizador(d).find((f) => f.rotulo === 'Falas')

  expect(falas?.blocos.map((b) => b.nome)).toEqual(['Fala: Boa noite, 00:00 a 00:03'])
})
