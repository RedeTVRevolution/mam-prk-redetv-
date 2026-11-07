import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, irPara, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// A paridade do trecho marcado (I, O, A) com o Trecho.test.tsx da interface antiga.

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
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [{ id: 'c1', marca: 'Marca X', tipo: 'intervalo', inicio_ms: 40_000, fim_ms: 50_000 }],
  transcricao: [{ id: 'f1', locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [{ id: 't1', tipo: 'gc', texto: 'Leão Lobo, jurado', inicio_ms: 12_000, fim_ms: 15_000 }],
  objetos: [],
}

const correcoes: Record<string, unknown>[] = []
const consultas: string[] = []
const criados: { nome: string }[] = []
let decupagemAtual: object = DECUPAGEM

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 2959, cortes_ms: [] }),
    () => decupagemAtual,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/revisao/aprovar', () => HttpResponse.json({ indexacao: 'pendente' }, { status: 202 })),
  http.get('/v1/catalogo/pessoas', ({ request }) => {
    consultas.push(new URL(request.url).searchParams.get('q') ?? '')
    return HttpResponse.json([{ id: 'cat-sabrina', nome: 'Sabrina Sato', papel: 'apresentadora', rotulo: 'Sabrina Sato (apresentadora)', a_revisar: false }])
  }),
  http.get('/v1/catalogo/marcas', ({ request }) => {
    consultas.push(new URL(request.url).searchParams.get('q') ?? '')
    return HttpResponse.json([{ id: 'cat-marca', nome: 'Marca Y', a_revisar: false }])
  }),
  http.get('/v1/objetos/tipos', () => HttpResponse.json([])),
  http.post('/v1/catalogo/:catalogo', async ({ request }) => {
    criados.push((await request.json()) as { nome: string })
    return HttpResponse.json({ id: 'cat-nova', nome: criados.at(-1)?.nome, rotulo: criados.at(-1)?.nome, a_revisar: true }, { status: 201 })
  }),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  correcoes.length = 0
  consultas.length = 0
  criados.length = 0
  decupagemAtual = DECUPAGEM
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

/** Abre o vídeo; `revisando` liga o modo de revisão (E). */
async function abrir({ revisando = true } = {}) {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ permissoes: ['decupagem.editar'] })
  ;(document.activeElement as HTMLElement).blur()
  if (revisando) await usuario.keyboard('e')
  return { usuario, player, ir: (s: number) => irPara(player, s) }
}

async function trechoPorTeclas(de: number, ate: number) {
  const { usuario, ir } = await abrir()
  ir(de)
  await usuario.keyboard('i')
  ir(ate)
  await usuario.keyboard('o')
  return { usuario, ir }
}

const trecho = () => screen.getByRole('group', { name: 'Trecho' })

test('I, O, A, 4, texto e Enter criam um texto na tela com os tempos do trecho', async () => {
  const { usuario } = await trechoPorTeclas(724, 731)
  expect(within(trecho()).getByText('12:04–12:11')).toBeTruthy()

  await usuario.keyboard('a')
  await usuario.keyboard('4')
  await usuario.type(screen.getByLabelText('Texto'), 'Rodrigo Faro{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'texto_na_tela.acrescentar', item_id: '', motivo: 'trecho marcado pelo editor' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({ inicio_ms: 724_000, fim_ms: 731_000, tipo: 'gc', texto: 'Rodrigo Faro' })
  await waitFor(() => expect(screen.queryByText('12:04–12:11')).toBeNull())
}, 15_000)

test('o mesmo trecho se cria só com cliques', async () => {
  const { usuario, ir } = await abrir()
  ir(724)
  await usuario.click(screen.getByRole('button', { name: 'Marcar entrada' }))
  ir(731)
  await usuario.click(screen.getByRole('button', { name: 'Marcar saída' }))
  await usuario.click(screen.getByRole('button', { name: 'Descrever o trecho' }))
  await usuario.click(screen.getByRole('tab', { name: 'Texto na tela' }))
  await usuario.type(screen.getByLabelText('Texto'), 'Rodrigo Faro')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'texto_na_tela.acrescentar' })
  expect(JSON.parse(String(correcoes[0].valor))).toMatchObject({ inicio_ms: 724_000, fim_ms: 731_000, texto: 'Rodrigo Faro' })
})

test('aba Pessoa: acrescenta a aparição com o nome e a evidência', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('1')
  await usuario.type(screen.getByLabelText('Nome'), 'Sabrina Sato')
  await usuario.type(screen.getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.acrescentar_aparicao', item_id: '' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({ inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', nome: 'Sabrina Sato' })
})

