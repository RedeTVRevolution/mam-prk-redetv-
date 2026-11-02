import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import catalogo from './catalogo.fixture.json'
import type { Job } from './jobs.ts'
import { render } from './render-teste.tsx'
import Visualizador from './Visualizador.tsx'

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
}

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 120,
  criado_em: '2026-10-21T10:00:00Z',
}

const correcoes: Record<string, unknown>[] = []
const consultas: string[] = []
const criados: { nome: string }[] = []
let desfeitas: { id: string; motivo: unknown }[] = []
let historico: Record<string, unknown>[] = []
let decupagemAtual: typeof DECUPAGEM = DECUPAGEM

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagemAtual)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/eu', () =>
    HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
  ),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json(historico)),
  http.get('/v1/jobs/j1/fila', () => HttpResponse.json([])),
  http.get('/v1/catalogo/pessoas', ({ request }) => {
    consultas.push(new URL(request.url).searchParams.get('q') ?? '')
    return HttpResponse.json([
      { id: 'cat-sabrina', nome: 'Sabrina Sato', papel: 'apresentadora', rotulo: 'Sabrina Sato (apresentadora)', a_revisar: false },
    ])
  }),
  http.get('/v1/catalogo/marcas', ({ request }) => {
    consultas.push(new URL(request.url).searchParams.get('q') ?? '')
    return HttpResponse.json([{ id: 'cat-marca', nome: 'Marca Y', a_revisar: false }])
  }),
  http.post('/v1/catalogo/:catalogo', async ({ request }) => {
    criados.push((await request.json()) as { nome: string })
    return HttpResponse.json({ id: 'cat-nova', nome: criados.at(-1)?.nome, rotulo: criados.at(-1)?.nome, a_revisar: true }, { status: 201 })
  }),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
  http.post('/v1/jobs/j1/correcoes/:id/desfazer', async ({ request, params }) => {
    desfeitas.push({ id: String(params.id), motivo: ((await request.json()) as { motivo: unknown }).motivo })
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  correcoes.length = 0
  consultas.length = 0
  criados.length = 0
  desfeitas = []
  historico = []
  decupagemAtual = DECUPAGEM
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(podeEditar: boolean) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={podeEditar} />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 1' })
  return userEvent.setup()
}

async function marcar(usuario: ReturnType<typeof userEvent.setup>, de: number, ate: number) {
  const player = (await screen.findByLabelText('Player')) as HTMLVideoElement
  const ir = (s: number) => {
    player.currentTime = s
    fireEvent.timeUpdate(player)
  }
  return { player, ir, de, ate, usuario }
}

async function trechoPorTeclas(de: number, ate: number) {
  const usuario = await abrir(true)
  const { ir } = await marcar(usuario, de, ate)
  await usuario.keyboard('e')
  ir(de)
  await usuario.keyboard('i')
  ir(ate)
  await usuario.keyboard('o')
  return usuario
}

test('I, O, A, 4, texto e Enter criam um texto na tela com os tempos do trecho', async () => {
  const usuario = await trechoPorTeclas(724, 731)
  expect(screen.getByText('12:04–12:11')).toBeTruthy()

  await usuario.keyboard('a')
  await usuario.keyboard('4')
  await usuario.type(screen.getByLabelText('Texto'), 'Rodrigo Faro{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'texto_na_tela.acrescentar',
    item_id: '',
    motivo: 'trecho marcado pelo editor',
  })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({
    inicio_ms: 724_000,
    fim_ms: 731_000,
    tipo: 'gc',
    texto: 'Rodrigo Faro',
  })
  await waitFor(() => expect(screen.queryByText('12:04–12:11')).toBeNull())
})

test('o mesmo trecho se cria só com cliques', async () => {
  const usuario = await abrir(true)
  const { ir } = await marcar(usuario, 724, 731)
  await usuario.keyboard('e')
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
  const usuario = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('1')
  await usuario.type(screen.getByLabelText('Nome'), 'Sabrina Sato')
  await usuario.type(screen.getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.acrescentar_aparicao', item_id: '' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({
    inicio_ms: 10_000,
    fim_ms: 20_000,
    evidencia: 'rosto',
    nome: 'Sabrina Sato',
  })
})

