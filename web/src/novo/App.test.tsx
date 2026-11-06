import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { PedidoInvalido, SessaoExpirada } from '../api.ts'
import { ContaBloqueada } from '../auth/autenticador.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../auth/falso.ts'
import { NOME_DO_CACHE } from '../cacheDeImagens.ts'
import { AutenticadorIndisponivel } from '../auth/indisponivel.ts'
import App from './App.tsx'
import { criarClienteDeConsultas } from './consultas.ts'

const ANA = 'ana@redetv.com.br'
const chamadas: (string | null)[] = []
let permissoes = ['decupagem.ver', 'video.enviar']

// API simulada: só reconhece o token que o autenticador falso emite para a Ana.
const servidor = setupServer(
  http.get('/v1/eu', ({ request }) => {
    const autorizacao = request.headers.get('Authorization')
    chamadas.push(autorizacao)
    if (autorizacao !== `Bearer token-de-${ANA}`) return new HttpResponse(null, { status: 401 })
    return HttpResponse.json({ uid: 'u1', email: ANA, papeis: ['consulta', 'editor'], permissoes })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  chamadas.length = 0
  permissoes = ['decupagem.ver', 'video.enviar']
})
afterAll(() => servidor.close())

function autenticador(totpCadastrado = true) {
  return new AutenticadorFalso([{ email: ANA, senha: 'senha-forte-1', totpCadastrado }])
}

async function comSessao() {
  const auth = autenticador()
  await auth.entrar(ANA, 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

async function preencherSenha(usuario: ReturnType<typeof userEvent.setup>, senha = 'senha-forte-1') {
  await usuario.type(await screen.findByLabelText(/^E-mail/), ANA)
  await usuario.type(screen.getByLabelText(/^Senha/), senha)
  await usuario.click(screen.getByRole('button', { name: 'Entrar' }))
}

async function confirmar(usuario: ReturnType<typeof userEvent.setup>, codigo = CODIGO_TOTP_FALSO) {
  await usuario.type(await screen.findByLabelText('Código do autenticador'), codigo)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))
}

function trilho() {
  return within(screen.getByRole('navigation', { name: 'Principal' }))
}

test('sem sessão, mostra só o login e não chama a API', async () => {
  render(<App autenticador={autenticador()} />)

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(screen.queryByRole('navigation')).toBeNull()
  expect(chamadas).toEqual([])
})

test('senha e código abrem a casca, com o token na API, e `/` vai ao acervo', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)

  await preencherSenha(usuario)
  expect(screen.queryByRole('navigation')).toBeNull()
  await confirmar(usuario)

  expect(await screen.findByRole('navigation', { name: 'Principal' })).toBeTruthy()
  expect(chamadas.at(-1)).toBe(`Bearer token-de-${ANA}`)
  await waitFor(() => expect(location.pathname).toBe('/acervo'))
  expect(trilho().getByRole('link', { name: 'Acervo' }).getAttribute('aria-current')).toBe('page')
})

test('o primeiro acesso cadastra o autenticador com o segredo e o link', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador(false)} />)

  await preencherSenha(usuario)

  expect((await screen.findByLabelText('Segredo do autenticador')).textContent).toBe('SEGREDOFALSO')
  expect(screen.getByRole('link', { name: /Abrir no aplicativo autenticador/ }).getAttribute('href')).toBe('otpauth://totp/MAM')
  await confirmar(usuario)
  expect(await screen.findByRole('navigation', { name: 'Principal' })).toBeTruthy()
})

test('o código só pode ser confirmado com 6 números, e o errado mostra erro', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await preencherSenha(usuario)

  const campo = await screen.findByLabelText('Código do autenticador')
  await usuario.type(campo, '12a3')
  expect((campo as HTMLInputElement).value).toBe('123')
  expect(screen.getByRole('button', { name: 'Confirmar' }).hasAttribute('disabled')).toBe(true)

  await usuario.clear(campo)
  await confirmar(usuario, '654321')
  expect((await screen.findByRole('alert')).textContent).toContain('inválid')
  expect(screen.queryByRole('navigation')).toBeNull()
})

test('voltar do código recomeça pela senha', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={autenticador()} />)
  await preencherSenha(usuario)

  await usuario.click(await screen.findByRole('button', { name: 'Voltar' }))
  expect((screen.getByLabelText(/^E-mail/) as HTMLInputElement).value).toBe('')
})

test.each([
  ['senha errada', autenticador(), 'Credenciais inválidas'],
  ['conta bloqueada', Object.assign(autenticador(), { entrar: async () => Promise.reject(new ContaBloqueada()) }), 'Muitas tentativas'],
  ['falha inesperada', Object.assign(autenticador(), { entrar: async () => Promise.reject(new Error('rede fora')) }), 'Login indisponível'],
  ['login sem configuração', new AutenticadorIndisponivel(), 'Login indisponível'],
])('%s mostra o erro e continua no login', async (_caso, auth, mensagem) => {
  const usuario = userEvent.setup()
  render(<App autenticador={auth} />)

  await preencherSenha(usuario, 'errada')

  expect((await screen.findByRole('alert')).textContent).toContain(mensagem)
  expect(screen.queryByLabelText('Código do autenticador')).toBeNull()
})

