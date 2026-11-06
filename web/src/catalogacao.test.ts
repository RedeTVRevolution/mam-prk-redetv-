import { expect, test } from 'vitest'
import { ABAS_DO_TRECHO, editorDoTrecho } from './trecho.ts'
import catalogoJson from './catalogo.fixture.json'
import type { CatalogoDeCorrecoes } from './catalogo.ts'
import {
  aindaIndexando,
  editorDeNovaAparicao,
  editorDoItem,
  marcasDosItens,
  motivoDaRemocao,
  podeRemover,
  pedidoDeRemocao,
  TIPOS_FORA_DESTE_TICKET,
  teclasDasOpcoes,
} from './catalogacao.ts'
import { itensDoPainel } from './painel.ts'
import { editorDeDivisao, editorDeJuncao } from './pautas.ts'
import type { Decupagem, Pauta } from './decupagem.ts'

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
  objetos: [
    {
      id: 'o1',
      categoria: 'roupa',
      tipo: 'camisa',
      cor_base: ['azul'],
      cor: 'azul marinho',
      detalhe: 'listrada',
      marca: 'Lacoste',
      pessoa: 'p1',
      relacao: 'veste',
      ocorrencias: [{ inicio_ms: 10_000, fim_ms: 20_000 }],
    },
    {
      id: 'o2',
      categoria: 'mobiliario',
      tipo: 'mesa',
      cor_base: [],
      ocorrencias: [{ inicio_ms: 0, fim_ms: 5_000 }],
    },
  ],
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

test('cada tipo de correção do catálogo tem caminho pelo teclado, menos os da fila (#165)', () => {
  const caminhos = new Set<string>()
  for (const chave of itens.map((i) => i.chave)) {
    const e = editor(chave)
    if (!e) continue
    // Todos os campos mudados de uma vez: cada tipo que o editor sabe gerar aparece.
    for (const t of e.tiposPossiveis) caminhos.add(t)
  }
  caminhos.add('pessoa.nao_e')
  caminhos.add('objeto.nao_existe')
  caminhos.add('desfazer')
  for (const t of editorDeNovaAparicao(D.pessoas[0], 0, catalogo).tiposPossiveis) caminhos.add(t)

  const trecho = { inicio_ms: 0, fim_ms: 1_000 }
  for (const aba of ABAS_DO_TRECHO)
    for (const t of editorDoTrecho(aba.valor, trecho, catalogo, []).tiposPossiveis) caminhos.add(t)

  const pautas = D.pautas as unknown as Pauta[]
  for (const t of editorDeJuncao(pautas, catalogo).tiposPossiveis) caminhos.add(t)
  for (const t of editorDeDivisao(pautas[0], 30_000, catalogo).tiposPossiveis) caminhos.add(t)

  const sem = catalogo.tipos.map((t) => t.valor).filter((t) => !caminhos.has(t))
  expect(sem.sort()).toEqual([...TIPOS_FORA_DESTE_TICKET].sort())
})

test('objeto: tipo, cor base, tom, detalhe e marca geram um objeto.atributos só', () => {
  const e = editor('objeto-0')!
  expect(e.pedidos(e.inicial)).toEqual([])

  const pedidos = e.pedidos({ ...e.inicial, tipo: 'camiseta', cor_base: ['azul', 'branco'], cor: 'azul claro', detalhe: '', marca: 'Nike' })

  expect(pedidos).toEqual([
    {
      tipo: 'objeto.atributos',
      item_id: 'o1',
      valor: JSON.stringify({ tipo: 'camiseta', cor_base: ['azul', 'branco'], cor: 'azul claro', detalhe: null, marca: 'Nike' }),
    },
  ])
  expect(e.motivo(pedidos!)).toBe('atributos do objeto corrigidos pelo editor')
})

