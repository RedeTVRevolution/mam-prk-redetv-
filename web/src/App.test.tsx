import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'

const chamadas: { url: string; autorizacao: string | null }[] = []

// API simulada: só reconhece o token que o autenticador falso emite para a Ana.
const servidor = setupServer(
  http.get('/v1/eu', ({ request }) => {
    const autorizacao = request.headers.get('Authorization')
    chamadas.push({ url: request.url, autorizacao })
    if (autorizacao !== 'Bearer token-de-ana@redetv.com.br') {
      return new HttpResponse(null, { status: 401 })
    }
    return HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br' })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  chamadas.length = 0
  cleanup()
})
afterAll(() => servidor.close())

function autenticador(totpCadastrado = true) {
  return new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado },
  ])
}

async function preencherSenha(
  usuario: ReturnType<typeof userEvent.setup>,
  senha = 'senha-forte-1',
) {
  await usuario.type(screen.getByLabelText('E-mail'), 'ana@redetv.com.br')
  await usuario.type(screen.getByLabelText('Senha'), senha)
  await usuario.click(screen.getByRole('button', { name: 'Entrar' }))
}

async function confirmarCodigo(usuario: ReturnType<typeof userEvent.setup>) {
  await usuario.type(await screen.findByLabelText('Código do autenticador'), CODIGO_TOTP_FALSO)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))
}

async function autenticadorComSessao() {
  const auth = autenticador()
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

test('sem sessão, mostra só o login e não chama a API', async () => {
  render(<App autenticador={autenticador()} />)

  expect(await screen.findByLabelText('E-mail')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Sair' })).toBeNull()
  expect(screen.queryByText('Biblioteca')).toBeNull()
  expect(chamadas).toEqual([])
})

test('login com senha e código TOTP abre a Biblioteca com o token na API', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)

  await screen.findByLabelText('E-mail')
  await preencherSenha(usuario)
  expect(screen.queryByText('Biblioteca')).toBeNull()
  await confirmarCodigo(usuario)

  expect(await screen.findByText('Biblioteca')).toBeTruthy()
  expect(screen.getByText('ana@redetv.com.br')).toBeTruthy()
  expect(chamadas.at(-1)?.autorizacao).toBe('Bearer token-de-ana@redetv.com.br')
})

test('senha errada mostra erro e continua no login', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText('E-mail')

  await preencherSenha(usuario, 'errada')

  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByLabelText('Código do autenticador')).toBeNull()
})

test('código TOTP errado mostra erro e não entra', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText('E-mail')
  await preencherSenha(usuario)

  await usuario.type(await screen.findByLabelText('Código do autenticador'), '000000')
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))

  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByText('Biblioteca')).toBeNull()
})

test('primeiro acesso mostra o cadastro do autenticador e entra ao confirmar o código', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador(false)} />)
  await screen.findByLabelText('E-mail')
  await preencherSenha(usuario)

  expect(await screen.findByText('SEGREDOFALSO')).toBeTruthy()
  expect(
    screen.getByRole('link', { name: 'Abrir no aplicativo autenticador' }).getAttribute('href'),
  ).toBe('otpauth://totp/MAM')
  await confirmarCodigo(usuario)

  expect(await screen.findByText('Biblioteca')).toBeTruthy()
})

test('o botão sair volta ao login e apaga a sessão', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  render(<App autenticador={auth} />)
  await screen.findByLabelText('E-mail')
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)
  await usuario.click(await screen.findByRole('button', { name: 'Sair' }))

  expect(await screen.findByLabelText('E-mail')).toBeTruthy()
  expect(screen.queryByText('Biblioteca')).toBeNull()
  expect(await auth.token()).toBeNull()
})

test('sessão já existente abre direto na Biblioteca', async () => {
  const auth = await autenticadorComSessao()
  render(<App autenticador={auth} />)

  expect(await screen.findByText('Biblioteca')).toBeTruthy()
})

test('401 da API derruba a sessão e leva ao login', async () => {
  const auth = await autenticadorComSessao()
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 401 })))
  render(<App autenticador={auth} />)

  expect(await screen.findByLabelText('E-mail')).toBeTruthy()
  await waitFor(async () => expect(await auth.token()).toBeNull())
  expect(screen.queryByText('Biblioteca')).toBeNull()
})

test('API recusando o token logo depois do login volta ao início do login', async () => {
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 401 })))
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText('E-mail')
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  expect(await screen.findByLabelText('E-mail')).toBeTruthy()
  expect(screen.queryByLabelText('Código do autenticador')).toBeNull()
})

test('API fora do ar mostra aviso sem dados, e tentar de novo entra', async () => {
  const usuario = userEvent.setup()
  const auth = await autenticadorComSessao()
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 500 })))
  render(<App autenticador={auth} />)

  expect((await screen.findByRole('alert')).textContent).toContain('API')
  expect(screen.queryByText('Biblioteca')).toBeNull()

  servidor.resetHandlers()
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))
  expect(await screen.findByText('Biblioteca')).toBeTruthy()
})
