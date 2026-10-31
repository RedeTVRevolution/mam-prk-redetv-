import { expect, test } from 'vitest'
import {
  abaDaChave,
  agora,
  deltaDeRolagem,
  deltaParaUmTerco,
  itensDoPainel,
  itensDaAba,
  objetosDaAba,
  semDecupagemEm,
  vizinhoNoPainel,
} from './painel.ts'
import { faixasDoVisualizador } from './linhaDoTempo.ts'
import type { Decupagem } from './Video.tsx'

const D: Decupagem = {
  pautas: [
    { id: 'pa2', titulo: 'Eleição', inicio_ms: 0, fim_ms: 724_000, tom: 'informativo', resumo: 'Resumo da eleição' },
    { id: 'pa1', titulo: 'Bastidores', inicio_ms: 724_000, fim_ms: 940_000, tom: 'leve' },
  ],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      fontes_do_nome: ['gc', 'fala', 'rosto'],
      na_imagem: [
        { inicio_ms: 211_000, fim_ms: 261_000, evidencia: 'rosto', papel: 'colunista', visual: 'terno preto' },
      ],
      citada_na_fala: [{ inicio_ms: 10_000, fim_ms: 12_000 }],
      citada_no_texto: [],
    },
    {
      id: 'p2',
      nome: 'Não identificado, mulher loira',
      na_imagem: [{ inicio_ms: 220_000, fim_ms: 250_000, evidencia: 'rosto' }],
      citada_na_fala: [],
      citada_no_texto: [],
    },
    {
      id: 'p3',
      nome: 'Felipe Camargo',
      na_imagem: [],
      citada_na_fala: [],
      citada_no_texto: [{ inicio_ms: 5_000, fim_ms: 9_000, texto: 'Felipe' }],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', acao: 'apresentadora em pé', inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [{ marca: 'Ultrafarma', tipo: 'merchandising', inicio_ms: 100_000, fim_ms: 130_000 }],
  objetos: [
    {
      id: 'o1',
      categoria: 'calcado',
      tipo: 'sandália',
      cor_base: ['vermelho'],
      cor: 'vermelho vivo',
      marca: 'Arezzo',
      pessoa: 'p2',
      relacao: 'calca',
      ocorrencias: [
        { inicio_ms: 230_000, fim_ms: 240_000 },
        { inicio_ms: 400_000, fim_ms: 410_000 },
      ],
    },
    { id: 'o2', categoria: 'em_cena', tipo: 'troféu', cor_base: ['dourado', 'preto'], ocorrencias: [{ inicio_ms: 100_000, fim_ms: 110_000 }] },
  ],
  transcricao: [
    { locutor: 'Ana', texto: 'Aqui o leão lobo falando', inicio_ms: 220_000, fim_ms: 225_000 },
  ],
  textos_na_tela: [{ tipo: 'GC', texto: 'LEÃO LOBO', inicio_ms: 211_000, fim_ms: 215_000 }],
}

test('cada bloco da linha do tempo tem o item do painel com a mesma chave e o mesmo tempo', () => {
  const itens = itensDoPainel(D)
  for (const f of faixasDoVisualizador(D)) {
    for (const b of f.blocos) {
      const item = itens.find((i) => i.chave === b.chave)
      expect(item, b.chave).toBeDefined()
      expect([item?.inicio_ms, item?.fim_ms]).toEqual([b.inicio_ms, b.fim_ms])
    }
  }
})

test('a pessoa sem nome vira "não identificado" com a descrição, sem selos de nome', () => {
  const item = itensDoPainel(D).find((i) => i.chave === 'aparicao-1')
  expect(item?.titulo).toBe('não identificado')
  expect(item?.linhas).toContain('mulher loira')
  expect(item?.selos).toEqual([])
})

test('os selos do nome trazem o tempo da prova: GC e fala', () => {
  const item = itensDoPainel(D).find((i) => i.chave === 'aparicao-0')
  expect(item?.selos).toEqual([
    { rotulo: 'GC', inicio_ms: 211_000 },
    { rotulo: 'Fala', inicio_ms: 220_000 },
    { rotulo: 'Rosto', inicio_ms: null },
  ])
  expect(item?.linhas).toEqual(['colunista · terno preto'])
})

test('o selo só casa o nome inteiro: "Ana" não acha a prova em "MARIANA"', () => {
  const d: Decupagem = {
    ...D,
    pessoas: [{ ...D.pessoas[0], nome: 'Ana', fontes_do_nome: ['gc'] }],
    textos_na_tela: [
      { tipo: 'GC', texto: 'MARIANA SOUZA', inicio_ms: 100_000, fim_ms: 105_000 },
      { tipo: 'GC', texto: 'ANA · repórter', inicio_ms: 200_000, fim_ms: 205_000 },
    ],
  }
  expect(itensDoPainel(d).find((i) => i.chave === 'aparicao-0')?.selos).toEqual([{ rotulo: 'GC', inicio_ms: 200_000 }])
})

test('menção e aparição têm tipos separados', () => {
  const tipos = itensDoPainel(D).map((i) => [i.chave, i.tipo])
  expect(tipos).toContainEqual(['aparicao-0', 'aparicao'])
  expect(tipos).toContainEqual(['mencao-0', 'mencao'])
  expect(itensDoPainel(D).find((i) => i.chave === 'mencao-0')?.linhas).toEqual(['citado na fala'])
})

