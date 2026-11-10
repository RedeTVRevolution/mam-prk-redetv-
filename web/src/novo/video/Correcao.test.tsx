import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade da correção com o Catalogacao.test.tsx, o Trecho.test.tsx (o campo de nome) e o
// BuscaNoVisualizador.test.tsx (as marcas da correção) da interface antiga. Sem o modo de
// catalogação (fase 5): quem tem decupagem.editar corrige pelo detalhe do item, com F2 e Del.

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      fontes_do_nome: ['rosto'],
      na_imagem: [{ inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' }],
      citada_na_fala: [{ inicio_ms: 30_000, fim_ms: 32_000 }],
      citada_no_texto: [],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 5_000, fim_ms: 9_000 }],
  comerciais: [{ id: 'c1', marca: 'Marca X', tipo: 'intervalo', inicio_ms: 40_000, fim_ms: 50_000 }],
  transcricao: [{ id: 'f1', locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [],
  objetos: [
    {
      id: 'o1',
      categoria: 'roupa',
      tipo: 'camisa',
      cor_base: ['azul'],
      cor: 'azul marinho',
      pessoa: 'p1',
      relacao: 'veste',
      ocorrencias: [{ inicio_ms: 10_000, fim_ms: 20_000 }],
    },
  ],
}

const correcoes: Record<string, unknown>[] = []
const consultas: string[] = []
const criados: { nome: string }[] = []
let historico: Record<string, unknown>[] = []
let cargas = 0
let decupagem: Record<string, unknown> = DECUPAGEM

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => {
      cargas += 1
      return decupagem
    },
  ),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json(historico)),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
  http.get('/v1/catalogo/pessoas', ({ request }) => {
    consultas.push(new URL(request.url).searchParams.get('q') ?? '')
    return HttpResponse.json([{ id: 'cat-sabrina', nome: 'Sabrina Sato', papel: 'apresentadora', rotulo: 'Sabrina Sato (apresentadora)', a_revisar: false }])
  }),
  http.post('/v1/catalogo/:catalogo', async ({ request }) => {
    criados.push((await request.json()) as { nome: string })
    return HttpResponse.json({ id: 'cat-nova', nome: criados.at(-1)?.nome, rotulo: criados.at(-1)?.nome, a_revisar: true }, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  correcoes.length = 0
  consultas.length = 0
  criados.length = 0
  historico = []
  cargas = 0
  decupagem = DECUPAGEM
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const inspetor = () => within(screen.getByRole('complementary', { name: 'Inspetor' }))
const detalhe = () => within(inspetor().getByRole('region', { name: /^Detalhe:/ }))

async function abrirItem(secao: string, item: RegExp, grupo?: RegExp, permissoes = ['decupagem.editar']) {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes })
  const botao = inspetor().getByRole('button', { name: new RegExp(`^${secao} \\d+$`) })
  if (botao.getAttribute('aria-expanded') !== 'true') await usuario.click(botao)
  if (grupo) await usuario.click(inspetor().getByRole('button', { name: grupo }))
  await usuario.click(await inspetor().findByRole('button', { name: item }))
  // O catálogo chega depois da decupagem: só com ele há o que corrigir.
  await detalhe().findByRole('button', { name: 'Corrigir' })
  ;(document.activeElement as HTMLElement).blur()
  return usuario
}

const abrirPauta = () => abrirItem('Pautas', /^Eleição, 00:00 a 01:00/)
const abrirAparicao = () => abrirItem('Pessoas', /^Leão Lobo, 00:10 a 00:20/, /^Leão Lobo, 1 aparição/)
const abrirObjeto = () => abrirItem('Objetos', /^camisa, 00:10 a 00:20/, /^camisa, 1 ocorrência/)

test('F2 → editar → Enter grava a correção com o motivo do gesto, sem diálogo', async () => {
  const usuario = await abrirPauta()

  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  expect(screen.queryByRole('dialog')).toBeNull()
  const titulo = within(formulario).getByLabelText('Título')
  expect(document.activeElement).toBe(titulo)
  expect((within(formulario).getByLabelText('Motivo (opcional)') as HTMLInputElement).value).toBe('')

  await usuario.clear(titulo)
  await usuario.type(titulo, 'Eleição 2026')
  expect((within(formulario).getByLabelText('Motivo (opcional)') as HTMLInputElement).value).toBe('título da pauta corrigido pelo editor')
  const antes = cargas
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pauta.titulo', item_id: 'pa1', valor: 'Eleição 2026', motivo: 'título da pauta corrigido pelo editor', versao: 'v1' })
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  await waitFor(() => expect(cargas).toBeGreaterThan(antes))
})

test('o motivo apagado vale o do gesto; o motivo escrito vale como escrito', async () => {
  const usuario = await abrirPauta()
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')
  const motivo = within(formulario).getByLabelText('Motivo (opcional)')
  await usuario.clear(motivo)
  await usuario.type(motivo, 'a emissora mudou o nome')
  await usuario.click(within(formulario).getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ motivo: 'a emissora mudou o nome' })
})

