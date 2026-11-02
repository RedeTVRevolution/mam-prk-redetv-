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
})