test('aba Marca: acrescenta o comercial com marca, tipo e evidências', async () => {
  const { usuario } = await trechoPorTeclas(40, 50)
  await usuario.keyboard('a')
  await usuario.keyboard('3')
  await usuario.type(screen.getByLabelText('Marca'), 'Marca Y')
  await usuario.click(screen.getByRole('checkbox', { name: 'Logo' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'comercial.acrescentar' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({ marca: 'Marca Y', tipo: 'intervalo', inicio_ms: 40_000, fim_ms: 50_000, evidencias: ['logo'] })
})

test('aba Objeto pela tecla 2: acrescenta o objeto com categoria, tipo, até 2 cores e dono', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('2')
  await usuario.type(screen.getByLabelText('Tipo'), 'camiseta')
  const grupo = screen.getByRole('group', { name: 'Cor base (até 2)' })
  await usuario.click(within(grupo).getByRole('button', { name: 'verde' }))
  await usuario.click(within(grupo).getByRole('button', { name: 'azul' }))
  await usuario.click(within(grupo).getByRole('button', { name: 'roxo' }))
  expect(within(grupo).getByRole('button', { name: 'roxo' }).getAttribute('aria-pressed')).toBe('false')
  await usuario.type(screen.getByLabelText('Tom'), 'verde-musgo')
  await usuario.type(screen.getByLabelText('Detalhe'), 'listrada')
  await usuario.selectOptions(screen.getByRole('combobox', { name: 'Dono' }), 'Leão Lobo')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'objeto.acrescentar', item_id: '' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({
    categoria: 'roupa',
    tipo: 'camiseta',
    cor_base: ['verde', 'azul'],
    cor: 'verde-musgo',
    detalhe: 'listrada',
    marca: null,
    pessoa: 'p1',
    relacao: 'veste',
    inicio_ms: 10_000,
    fim_ms: 20_000,
  })
})

test('aba Objeto: a cor base pela tecla, com o foco no grupo, recusa a terceira', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('2')
  await usuario.type(screen.getByLabelText('Tipo'), 'boné')
  const grupo = screen.getByRole('group', { name: 'Cor base (até 2)' })
  act(() => within(grupo).getByRole('button', { name: 'verde' }).focus())
  await usuario.keyboard('v')
  await usuario.keyboard('z')
  await usuario.keyboard('l')
  expect(within(grupo).getByRole('button', { name: 'laranja' }).getAttribute('aria-pressed')).toBe('false')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(JSON.parse(String(correcoes[0].valor)).cor_base).toEqual(['vermelho', 'azul'])
})

test('aba Objeto pelo clique, sem dono: não manda pessoa nem relação', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.click(screen.getByRole('tab', { name: 'Objeto' }))
  await usuario.type(screen.getByLabelText('Tipo'), 'vaso')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'objeto.acrescentar' })
  const valor = JSON.parse(String(correcoes[0].valor))
  expect(valor).toMatchObject({ tipo: 'vaso', cor_base: [], inicio_ms: 10_000, fim_ms: 20_000 })
  expect(valor.pessoa ?? null).toBeNull()
  expect(valor.relacao ?? null).toBeNull()
})

test('aba Pauta: acrescenta a pauta com título e tom', async () => {
  const { usuario } = await trechoPorTeclas(70, 90)
  await usuario.keyboard('a')
  await usuario.keyboard('5')
  await usuario.type(screen.getByLabelText('Título'), 'Clima')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pauta.acrescentar' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({ titulo: 'Clima', tom: 'informativo', inicio_ms: 70_000, fim_ms: 90_000 })
})

test('Esc descarta o trecho e o botão Descartar também', async () => {
  const { usuario, ir } = await trechoPorTeclas(10, 20)
  expect(screen.getByText('00:10–00:20')).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByText('00:10–00:20')).toBeNull()

  ir(10)
  await usuario.keyboard('i')
  ir(20)
  await usuario.keyboard('o')
  await usuario.click(screen.getByRole('button', { name: 'Descartar o trecho' }))
  expect(screen.queryByText('00:10–00:20')).toBeNull()
  expect(correcoes).toEqual([])
})

test('I e O de novo movem a borda', async () => {
  const { usuario, ir } = await trechoPorTeclas(10, 20)
  ir(12)
  await usuario.keyboard('i')
  expect(screen.getByText('00:12–00:20')).toBeTruthy()
})