test('Esc e Cancelar descartam a correção sem gravar, e o detalhe continua aberto', async () => {
  const usuario = await abrirPauta()
  await usuario.keyboard('{F2}')
  let formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')

  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(detalhe().getByRole('heading', { name: 'Eleição' })).toBeTruthy()

  await usuario.keyboard('{F2}')
  formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.click(within(formulario).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toEqual([])
})

test('sem decupagem.editar, ou sem o catálogo, não há o que corrigir', async () => {
  const usuario = userEvent.setup()
  await abrirVideo()
  await usuario.click(inspetor().getByRole('button', { name: /^Pautas \d+$/ }))
  await usuario.click(inspetor().getByRole('button', { name: /^Eleição, 00:00/ }))
  await usuario.keyboard('{F2}')
  expect(detalhe().queryByRole('button', { name: 'Corrigir' })).toBeNull()
  expect(screen.queryByRole('form')).toBeNull()
  cleanup()

  let falhar = true
  servidor.use(http.get('/v1/correcoes/catalogo', () => (falhar ? new HttpResponse(null, { status: 503 }) : HttpResponse.json(catalogo))))
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  await usuario.click(inspetor().getByRole('button', { name: /^Pautas \d+$/ }))
  await usuario.click(inspetor().getByRole('button', { name: /^Eleição, 00:00/ }))
  await usuario.keyboard('{F2}')
  expect(detalhe().queryByRole('button', { name: 'Corrigir' })).toBeNull()
  expect(screen.queryByRole('form')).toBeNull()

  // A falha do catálogo avisa, e o "Tentar de novo" traz a correção de volta.
  const aviso = (await screen.findByText(/Não foi possível carregar as opções de correção/)).closest<HTMLElement>('[role="alert"]')!
  falhar = false
  await usuario.click(within(aviso).getByRole('button', { name: 'Tentar de novo' }))
  expect(await detalhe().findByRole('button', { name: 'Corrigir' })).toBeTruthy()
})

test('F2 sem item selecionado avisa', async () => {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  await waitFor(() => expect(cargas).toBe(1))
  await new Promise((r) => setTimeout(r, 50))

  await usuario.keyboard('{F2}')

  expect(await screen.findByText('Selecione um item que possa ser corrigido (↑ ↓).')).toBeTruthy()
})

test('um 409 mostra a mensagem do servidor, fecha o formulário e recarrega a decupagem', async () => {
  servidor.use(http.post('/v1/jobs/j1/correcoes', () => HttpResponse.json({ detail: 'A decupagem mudou. Confira e corrija de novo.' }, { status: 409 })))
  const usuario = await abrirPauta()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')
  const antes = cargas

  await usuario.keyboard('{Enter}')

  expect(await screen.findByText('A decupagem mudou. Confira e corrija de novo.')).toBeTruthy()
  await waitFor(() => expect(cargas).toBeGreaterThan(antes))
  expect(screen.queryByRole('form')).toBeNull()
})

test('um 422 fica no formulário, com a mensagem do servidor', async () => {
  servidor.use(http.post('/v1/jobs/j1/correcoes', () => HttpResponse.json({ detail: 'O título é longo demais.' }, { status: 422 })))
  const usuario = await abrirPauta()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')

  await usuario.keyboard('{Enter}')

  expect((await within(formulario).findByRole('alert')).textContent).toBe('O título é longo demais.')
  expect(screen.getByRole('form', { name: /Corrigir Eleição/ })).toBeTruthy()
})

test('pelo clique: resumo e tom da pauta', async () => {
  const usuario = await abrirPauta()
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Eleição/ }))
  await usuario.type(formulario.getByLabelText('Resumo'), ' na TV')
  await usuario.selectOptions(formulario.getByLabelText('Tom'), 'polemico')
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(2))
  expect(correcoes.map((c) => [c.tipo, c.valor])).toEqual([
    ['pauta.resumo', 'Debate na TV'],
    ['pauta.tom', 'polemico'],
  ])
})

