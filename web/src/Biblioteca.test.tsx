import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import Biblioteca from './Biblioteca.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'

interface JobApi {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  duracao_s: number | null
  criado_em: string
  atualizado_em: string
}

function job(extra: Partial<JobApi>): JobApi {
  return {
    id: 'j1',
    nome: 'clipe.mp4',
    estado: 'aguardando_upload',
    codigo_falha: null,
    duracao_s: null,
    criado_em: '2026-10-29T15:00:00Z',
    atualizado_em: '2026-10-29T15:00:00Z',
    ...extra,
  }
}

let jobs: JobApi[] = []
let statusDaLista = 200
const criacoes: unknown[] = []
const pedacosEnviados: number[] = []
const URL_UPLOAD = 'https://storage.exemplo/quarentena/novo?assinatura=x'
const SESSAO = 'https://storage.exemplo/sessao/novo'

const servidor = setupServer(
  http.get('/v1/jobs', () =>
    statusDaLista === 200
      ? HttpResponse.json(jobs)
      : new HttpResponse(null, { status: statusDaLista }),
  ),
  http.post('/v1/jobs', async ({ request }) => {
    criacoes.push(await request.json())
    const novo = job({ id: 'novo', nome: 'enviado.mp4' })
    jobs = [novo, ...jobs]
    return HttpResponse.json({ ...novo, url_de_upload: URL_UPLOAD }, { status: 202 })
  }),
  http.post(URL_UPLOAD, () => new HttpResponse(null, { status: 201, headers: { Location: SESSAO } })),
  http.put(SESSAO, async ({ request }) => {
    pedacosEnviados.push((await request.arrayBuffer()).byteLength)
    return new HttpResponse(null, { status: 200 })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  jobs = []
  statusDaLista = 200
  criacoes.length = 0
  pedacosEnviados.length = 0
  cleanup()
})
afterAll(() => servidor.close())

async function comSessao() {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

function mp4(nome = 'enviado.mp4') {
  const bytes = new Uint8Array(64)
  bytes.set(new TextEncoder().encode('ftypisom'), 4)
  return new File([bytes], nome, { type: 'video/mp4' })
}

async function abrir(opcoes: { intervaloMs?: number; aoSessaoExpirada?: () => void } = {}) {
  render(
    <Biblioteca
      autenticador={await comSessao()}
      aoSessaoExpirada={opcoes.aoSessaoExpirada ?? (() => {})}
      intervaloMs={opcoes.intervaloMs}
    />,
  )
}

test('lista nome, data e estado de cada Job, e o código de quem falhou', async () => {
  jobs = [
    job({ id: 'a', nome: 'quebrado.mp4', estado: 'falhou', codigo_falha: 'codec_nao_suportado' }),
    job({ id: 'b', nome: 'novo.mp4', estado: 'validando', criado_em: '2026-10-29T15:00:00Z' }),
  ]
  await abrir()

  const linhas = await screen.findAllByRole('row')
  const falhou = within(linhas[1]!)
  expect(falhou.getByText('quebrado.mp4')).toBeTruthy()
  expect(falhou.getByText('falhou')).toBeTruthy()
  expect(falhou.getByText('codec_nao_suportado')).toBeTruthy()
  const validando = within(linhas[2]!)
  expect(validando.getByText('validando')).toBeTruthy()
  expect(validando.getByText(/29\/10\/2026/)).toBeTruthy()
})

test('a lista acompanha o estado por consulta periódica', async () => {
  jobs = [job({ estado: 'validando' })]
  await abrir({ intervaloMs: 20 })
  await screen.findByText('validando')

  jobs = [job({ estado: 'concluido' })]

  expect(await screen.findByText('concluido')).toBeTruthy()
  expect(screen.queryByText('validando')).toBeNull()
})

test('recusa na hora o arquivo que não é MP4, sem chamar a API', async () => {
  const usuario = userEvent.setup({ applyAccept: false })
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.upload(screen.getByLabelText('Enviar vídeo'), mp4('filme.mov'))

  expect((await screen.findByRole('alert')).textContent).toContain('.mp4')
  expect(criacoes).toEqual([])
})

test('envia o MP4: cria o Job, sobe o arquivo e mostra o Job aguardando upload', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.upload(screen.getByLabelText('Enviar vídeo'), mp4())

  expect(await screen.findByText('Envio concluído.')).toBeTruthy()
  expect(criacoes).toEqual([{ nome: 'enviado.mp4', tamanho_bytes: 64, tipo: 'video/mp4' }])
  expect(pedacosEnviados).toEqual([64])
  expect(await screen.findByText('enviado.mp4')).toBeTruthy()
  expect(screen.getByText('aguardando_upload')).toBeTruthy()
})

test('um 401 na lista avisa que a sessão expirou', async () => {
  statusDaLista = 401
  const aoSessaoExpirada = vi.fn()

  await abrir({ aoSessaoExpirada })

  await waitFor(() => expect(aoSessaoExpirada).toHaveBeenCalled())
})
