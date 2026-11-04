import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'

interface Regra {
  tipo: string
  nome: string
  exige_aprovacao: boolean
}

const ADMIN = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['administrador'], permissoes: ['decupagem.ver', 'aprovacao.definir'] }
const CURADOR = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['curador'], permissoes: ['decupagem.ver', 'correcao.aprovar'] }

const regras = (): Regra[] => [
  { tipo: 'pessoa.renomear', nome: 'Renomear pessoa', exige_aprovacao: false },
  { tipo: 'pauta.titulo', nome: 'Título da pauta', exige_aprovacao: true },
]

let eu = ADMIN
// O "servidor": o estado sobrevive a recarregar a página.
let guardadas = regras()
const chamadas: { corpo: unknown }[] = []
let falhar = false

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(eu)),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json([])),
  http.get('/v1/admin/aprovacao', () => HttpResponse.json(guardadas)),
  http.put('/v1/admin/aprovacao', async ({ request }) => {
    const corpo = (await request.json()) as { tipo: string; exige_aprovacao: boolean }
    chamadas.push({ corpo })
    if (falhar) return new HttpResponse(JSON.stringify({ detail: 'fora do ar' }), { status: 500 })
    guardadas = guardadas.map((r) => (r.tipo === corpo.tipo ? { ...r, exige_aprovacao: corpo.exige_aprovacao } : r))
    return HttpResponse.json(guardadas)
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  eu = ADMIN
  guardadas = regras()
  chamadas.length = 0
  falhar = false
  cleanup()
})
afterAll(() => servidor.close())

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(<App autenticador={auth} />)
}

test('a aba lista os tipos com o nome e a chave no estado de cada um', async () => {
  await abrir('/admin/aprovacao')

  const tabela = await screen.findByRole('table', { name: 'Regras de aprovação' })
  expect(within(tabela).getByText('Renomear pessoa')).toBeTruthy()
  expect((within(tabela).getByRole('switch', { name: 'Exigir aprovação para Renomear pessoa' }) as HTMLInputElement).checked).toBe(false)
  expect((within(tabela).getByRole('switch', { name: 'Exigir aprovação para Título da pauta' }) as HTMLInputElement).checked).toBe(true)
  expect(screen.getByRole('link', { name: 'Regras de aprovação' }).getAttribute('href')).toBe('/admin/aprovacao')
})

test('ligar e desligar chama a rota com o tipo e o valor, e o estado sobrevive a recarregar', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/aprovacao')

  await usuario.click(await screen.findByRole('switch', { name: 'Exigir aprovação para Renomear pessoa' }))
  await waitFor(() =>
    expect((screen.getByRole('switch', { name: 'Exigir aprovação para Renomear pessoa' }) as HTMLInputElement).checked).toBe(true),
  )
  await usuario.click(screen.getByRole('switch', { name: 'Exigir aprovação para Título da pauta' }))
  await waitFor(() =>
    expect((screen.getByRole('switch', { name: 'Exigir aprovação para Título da pauta' }) as HTMLInputElement).checked).toBe(false),
  )
  expect(chamadas.map((c) => c.corpo)).toEqual([
    { tipo: 'pessoa.renomear', exige_aprovacao: true },
    { tipo: 'pauta.titulo', exige_aprovacao: false },
  ])

  cleanup()
  await abrir('/admin/aprovacao')
  expect((await screen.findByRole('switch', { name: 'Exigir aprovação para Renomear pessoa' }) as HTMLInputElement).checked).toBe(true)
  expect((screen.getByRole('switch', { name: 'Exigir aprovação para Título da pauta' }) as HTMLInputElement).checked).toBe(false)
})

test('se a rota falha, a chave fica como estava e a tela avisa', async () => {
  const usuario = userEvent.setup()
  falhar = true
  await abrir('/admin/aprovacao')

  await usuario.click(await screen.findByRole('switch', { name: 'Exigir aprovação para Renomear pessoa' }))

  expect(await screen.findByText(/Não foi possível/)).toBeTruthy()
  expect((screen.getByRole('switch', { name: 'Exigir aprovação para Renomear pessoa' }) as HTMLInputElement).checked).toBe(false)
})

test('sem aprovacao.definir a aba não existe, mesmo para o Curador', async () => {
  eu = CURADOR
  await abrir('/admin/aprovacao')

  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
  expect(screen.queryByRole('table', { name: 'Regras de aprovação' })).toBeNull()
})