test('pelo clique: descrição do plano e plano limpo', async () => {
  const usuario = await abrirItem('Planos', /^estúdio/)
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = within(await screen.findByRole('form', { name: /Corrigir estúdio/ }))
  await usuario.type(formulario.getByLabelText('Objetos (separados por vírgula)'), 'mesa, copo')
  await usuario.click(formulario.getByRole('checkbox', { name: 'Plano limpo' }))
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(2))
  expect(correcoes.map((c) => c.tipo)).toEqual(['plano.descricao', 'plano.limpo'])
})

test('pelo clique: tipo do comercial', async () => {
  const usuario = await abrirItem('Comerciais', /^Marca X/)
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Marca X/ }))
  await usuario.selectOptions(formulario.getByLabelText('Tipo'), 'testemunhal')
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes).toMatchObject([{ tipo: 'comercial.tipo', item_id: 'c1', valor: 'testemunhal' }])
})

test('pelo clique: papel da aparição, as fontes do nome e a aparição que vira menção', async () => {
  const usuario = await abrirAparicao()
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Leão Lobo/ }))
  await usuario.clear(formulario.getByLabelText('Papel na cena'))
  await usuario.type(formulario.getByLabelText('Papel na cena'), 'convidado')
  await usuario.click(formulario.getByRole('checkbox', { name: 'rosto' }))
  await usuario.click(formulario.getByRole('checkbox', { name: 'GC' }))
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(2))
  expect(correcoes.map((c) => [c.tipo, c.valor])).toEqual([
    ['pessoa.fontes_do_nome', JSON.stringify(['gc'])],
    ['aparicao.papel_visual', JSON.stringify({ papel: 'convidado', visual: 'barba' })],
  ])

  correcoes.length = 0
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const deNovo = within(await screen.findByRole('form', { name: /Corrigir Leão Lobo/ }))
  await usuario.selectOptions(deNovo.getByLabelText('Aparição ou menção'), 'citada_na_fala')
  await usuario.click(deNovo.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes).toMatchObject([{ tipo: 'pessoa.aparicao_para_mencao', valor: 'citada_na_fala', ocorrencia: { lista: 'na_imagem' } }])
})

test('pelo clique: a menção que vira aparição, com a evidência', async () => {
  const usuario = await abrirItem('Menções', /^Leão Lobo, 00:30/)
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Leão Lobo/ }))
  await usuario.selectOptions(formulario.getByLabelText('Aparição ou menção'), 'na_imagem')
  await usuario.type(formulario.getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes).toMatchObject([{ tipo: 'pessoa.mencao_para_aparicao', valor: 'rosto', ocorrencia: { lista: 'citada_na_fala' } }])
})

test('pelo clique: texto e locutor da fala', async () => {
  const usuario = await abrirItem('Falas', /^Ana: Boa noite, 00:00/)
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Boa noite/ }))
  await usuario.clear(formulario.getByLabelText('Locutor'))
  await usuario.type(formulario.getByLabelText('Locutor'), 'Bia')
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes).toMatchObject([{ tipo: 'fala.texto', item_id: 'f1', valor: JSON.stringify({ texto: 'Boa noite', locutor: 'Bia' }) }])
})

test('Del pede a confirmação no detalhe; Esc desiste e Enter grava o "não é esta pessoa"', async () => {
  const usuario = await abrirAparicao()

  await usuario.keyboard('{Delete}')
  expect(await screen.findByText('Remover Leão Lobo desta aparição?')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByText('Remover Leão Lobo desta aparição?')).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.keyboard('{Delete}')
  await screen.findByText('Remover Leão Lobo desta aparição?')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pessoa.nao_e',
    item_id: 'p1',
    ocorrencia: { lista: 'na_imagem', inicio_ms: 10_000, fim_ms: 20_000 },
    motivo: 'pessoa removida desta aparição pelo editor',
  })
})