test('objeto: cada atributo sozinho muda só ele, e mais de duas cores base não salvam', () => {
  const e = editor('objeto-0')!
  const valor = (v: Record<string, unknown>) => {
    const [p] = e.pedidos({ ...e.inicial, ...v } as never)!
    return JSON.parse(p.valor)
  }
  expect(valor({ tipo: 'camiseta' })).toMatchObject({ tipo: 'camiseta', cor_base: ['azul'], cor: 'azul marinho' })
  expect(valor({ cor_base: ['branco'] })).toMatchObject({ cor_base: ['branco'], cor: 'azul marinho', marca: 'Lacoste' })
  expect(valor({ cor: 'azul royal' })).toMatchObject({ cor_base: ['azul'], cor: 'azul royal' })
  expect(valor({ detalhe: 'lisa' })).toMatchObject({ detalhe: 'lisa', tipo: 'camisa' })
  expect(valor({ marca: 'Polo' })).toMatchObject({ marca: 'Polo' })
  expect(e.pedidos({ ...e.inicial, cor_base: ['azul', 'branco', 'preto'] })).toBeNull()
  // Só vale cor da lista fechada: a de fora não conta para o limite e não vai no pedido.
  expect(valor({ cor_base: ['azul', 'turquesa', 'branco'] }).cor_base.sort()).toEqual(['azul', 'branco'])
  expect(e.pedidos({ ...e.inicial, tipo: ' ' })).toBeNull()
  expect(e.pedidos(e.inicial)).toEqual([])
})

test('objeto: trocar o dono, a relação e tirar o dono geram objeto.dono', () => {
  const e = editor('objeto-0')!
  expect(e.inicial).toMatchObject({ dono: 'p1', relacao: 'veste' })
  expect(e.campos.find((c) => c.chave === 'dono')!.opcoes).toEqual([
    { valor: '', rotulo: 'Em cena' },
    { valor: 'p1', rotulo: 'Leão Lobo' },
  ])

  const tipo = (v: Record<string, string>) => e.pedidos({ ...e.inicial, ...v })
  expect(tipo({ relacao: 'segura' })).toEqual([
    { tipo: 'objeto.dono', item_id: 'o1', valor: JSON.stringify({ pessoa: 'p1', relacao: 'segura' }) },
  ])
  expect(tipo({ dono: '' })).toEqual([
    { tipo: 'objeto.dono', item_id: 'o1', valor: JSON.stringify({ pessoa: null, relacao: null }) },
  ])
  expect(e.motivo(tipo({ dono: '' })!)).toBe('dono do objeto corrigido pelo editor')

  const sem = editor('objeto-1')!
  expect(sem.inicial).toMatchObject({ dono: '' })
  expect(sem.pedidos({ ...sem.inicial, dono: 'p1', relacao: 'segura' })).toEqual([
    { tipo: 'objeto.dono', item_id: 'o2', valor: JSON.stringify({ pessoa: 'p1', relacao: 'segura' }) },
  ])
  expect(sem.pedidos(sem.inicial)).toEqual([])
})

test('objeto: atributos e dono mudados juntos geram dois pedidos', () => {
  const e = editor('objeto-0')!
  const pedidos = e.pedidos({ ...e.inicial, marca: 'Polo', dono: '' })!
  expect(pedidos.map((p) => p.tipo)).toEqual(['objeto.atributos', 'objeto.dono'])
})

