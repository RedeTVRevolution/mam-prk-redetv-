import { cleanup, screen, waitFor } from '@testing-library/react'
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

const PESSOA = (nome: string, catalogo_id: string) => ({
  id: 'p1',
  nome,
  catalogo_id,
  fontes_do_nome: ['rosto'],
  na_imagem: [{ inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' }],
  citada_na_fala: [],
  citada_no_texto: [],
})

const DECUPAGEM = (nome: string, catalogoId: string) => ({
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [PESSOA(nome, catalogoId)],
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [],
  transcricao: [{ id: 'f1', locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [],
  objetos: [],
})

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 120,
  criado_em: '2026-10-21T10:00:00Z',
}

let decupagemAtual = DECUPAGEM('Leo Lobo', 'cat-leo')
let pedidos: { id: string; corpo: { nome: string; previa: boolean } }[] = []
let consultas = 0
let retomadas = 0
let estadoFinal: 'concluida' | 'falhou' = 'concluida'

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagemAtual)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: [] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/fila', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/revisao/pulso', () => new HttpResponse(null, { status: 204 })),
  http.post('/v1/catalogo/pessoas/:id/renomear', async ({ request, params }) => {
    const corpo = (await request.json()) as { nome: string; previa: boolean }
    pedidos.push({ id: String(params.id), corpo })
    if (!corpo.previa) decupagemAtual = DECUPAGEM(corpo.nome, 'cat-leo')
    return HttpResponse.json({ nome_antigo: 'Leo Lobo', nome_novo: corpo.nome, videos: 3, momentos_afetados: 7, previa: corpo.previa })
  }),
  http.get('/v1/catalogo/pessoas/:id/renomear/andamento', () => {
    consultas += 1
    const feito = consultas > 1
    return HttpResponse.json({
      estado: feito ? estadoFinal : 'em_andamento',
      feitos: feito && estadoFinal === 'concluida' ? 3 : 1,
      total: 3,
      nome_antigo: 'Leo Lobo',
      nome_novo: 'Leão Lobo',
    })
  }),
  http.post('/v1/catalogo/pessoas/:id/renomear/retomar', () => {
    retomadas += 1
    estadoFinal = 'concluida'
    consultas = 0
    return HttpResponse.json({ estado: 'em_andamento', feitos: 1, total: 3, nome_antigo: 'Leo Lobo', nome_novo: 'Leão Lobo' })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  decupagemAtual = DECUPAGEM('Leo Lobo', 'cat-leo')
  pedidos = []
  consultas = 0
  retomadas = 0
  estadoFinal = 'concluida'
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(podeAprovar: boolean) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar podeAprovar={podeAprovar} />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 1' })
  const usuario = userEvent.setup()
  await usuario.keyboard('e')
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leo Lobo, 1 aparição/ }))
  return usuario
}

async function digitarOutroNome(usuario: ReturnType<typeof userEvent.setup>) {
  await usuario.click(await screen.findByRole('button', { name: 'Renomear Leo Lobo em todos os vídeos' }))
  const campo = screen.getByRole('textbox', { name: 'Novo nome' })
  await usuario.clear(campo)
  await usuario.type(campo, 'Leão Lobo')
}

test('mostra a prévia sem mudar nada e, com Enter, renomeia e acompanha a busca até terminar', async () => {
  const usuario = await abrir(true)
  await digitarOutroNome(usuario)

  await usuario.keyboard('{Enter}')

  expect(await screen.findByText(/Leo Lobo passa a ser Leão Lobo em 3 vídeos \(7 momentos\)/)).toBeTruthy()
  expect(pedidos).toEqual([{ id: 'cat-leo', corpo: { nome: 'Leão Lobo', previa: true } }])

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(pedidos[1]).toEqual({ id: 'cat-leo', corpo: { nome: 'Leão Lobo', previa: false } }))
  expect(await screen.findByText('Atualizando a busca: 1 de 3 vídeos.')).toBeTruthy()
  expect(await screen.findByRole('button', { name: /^Leão Lobo, 1 aparição/ })).toBeTruthy()
  expect(await screen.findByText(/Pronto: Leão Lobo em 3 vídeos/, undefined, { timeout: 4000 })).toBeTruthy()
}, 20_000)

test('Esc cancela depois da prévia sem renomear', async () => {
  const usuario = await abrir(true)
  await digitarOutroNome(usuario)
  await usuario.keyboard('{Enter}')
  await screen.findByText(/passa a ser Leão Lobo/)

  await usuario.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('form', { name: /Renomear/ })).toBeNull())
  expect(pedidos.map((p) => p.corpo.previa)).toEqual([true])
})

test('se a busca não termina, "Tentar de novo" retoma', async () => {
  estadoFinal = 'falhou'
  const usuario = await abrir(true)
  await digitarOutroNome(usuario)
  await usuario.keyboard('{Enter}')
  await screen.findByText(/passa a ser/)
  await usuario.keyboard('{Enter}')

  const retomar = await screen.findByRole('button', { name: 'Tentar de novo' }, { timeout: 4000 })
  expect(screen.getByText(/O nome novo já vale nas decupagens/)).toBeTruthy()
  await usuario.click(retomar)

  await waitFor(() => expect(retomadas).toBe(1))
  expect(await screen.findByText(/Pronto: Leão Lobo/, undefined, { timeout: 4000 })).toBeTruthy()
}, 20_000)

test('sem correcao.aprovar, o botão não aparece', async () => {
  await abrir(false)
  expect(screen.queryByRole('button', { name: /Renomear Leo Lobo/ })).toBeNull()
})
