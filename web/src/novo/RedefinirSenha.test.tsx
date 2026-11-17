import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { AutenticadorFalso, CODIGO_DE_SENHA_FALSO } from '../auth/falso.ts'
import App from './App.tsx'

const ANA = 'ana@redetv.com.br'
const SENHA_NOVA = 'Senha-nova-123!'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  history.replaceState(null, '', '/')
})

function abrir(busca: string, auth = new AutenticadorFalso([{ email: ANA, senha: 'antiga', totpCadastrado: true }])) {
  history.replaceState(null, '', `/redefinir-senha${busca}`)
  render(<App autenticador={auth} />)
  return auth
}

async function preencher(usuario: ReturnType<typeof userEvent.setup>, senha: string, confirmacao = senha) {
  await usuario.type(await screen.findByLabelText('Senha nova'), senha)
  await usuario.type(screen.getByLabelText('Confirme a senha nova'), confirmacao)
  await usuario.click(screen.getByRole('button', { name: 'Definir senha' }))
}

test.each(['?mode=verifyEmail&oobCode=x', '?mode=resetPassword', ''])('%s mostra link inválido com volta ao login', async (busca) => {
  abrir(busca)
  expect((await screen.findByRole('alert')).textContent).toContain('Link inválido')
  expect(screen.getByRole('link', { name: 'Ir ao login' }).getAttribute('href')).toBe('/')
  expect(screen.queryByLabelText('Senha nova')).toBeNull()
})

test('código vencido ou usado pede novo link ao administrador', async () => {
  abrir('?mode=resetPassword&oobCode=velho')
  expect((await screen.findByRole('alert')).textContent).toContain('administrador')
  expect(screen.queryByLabelText('Senha nova')).toBeNull()
})

test('mostra o e-mail da conta e a regra da senha, e tira o código do endereço', async () => {
  abrir(`?mode=resetPassword&oobCode=${CODIGO_DE_SENHA_FALSO}`)
  expect(await screen.findByText(ANA)).toBeTruthy()
  expect(screen.getByText(/Mínimo 12 caracteres/)).toBeTruthy()
  expect(location.search).toBe('')
})

test('senhas diferentes não chegam ao servidor', async () => {
  const usuario = userEvent.setup()
  const auth = abrir(`?mode=resetPassword&oobCode=${CODIGO_DE_SENHA_FALSO}`)
  const redefinir = vi.spyOn(auth, 'redefinirSenha')
  await preencher(usuario, SENHA_NOVA, 'outra-coisa-123!')
  expect((await screen.findByRole('alert')).textContent).toContain('não são iguais')
  expect(redefinir).not.toHaveBeenCalled()
})

test('senha fraca recusada pelo servidor mostra a regra e o erro dele', async () => {
  const usuario = userEvent.setup()
  abrir(`?mode=resetPassword&oobCode=${CODIGO_DE_SENHA_FALSO}`)
  await preencher(usuario, 'curta')
  expect((await screen.findByRole('alert')).textContent).toContain('menos de 12 caracteres')
  expect(screen.getByLabelText('Senha nova')).toBeTruthy()
})

test('sucesso volta ao login da aplicação com o aviso, sem usar endereço externo', async () => {
  const usuario = userEvent.setup()
  const auth = abrir(`?mode=resetPassword&oobCode=${CODIGO_DE_SENHA_FALSO}&continueUrl=https://mal.example/`)
  await preencher(usuario, SENHA_NOVA)
  expect((await screen.findByRole('status')).textContent).toContain('Senha definida, entre com a senha nova')
  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  await waitFor(() => expect(location.pathname).toBe('/'))
  expect(location.origin + location.pathname + location.search).toBe(`${location.origin}/`)
  // A senha nova vale no login.
  await expect(auth.entrar(ANA, SENHA_NOVA)).resolves.toBeTruthy()
})