test('"Não é isto" no objeto pede "Este objeto não está na imagem?"; Cancelar e Remover pelo clique', async () => {
  const usuario = await abrirObjeto()

  await usuario.click(detalhe().getByRole('button', { name: 'Não é isto' }))
  const confirmacao = await screen.findByRole('group', { name: 'Confirmar a remoção' })
  expect(within(confirmacao).getByText('Este objeto não está na imagem?')).toBeTruthy()
  await usuario.click(within(confirmacao).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('group', { name: 'Confirmar a remoção' })).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.click(detalhe().getByRole('button', { name: 'Não é isto' }))
  await usuario.click(within(await screen.findByRole('group', { name: 'Confirmar a remoção' })).getByRole('button', { name: 'Remover' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'objeto.nao_existe', item_id: 'o1', valor: 'nao_existe', motivo: 'objeto removido da imagem pelo editor' })
})

test('Enter com o foco no Cancelar da confirmação cancela, sem remover', async () => {
  const usuario = await abrirAparicao()
  await usuario.keyboard('{Delete}')
  const confirmacao = await screen.findByRole('group', { name: 'Confirmar a remoção' })
  within(confirmacao).getByRole('button', { name: 'Cancelar' }).focus()

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(screen.queryByRole('group', { name: 'Confirmar a remoção' })).toBeNull())
  expect(correcoes).toEqual([])
})

test('objeto: F2 e Enter gravam objeto.atributos', async () => {
  const usuario = await abrirObjeto()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir camisa/ })
  await usuario.type(within(formulario).getByLabelText('Marca'), 'Lacoste')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'objeto.atributos', item_id: 'o1', motivo: 'atributos do objeto corrigidos pelo editor' })
  expect(JSON.parse(correcoes[0].valor as string)).toEqual({ tipo: 'camisa', cor_base: ['azul'], cor: 'azul marinho', detalhe: null, marca: 'Lacoste' })
})

test('objeto: a cor base pela tecla, com o foco no grupo, recusa a terceira e diz por quê; o clique desmarca', async () => {
  const usuario = await abrirObjeto()
  await usuario.keyboard('{F2}')
  const formulario = within(await screen.findByRole('form', { name: /Corrigir camisa/ }))
  const grupo = formulario.getByRole('group', { name: 'Cor base (até 2)' })
  const marcada = (nome: string) => within(grupo).getByRole('button', { name: nome }).getAttribute('aria-pressed') === 'true'
  expect(marcada('azul')).toBe(true)

  act(() => within(grupo).getByRole('button', { name: 'azul' }).focus())
  await usuario.keyboard('v')
  expect(marcada('vermelho')).toBe(true)
  await usuario.keyboard('p')
  expect(marcada('preto')).toBe(false)
  expect(formulario.getByRole('alert').textContent).toBe('No máximo 2 cores: desmarque uma antes de marcar outra.')

  await usuario.click(within(grupo).getByRole('button', { name: 'azul' }))
  expect(marcada('azul')).toBe(false)
  await usuario.click(within(grupo).getByRole('button', { name: 'preto' }))
  expect(marcada('preto')).toBe(true)
})

