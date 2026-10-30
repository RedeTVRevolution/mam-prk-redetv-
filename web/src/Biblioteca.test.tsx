import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { render } from './render-teste.tsx'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { AppShell } from '@mantine/core'
import type { ReactNode } from 'react'
import Biblioteca from './Biblioteca.tsx'
import { NAVBAR_DA_BIBLIOTECA } from './tema.ts'
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

// No app, a Biblioteca fica dentro do AppShell do App.
function noShell(tela: ReactNode) {
  return <AppShell navbar={NAVBAR_DA_BIBLIOTECA}>{tela}</AppShell>
}

async function abrir(opcoes: { intervaloMs?: number; aoSessaoExpirada?: () => void } = {}) {
  render(
    noShell(
      <Biblioteca
        autenticador={await comSessao()}
        aoSessaoExpirada={opcoes.aoSessaoExpirada ?? (() => {})}
        intervaloMs={opcoes.intervaloMs}
      />,
    ),
  )
}

test('lista nome, data e estado de cada Job, e o código de quem falhou', async () => {
  jobs = [
    job({ id: 'a', nome: 'quebrado.mp4', estado: 'falhou', codigo_falha: 'codec_nao_suportado' }),
    job({ id: 'b', nome: 'novo.mp4', estado: 'validando', criado_em: '2026-10-29T15:00:00Z' }),
  ]
  await abrir()

  const falhou = within((await screen.findByText('quebrado.mp4')).closest('.mantine-Card-root') as HTMLElement)
  expect(falhou.getByText('Falhou')).toBeTruthy()
  expect(falhou.getByText('codec_nao_suportado')).toBeTruthy()
  const validando = within(screen.getByText('novo.mp4').closest('.mantine-Card-root') as HTMLElement)
  expect(validando.getByText('Em quarentena')).toBeTruthy()
  // 15:00Z é 12:00 em São Paulo, o fuso fixado em vite.config.ts.
  expect(validando.getByText(/29\/10\/2026.*12:00/)).toBeTruthy()
})

test('a lista acompanha o estado por consulta periódica', async () => {
  jobs = [job({ estado: 'validando' })]
  await abrir({ intervaloMs: 20 })
  const cartao = () => (screen.getByText('clipe.mp4').closest('.mantine-Card-root') as HTMLElement)
  await screen.findByText('clipe.mp4')
  expect(within(cartao()).getByText('Em quarentena')).toBeTruthy()

  jobs = [job({ estado: 'concluido' })]

  await waitFor(() => expect(within(cartao()).getByText('Concluído')).toBeTruthy())
  expect(within(cartao()).queryByText('Em quarentena')).toBeNull()
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
  const card = (screen.getByText('enviado.mp4').closest('.mantine-Card-root') as HTMLElement)
  expect(within(card).getByText('Aguardando envio')).toBeTruthy()
})

test('um 401 na lista avisa que a sessão expirou', async () => {
  statusDaLista = 401
  const aoSessaoExpirada = vi.fn()

  await abrir({ aoSessaoExpirada })

  await waitFor(() => expect(aoSessaoExpirada).toHaveBeenCalled())
})

test('uma falha da lista aparece como aviso, e some quando a lista volta', async () => {
  statusDaLista = 503
  await abrir({ intervaloMs: 20 })

  expect((await screen.findByRole('alert')).textContent).toContain('lista')

  statusDaLista = 200
  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

test('durante um envio não dá para escolher outro arquivo', async () => {
  let liberar = () => {}
  servidor.use(
    http.put(SESSAO, async () => {
      await new Promise<void>((resolve) => (liberar = resolve))
      return new HttpResponse(null, { status: 200 })
    }),
  )
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')
  const campo = screen.getByLabelText('Enviar vídeo') as HTMLInputElement

  await usuario.upload(campo, mp4())
  await screen.findByLabelText('Progresso do envio')

  expect(campo.disabled).toBe(true)
  liberar()
  await screen.findByText('Envio concluído.')
  expect(campo.disabled).toBe(false)
})

test('abrir um vídeo concluído ou falhado chama aoAbrir; os demais não são clicáveis', async () => {
  const usuario = userEvent.setup()
  jobs = [
    job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' }),
    job({ id: 'b', nome: 'andando.mp4', estado: 'analisando' }),
  ]
  const aoAbrir = vi.fn()
  render(
    noShell(
      <Biblioteca autenticador={await comSessao()} aoSessaoExpirada={() => {}} aoAbrir={aoAbrir} />,
    ),
  )

  await usuario.click(await screen.findByRole('button', { name: 'pronto.mp4' }))

  expect(aoAbrir).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }))
  expect(screen.queryByRole('button', { name: 'andando.mp4' })).toBeNull()
})

test('mostra a duração em mm:ss quando a API traz', async () => {
  jobs = [job({ estado: 'concluido', duracao_s: 125 })]
  await abrir()

  expect(await screen.findByText(/· 02:05/)).toBeTruthy()
})

test('desmarcar um estado esconde os cards daquele estado', async () => {
  const usuario = userEvent.setup()
  jobs = [
    job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' }),
    job({ id: 'b', nome: 'andando.mp4', estado: 'analisando' }),
  ]
  await abrir()
  await screen.findByText('andando.mp4')

  await usuario.click(screen.getByRole('checkbox', { name: 'Decupando' }))

  expect(screen.queryByText('andando.mp4')).toBeNull()
  expect(screen.getByText('pronto.mp4')).toBeTruthy()
})

test('depois de escolher um arquivo, o seletor fica livre para a mesma escolha de novo', async () => {
  const usuario = userEvent.setup({ applyAccept: false })
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')
  const campo = screen.getByLabelText('Enviar vídeo') as HTMLInputElement

  await usuario.upload(campo, mp4('filme.mov'))

  await screen.findByRole('alert')
  expect(campo.value).toBe('')
})

test('um estado fora do mapa continua visível, qualquer que seja o filtro', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ nome: 'estranho.mp4', estado: 'arquivado' })]
  await abrir()
  await screen.findByText('estranho.mp4')

  for (const caixa of screen.getAllByRole('checkbox')) await usuario.click(caixa)

  expect(screen.getByText('estranho.mp4')).toBeTruthy()
})