test('O antes do I avisa, e O antes da entrada também', async () => {
  const { usuario, ir } = await abrir()
  await usuario.keyboard('o')
  expect(screen.getByText('Marque a entrada antes (I).')).toBeTruthy()
  ir(20)
  await usuario.keyboard('i')
  ir(10)
  await usuario.keyboard('o')
  expect(screen.getByText(/A saída fica depois da entrada/)).toBeTruthy()
})

test('A sem a saída avisa', async () => {
  const { usuario, ir } = await abrir()
  ir(10)
  await usuario.keyboard('i')
  await usuario.keyboard('a')
  expect(screen.getByText('Marque a entrada e a saída do trecho antes (I e O).')).toBeTruthy()
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
})

test('I depois da saída, com o campo aberto, apaga a saída, fecha o campo e avisa', async () => {
  const { usuario, ir } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  expect(screen.getByRole('tablist', { name: 'Tipo do trecho' })).toBeTruthy()
  ir(30)
  await usuario.click(screen.getByRole('button', { name: 'Marcar entrada' }))
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
  expect(screen.getByText('00:30–…')).toBeTruthy()
  expect(screen.getByText(/marque a saída de novo/)).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByText('00:30–…')).toBeNull()
})

test('Esc no campo do trecho fecha o campo e deixa o trecho; o segundo Esc o descarta', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('{Escape}')
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
  expect(screen.getByText('00:10–00:20')).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByText('00:10–00:20')).toBeNull()
})

test('as alças do trecho movem as bordas; Enter grava o que o campo mostra e Esc descarta', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('5')
  await usuario.type(screen.getByLabelText('Título'), 'Clima')
  const fim = within(trecho()).getByRole('slider', { name: 'Fim do trecho' })
  act(() => fim.focus())
  await usuario.keyboard('{Shift>}{ArrowRight}{/Shift}')
  expect(within(trecho()).getByText('00:10–00:21')).toBeTruthy()
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(JSON.parse(String(correcoes[0].valor))).toMatchObject({ titulo: 'Clima', inicio_ms: 10_000, fim_ms: 21_000 })
})

test('sair do modo de catalogação descarta o trecho', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('e')
  expect(screen.queryByText('00:10–00:20')).toBeNull()
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
})

test('sem o modo de catalogação, I, O e A não fazem nada e não há botões do trecho', async () => {
  const { usuario } = await abrir({ revisando: false })
  await usuario.keyboard('io')
  expect(screen.queryByRole('group', { name: 'Trecho' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Marcar entrada' })).toBeNull()
  await usuario.keyboard('a')
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
})

test('com o foco num campo, I, O e A não são atalhos', async () => {
  const { usuario } = await abrir()
  await usuario.click(screen.getByLabelText('Campo'))
  await usuario.keyboard('io')
  expect(screen.queryByRole('group', { name: 'Trecho' })).toBeNull()
})

test('os atalhos do trecho estão na lista do ?', async () => {
  const { usuario } = await abrir()
  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).getByText(/Marcar a entrada do trecho/)).toBeTruthy()
  expect(within(lista).getByText(/Marcar a saída do trecho/)).toBeTruthy()
  expect(within(lista).getByText(/Descrever o trecho marcado/)).toBeTruthy()
  expect(within(lista).getByText(/o tipo Texto na tela/)).toBeTruthy()
  expect(within(lista).getByText(/criar o nome digitado no catálogo/)).toBeTruthy()
})

test('com a gaveta aberta, Esc fecha a gaveta e deixa o trecho', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.click(screen.getByRole('button', { name: /^Histórico/ }))
  await screen.findByRole('complementary', { name: 'Correções do vídeo' })
  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull())
  expect(screen.getByText('00:10–00:20')).toBeTruthy()
})

