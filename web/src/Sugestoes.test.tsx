import { cleanup, screen, waitFor, within } from '@testing-library/react'
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
      nome: 'Não identificado 1',
      fontes_do_nome: ['rosto'],
      na_imagem: [
        { inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' },
        { inicio_ms: 60_000, fim_ms: 70_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' },
      ],
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


const PESSOA = { tipo: 'pessoa.renomear', item_id: 'p1', valor: 'Leão Lobo' }
const SUGESTOES = () => [
  {
    id: 's1',
    tipo: 'identificar_pessoa',
    inicio_ms: 211_000,
    fim_ms: 261_000,
    pergunta: 'É Leão Lobo?',
    contexto: 'GC às 03:31: LEÃO LOBO · colunista',
    correcao: PESSOA,
    depois: [],
  },
  {
    id: 's2',
    tipo: 'tipo_novo_do_servidor',
    inicio_ms: 300_000,
    fim_ms: 330_000,
    pergunta: 'Acrescentar vestido vermelho?',
    contexto: 'Visual cita uma peça fora dos objetos',
    correcao: { tipo: 'objeto.acrescentar', item_id: '', valor: 'vestido vermelho' },
    depois: [],
  },
]

let lista: Record<string, unknown>[] = []
let aceitas: { id: string; corpo: unknown }[] = []
let recusadas: string[] = []

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/eu', () =>
    HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
  ),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/fila', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/sugestoes', () => HttpResponse.json(lista)),
  http.post('/v1/jobs/j1/sugestoes/:id/aceitar', async ({ request, params }) => {
    const texto = await request.text()
    aceitas.push({ id: String(params.id), corpo: texto ? JSON.parse(texto) : null })
    lista = lista.filter((s) => s.id !== params.id)
    return HttpResponse.json({ id: 'c1', ids: ['c1'] }, { status: 201 })
  }),
  http.post('/v1/jobs/j1/sugestoes/:id/recusar', ({ params }) => {
    recusadas.push(String(params.id))
    lista = lista.filter((s) => s.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),
  http.get('/v1/catalogo/pessoas', () =>
    HttpResponse.json([
      { id: 'cat-sabrina', nome: 'Sabrina Sato', rotulo: 'Sabrina Sato (apresentadora)', a_revisar: false },
    ]),
  ),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  lista = SUGESTOES()
  aceitas = []
  recusadas = []
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(podeEditar = true) {
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

async function catalogar() {
  const usuario = await abrir()
  await usuario.keyboard('e')
  await screen.findByRole('button', { name: /Sugestões \(2\)/ })
  return usuario
}

test('com as sugestões abertas, a seção mostra a pergunta, o trecho e o contexto', async () => {
  await catalogar()
  expect(screen.getByText('É Leão Lobo?')).toBeTruthy()
  expect(screen.getByText('03:31–04:21')).toBeTruthy()
  expect(screen.getByText('GC às 03:31: LEÃO LOBO · colunista')).toBeTruthy()
})

test('S aceita a sugestão em foco, ela some e a contagem diminui; a linha diz a quantas aparições vale', async () => {
  const usuario = await catalogar()
  await usuario.keyboard('s')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: null }]))
  await screen.findByRole('button', { name: /Sugestões \(1\)/ })
  expect(screen.queryByText('É Leão Lobo?')).toBeNull()
  expect(await screen.findByText('Vale para as 2 aparições de Leão Lobo neste vídeo.')).toBeTruthy()
})

test('N recusa a sugestão em foco', async () => {
  const usuario = await catalogar()
  await usuario.keyboard('n')
  await waitFor(() => expect(recusadas).toEqual(['s1']))
  await screen.findByRole('button', { name: /Sugestões \(1\)/ })
})

test('↑ ↓ trocam a sugestão em foco e S aceita a escolhida', async () => {
  const usuario = await catalogar()
  await usuario.click(screen.getByRole('group', { name: 'É Leão Lobo?' }))
  await usuario.keyboard('{ArrowDown}')
  await usuario.keyboard('s')
  await waitFor(() => expect(aceitas.map((a) => a.id)).toEqual(['s2']))
})

