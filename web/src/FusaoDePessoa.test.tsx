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
let fundidas: { origem: string; corpo: unknown }[] = []

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
  http.get('/v1/catalogo/pessoas', () =>
    HttpResponse.json([{ id: 'cat-leao', nome: 'Leão Lobo', rotulo: 'Leão Lobo (jurado)', a_revisar: false }]),
  ),
  http.get('/v1/catalogo/pessoas/:id/fundir/impacto', () =>
    HttpResponse.json({ origem_nome: 'Leo Lobo', destino_nome: 'Leão Lobo', videos: 3, aparicoes: 5, fotos_apagadas: 2 }),
  ),
  http.post('/v1/catalogo/pessoas/:id/fundir', async ({ request, params }) => {
    fundidas.push({ origem: String(params.id), corpo: await request.json() })
    decupagemAtual = DECUPAGEM('Leão Lobo', 'cat-leao')
    return HttpResponse.json({})
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  decupagemAtual = DECUPAGEM('Leo Lobo', 'cat-leo')
  fundidas = []
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(podeFundir: boolean) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar podeFundir={podeFundir} />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 1' })
  const usuario = userEvent.setup()
  await usuario.keyboard('e')
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leo Lobo, 1 aparição/ }))
  return usuario
}

test('Fundir com…: escolhe o destino, vê o efeito e Enter funde com o motivo; o painel mostra o destino', async () => {
  const usuario = await abrir(true)
  await usuario.click(await screen.findByRole('button', { name: 'Fundir Leo Lobo com…' }))

  await usuario.type(screen.getByRole('combobox', { name: 'Fundir com' }), 'leão')
  await usuario.click(await screen.findByRole('option', { name: 'Leão Lobo (jurado)' }))
  expect(await screen.findByText(/Leo Lobo passa a ser Leão Lobo em 3 vídeos\. As fotos de referência de Leo Lobo serão apagadas\./)).toBeTruthy()

  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(fundidas).toEqual([{ origem: 'cat-leo', corpo: { destino_id: 'cat-leao', motivo: 'nome duplicado' } }]))
  expect(await screen.findByRole('button', { name: /^Leão Lobo, 1 aparição/ })).toBeTruthy()
  expect(screen.queryByRole('form', { name: /Fundir/ })).toBeNull()
})

test('Esc cancela a fusão sem chamar a rota', async () => {
  const usuario = await abrir(true)
  await usuario.click(await screen.findByRole('button', { name: 'Fundir Leo Lobo com…' }))
  await screen.findByRole('form', { name: 'Fundir Leo Lobo com' })

  await usuario.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('form', { name: /Fundir/ })).toBeNull())
  expect(fundidas).toEqual([])
})

test('sem catalogo.fundir, o botão não aparece', async () => {
  await abrir(false)
  expect(screen.queryByRole('button', { name: /Fundir Leo Lobo/ })).toBeNull()
})