test('no trecho, a marca do catálogo preenche o nome, sem catalogo_id (a API só o aceita ao renomear)', async () => {
  const { usuario } = await trechoPorTeclas(40, 50)
  await usuario.keyboard('a')
  await usuario.keyboard('3')
  await usuario.type(screen.getByLabelText('Marca'), 'marc')
  await usuario.click(await screen.findByRole('option', { name: 'Marca Y' }))
  await usuario.click(screen.getByRole('checkbox', { name: 'Logo' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).not.toHaveProperty('catalogo_id')
  expect(JSON.parse(String(correcoes[0].valor))).toMatchObject({ marca: 'Marca Y' })
})

test('aba Pessoa com "Citada": acrescenta a aparição e troca para menção na fala, com o id da pessoa nova', async () => {
  const nova = {
    ...DECUPAGEM,
    pessoas: [...DECUPAGEM.pessoas, { id: 'p9', nome: 'Sabrina Sato', fontes_do_nome: [], na_imagem: [], citada_na_fala: [], citada_no_texto: [] }],
  }
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(correcoes.length > 0 ? nova : DECUPAGEM)))
  const { usuario } = await trechoPorTeclas(30, 32)
  await usuario.keyboard('a')
  await usuario.keyboard('1')
  await usuario.type(screen.getByLabelText('Nome'), 'sabrina sato')
  await usuario.click(screen.getByRole('checkbox', { name: 'Citada (não aparece na imagem)' }))
  expect(screen.queryByLabelText('Evidência na imagem')).toBeNull()
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(2))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.acrescentar_aparicao', item_id: '' })
  expect(correcoes[1]).toMatchObject({
    tipo: 'pessoa.aparicao_para_mencao',
    item_id: 'p9',
    valor: 'citada_na_fala',
    ocorrencia: { lista: 'na_imagem', inicio_ms: 30_000, fim_ms: 32_000 },
    motivo: 'trecho marcado pelo editor',
  })
  expect(correcoes[1]).not.toHaveProperty('pessoa_do_nome')
})

test('Descrever o trecho com a comparação aberta fecha a comparação e mostra o campo', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/passadas', () => HttpResponse.json([{ id: 'p1', job_id: 'j1', modelo: 'gemini-3.8-flash', criada_em: '2026-11-02T12:00:00Z', custo: {}, etapas: [] }])),
    http.get('/v1/jobs/j1/passadas/p1/comparacao', () => HttpResponse.json({ passada_id: 'p1', modelo: 'm', modelo_do_job: 'n', duracao_ms: 60_000, a: { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 1, etapas: [] }, b: { custo_usd: null, custo_por_hora_usd: null, tempo_total_s: 1, etapas: [] }, requisitos: [] })),
  )
  const { usuario } = await trechoPorTeclas(10, 20)
  await usuario.selectOptions(await screen.findByRole('combobox', { name: 'Comparar com' }), 'p1')
  await screen.findByRole('complementary', { name: 'Comparação com a passada' })

  await usuario.click(screen.getByRole('button', { name: 'Descrever o trecho' }))

  expect(await screen.findByRole('tablist', { name: 'Tipo do trecho' })).toBeTruthy()
  expect(screen.queryByRole('complementary', { name: 'Comparação com a passada' })).toBeNull()
})

test('abrir a correção de um item com o campo do trecho aberto fecha o campo do trecho', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  const inspetor = within(screen.getByRole('complementary', { name: 'Inspetor' }))
  await usuario.click(inspetor.getByRole('button', { name: /^Pautas \d+$/ }))
  await usuario.click(await inspetor.findByRole('button', { name: /^Eleição, 00:00 a 01:00/ }))
  await inspetor.findByRole('button', { name: 'Corrigir' })
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('a')
  expect(await screen.findByRole('tablist', { name: 'Tipo do trecho' })).toBeTruthy()

  await usuario.click(inspetor.getByRole('button', { name: 'Corrigir' }))

  await waitFor(() => expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull())
  expect(screen.getByText('00:10–00:20')).toBeTruthy()
})

test('com o detalhe de um item aberto, o primeiro Esc descarta o trecho e o segundo volta à lista', async () => {
  const { usuario } = await trechoPorTeclas(10, 20)
  const inspetor = within(screen.getByRole('complementary', { name: 'Inspetor' }))
  await usuario.click(inspetor.getByRole('button', { name: /^Pautas \d+$/ }))
  await usuario.click(await inspetor.findByRole('button', { name: /^Eleição, 00:00 a 01:00/ }))
  await inspetor.findByRole('region', { name: /^Detalhe:/ })
  ;(document.activeElement as HTMLElement).blur()

  await usuario.keyboard('{Escape}')

  expect(screen.queryByText('00:10–00:20')).toBeNull()
  expect(inspetor.getByRole('region', { name: /^Detalhe:/ })).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(inspetor.queryByRole('region', { name: /^Detalhe:/ })).toBeNull()
})

test('E e o botão Revisar, com a decupagem ainda sem chegar, avisam em vez de não fazer nada', async () => {
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => new Promise(() => {})))
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'], esperarFaixas: false })
  ;(document.activeElement as HTMLElement).blur()

  await usuario.keyboard('e')

  expect(await screen.findByText('Espere a decupagem carregar para revisar ou aprovar a revisão.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Revisar' })).toBeTruthy()
})
