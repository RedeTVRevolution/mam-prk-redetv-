import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'
import { guardarResultado } from './resultadoDaBusca.ts'
import TelaDoVideo from './TelaDoVideo.tsx'
import { useRota } from './rotas.ts'

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [],
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

const momento = (inicio_ms: number, fim_ms: number, motivo: string) => ({
  tipo: 'plano',
  inicio_ms,
  fim_ms,
  motivo,
  destaques: [],
  quadro_url: null,
})

const video = (id: string, momentos: ReturnType<typeof momento>[]) => ({
  job_id: id,
  nome: `${id}.mp4`,
  programa: 'TV Fama',
  data_exibicao: '2026-10-21',
  duracao_s: 120,
  n_momentos: momentos.length,
  momentos,
})

const RESULTADO = {
  entendida: { evidencias: ['imagem'], programa: null, desde: null, ate: null },
  videos: [
    video('v1', [momento(10_000, 14_000, 'Objeto: sandália vermelha'), momento(50_000, 52_000, 'Fala: sapato vermelho')]),
    video('v2', [momento(20_000, 24_000, 'Objeto: scarpin vermelho'), momento(70_000, 74_000, 'Fala: sapato')]),
  ],
  sem_aparicoes: [],
  facetas: { programa: [], mes: [], pessoa: [], marca: [], tipo: [] },
  plano_b: false,
}

const buscas: URLSearchParams[] = []
let historico: Record<string, unknown>[] = []

const servidor = setupServer(
  http.get('/v1/jobs/:id/decupagem', () => HttpResponse.json(DECUPAGEM)),
  http.get('/v1/jobs/:id/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/jobs/:id', ({ params }) =>
    HttpResponse.json({
      id: params.id,
      nome: `${params.id}.mp4`,
      estado: 'concluido',
      codigo_falha: null,
      duracao_s: 120,
      criado_em: '2026-10-21T10:00:00Z',
    }),
  ),
  http.get('/v1/eu', () =>
    HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
  ),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json({ tipos: [], limites: {} })),
  http.get('/v1/jobs/:id/correcoes', () => HttpResponse.json(historico)),
  http.get('/v1/jobs/:id/fila', () => HttpResponse.json([])),
  http.get('/v1/busca', ({ request }) => {
    buscas.push(new URL(request.url).searchParams)
    return HttpResponse.json(RESULTADO)
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  buscas.length = 0
  historico = []
  sessionStorage.clear()
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

/** A tela Vídeo pelo endereço, como o App a monta. */
function Tela({ api }: { api: ReturnType<typeof criarClienteDaApi> }) {
  const rota = useRota()
  if (rota.tipo !== 'video') return null
  return (
    <TelaDoVideo api={api} id={rota.id} t={rota.t} busca={rota.busca} podeEditar podeAprovar={false} />
  )
}

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(
    <AtalhosProvider>
      <Tela api={criarClienteDaApi(auth, () => {})} />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 1' })
  return userEvent.setup()
}

function irPara(segundos: number) {
  const player = document.querySelector('video') as HTMLVideoElement
  player.currentTime = segundos
  fireEvent.timeUpdate(player)
}

const parametros = () => new URLSearchParams(location.search)

test('aberto pela busca, o vídeo mostra a faixa com os momentos dele, e o motivo é a dica', async () => {
  await abrir('/video/v1?busca=sapato%20vermelho')

  const faixa = await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })
  expect(within(faixa).getByRole('button', { name: 'Objeto: sandália vermelha' })).toBeTruthy()
  expect(within(faixa).getByRole('button', { name: 'Fala: sapato vermelho' })).toBeTruthy()
  expect(buscas[0].get('q')).toBe('sapato vermelho')
})

test('com o resultado guardado na sessão, a busca não é refeita', async () => {
  guardarResultado('sapato vermelho', [
    { job_id: 'v1', momentos: [{ inicio_ms: 5_000, fim_ms: 6_000, motivo: 'Guardado' }] },
  ])
  await abrir('/video/v1?busca=sapato%20vermelho')

  expect(await screen.findByRole('button', { name: 'Guardado' })).toBeTruthy()
  expect(buscas).toHaveLength(0)
})

test('sem busca no endereço não há faixa nem chamada à busca', async () => {
  await abrir('/video/v1')

  expect(screen.queryByRole('group', { name: /^Busca/ })).toBeNull()
  expect(buscas).toHaveLength(0)
})