test('acrescentar aparição grava e cancela pelos botões', async () => {
  const usuario = await abrirAparicao()
  await usuario.click(detalhe().getByRole('button', { name: 'Acrescentar aparição de Leão Lobo' }))
  let formulario = await screen.findByRole('form', { name: 'Acrescentar aparição de Leão Lobo' })
  await usuario.type(within(formulario).getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.click(within(formulario).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.click(detalhe().getByRole('button', { name: 'Acrescentar aparição de Leão Lobo' }))
  formulario = await screen.findByRole('form', { name: 'Acrescentar aparição de Leão Lobo' })
  await usuario.type(within(formulario).getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.acrescentar_aparicao', item_id: 'p1' })
  expect(JSON.parse(String(correcoes[0].valor))).toMatchObject({ evidencia: 'rosto' })
})

test('separar pessoa: mostra o motivo de cada origem e grava pessoa.separar', async () => {
  const origem = (id: string, nome: string, inicio: number, motivo: string | null) => ({
    id,
    chave: `${nome.toLowerCase()}@${inicio}-${inicio + 10_000}`,
    nome,
    janela: 0,
    motivo,
    na_imagem: [],
  })
  decupagem = {
    ...DECUPAGEM,
    pessoas: [
      ...DECUPAGEM.pessoas,
      {
        id: 'p2',
        nome: 'Não identificado, blusa vermelha',
        na_imagem: [
          { inicio_ms: 70_000, fim_ms: 80_000, evidencia: 'visto' },
          { inicio_ms: 90_000, fim_ms: 100_000, evidencia: 'visto' },
        ],
        citada_na_fala: [],
        citada_no_texto: [],
        origens: [
          origem('pes02', 'Não identificado, blusa vermelha', 70_000, null),
          origem('pes03', 'Não identificado, blusa vermelha, calvo', 90_000, 'modelo forte: sim (0.62)'),
        ],
      },
    ],
  }
  const usuario = await abrirItem('Pessoas', /^não identificado.*01:10 a 01:20/i, /^não identificado/i)
  await usuario.click(detalhe().getByRole('button', { name: 'Separar pessoa' }))
  const formulario = await screen.findByRole('form', { name: 'Separar Não identificado, blusa vermelha' })
  await usuario.click(within(formulario).getByRole('combobox', { name: 'Pessoa a separar' }))
  expect(screen.getByRole('option', { name: /calvo \(01:30–01:40\), modelo forte: sim \(0.62\)/ })).toBeTruthy()
  await usuario.click(screen.getByRole('option', { name: /calvo/ }))
  await usuario.click(within(formulario).getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pessoa.separar',
    item_id: 'p2',
    valor: 'não identificado, blusa vermelha, calvo@90000-100000',
    versao: 'v1',
  })
})

test('separar pessoa não aparece na pessoa que a junção não formou', async () => {
  await abrirAparicao()

  expect(detalhe().queryByRole('button', { name: 'Separar pessoa' })).toBeNull()
})

test('as alças aparecem na faixa e movem os tempos de 0,1 s; Enter grava, Esc descarta', async () => {
  const usuario = await abrirAparicao()
  await usuario.keyboard('{F2}')
  await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })

  const inicio = screen.getByRole('slider', { name: 'Início do item' })
  expect(inicio.getAttribute('aria-valuetext')).toBe('00:10')
  inicio.focus()
  await usuario.keyboard('{ArrowRight}{ArrowRight}{ArrowRight}')
  expect(screen.getByRole('slider', { name: 'Início do item' }).getAttribute('aria-valuenow')).toBe('10300')
  screen.getByRole('slider', { name: 'Fim do item' }).focus()
  await usuario.keyboard('{Shift>}{ArrowRight}{/Shift}{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'item.tempos', tipo_do_item: 'pessoa', valor: '10300-21000' })

  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  await usuario.click(detalhe().getByRole('button', { name: 'Corrigir' }))
  screen.getByRole('slider', { name: 'Início do item' }).focus()
  await usuario.keyboard('{ArrowRight}{Escape}')
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toHaveLength(1)
})

test('a faixa do item em correção aparece mesmo desligada nos chips', async () => {
  const usuario = await abrirItem('Menções', /^Leão Lobo, 00:30/)
  expect(screen.queryByRole('group', { name: 'Menções 1' })).toBeNull()

  await usuario.keyboard('{F2}')

  expect(await screen.findByRole('group', { name: 'Menções 1' })).toBeTruthy()
  expect(screen.getByRole('slider', { name: 'Fim do item' })).toBeTruthy()
})

async function renomearLeao() {
  const usuario = await abrirAparicao()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })
  const nome = within(formulario).getByLabelText('Nome')
  await usuario.clear(nome)
  return { usuario, nome, formulario: within(formulario) }
}

test('o nome: 2 letras consultam o catálogo; ↓ e Enter escolhem, e o Enter seguinte manda o catalogo_id', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'sabrin')
  expect(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' })).toBeTruthy()
  expect(consultas.at(-1)).toBe('sabrin')
  await usuario.keyboard('{ArrowDown}{Enter}')
  expect(correcoes).toEqual([])
  expect((nome as HTMLInputElement).value).toBe('Sabrina Sato')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.renomear', item_id: 'p1', valor: 'Sabrina Sato', catalogo_id: 'cat-sabrina' })
})

test('o nome: digitar rápido consulta o catálogo uma vez só, depois da pausa', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'sabrin')
  await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' })

  expect(consultas).toEqual(['sabrin'])
})

test('o nome: a tecla seguinte desmarca o item, e o Enter na pausa não escolhe um nome de outro texto', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'sabrin')
  await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' })
  await usuario.keyboard('{ArrowDown}')
  await usuario.type(nome, 'x{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ valor: 'sabrinx' })
  expect(correcoes[0]).not.toHaveProperty('catalogo_id')
})

test('o nome: uma letra não consulta; o texto digitado sem escolher não manda catalogo_id', async () => {
  const { usuario, nome, formulario } = await renomearLeao()

  await usuario.type(nome, 'S')
  expect(consultas).toEqual([])
  await usuario.type(nome, 'abrina S.')
  await screen.findByRole('option', { name: /Shift\+Enter: criar 'Sabrina S\.' como nova/ })
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ valor: 'Sabrina S.' })
  expect(correcoes[0]).not.toHaveProperty('catalogo_id')
})