test('o objeto tem "Este objeto não está na imagem?" e gera objeto.nao_existe', () => {
  const item = itens.find((i) => i.chave === 'objeto-0')!
  expect(podeRemover(D, item)).toBe(true)
  const pedido = pedidoDeRemocao(D, item)!
  expect(pedido).toEqual({ tipo: 'objeto.nao_existe', item_id: 'o1', valor: 'nao_existe' })
  expect(motivoDaRemocao(pedido)).toBe('objeto removido da imagem pelo editor')
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

test('acima de uma hora os campos mostram e leem H:MM:SS', () => {
  const e = editorDeNovaAparicao(D.pessoas[0], 3_661_000, catalogo)

  expect(e.inicial).toMatchObject({ inicio: '1:01:01', fim: '1:01:06' })
  expect(e.pedidos({ ...e.inicial, evidencia: 'rosto' })).toEqual([
    {
      tipo: 'pessoa.acrescentar_aparicao',
      item_id: 'p1',
      valor: JSON.stringify({ inicio_ms: 3_661_000, fim_ms: 3_666_000, evidencia: 'rosto' }),
    },
  ])
})

test('um item depois de 1:00:00 abre e grava os tempos em H:MM:SS', () => {
  const tarde = { ...D, comerciais: [{ id: 'c1', marca: 'Marca X', tipo: 'intervalo', inicio_ms: 3_700_250, fim_ms: 3_710_000 }] } as Decupagem
  const item = itensDoPainel(tarde).find((i) => i.chave === 'comercial-0')!
  const e = editorDoItem(tarde, item, catalogo)!

  expect(e.inicial).toMatchObject({ inicio: '1:01:40', fim: '1:01:50' })
  expect(e.pedidos(e.inicial)).toEqual([])
  expect(e.pedidos({ ...e.inicial, fim: '1:02:05' })).toEqual([
    { tipo: 'item.tempos', tipo_do_item: 'comercial', item_id: 'c1', valor: '3700250-3725000' },
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

test('a tela volta a perguntar enquanto uma correção que vale (ativa ou aprovada) está indexando', () => {
  const h = (estado: string, na_busca: string) => ({ estado, na_busca }) as never

  expect(aindaIndexando([h('ativa', 'na_busca'), h('aprovada', 'indexando')])).toBe(true)
  expect(aindaIndexando([h('ativa', 'indexando')])).toBe(true)
  expect(aindaIndexando([h('desfeita', 'indexando'), h('ativa', 'salva')])).toBe(false)
})

test('teclasDasOpcoes: a primeira letra livre do rótulo, sem repetir nenhuma', () => {
  const cores = ['verde', 'vermelho', 'azul', 'amarelo', 'índigo'].map((r) => ({ valor: r, rotulo: r }))
  expect([...teclasDasOpcoes(cores).values()]).toEqual(['v', 'e', 'a', 'm', 'i'])
})

test('marcas: uma decupagem de 2 h com 300 correções não trava a tela (teto de 25 ms; com a CPU 4× mais lenta, 100 ms)', () => {
  const faixa = (i: number, passo: number) => ({ inicio_ms: i * passo, fim_ms: i * passo + passo - 100 })
  const d = {
    versao_decupagem: 'v1',
    pautas: Array.from({ length: 60 }, (_, i) => ({ id: `pa${i}`, titulo: `P${i}`, resumo: '', tom: 'informativo', ...faixa(i, 115_000) })),
    pessoas: Array.from({ length: 40 }, (_, i) => ({
      id: `p${i}`,
      nome: `Pessoa ${i}`,
      fontes_do_nome: ['gc'],
      na_imagem: Array.from({ length: 38 }, (_, j) => ({ ...faixa(j, 10_000), evidencia: 'rosto' })),
      citada_na_fala: [],
      citada_no_texto: [],
    })),
    planos: Array.from({ length: 1800 }, (_, i) => ({ id: `pl${i}`, ambiente: 'estúdio', acao: null, objetos: [], plano_limpo: false, ...faixa(i, 4_000) })),
    comerciais: [],
    transcricao: Array.from({ length: 2500 }, (_, i) => ({ id: `f${i}`, locutor: 'Ana', texto: 'fala', ...faixa(i, 2_880) })),
    textos_na_tela: Array.from({ length: 1500 }, (_, i) => ({ id: `t${i}`, tipo: 'GC', texto: 'texto', ...faixa(i, 4_800) })),
    objetos: [],
  } as unknown as Decupagem
  const itensGrandes = itensDoPainel(d)
  const historico = Array.from({ length: 300 }, (_, i) => ({
    id: `c${i}`,
    tipo: 'pessoa.renomear',
    estado: 'ativa',
    item_id: `p${i % 40}`,
    ancora: { versao: 'v1', tipo_do_item: 'pessoa' },
    autor_email: 'ana@redetv.com.br',
    criada_em: '2026-10-31T12:00:00Z',
    motivo: 'nome',
  })) as never

  const antes = performance.now()
  const marcas = marcasDosItens(d, itensGrandes, historico)
  const gasto = performance.now() - antes

  expect(Object.keys(marcas).length).toBeGreaterThan(0)
  expect(gasto).toBeLessThan(25)
})
