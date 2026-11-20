import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { act } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { navegar } from '../../rotas.ts'
import App from '../App.tsx'
import { irPara, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// O vídeo aberto pelo endereço real (`lerRota` e `App`): a consulta inteira vai no `?consulta=` (#804).

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [],
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
}

const resultado = (motivo: string) => ({
  entendida: { evidencias: ['imagem'], programa: null, desde: null, ate: null },
  videos: [
    {
      job_id: 'j1',
      nome: 'j1.mp4',
      programa: 'TV Fama',
      data_exibicao: '2026-10-21',
      duracao_s: 120,
      n_momentos: 1,
      momentos: [{ tipo: 'plano', inicio_ms: 10_000, fim_ms: 14_000, motivo, destaques: [], quadro: null }],
    },
  ],
  sem_aparicoes: [],
  facetas: { programa: [], mes: [], pessoa: [], marca: [], tipo: [] },
  plano_b: false,
})

const buscas: URLSearchParams[] = []
const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', papeis: [], permissoes: ['decupagem.ver'] })),
  ...rotasDoVideo(() => ({}), () => DECUPAGEM),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama'])),
  http.get('/v1/jobs/j1/passadas', () => HttpResponse.json([])),
  // O motivo diz qual busca foi: o texto pedido.
  http.get('/v1/busca', ({ request }) => {
    const p = new URL(request.url).searchParams
    buscas.push(p)
    return HttpResponse.json(resultado(`Momento de ${p.get('q')}`))
  }),
)
// O jsdom não mede nada: a rolagem tem 1000 px de altura, e cada fileira da grade, 100 px.
beforeAll(() => {
  servidor.listen({ onUnhandledFrame: 'error' })
  Object.defineProperty(Element.prototype, 'clientHeight', { configurable: true, get: () => 1000 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute('data-index') ? 100 : 0
    },
  })
})
simularPlayer()
beforeEach(() => {
  buscas.length = 0
  sessionStorage.clear()
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(<App autenticador={auth} />)
}

test('sem lista na sessão, o vídeo refaz a busca com os mesmos filtros e a mesma ordem do endereço', async () => {
  await abrir('/video/j1?consulta=q%3Dsapato%26ev%3Dfala%26programa%3DTV%2BFama%26ano%3D2024%26ordem%3Drelevancia')

  expect(await screen.findByRole('group', { name: 'Busca: sapato (1)' })).toBeTruthy()
  expect(buscas).toHaveLength(1)
  expect(buscas[0].get('q')).toBe('sapato')
  expect(buscas[0].getAll('ev')).toEqual(['fala'])
  expect(buscas[0].get('programa')).toBe('TV Fama')
  expect(buscas[0].get('ordem')).toBe('relevancia')
})

test('o link antigo ?busca=sapato abre e busca pelo texto, com a consulta nova', async () => {
  await abrir('/video/j1?busca=sapato')

  expect(await screen.findByRole('group', { name: 'Busca: sapato (1)' })).toBeTruthy()
  expect(buscas[0].get('q')).toBe('sapato')
  expect(buscas[0].get('ordem')).toBe('data')
  expect(buscas[0].has('programa')).toBe(false)
})

test('o link antigo com o texto "q=sapato" e o novo com "sapato" não reaproveitam a lista um do outro', async () => {
  await abrir('/video/j1?busca=q%3Dsapato')
  const faixa = await screen.findByRole('group', { name: 'Busca: q=sapato (1)' })
  expect(within(faixa).getByRole('button', { name: 'Momento de q=sapato' })).toBeTruthy()

  act(() => navegar('/video/j1?consulta=q%3Dsapato'))

  const nova = await screen.findByRole('group', { name: 'Busca: sapato (1)' })
  expect(within(nova).getByRole('button', { name: 'Momento de sapato' })).toBeTruthy()
  expect(buscas.map((p) => p.get('q'))).toEqual(['q=sapato', 'sapato'])
})

test('uma lista no formato anterior (mam:busca, q "q=sapato") não é usada e é apagada', async () => {
  sessionStorage.setItem(
    'mam:busca',
    JSON.stringify({ q: 'q=sapato', videos: [{ job_id: 'j1', momentos: [{ inicio_ms: 1000, fim_ms: 2000, motivo: 'Antigo' }] }] }),
  )
  await abrir('/video/j1?consulta=q%3Dsapato')

  expect(await screen.findByRole('button', { name: 'Momento de sapato' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Antigo' })).toBeNull()
  expect(sessionStorage.getItem('mam:busca')).toBeNull()
})

test('"Fechar busca" tira a consulta do endereço e a faixa some', async () => {
  const usuario = userEvent.setup()
  await abrir('/video/j1?consulta=q%3Dsapato%26ordem%3Drelevancia&t=12')
  await screen.findByRole('group', { name: 'Busca: sapato (1)' })
  irPara((await screen.findByLabelText('Player')) as HTMLVideoElement, 12)

  await usuario.click(screen.getByRole('button', { name: 'Fechar busca' }))

  await waitFor(() => expect(screen.queryByRole('group', { name: /^Busca/ })).toBeNull())
  expect(location.search).not.toContain('consulta')
  expect(location.search).toContain('t=12')
})

test('copiar o link do vídeo aberto pela busca leva o ?consulta=', async () => {
  const usuario = userEvent.setup()
  await abrir('/video/j1?consulta=q%3Dsapato%26programa%3DTV%2BFama')
  await screen.findByRole('group', { name: 'Busca: sapato (1)' })

  await usuario.click(screen.getByRole('button', { name: 'Copiar o link neste tempo' }))

  const copiado = new URL(await navigator.clipboard.readText())
  expect(copiado.searchParams.get('consulta')).toBe('q=sapato&programa=TV+Fama')
  expect(copiado.searchParams.has('busca')).toBe(false)
})

test('ida e volta: da busca filtrada ao vídeo e Voltar mostra a mesma busca, sem refazê-la', async () => {
  const usuario = userEvent.setup()
  const origem = '/busca?q=sapato&programa=TV+Fama&ordem=relevancia'
  await abrir(origem)
  await usuario.click(await screen.findByRole('link', { name: /j1\.mp4/ }))

  await screen.findByRole('group', { name: 'Busca: sapato (1)' })
  expect(new URLSearchParams(location.search).get('consulta')).toBe('q=sapato&programa=TV+Fama&ordem=relevancia')

  act(() => history.back())

  await waitFor(() => expect(location.pathname + location.search).toBe(origem))
  expect(await screen.findByRole('link', { name: /j1\.mp4/ })).toBeTruthy()
  expect(buscas).toHaveLength(1)
  expect(buscas[0].get('programa')).toBe('TV Fama')
  expect(buscas[0].get('ordem')).toBe('relevancia')
})
