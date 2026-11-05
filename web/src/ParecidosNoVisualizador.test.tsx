import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { PlanosParecidos } from './PlanosParecidos.tsx'
import { render } from './render-teste.tsx'
import { useRota } from './rotas.ts'
import TelaDoVideo from './TelaDoVideo.tsx'

const plano = (id: string, inicio_ms: number) => ({ id, ambiente: `ambiente ${id}`, plano_limpo: false, inicio_ms, fim_ms: inicio_ms + 5_000 })

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [],
  planos: [plano('pl0', 0), plano('pl1', 10_000)],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

const PARECIDOS = {
  entendida: { evidencias: [], programa: null, desde: null, ate: null, visual: true },
  videos: [
    {
      job_id: 'v2',
      nome: 'v2.mp4',
      programa: 'TV Fama',
      data_exibicao: '2026-10-21',
      duracao_s: 120,
      n_momentos: 1,
      momentos: [{ tipo: 'plano', inicio_ms: 20_000, fim_ms: 25_000, motivo: 'Plano: rua molhada', destaques: [], quadro_url: null, quadro: 'quadros/plano-4.jpg' }],
    },
  ],
  sem_aparicoes: [],
  plano_b: false,
  facetas: { programa: [], mes: [], pessoa: [], marca: [], tipo: [] },
}

let comVetor: number[] = [1]
let indexacao: { estado: string; em: string } | null = { estado: 'indexado', em: '2026-10-21T10:00:00Z' }
const parecidos: URLSearchParams[] = []

const servidor = setupServer(
  http.get('/v1/jobs/:id/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/:id/reproducao', () => HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' })),
  http.get('/v1/jobs/:id/correcoes', () => HttpResponse.json([])),
  http.get('/v1/jobs/:id/fila', () => HttpResponse.json([])),
  http.get('/v1/jobs/:id', ({ params }) =>
    HttpResponse.json({ id: params.id, nome: `${params.id}.mp4`, estado: 'concluido', codigo_falha: null, duracao_s: 120, criado_em: '2026-10-21T10:00:00Z', indexacao }),
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.ver'] })),
  // A busca não traz URL assinada (#335): o quadro de cada parecido vem da rota do quadro.
  http.get('/v1/jobs/:id/quadros/:arquivo', ({ params }) =>
    HttpResponse.json({ url: `https://q.exemplo/${params.id}/${params.arquivo}`, expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/busca/parecidos/planos', () => HttpResponse.json({ planos: comVetor })),
  http.get('/v1/busca/parecidos', ({ request }) => {
    parecidos.push(new URL(request.url).searchParams)
    return HttpResponse.json(PARECIDOS)
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  comVetor = [1]
  indexacao = { estado: 'indexado', em: '2026-10-21T10:00:00Z' }
  parecidos.length = 0
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

function Tela({ api }: { api: ReturnType<typeof criarClienteDaApi> }) {
  const rota = useRota()
  if (rota.tipo === 'parecidos') return <PlanosParecidos api={api} job={rota.job} plano={rota.plano} />
  if (rota.tipo !== 'video') return null
  return <TelaDoVideo api={api} id={rota.id} t={rota.t} busca={rota.busca} podeEditar={false} podeAprovar={false} />
}

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(
    <AtalhosProvider>
      <Tela api={criarClienteDaApi(auth, () => {})} />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 1' })
  const usuario = userEvent.setup()
  await usuario.click(screen.getByRole('tab', { name: /Planos/ }))
  return usuario
}

test('o botão aparece só no plano com vetor e leva à grade dos parecidos', async () => {
  const usuario = await abrir('/video/v1')

  const botoes = await screen.findAllByRole('button', { name: 'Planos parecidos com este' })
  expect(botoes).toHaveLength(1)

  await usuario.click(botoes[0])

  expect(await screen.findByText('1 plano parecido em 1 vídeo')).toBeTruthy()
  expect(location.pathname + location.search).toBe('/busca/parecidos?job=v1&plano=1')
  expect(parecidos[0].get('job')).toBe('v1')
  expect(parecidos[0].get('plano')).toBe('1')
  const grade = screen.getByRole('list', { name: 'Planos' })
  const card = within(grade).getByRole('link', { name: 'v2.mp4 em 00:20' })
  await waitFor(() => expect(card.querySelector('img')?.getAttribute('src')).toBe('https://q.exemplo/v2/plano-4.jpg'))
})

test('vídeo sem vetor nos planos não mostra o botão', async () => {
  comVetor = []
  await abrir('/video/v1')

  await screen.findByText('ambiente pl1')
  expect(screen.queryByRole('button', { name: 'Planos parecidos com este' })).toBeNull()
})

test('vídeo ainda não indexado não mostra o botão nem consulta os vetores', async () => {
  indexacao = { estado: 'pendente', em: '2026-10-21T10:00:00Z' }
  await abrir('/video/v1')

  await screen.findByText('ambiente pl1')
  expect(screen.queryByRole('button', { name: 'Planos parecidos com este' })).toBeNull()
})

test('plano sem vetor no endereço mostra a mensagem do 404', async () => {
  servidor.use(http.get('/v1/busca/parecidos', () => HttpResponse.json({ detail: 'sem vetor' }, { status: 404 })))
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(<PlanosParecidos api={criarClienteDaApi(auth, () => {})} job="v1" plano={4} />)

  expect(await screen.findByText(/não tem vetor do quadro/)).toBeTruthy()
})