test('clicar num bloco da busca salta o player ao momento', async () => {
  const usuario = await abrir('/video/v1?busca=sapato%20vermelho')

  await usuario.click(await screen.findByRole('button', { name: 'Fala: sapato vermelho' }))

  expect((document.querySelector('video') as HTMLVideoElement).currentTime).toBe(50)
})

test('N vai ao momento seguinte do mesmo vídeo', async () => {
  const usuario = await abrir('/video/v1?busca=sapato%20vermelho')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })
  irPara(10)

  await usuario.keyboard('n')

  expect((document.querySelector('video') as HTMLVideoElement).currentTime).toBe(50)
  expect(location.pathname).toBe('/video/v1')
})

test('N no último momento abre o vídeo seguinte no primeiro momento dele, mantendo a busca', async () => {
  const usuario = await abrir('/video/v1?busca=sapato%20vermelho')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })
  irPara(50)

  await usuario.keyboard('n')

  await waitFor(() => expect(location.pathname).toBe('/video/v2'))
  expect(parametros().get('t')).toBe('20')
  expect(parametros().get('busca')).toBe('sapato vermelho')
  expect(await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })).toBeTruthy()
  // O resultado veio da sessão: uma busca só.
  expect(buscas).toHaveLength(1)
})

test('Shift+N no primeiro momento volta ao último do vídeo anterior', async () => {
  const usuario = await abrir('/video/v2?busca=sapato%20vermelho&t=20')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })
  irPara(20)

  await usuario.keyboard('{Shift>}n{/Shift}')

  await waitFor(() => expect(location.pathname).toBe('/video/v1'))
  expect(parametros().get('t')).toBe('50')
  expect(parametros().get('busca')).toBe('sapato vermelho')
})

test('no último momento do resultado, N avisa e fica', async () => {
  const usuario = await abrir('/video/v2?busca=sapato%20vermelho')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })
  irPara(70)

  await usuario.keyboard('n')

  expect(await screen.findByText('Este é o último momento da busca.')).toBeTruthy()
  expect(location.pathname).toBe('/video/v2')
})

test('N não age sem busca, nem com o foco num campo de texto', async () => {
  const usuario = await abrir('/video/v1?busca=sapato%20vermelho')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })
  irPara(10)
  const campo = document.createElement('input')
  document.body.append(campo)
  campo.focus()

  await usuario.keyboard('n')

  expect((document.querySelector('video') as HTMLVideoElement).currentTime).toBe(10)
  campo.remove()
})

test('"Fechar busca" tira o busca do endereço e a faixa some', async () => {
  const usuario = await abrir('/video/v1?busca=sapato%20vermelho&t=12')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })

  await usuario.click(screen.getByRole('button', { name: 'Fechar busca' }))

  await waitFor(() => expect(screen.queryByRole('group', { name: /^Busca/ })).toBeNull())
  expect(parametros().has('busca')).toBe(false)
  expect(location.pathname).toBe('/video/v1')
})

test('N e Shift+N estão na lista do ?, só com busca', async () => {
  const usuario = await abrir('/video/v1?busca=sapato%20vermelho')
  await screen.findByRole('group', { name: 'Busca: sapato vermelho (2)' })

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).getByText(/momento seguinte da busca/)).toBeTruthy()
  expect(within(lista).getByText(/momento anterior da busca/)).toBeTruthy()
})

const correcaoDoTitulo = (na_busca: string) => ({
  id: 'c1',
  tipo: 'pauta.titulo',
  estado: 'ativa',
  item_id: 'pa1',
  ancora: { versao: 'v1', tipo_do_item: 'pauta' },
  criada_em: '2026-10-31T12:00:00Z',
  motivo: 'título corrigido',
  autor_email: 'ana@redetv.com.br',
  antes_legivel: 'Eleição',
  depois_legivel: 'Eleição 2026',
  na_busca,
})

test('a correção nova mostra "indexando" e passa a "na busca" quando o índice confirma', async () => {
  historico = [correcaoDoTitulo('indexando')]
  const usuario = await abrir('/video/j1')
  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  expect(await screen.findByText('indexando')).toBeTruthy()

  historico = [correcaoDoTitulo('na_busca')]

  expect(await screen.findByText('na busca', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.queryByText('indexando')).toBeNull()
})

test('a correção só gravada mostra "salva"', async () => {
  historico = [correcaoDoTitulo('salva')]
  const usuario = await abrir('/video/j1')

  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))

  expect(await screen.findByText('salva')).toBeTruthy()
})