test('o trilho mostra o Painel e a Administração só para quem pode', async () => {
  render(<App autenticador={await comSessao()} />)
  await screen.findByRole('navigation', { name: 'Principal' })
  expect(trilho().getAllByRole('link').map((l) => l.textContent)).toEqual(['Acervo', 'Busca', 'Tempo de tela', 'Marcas'])
  cleanup()

  permissoes = ['decupagem.ver', 'painel.ver', 'usuarios.gerir']
  render(<App autenticador={await comSessao()} />)
  await screen.findByRole('navigation', { name: 'Principal' })
  expect(trilho().getAllByRole('link').map((l) => l.textContent)).toEqual([
    'Acervo',
    'Busca',
    'Tempo de tela',
    'Marcas',
    'Painel da diretoria',
    'Administração',
  ])
})

test('quem só vê o painel começa nele', async () => {
  permissoes = ['painel.ver']
  render(<App autenticador={await comSessao()} />)
  await waitFor(() => expect(location.pathname).toBe('/painel'))
})

test('a tela que não migrou leva à mesma URL na interface atual', async () => {
  // Com relatórios e administração migrados, só a amostra do sistema visual sobra.
  history.replaceState(null, '', '/amostra?x=1')
  render(<App autenticador={await comSessao()} />)

  const link = await screen.findByRole('link', { name: /Abrir na interface atual/ })
  expect(link.getAttribute('href')).toBe('/amostra?x=1&interface=atual')
})

test('sair pelo menu da conta volta ao login e apaga a sessão', async () => {
  const usuario = userEvent.setup()
  const auth = await comSessao()
  const apagar = vi.fn(async () => true)
  vi.stubGlobal('caches', { delete: apagar })
  render(<App autenticador={auth} />)

  await usuario.click(await screen.findByRole('button', { name: `Conta: ${ANA}` }))
  expect(await screen.findByText('Consulta, Editor')).toBeTruthy()
  await usuario.click(screen.getByRole('menuitem', { name: 'Sair' }))

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(await auth.token()).toBeNull()
  // O cache de imagens some junto com a sessão.
  expect(apagar).toHaveBeenCalledWith(NOME_DO_CACHE)
})

test('a sessão expirada (401) leva ao login, e o login seguinte entra', async () => {
  const usuario = userEvent.setup()
  const auth = await comSessao()
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 401 }), { once: true }))
  render(<App autenticador={auth} />)

  expect(await screen.findByLabelText(/^E-mail/)).toBeTruthy()
  expect(await auth.token()).toBeNull()

  await preencherSenha(usuario)
  await confirmar(usuario)
  expect(await screen.findByRole('navigation', { name: 'Principal' })).toBeTruthy()
})

test('sem a API, avisa e deixa tentar de novo', async () => {
  const usuario = userEvent.setup()
  servidor.use(http.get('/v1/eu', () => new HttpResponse(null, { status: 503 }), { once: true }))
  render(<App autenticador={await comSessao()} />)

  expect((await screen.findByRole('alert')).textContent).toContain('Não foi possível falar com a API')
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))
  expect(await screen.findByRole('navigation', { name: 'Principal' })).toBeTruthy()
})

test('a busca global abre com `/` e busca o texto no conteúdo', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={await comSessao()} />)
  await screen.findByRole('navigation', { name: 'Principal' })

  await usuario.keyboard('/')
  const dialogo = await screen.findByRole('dialog', { name: 'Buscar no acervo' })
  await usuario.type(within(dialogo).getByRole('combobox', { name: 'Buscar no acervo' }), 'Leão Lobo{Enter}')

  await waitFor(() => expect(location.pathname).toBe('/busca'))
  expect(new URLSearchParams(location.search).get('q')).toBe('Leão Lobo')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('G e uma letra vão à tela, e `?` lista os atalhos', async () => {
  const usuario = userEvent.setup()
  render(<App autenticador={await comSessao()} />)
  await screen.findByRole('navigation', { name: 'Principal' })

  await usuario.keyboard('gm')
  expect(location.pathname).toBe('/relatorios/marcas')
  // A letra sozinha não navega.
  await usuario.keyboard('t')
  expect(location.pathname).toBe('/relatorios/marcas')

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog', { name: 'Atalhos de teclado' })
  expect(within(lista).getByText('Ir para Tempo de tela')).toBeTruthy()
  expect(within(lista).queryByText('Ir para Painel da diretoria')).toBeNull()

  // Com a lista aberta, os atalhos da tela de trás não agem.
  await usuario.keyboard('gt')
  expect(location.pathname).toBe('/relatorios/marcas')
  await usuario.keyboard('{Control>}k{/Control}')
  expect(screen.queryByRole('dialog', { name: 'Buscar no acervo' })).toBeNull()
})

test('as consultas saem do cache em 30 s, não voltam ao focar e não repetem o 401', () => {
  const { queries } = criarClienteDeConsultas().getDefaultOptions()
  expect(queries?.gcTime).toBe(30_000)
  expect(queries?.refetchOnWindowFocus).toBe(false)
  const repetir = queries?.retry as (falhas: number, erro: Error) => boolean
  expect(repetir(0, new SessaoExpirada())).toBe(false)
  expect(repetir(0, new PedidoInvalido('Cursor inválido'))).toBe(false)
  expect(repetir(0, new Error('rede'))).toBe(true)
  expect(repetir(2, new Error('rede'))).toBe(false)
})