test('clicar numa sugestão a põe em foco para as teclas', async () => {
  const usuario = await catalogar()
  await usuario.click(screen.getByText('Acrescentar vestido vermelho?'))
  await usuario.keyboard('n')
  await waitFor(() => expect(recusadas).toEqual(['s2']))
})

test('R abre o autocompletar, o nome escolhido e Enter aceitam com o nome dado', async () => {
  const usuario = await catalogar()
  await usuario.keyboard('r')
  const campo = await screen.findByRole('combobox', { name: 'Outro nome' })
  await usuario.type(campo, 'Sabrin')
  await usuario.click(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' }))
  expect((campo as HTMLInputElement).value).toBe('Sabrina Sato')
  await usuario.type(campo, '{Enter}')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: { valor: 'Sabrina Sato' } }]))
})

test('R, nome digitado e Enter aceitam; Esc cancela sem aceitar', async () => {
  const usuario = await catalogar()
  await usuario.keyboard('r')
  await usuario.type(await screen.findByRole('combobox', { name: 'Outro nome' }), 'X{Escape}')
  expect(screen.queryByRole('combobox', { name: 'Outro nome' })).toBeNull()
  expect(aceitas).toEqual([])
  await usuario.keyboard('r')
  await usuario.type(await screen.findByRole('combobox', { name: 'Outro nome' }), 'Ana{Enter}')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: { valor: 'Ana' } }]))
})

test('os botões Aceitar e Recusar fazem o mesmo que S e N', async () => {
  const usuario = await catalogar()
  await usuario.click(within(screen.getByRole('group', { name: 'É Leão Lobo?' })).getByRole('button', { name: 'Aceitar' }))
  await waitFor(() => expect(aceitas.map((a) => a.id)).toEqual(['s1']))
  await usuario.click(within(screen.getByRole('group', { name: 'Acrescentar vestido vermelho?' })).getByRole('button', { name: 'Recusar' }))
  await waitFor(() => expect(recusadas).toEqual(['s2']))
  await waitFor(() => expect(screen.queryByRole('button', { name: /Sugestões/ })).toBeNull())
})

test('Outro nome, clique na opção e Salvar aceitam com o nome dado', async () => {
  const usuario = await catalogar()
  await usuario.click(within(screen.getByRole('group', { name: 'É Leão Lobo?' })).getByRole('button', { name: 'Outro nome' }))
  await usuario.type(await screen.findByRole('combobox', { name: 'Outro nome' }), 'Sabrin')
  await usuario.click(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: { valor: 'Sabrina Sato' } }]))
})

test('um tipo de sugestão que a tela não conhece aparece e se resolve', async () => {
  lista = [SUGESTOES()[1]]
  const usuario = await abrir()
  await usuario.keyboard('e')
  expect(await screen.findByText('Acrescentar vestido vermelho?')).toBeTruthy()
  await usuario.keyboard('s')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's2', corpo: null }]))
  await waitFor(() => expect(screen.queryByText('Acrescentar vestido vermelho?')).toBeNull())
})

test('a seção recolhe e abre', async () => {
  const usuario = await catalogar()
  await usuario.click(screen.getByRole('button', { name: /Sugestões \(2\)/ }))
  expect(screen.queryByText('É Leão Lobo?')).toBeNull()
  await usuario.click(screen.getByRole('button', { name: /Sugestões \(2\)/ }))
  expect(screen.getByText('É Leão Lobo?')).toBeTruthy()
})

test('fora do modo de catalogação não há seção, e S, N e R não fazem nada', async () => {
  const usuario = await abrir()
  await usuario.keyboard('snr')
  expect(screen.queryByText('É Leão Lobo?')).toBeNull()
  expect(screen.queryByRole('button', { name: /Sugestões/ })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Aceitar' })).toBeNull()
  expect(aceitas).toEqual([])
  expect(recusadas).toEqual([])
})

test('S, N e R aparecem na lista de atalhos', async () => {
  const usuario = await catalogar()
  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).getByText('Sugestão em foco: aceitar')).toBeTruthy()
  expect(within(lista).getByText('Sugestão em foco: recusar')).toBeTruthy()
  expect(within(lista).getByText('Sugestão em foco: outro nome')).toBeTruthy()
})
