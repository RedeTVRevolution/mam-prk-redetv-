import { expect, test } from 'vitest'
import catalogoJson from './catalogo.fixture.json'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import {
  editorDeNovaAparicao,
  editorDoItem,
  marcasDosItens,
  motivoDaRemocao,
  podeRemover,
  pedidoDeRemocao,
  TIPOS_FORA_DESTE_TICKET,
} from './catalogacao.ts'
import { itensDoPainel } from './painel.ts'
import type { Decupagem } from './Video.tsx'

const catalogo = catalogoJson as CatalogoDeCorrecoes

const D = {
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      fontes_do_nome: ['rosto'],
      na_imagem: [{ inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' }],
      citada_na_fala: [{ inicio_ms: 30_000, fim_ms: 32_000 }],
      citada_no_texto: [{ inicio_ms: 33_000, fim_ms: 34_000, texto: 'Leão no GC' }],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', acao: null, objetos: ['mesa'], plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [{ id: 'c1', marca: 'Marca X', tipo: 'intervalo', inicio_ms: 40_000, fim_ms: 50_000 }],
  transcricao: [{ id: 'f1', locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [{ id: 't1', tipo: 'gc', texto: 'Leão Lobo, jurado', inicio_ms: 12_000, fim_ms: 15_000 }],
} as unknown as Decupagem

const itens = itensDoPainel(D)
const editor = (chave: string) => {
  const item = itens.find((i) => i.chave === chave)
  if (!item) throw new Error(chave)
  return editorDoItem(D, item, catalogo)
}

test('mudar o título da pauta gera uma correção só, com o motivo do gesto', () => {
  const e = editor('pauta-0')!
  const pedidos = e.pedidos({ ...e.inicial, titulo: 'Eleição 2026' })

  expect(pedidos).toEqual([{ tipo: 'pauta.titulo', item_id: 'pa1', valor: 'Eleição 2026' }])
  expect(e.motivo(pedidos!)).toBe('título da pauta corrigido pelo editor')
})

test('sem mudar nada, não há o que gravar', () => {
  const e = editor('pauta-0')!
  expect(e.pedidos(e.inicial)).toEqual([])
})

test('tempos da pessoa levam a ocorrência original; o motivo fala dos tempos', () => {
  const e = editor('aparicao-0')!
  const pedidos = e.pedidos({ ...e.inicial, inicio: '00:08' })

  expect(pedidos).toEqual([
    {
      tipo: 'item.tempos',
      tipo_do_item: 'pessoa',
      item_id: 'p1',
      ocorrencia: { lista: 'na_imagem', inicio_ms: 10_000, fim_ms: 20_000 },
      valor: '8000-20000',
    },
  ])
  expect(e.motivo(pedidos!)).toBe('tempos ajustados pelo editor')
})

test('tempo que não é MM:SS, ou início depois do fim, não deixa salvar', () => {
  const e = editor('pauta-0')!
  expect(e.pedidos({ ...e.inicial, inicio: 'abc' })).toBeNull()
  expect(e.pedidos({ ...e.inicial, inicio: '02:00' })).toBeNull()
})

test('renomear e ajustar o papel da aparição geram duas correções', () => {
  const e = editor('aparicao-0')!
  const pedidos = e.pedidos({ ...e.inicial, nome: 'Leão Lobo Filho', papel: 'convidado' })

  expect(pedidos?.map((p) => p.tipo)).toEqual(['pessoa.renomear', 'aparicao.papel_visual'])
  expect(pedidos?.[1].valor).toBe(JSON.stringify({ papel: 'convidado', visual: 'barba' }))
})

test('trocar a aparição por menção e as fontes do nome', () => {
  const e = editor('aparicao-0')!
  const pedidos = e.pedidos({ ...e.inicial, destino: 'citada_na_fala', fontes: ['rosto', 'gc'] })

  expect(pedidos?.map((p) => p.tipo)).toEqual(['pessoa.fontes_do_nome', 'pessoa.aparicao_para_mencao'])
  expect(pedidos?.[0].valor).toBe(JSON.stringify(['rosto', 'gc']))
  expect(pedidos?.[1]).toMatchObject({ valor: 'citada_na_fala', ocorrencia: { lista: 'na_imagem' } })
})

test('a menção vira aparição com a evidência escrita; sem ela, não salva', () => {
  const e = editor('mencao-0')!
  expect(e.pedidos({ ...e.inicial, destino: 'na_imagem' })).toBeNull()
  const pedidos = e.pedidos({ ...e.inicial, destino: 'na_imagem', evidencia: 'rosto' })

  expect(pedidos).toEqual([
    {
      tipo: 'pessoa.mencao_para_aparicao',
      item_id: 'p1',
      ocorrencia: { lista: 'citada_na_fala', inicio_ms: 30_000, fim_ms: 32_000 },
      valor: 'rosto',
    },
  ])
})

test('comercial, plano, fala e texto na tela têm os campos do tipo', () => {
  const c = editor('comercial-0')!
  expect(c.pedidos({ ...c.inicial, marca: 'Marca Y', tipo: 'testemunhal' })?.map((p) => p.tipo)).toEqual([
    'comercial.marca',
    'comercial.tipo',
  ])
  const p = editor('plano-0')!
  expect(p.campos.map((x) => x.chave)).toEqual(['ambiente', 'acao', 'objetos', 'limpo'])
  expect(p.pedidos({ ...p.inicial, limpo: true, objetos: 'mesa, copo' })?.map((x) => x.tipo)).toEqual([
    'plano.descricao',
    'plano.limpo',
  ])
  const f = editor('fala-0')!
  expect(f.pedidos({ ...f.inicial, locutor: 'Bia' })).toEqual([
    { tipo: 'fala.texto', item_id: 'f1', valor: JSON.stringify({ texto: 'Boa noite', locutor: 'Bia' }) },
  ])
  const t = editor('texto-0')!
  expect(t.pedidos({ ...t.inicial, tipo: 'tarja', inicio: '00:13' })?.map((x) => x.tipo)).toEqual([
    'texto_na_tela.texto',
    'item.tempos',
  ])
})

test('só pessoa tem "não é isto", e só com nome', () => {
  const aparicao = itens.find((i) => i.chave === 'aparicao-0')!
  expect(podeRemover(D, aparicao)).toBe(true)
  expect(pedidoDeRemocao(D, aparicao)).toEqual({
    tipo: 'pessoa.nao_e',
    item_id: 'p1',
    valor: 'Não identificado',
    ocorrencia: { lista: 'na_imagem', inicio_ms: 10_000, fim_ms: 20_000 },
  })
  expect(podeRemover(D, itens.find((i) => i.chave === 'pauta-0')!)).toBe(false)
})

test('o motivo do "não é isto" diz se era aparição ou menção', () => {
  const aparicao = pedidoDeRemocao(D, itens.find((i) => i.chave === 'aparicao-0')!)!
  const mencao = pedidoDeRemocao(D, itens.find((i) => i.chave === 'mencao-0')!)!
  expect(motivoDaRemocao(aparicao)).toBe('pessoa removida desta aparição pelo editor')
  expect(motivoDaRemocao(mencao)).toBe('pessoa removida desta menção pelo editor')
})

test('cada tipo de correção do catálogo tem caminho pelo teclado, menos os de acrescentar trecho (#166) e os da fila (#165)', () => {
  const caminhos = new Set<string>()
  for (const chave of itens.map((i) => i.chave)) {
    const e = editor(chave)
    if (!e) continue
    // Todos os campos mudados de uma vez: cada tipo que o editor sabe gerar aparece.
    for (const t of e.tiposPossiveis) caminhos.add(t)
  }
  caminhos.add('pessoa.nao_e')
  caminhos.add('desfazer')
  for (const t of editorDeNovaAparicao(D.pessoas[0], 0, catalogo).tiposPossiveis) caminhos.add(t)

  const sem = catalogo.tipos.map((t) => t.valor).filter((t) => !caminhos.has(t))
  expect(sem.sort()).toEqual([...TIPOS_FORA_DESTE_TICKET].sort())
})

test('as alças mandam nos tempos, com os décimos, no lugar dos campos', () => {
  const e = editor('comercial-0')!
  expect(e.intervalo).toEqual({ inicio_ms: 40_000, fim_ms: 50_000 })

  const pedidos = e.pedidos(e.inicial, { inicio_ms: 40_300, fim_ms: 51_000 })

  expect(pedidos).toEqual([
    { tipo: 'item.tempos', tipo_do_item: 'comercial', item_id: 'c1', valor: '40300-51000' },
  ])
  expect(e.pedidos(e.inicial, { inicio_ms: 52_000, fim_ms: 51_000 })).toBeNull()
})

test('plano e fala não têm tempos para as alças', () => {
  expect(editor('plano-0')!.intervalo).toBeUndefined()
  expect(editor('fala-0')!.intervalo).toBeUndefined()
})

test('acrescentar aparição pede tempos e evidência e vai para a pessoa', () => {
  const e = editorDeNovaAparicao(D.pessoas[0], 61_000, catalogo)

  expect(e.inicial).toMatchObject({ inicio: '01:01', fim: '01:06' })
  expect(e.pedidos(e.inicial)).toBeNull()
  expect(e.pedidos({ ...e.inicial, evidencia: 'rosto' })).toEqual([
    {
      tipo: 'pessoa.acrescentar_aparicao',
      item_id: 'p1',
      valor: JSON.stringify({ inicio_ms: 61_000, fim_ms: 66_000, evidencia: 'rosto' }),
    },
  ])
})

test('marcas: corrigido, ou aguardando o Curador; só as da versão aberta e ainda de pé', () => {
  const d = { ...D, versao_decupagem: 'v1' } as Decupagem
  const h = (id: string, tipo_do_item: string, item_id: string, estado: string, versao = 'v1') =>
    ({
      id,
      tipo: 'pauta.titulo',
      estado,
      item_id,
      ancora: { versao, tipo_do_item },
      autor_email: 'ana@redetv.com.br',
      criada_em: '2026-10-31T12:00:00Z',
      motivo: 'título corrigido',
    }) as never

  const marcas = marcasDosItens(d, itens, [
    h('1', 'pauta', 'pa1', 'ativa'),
    h('2', 'pessoa', 'p1', 'pendente'),
    h('3', 'comercial', 'c1', 'desfeita'),
    h('4', 'plano', 'pl1', 'ativa', 'v0'),
  ])

  expect(marcas['pauta-0'].pendente).toBe(false)
  expect(marcas['pauta-0'].dica).toContain('ana@redetv.com.br')
  expect(marcas['pauta-0'].dica).toContain('título corrigido')
  expect(marcas['aparicao-0'].pendente).toBe(true)
  expect(marcas['comercial-0']).toBeUndefined()
  expect(marcas['plano-0']).toBeUndefined()
})
