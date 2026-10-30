import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { render } from './render-teste.tsx'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from './App.tsx'
import { ContaBloqueada } from './auth/autenticador.ts'
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
    return HttpResponse.json({
      uid: 'u1',
      email: 'ana@redetv.com.br',
      papeis: ['consulta', 'operador'],
      permissoes: ['decupagem.ver', 'video.enviar'],
    })
  }),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json([])),
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
  await usuario.type(screen.getByLabelText(/^E-mail/), 'ana@redetv.com.br')
  await usuario.type(screen.getByLabelText(/^Senha/), senha)
  await usuario.click(screen.getByRole('button', { name: 'Entrar' }))
}

async function digitarCodigo(usuario: ReturnType<typeof userEvent.setup>, codigo: string) {
  const grupo = await screen.findByLabelText('Código do autenticador')
  const campos = within(grupo).getAllByRole('textbox')
  expect(campos).toHaveLength(6)
  await usuario.type(campos[0], codigo)
}

async function confirmarCodigo(usuario: ReturnType<typeof userEvent.setup>) {
  await digitarCodigo(usuario, CODIGO_TOTP_FALSO)
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

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Sair' })).toBeNull()
  expect(screen.queryByText('Biblioteca')).toBeNull()
  expect(chamadas).toEqual([])
})

test('login com senha e código TOTP abre a Biblioteca com o token na API', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)

  await screen.findByLabelText(/^E-mail/)
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
  await screen.findByLabelText(/^E-mail/)

  await preencherSenha(usuario, 'errada')

  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('conta bloqueada por tentativas erradas pede para esperar', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  auth.entrar = async () => {
    throw new ContaBloqueada()
  }
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)

  await preencherSenha(usuario)

  expect((await screen.findByRole('alert')).textContent).toContain('Muitas tentativas')
})

test('falha inesperada no login mostra login indisponível', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  auth.entrar = async () => {
    throw new Error('rede fora')
  }
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)

  await preencherSenha(usuario)

  expect((await screen.findByRole('alert')).textContent).toContain('Login indisponível')
})

test('código incompleto não pode ser confirmado', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  let tentativas = 0
  auth.confirmarTotp = async () => {
    tentativas++
  }
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)

  await digitarCodigo(usuario, '123')

  const confirmar = screen.getByRole('button', { name: 'Confirmar' })
  expect(confirmar.hasAttribute('disabled')).toBe(true)
  await usuario.click(confirmar)
  expect(tentativas).toBe(0)
})

test('código TOTP errado mostra erro e não entra', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)

  await digitarCodigo(usuario, '000000')
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))

  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByText('Biblioteca')).toBeNull()
})

test('primeiro acesso mostra o cadastro do autenticador e entra ao confirmar o código', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador(false)} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)

  expect(await screen.findByText('SEGREDOFALSO')).toBeTruthy()
  expect(
    screen.getByRole('link', { name: 'Abrir no aplicativo autenticador' }).getAttribute('href'),
  ).toBe('otpauth://totp/MAM')
  await confirmarCodigo(usuario)

  expect(await screen.findByText('Biblioteca')).toBeTruthy()
})

test('fechar o modal do autenticador volta ao início do login', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await screen.findByRole('dialog', { name: 'Verificação em duas etapas' })

  await usuario.click(screen.getByRole('button', { name: 'Fechar' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect((screen.getByLabelText(/^E-mail/) as HTMLInputElement).value).toBe('')
  expect((screen.getByLabelText(/^Senha/) as HTMLInputElement).value).toBe('')
})

test('o botão sair volta ao login e apaga a sessão', async () => {
  const usuario = userEvent.setup()
  const auth = autenticador()
  render(<App autenticador={auth} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)
  await usuario.click(await screen.findByRole('button', { name: 'Sair' }))

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
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

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  await waitFor(async () => expect(await auth.token()).toBeNull())
  expect(screen.queryByText('Biblioteca')).toBeNull()
})

test('API recusando o token logo depois do login volta ao início do login', async () => {
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 401 })))
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
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

test('com sessão, o cabeçalho mostra a marca, a tela atual e o e-mail', async () => {
  render(<App autenticador={await autenticadorComSessao()} />)

  expect(await screen.findByText('MAM')).toBeTruthy()
  expect(screen.getByText('RedeTV')).toBeTruthy()
  expect(screen.getByRole('banner').textContent).toContain('Biblioteca')
  expect(screen.getByRole('banner').textContent).toContain('ana@redetv.com.br')
  expect(screen.getByRole('button', { name: 'Sair' })).toBeTruthy()
})

test('verificando a sessão mostra um indicador de carregamento', async () => {
  render(<App autenticador={await autenticadorComSessao()} />)

  expect(screen.getByRole('status', { name: 'Verificando a sessão' })).toBeTruthy()
  await screen.findByText('Biblioteca')
})

test('quem só tem Consulta não vê o upload na Biblioteca', async () => {
  servidor.use(
    http.get('/v1/eu', () =>
      HttpResponse.json({
        uid: 'u1',
        email: 'ana@redetv.com.br',
        papeis: ['consulta'],
        permissoes: ['decupagem.ver'],
      }),
    ),
  )
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  await screen.findByText('Nenhum vídeo enviado ainda.')
  expect(screen.queryByRole('button', { name: 'Enviar MP4' })).toBeNull()
})

test('quem tem video.enviar vê o upload na Biblioteca', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await screen.findByLabelText(/^E-mail/)
  await preencherSenha(usuario)
  await confirmarCodigo(usuario)

  expect(await screen.findByRole('button', { name: 'Enviar MP4' })).toBeTruthy()
})
