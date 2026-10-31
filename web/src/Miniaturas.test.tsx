import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import type { Job } from './jobs.ts'
import { render } from './render-teste.tsx'
import Visualizador from './Visualizador.tsx'

const DECUPAGEM = {
  pautas: [],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      na_imagem: [
        { inicio_ms: 1_000, fim_ms: 5_000, evidencia: 'rosto', quadro: 'quadros/aparicao-0-0.jpg' },
        { inicio_ms: 6_000, fim_ms: 8_000, evidencia: 'rosto' },
      ],
      citada_na_fala: [],
      citada_no_texto: [],
    },
  ],
  planos: [
    { id: 'pl1', ambiente: 'Estúdio', inicio_ms: 0, fim_ms: 5_000, quadro: 'quadros/plano-0.jpg' },
    { id: 'pl2', ambiente: 'Externa', inicio_ms: 5_000, fim_ms: 9_000 },
  ],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
  objetos: [
    {
      id: 'o1',
      categoria: 'calcado',
      tipo: 'sandália',
      cor_base: ['vermelho'],
      quadro: 'quadros/objeto-0.jpg',
      ocorrencias: [{ inicio_ms: 2_000, fim_ms: 3_000 }],
    },
  ],
}

const pedidos: string[] = []
const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/jobs/j1/quadros/:arquivo', ({ params }) => {
    pedidos.push(String(params.arquivo))
    return HttpResponse.json({
      url: `https://exemplo.test/quadros/${String(params.arquivo)}`,
      expira_em: '2999-01-01T00:00:00Z',
    })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  pedidos.length = 0
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 9,
  criado_em: '2026-10-21T12:00:00Z',
}

async function abrir() {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={false} />
    </AtalhosProvider>,
  )
  await screen.findByRole('tablist')
}

const fontes = () =>
  Array.from(screen.getByRole('tabpanel').querySelectorAll('img')).map((i) => i.getAttribute('src'))

test('as linhas dos planos pedem a URL do quadro do momento e o plano sem quadro fica no retângulo', async () => {
  await abrir()
  await userEvent.setup().click(screen.getByRole('tab', { name: /Planos/ }))

  await waitFor(() => expect(fontes()).toEqual(['https://exemplo.test/quadros/plano-0.jpg']))
  expect(pedidos).toEqual(['plano-0.jpg'])
  expect(screen.getByRole('tabpanel').querySelectorAll('img[loading="lazy"]')).toHaveLength(1)
})

test('cada aparição pede o quadro dela; a sem quadro não pede nada', async () => {
  await abrir()
  const usuario = userEvent.setup()
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(screen.getByRole('button', { name: /Leão Lobo, 2 aparições/ }))

  await waitFor(() => expect(fontes()).toEqual(['https://exemplo.test/quadros/aparicao-0-0.jpg']))
  expect(pedidos).toEqual(['aparicao-0-0.jpg'])
})

test('o objeto mostra o quadro da primeira ocorrência', async () => {
  await abrir()
  await userEvent.setup().click(screen.getByRole('tab', { name: /Objetos/ }))

  await waitFor(() => expect(fontes()).toEqual(['https://exemplo.test/quadros/objeto-0.jpg']))
})

test('a aba Agora traz a miniatura dos itens do momento e a outra aba reaproveita a URL já pedida', async () => {
  await abrir()
  const player = screen.getByLabelText('Player') as HTMLVideoElement
  player.currentTime = 2.5
  fireEvent.timeUpdate(player)

  await waitFor(() =>
    expect(fontes().sort()).toEqual([
      'https://exemplo.test/quadros/aparicao-0-0.jpg',
      'https://exemplo.test/quadros/objeto-0.jpg',
    ]),
  )
  await userEvent.setup().click(screen.getByRole('tab', { name: /Objetos/ }))

  await waitFor(() => expect(fontes()).toEqual(['https://exemplo.test/quadros/objeto-0.jpg']))
  expect(pedidos.sort()).toEqual(['aparicao-0-0.jpg', 'objeto-0.jpg'])
})