test('aba Marca: acrescenta o comercial com marca, tipo e evidências', async () => {
  const usuario = await trechoPorTeclas(40, 50)
  await usuario.keyboard('a')
  await usuario.keyboard('3')
  await usuario.type(screen.getByLabelText('Marca'), 'Marca Y')
  await usuario.click(screen.getByRole('checkbox', { name: 'Logo' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'comercial.acrescentar' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({
    marca: 'Marca Y',
    tipo: 'intervalo',
    inicio_ms: 40_000,
    fim_ms: 50_000,
    evidencias: ['logo'],
  })
})

test('aba Pauta: acrescenta a pauta com título e tom', async () => {
  const usuario = await trechoPorTeclas(70, 90)
  await usuario.keyboard('a')
  await usuario.keyboard('5')
  await usuario.type(screen.getByLabelText('Título'), 'Clima')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pauta.acrescentar' })
  expect(JSON.parse(String(correcoes[0].valor))).toEqual({
    titulo: 'Clima',
    tom: 'informativo',
    inicio_ms: 70_000,
    fim_ms: 90_000,
  })
})

test('Esc descarta o trecho e o botão Descartar também', async () => {
  const usuario = await trechoPorTeclas(10, 20)
  expect(screen.getByText('00:10–00:20')).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByText('00:10–00:20')).toBeNull()

  const { ir } = await marcar(usuario, 0, 0)
  ir(10)
  await usuario.keyboard('i')
  ir(20)
  await usuario.keyboard('o')
  await usuario.click(screen.getByRole('button', { name: 'Descartar o trecho' }))
  expect(screen.queryByText('00:10–00:20')).toBeNull()
  expect(correcoes).toEqual([])
})

test('I e O de novo movem a borda', async () => {
  const usuario = await trechoPorTeclas(10, 20)
  const { ir } = await marcar(usuario, 0, 0)
  ir(12)
  await usuario.keyboard('i')
  expect(screen.getByText('00:12–00:20')).toBeTruthy()
})

test('I depois da saída, com o campo aberto, apaga a saída, fecha o campo e avisa', async () => {
  const usuario = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  expect(screen.getByRole('tablist', { name: 'Tipo do trecho' })).toBeTruthy()
  const { ir } = await marcar(usuario, 0, 0)
  ir(30)
  await usuario.click(screen.getByRole('button', { name: 'Marcar entrada' }))
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
  expect(screen.getByText('00:30–…')).toBeTruthy()
  expect(screen.getByText(/marque a saída de novo/)).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByText('00:30–…')).toBeNull()
})

test('sair do modo de catalogação descarta o trecho', async () => {
  const usuario = await trechoPorTeclas(10, 20)
  await usuario.keyboard('a')
  await usuario.keyboard('ee')
  expect(screen.queryByText('00:10–00:20')).toBeNull()
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
})

test('sem o modo de catalogação, I, O e A não fazem nada; com o foco num campo também não', async () => {
  const usuario = await abrir(true)
  await usuario.keyboard('io')
  expect(screen.queryByRole('button', { name: 'Descartar o trecho' })).toBeNull()
  await usuario.keyboard('e')
  await usuario.keyboard('a')
  expect(screen.queryByRole('tablist', { name: 'Tipo do trecho' })).toBeNull()
})

test('os atalhos do trecho estão na lista do ?', async () => {
  const usuario = await abrir(true)
  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).getByText(/Marcar a entrada do trecho/)).toBeTruthy()
  expect(within(lista).getByText(/Marcar a saída do trecho/)).toBeTruthy()
  expect(within(lista).getByText(/Descrever o trecho marcado/)).toBeTruthy()
  expect(within(lista).getByText(/o tipo Texto na tela/)).toBeTruthy()
  expect(within(lista).getByText(/criar o nome digitado no catálogo/)).toBeTruthy()
})

async function renomearLeao() {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leão Lobo, 1 aparição/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leão Lobo, 00:10 a 00:20/ }))
  await usuario.keyboard('e')
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })
  const nome = within(formulario).getByLabelText('Nome')
  await usuario.clear(nome)
  return { usuario, nome }
}

test('F2: digitar 2 letras consulta o catálogo; ↓ e Enter escolhem e o Enter seguinte manda o catalogo_id', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'sabrin')
  expect(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' })).toBeTruthy()
  expect(consultas.at(-1)).toBe('sabrin')
  await usuario.keyboard('{ArrowDown}{Enter}')
  expect(correcoes).toEqual([])
  expect((nome as HTMLInputElement).value).toBe('Sabrina Sato')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pessoa.renomear',
    item_id: 'p1',
    valor: 'Sabrina Sato',
    catalogo_id: 'cat-sabrina',
  })
})

test('F2: clicar na opção manda o catalogo_id', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'sabrin')
  await usuario.click(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.renomear', valor: 'Sabrina Sato', catalogo_id: 'cat-sabrina' })
})

test('F2: uma letra não consulta; texto digitado sem escolher não manda catalogo_id', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'S')
  expect(consultas).toEqual([])
  await usuario.type(nome, 'abrina S.')
  await screen.findByRole('option', { name: /Shift\+Enter: criar 'Sabrina S\.' como nova/ })
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ valor: 'Sabrina S.' })
  expect(correcoes[0]).not.toHaveProperty('catalogo_id')
})

test('F2: Shift+Enter cria o nome novo no catálogo e a correção leva o id dele', async () => {
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

test('F2: clicar na última linha cria o nome novo', async () => {
  const { usuario, nome } = await renomearLeao()

  await usuario.type(nome, 'Sabrina S.')
  await usuario.click(await screen.findByRole('option', { name: /Shift\+Enter: criar 'Sabrina S\.' como nova/ }))
  await waitFor(() => expect(criados).toEqual([{ nome: 'Sabrina S.' }]))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ valor: 'Sabrina S.', catalogo_id: 'cat-nova' })
})

test('a marca do comercial (F2) escolhida do catálogo manda o catalogo_id', async () => {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Comerciais/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Marca X/ }))
  await usuario.keyboard('e')
  await usuario.keyboard('{F2}')
  const marca = await screen.findByLabelText('Marca')
  await usuario.clear(marca)
  await usuario.type(marca, 'marc')
  await usuario.click(await screen.findByRole('option', { name: 'Marca Y' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'comercial.marca', item_id: 'c1', valor: 'Marca Y', catalogo_id: 'cat-marca' })
})

test('no trecho, a marca do catálogo preenche o nome, sem catalogo_id (a API só o aceita ao renomear)', async () => {
  const usuario = await trechoPorTeclas(40, 50)
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
    pessoas: [
      ...DECUPAGEM.pessoas,
      { id: 'p9', nome: 'Sabrina Sato', fontes_do_nome: [], na_imagem: [], citada_na_fala: [], citada_no_texto: [] },
    ],
  }
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(correcoes.length > 0 ? nova : DECUPAGEM)),
  )
  const usuario = await trechoPorTeclas(30, 32)
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