test('agora: só o que contém o tempo, agrupado por tipo; fim do intervalo é aberto', () => {
  const itens = itensDoPainel(D)
  expect(agora(itens, 222_000).map((i) => i.chave)).toEqual(['aparicao-0', 'aparicao-1'])
  expect(agora(itens, 215_000).map((i) => i.chave)).toEqual(['aparicao-0'])
  expect(agora(itens, 261_000).map((i) => i.chave)).toEqual([])
})

test('a aba do item: pessoas para aparição e menção, e transcrição para fala', () => {
  expect(abaDaChave('aparicao-3')).toBe('pessoas')
  expect(abaDaChave('mencao-0')).toBe('pessoas')
  expect(abaDaChave('pauta-1')).toBe('pautas')
  expect(abaDaChave('comercial-0')).toBe('comerciais')
  expect(abaDaChave('texto-2')).toBe('textos')
  expect(abaDaChave('plano-2')).toBe('planos')
  expect(abaDaChave('fala-2')).toBe('transcricao')
})

test('itens da aba pautas ficam em ordem de início', () => {
  expect(itensDaAba(itensDoPainel(D), 'pautas').map((i) => i.titulo)).toEqual(['Eleição', 'Bastidores'])
})

test('vizinho: setas movem, sem seleção começa pelo primeiro e as pontas ficam', () => {
  const chaves = ['a', 'b', 'c']
  expect(vizinhoNoPainel(chaves, null, 1)).toBe('a')
  expect(vizinhoNoPainel(chaves, 'a', 1)).toBe('b')
  expect(vizinhoNoPainel(chaves, 'c', 1)).toBe('c')
  expect(vizinhoNoPainel(chaves, 'a', -1)).toBe('a')
  expect(vizinhoNoPainel(chaves, 'fora', 1)).toBe('a')
  expect(vizinhoNoPainel([], null, 1)).toBeNull()
})

test('trecho sem decupagem: o vão que nenhuma pauta cobre', () => {
  expect(semDecupagemEm(D.pautas, 2_959_000, 500_000)).toBeNull()
  expect(semDecupagemEm(D.pautas, 2_959_000, 1_500_000)).toEqual({ inicio_ms: 940_000, fim_ms: 2_959_000 })
})

test('rolagem: só o tanto para o item entrar na vista', () => {
  expect(deltaDeRolagem({ topo: 100, base: 300 }, { topo: 150, base: 200 })).toBe(0)
  expect(deltaDeRolagem({ topo: 100, base: 300 }, { topo: 80, base: 120 })).toBe(-20)
  expect(deltaDeRolagem({ topo: 100, base: 300 }, { topo: 280, base: 330 })).toBe(30)
})

test('a transcrição acompanha a fala a um terço do topo do painel', () => {
  // Painel de 300 px de altura: um terço é 100 px abaixo do topo.
  expect(deltaParaUmTerco({ topo: 0, base: 300 }, { topo: 400, base: 440 })).toBe(300)
  expect(deltaParaUmTerco({ topo: 0, base: 300 }, { topo: 100, base: 140 })).toBe(0)
  expect(deltaParaUmTerco({ topo: 50, base: 350 }, { topo: 60, base: 100 })).toBe(-90)
})

test('o objeto traz tipo, cores, categoria, dono com a relação e marca; sem dono, "em cena"', () => {
  const itens = itensDoPainel(D).filter((i) => i.tipo === 'objeto')

  expect(itens.map((i) => i.chave)).toEqual(['objeto-0', 'objeto-1', 'objeto-2'])
  expect(itens[0].objeto).toEqual({
    id: 'o1',
    tipo: 'sandália',
    categoria: 'calçado',
    coresBase: ['vermelho'],
    tom: 'vermelho vivo',
    dono: { id: 'p2', nome: 'não identificado', relacao: 'calçado por' },
    marca: 'Arezzo',
    detalhe: undefined,
    ocorrencias: 2,
  })
  expect(itens[2].objeto).toMatchObject({ tom: 'dourado e preto', dono: null, categoria: 'em cena' })
})

test('a aba Objetos lista cada objeto uma vez, em ordem de tempo, com as suas ocorrências', () => {
  const objetos = objetosDaAba(itensDoPainel(D))

  expect(objetos.map((o) => [o.dados.id, o.ocorrencias.map((i) => i.chave)])).toEqual([
    ['o2', ['objeto-2']],
    ['o1', ['objeto-0', 'objeto-1']],
  ])
  expect(abaDaChave('objeto-1')).toBe('objetos')
})

test('o agora traz os objetos visíveis no tempo, depois das menções', () => {
  expect(agora(itensDoPainel(D), 235_000).filter((i) => i.tipo === 'objeto').map((i) => i.chave)).toEqual(['objeto-0'])
})

test('uma decupagem anterior ao 1.3 não tem objetos', () => {
  const { objetos: _, ...antiga } = D
  expect(itensDoPainel(antiga).some((i) => i.tipo === 'objeto')).toBe(false)
})