test('o nome: Shift+Enter cria o nome novo no catálogo, e a correção leva o id dele', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'Sabrina S.')
  await screen.findByRole('option', { name: /Shift\+Enter: criar/ })
  await usuario.keyboard('{Shift>}{Enter}{/Shift}')
  await waitFor(() => expect(criados).toEqual([{ nome: 'Sabrina S.' }]))
  expect(correcoes).toEqual([])
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.renomear', valor: 'Sabrina S.', catalogo_id: 'cat-nova' })
})

const doHistorico = (id: string, tipo: string, item_id: string, tipo_do_item: string, estado: string, na_busca?: string) => ({
  id,
  tipo,
  estado,
  item_id,
  ancora: { versao: 'v1', tipo_do_item },
  criada_em: '2026-10-31T12:00:00Z',
  motivo: 'corrigido',
  autor_email: 'ana@redetv.com.br',
  antes_legivel: 'a',
  depois_legivel: 'b',
  ...(na_busca ? { na_busca } : {}),
})

test('o item corrigido mostra onde a correção está na busca, e o pendente, "aguardando o Curador"', async () => {
  historico = [doHistorico('c1', 'pauta.titulo', 'pa1', 'pauta', 'ativa', 'na_busca'), doHistorico('c2', 'comercial.marca', 'c1', 'comercial', 'pendente')]
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'] })

  await usuario.click(inspetor().getByRole('button', { name: /^Pautas \d+$/ }))
  expect(await inspetor().findByText('na busca')).toBeTruthy()
  await usuario.click(inspetor().getByRole('button', { name: /^Comerciais \d+$/ }))
  expect(await inspetor().findByText('aguardando o Curador')).toBeTruthy()
})

test('a correção nova mostra "indexando" e passa a "na busca" quando o índice confirma', async () => {
  historico = [doHistorico('c1', 'pauta.titulo', 'pa1', 'pauta', 'ativa', 'indexando')]
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'], indexacaoMs: 20 })
  await usuario.click(inspetor().getByRole('button', { name: /^Pautas \d+$/ }))
  expect(await inspetor().findByText('indexando')).toBeTruthy()
  expect(inspetor().getByText('Atualizando o índice…')).toBeTruthy()

  historico = [doHistorico('c1', 'pauta.titulo', 'pa1', 'pauta', 'ativa', 'na_busca')]

  expect(await inspetor().findByText('na busca')).toBeTruthy()
  expect(inspetor().queryByText('indexando')).toBeNull()
  expect(inspetor().queryByText('Atualizando o índice…')).toBeNull()
})

test('os atalhos da correção estão na lista do ?, só para quem edita', async () => {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  await waitFor(() => expect(cargas).toBe(1))
  await new Promise((r) => setTimeout(r, 50))

  await usuario.keyboard('?')
  const grupo = within(await screen.findByRole('region', { name: 'Correção' }))
  expect(grupo.getByText('Corrigir o item selecionado')).toBeTruthy()
  expect(grupo.getByText(/Não é isto/)).toBeTruthy()
  cleanup()

  await abrirVideo()
  await usuario.keyboard('?')
  await screen.findByRole('dialog')
  expect(screen.queryByRole('region', { name: 'Correção' })).toBeNull()
})

test('F2 com o inspetor recolhido abre o inspetor com o formulário', async () => {
  const usuario = await abrirPauta()
  await usuario.click(inspetor().getByRole('button', { name: 'Recolher o inspetor' }))
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()

  await usuario.keyboard('{F2}')

  expect(await screen.findByRole('form', { name: /Corrigir Eleição/ })).toBeTruthy()
})

test('F2 e Del com a comparação aberta fecham a comparação e mostram o formulário', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/passadas', () => HttpResponse.json([{ id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] }])),
    http.get('/v1/jobs/j1/passadas/p1/comparacao', () => HttpResponse.json({ passada_id: 'p1', modelo: 'm', modelo_do_job: 'n', duracao_ms: 60_000, a: { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 1, etapas: [] }, b: { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 1, etapas: [] }, requisitos: [] })),
  )
  const usuario = await abrirPauta()
  await usuario.selectOptions(await screen.findByRole('combobox', { name: 'Comparar com' }), 'p1')
  await screen.findByRole('complementary', { name: 'Comparação com a passada' })
  ;(document.activeElement as HTMLElement).blur()

  await usuario.keyboard('{F2}')

  expect(await screen.findByRole('form', { name: /Corrigir Eleição/ })).toBeTruthy()
  expect(screen.queryByRole('complementary', { name: 'Comparação com a passada' })).toBeNull()
})
