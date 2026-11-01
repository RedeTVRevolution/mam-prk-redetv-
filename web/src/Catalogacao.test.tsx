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

test('E liga e desliga o modo de catalogação, só para quem edita', async () => {
  const usuario = await abrir(true)
  expect(screen.queryByText('Catalogando')).toBeNull()

  await usuario.keyboard('e')
  expect(screen.getByText('Catalogando')).toBeTruthy()

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()
})

test('sem decupagem.editar, E não faz nada e não está na lista do ?', async () => {
  const usuario = await abrir(false)

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).queryByText('Catalogar')).toBeNull()
  expect(within(lista).queryByText(/catalogação/i)).toBeNull()
})

test('com decupagem.editar, a lista do ? traz os atalhos da catalogação', async () => {
  const usuario = await abrir(true)

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  for (const acao of [/Ligar e desligar o modo de catalogação/, /Desfazer a última correção/])
    expect(within(lista).getByText(acao)).toBeTruthy()
  await waitFor(() => expect(within(lista).getByRole('table', { name: 'Catalogação' })).toBeTruthy())
})

function correcaoDoHistorico(id: string, autor: string, estado = 'ativa', tipo = 'pessoa.renomear') {
  return {
    id,
    tipo,
    estado,
    autor_email: autor,
    antes_legivel: 'Não identificado',
    depois_legivel: 'Leão Lobo',
  }
}

test('Ctrl+Z desfaz a última correção do próprio editor e avisa', async () => {
  servidor.use(
    http.get('/v1/eu', () =>
      HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
    ),
  )
  historico = [
    correcaoDoHistorico('c3', 'outro@redetv.com.br'),
    correcaoDoHistorico('c2', 'ana@redetv.com.br', 'desfeita'),
    correcaoDoHistorico('c1', 'ana@redetv.com.br'),
  ]
  const usuario = await abrir(true)
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  expect(await screen.findByText('Desfeito: Renomear pessoa (Leão Lobo → Não identificado)')).toBeTruthy()
  expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }])
})

test('Ctrl+Z pula a correção pendente, que a API não desfaz, e desfaz a aprovada', async () => {
  historico = [
    correcaoDoHistorico('c2', 'ana@redetv.com.br', 'pendente'),
    correcaoDoHistorico('c1', 'ana@redetv.com.br', 'aprovada'),
  ]
  const usuario = await abrir(true)
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  await waitFor(() => expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }]))
})

test('Ctrl+Shift+Z não desfaz', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir(true)
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}{Shift>}z{/Shift}{/Control}')

  expect(desfeitas).toEqual([])
})

test('Ctrl+Z fora do modo de catalogação não desfaz nada', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir(true)

  await usuario.keyboard('{Control>}z{/Control}')

  expect(desfeitas).toEqual([])
})

test('o botão Catalogar liga e desliga o modo como o E, com a dica Catalogar (E)', async () => {
  const usuario = await abrir(true)
  const botao = screen.getByRole('button', { name: 'Catalogar' })
  expect(botao.getAttribute('aria-pressed')).toBe('false')

  await usuario.hover(botao)
  expect(await screen.findByText('Catalogar (E)')).toBeTruthy()

  await usuario.click(botao)
  expect(screen.getByText('Catalogando')).toBeTruthy()
  expect(botao.getAttribute('aria-pressed')).toBe('true')

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()
  expect(botao.getAttribute('aria-pressed')).toBe('false')
})

test('sem decupagem.editar, o botão Catalogar não aparece', async () => {
  await abrir(false)
  expect(screen.queryByRole('button', { name: 'Catalogar' })).toBeNull()
})

test('o botão Desfazer faz o mesmo que o Ctrl+Z, com a dica que mostra Ctrl+Z', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))

  const botao = screen.getByRole('button', { name: 'Desfazer' })
  await waitFor(() => expect((botao as HTMLButtonElement).disabled).toBe(false))
  await usuario.hover(botao)
  expect(await screen.findByText('Desfazer a última correção (Ctrl+Z)')).toBeTruthy()

  await usuario.click(botao)

  expect(await screen.findByText('Desfeito: Renomear pessoa (Leão Lobo → Não identificado)')).toBeTruthy()
  expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }])
})

test('o botão Desfazer fica desabilitado sem correção do editor para desfazer', async () => {
  historico = [correcaoDoHistorico('c1', 'outro@redetv.com.br')]
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))

  const botao = screen.getByRole('button', { name: 'Desfazer' })
  await waitFor(() => expect((botao as HTMLButtonElement).disabled).toBe(true))
})
