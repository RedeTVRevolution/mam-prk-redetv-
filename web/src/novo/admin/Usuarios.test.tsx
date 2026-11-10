import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import App from '../App.tsx'

interface Conta {
  uid: string
  email: string
  nome: string
  papeis: string[]
  criada_em: string | null
  ultimo_acesso: string | null
  situacao: 'ativa' | 'desativada'
}

const ADMIN = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['administrador'], permissoes: ['decupagem.ver', 'usuarios.gerir'] }
const COMUM = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['consulta'], permissoes: ['decupagem.ver'] }

const contas = (): Conta[] => [
  { uid: 'u1', email: 'ana@redetv.com.br', nome: 'Ana Lima', papeis: ['administrador'], criada_em: null, ultimo_acesso: '2026-10-28T14:02:00Z', situacao: 'ativa' },
  { uid: 'u2', email: 'rui@redetv.com.br', nome: 'Rui Prado', papeis: ['editor', 'operador'], criada_em: null, ultimo_acesso: null, situacao: 'ativa' },
  { uid: 'u3', email: 'eva@redetv.com.br', nome: 'Eva Costa', papeis: ['consulta'], criada_em: null, ultimo_acesso: null, situacao: 'desativada' },
]

let eu = ADMIN
let lista: Conta[] = contas()
const chamadas: { metodo: string; caminho: string; corpo: unknown }[] = []
let falhaDaAcao: number | null = null

async function registrar(request: Request) {
  const url = new URL(request.url)
  const texto = await request.text()
  chamadas.push({ metodo: request.method, caminho: url.pathname, corpo: texto ? JSON.parse(texto) : null })
  if (falhaDaAcao) return new HttpResponse(JSON.stringify({ detail: 'sem permissão' }), { status: falhaDaAcao })
  return null
}

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(eu)),
  http.get('/v1/admin/usuarios', async ({ request }) => (await registrar(request)) ?? HttpResponse.json(lista)),
  http.post('/v1/admin/usuarios', async ({ request }) => {
    const falha = await registrar(request)
    if (falha) return falha
    const corpo = chamadas.at(-1)!.corpo as { email: string; nome: string; papeis: string[] }
    const nova: Conta = { uid: 'u9', ...corpo, criada_em: null, ultimo_acesso: null, situacao: 'ativa' }
    lista = [...lista, nova]
    return HttpResponse.json(nova, { status: 201 })
  }),
  http.post('/v1/admin/usuarios/:uid/link-de-senha', async ({ request }) => (await registrar(request)) ?? HttpResponse.json({ enviado: true })),
  http.put('/v1/admin/usuarios/:uid/papeis', async ({ request, params }) => {
    const falha = await registrar(request)
    if (falha) return falha
    const conta = { ...lista.find((c) => c.uid === params.uid)!, papeis: (chamadas.at(-1)!.corpo as { papeis: string[] }).papeis }
    return HttpResponse.json(conta)
  }),
  http.post('/v1/admin/usuarios/:uid/desativar', async ({ request, params }) => {
    const falha = await registrar(request)
    if (falha) return falha
    return HttpResponse.json({ ...lista.find((c) => c.uid === params.uid)!, situacao: 'desativada' })
  }),
  http.post('/v1/admin/usuarios/:uid/reativar', async ({ request, params }) => {
    const falha = await registrar(request)
    if (falha) return falha
    return HttpResponse.json({ ...lista.find((c) => c.uid === params.uid)!, situacao: 'ativa' })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  eu = ADMIN
  lista = contas()
  chamadas.length = 0
  falhaDaAcao = null
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

async function linhaDe(nome: string) {
  const tabela = await screen.findByRole('table', { name: 'Usuários' })
  return within(tabela).getByRole('row', { name: new RegExp(nome) })
}

async function abrirMenu(usuario: ReturnType<typeof userEvent.setup>, nome: string) {
  const linha = await linhaDe(nome)
  await usuario.click(within(linha).getByRole('button', { name: `Ações de ${nome}` }))
}

test('uma conta sem nome usa o e-mail no botão de ações e a inicial dele no avatar', async () => {
  lista = [...contas(), { uid: 'u4', email: 'zeca@redetv.com.br', nome: '', papeis: ['consulta'], criada_em: null, ultimo_acesso: null, situacao: 'ativa' }]
  await abrir('/admin/usuarios')
  const linha = await linhaDe('zeca@redetv.com.br')
  expect(within(linha).getByRole('button', { name: 'Ações de zeca@redetv.com.br' })).toBeTruthy()
  expect(linha.textContent).toContain('Z')
  expect(linha.textContent).not.toContain('?')
})

test('o link Administração só aparece para quem abre alguma aba da área', async () => {
  eu = COMUM
  await abrir('/acervo')
  await screen.findByRole('navigation', { name: 'Principal' })
  expect(screen.queryByRole('link', { name: 'Administração' })).toBeNull()
  cleanup()

  // Uma permissão que não abre aba (apagar do catálogo) não leva a uma área vazia.
  eu = { ...COMUM, permissoes: ['decupagem.ver', 'catalogo.apagar'] }
  await abrir('/acervo')
  await screen.findByRole('navigation', { name: 'Principal' })
  expect(screen.queryByRole('link', { name: 'Administração' })).toBeNull()
  cleanup()

  eu = ADMIN
  await abrir('/acervo')
  const link = await screen.findByRole('link', { name: 'Administração' })
  expect(link.getAttribute('href')).toBe('/admin')
})

test('a área tem o título, as abas com o endereço de cada uma e a aba atual marcada', async () => {
  eu = { ...ADMIN, permissoes: ['decupagem.ver', 'usuarios.gerir', 'auditoria.ver'] }
  await abrir('/admin/usuarios')
  expect(await screen.findByRole('heading', { name: 'Administração' })).toBeTruthy()
  const abas = within(screen.getByRole('navigation', { name: 'Abas da administração' }))
  expect(abas.getAllByRole('link').map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
    ['Usuários', '/admin/usuarios'],
    ['Auditoria', '/admin/auditoria'],
  ])
  expect(abas.getByRole('link', { name: 'Usuários' }).getAttribute('aria-current')).toBe('page')
  expect(abas.getByRole('link', { name: 'Auditoria' }).getAttribute('aria-current')).toBeNull()
})

test('uma aba que não existe ou não é permitida não abre', async () => {
  await abrir('/admin/qualquer')
  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
  cleanup()
  await abrir('/admin/auditoria')
  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Ir ao acervo' }).getAttribute('href')).toBe('/acervo')
})

test('/admin abre a primeira aba permitida', async () => {
  await abrir('/admin')
  await screen.findByRole('table', { name: 'Usuários' })
  expect(location.pathname).toBe('/admin/usuarios')
  expect(screen.getByRole('link', { name: 'Usuários' }).getAttribute('href')).toBe('/admin/usuarios')
})

test('a tabela mostra nome, e-mail, papéis em texto, último acesso e situação', async () => {
  await abrir('/admin/usuarios')
  const rui = await linhaDe('Rui Prado')
  expect(within(rui).getByText('rui@redetv.com.br')).toBeTruthy()
  expect(within(rui).getByText('Editor, Operador')).toBeTruthy()
  expect(within(rui).getByText('Ativa')).toBeTruthy()
  expect(within(await linhaDe('Eva Costa')).getByText('Desativada')).toBeTruthy()
})

test('a busca e os filtros reduzem a tabela', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await linhaDe('Rui Prado')
  await usuario.type(screen.getByRole('textbox', { name: 'Buscar por nome ou e-mail' }), 'eva@')
  const tabela = screen.getByRole('table', { name: 'Usuários' })
  expect(within(tabela).queryByText('Rui Prado')).toBeNull()
  expect(within(tabela).getByText('Eva Costa')).toBeTruthy()

  await usuario.clear(screen.getByRole('textbox', { name: 'Buscar por nome ou e-mail' }))
  await usuario.selectOptions(screen.getByRole('combobox', { name: 'Situação' }), 'Desativada')
  expect(within(tabela).queryByText('Rui Prado')).toBeNull()
  expect(within(tabela).getByText('Eva Costa')).toBeTruthy()
})

test('Nova conta cria e avisa para onde foi o link', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await usuario.click(await screen.findByRole('button', { name: 'Nova conta' }))
  const dialogo = await screen.findByRole('dialog')
  expect(within(dialogo).getByText(/Editor: envia vídeos, reprocessa o que falhou e corrige a decupagem/)).toBeTruthy()
  await usuario.type(within(dialogo).getByLabelText('E-mail'), 'bia@redetv.com.br')
  await usuario.type(within(dialogo).getByLabelText('Nome'), 'Bia Souza')
  await usuario.click(within(dialogo).getByRole('checkbox', { name: /Editor/ }))
  await usuario.click(within(dialogo).getByRole('button', { name: 'Criar conta' }))

  await screen.findByText('Conta criada. O link para definir a senha foi enviado para bia@redetv.com.br.')
  const criacao = chamadas.find((c) => c.metodo === 'POST')!
  expect(criacao.caminho).toBe('/v1/admin/usuarios')
  expect(criacao.corpo).toEqual({ email: 'bia@redetv.com.br', nome: 'Bia Souza', papeis: ['editor'] })
  expect(await linhaDe('Bia Souza')).toBeTruthy()
})

test('Editar papéis grava os papéis marcados e atualiza a linha', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await abrirMenu(usuario, 'Rui Prado')
  await usuario.click(await screen.findByRole('menuitem', { name: 'Editar papéis' }))
  const dialogo = await screen.findByRole('dialog')
  await usuario.click(within(dialogo).getByRole('checkbox', { name: /Operador/ }))
  await usuario.click(within(dialogo).getByRole('checkbox', { name: /Curador/ }))
  await usuario.click(within(dialogo).getByRole('checkbox', { name: /Diretoria/ }))
  await usuario.click(within(dialogo).getByRole('button', { name: 'Salvar' }))

  await within(await linhaDe('Rui Prado')).findByText('Editor, Curador, Diretoria')
  const chamada = chamadas.find((c) => c.metodo === 'PUT')!
  expect(chamada.caminho).toBe('/v1/admin/usuarios/u2/papeis')
  expect(chamada.corpo).toEqual({ papeis: ['editor', 'curador', 'diretoria'] })
})

test('Reenviar link de senha chama a API e avisa', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await abrirMenu(usuario, 'Rui Prado')
  await usuario.click(await screen.findByRole('menuitem', { name: 'Reenviar link de senha' }))
  await screen.findByText('Link de senha reenviado para rui@redetv.com.br.')
  expect(chamadas.some((c) => c.caminho === '/v1/admin/usuarios/u2/link-de-senha')).toBe(true)
})

test('Desativar pede confirmação na linha, e Reativar volta a conta', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await abrirMenu(usuario, 'Rui Prado')
  await usuario.click(await screen.findByRole('menuitem', { name: 'Desativar' }))
  expect(await screen.findByText('Desativar Rui Prado? A conta sai na hora. Enter confirma')).toBeTruthy()
  expect(chamadas.some((c) => c.caminho.endsWith('/desativar'))).toBe(false)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar desativação' }))
  await within(await linhaDe('Rui Prado')).findByText('Desativada')
  expect(chamadas.some((c) => c.caminho === '/v1/admin/usuarios/u2/desativar')).toBe(true)

  await abrirMenu(usuario, 'Eva Costa')
  await usuario.click(await screen.findByRole('menuitem', { name: 'Reativar' }))
  await within(await linhaDe('Eva Costa')).findByText('Ativa')
  expect(chamadas.some((c) => c.caminho === '/v1/admin/usuarios/u3/reativar')).toBe(true)
})

test('na própria conta, Desativar e o papel Administrador ficam desabilitados com a dica', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await abrirMenu(usuario, 'Ana Lima')
  const desativar = await screen.findByRole('menuitem', { name: 'Desativar' })
  expect(desativar.hasAttribute('disabled') || desativar.getAttribute('data-disabled') !== null).toBe(true)
  expect(screen.getByText('Você não pode desativar a própria conta.')).toBeTruthy()
  await usuario.click(screen.getByRole('menuitem', { name: 'Editar papéis' }))
  const dialogo = await screen.findByRole('dialog')
  expect((within(dialogo).getByRole('checkbox', { name: /Administrador/ }) as HTMLInputElement).disabled).toBe(true)
  expect(within(dialogo).getByText('Você não pode tirar o seu próprio papel de Administrador.')).toBeTruthy()
})

test('403 da API mostra a mensagem de permissão sem quebrar a tela', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await abrirMenu(usuario, 'Rui Prado')
  falhaDaAcao = 403
  await usuario.click(await screen.findByRole('menuitem', { name: 'Reenviar link de senha' }))
  expect(await screen.findByText('Você não tem permissão para isto.')).toBeTruthy()
  expect(screen.getByRole('table', { name: 'Usuários' })).toBeTruthy()
})

test('a lista que ainda vinha do servidor não desfaz a desativação feita no meio', async () => {
  eu = { ...ADMIN, permissoes: [...ADMIN.permissoes, 'chaves.gerir'] }
  const usuario = userEvent.setup()
  await abrir('/admin/usuarios')
  await linhaDe('Rui Prado')
  // Ao voltar à aba, o cache mostra a lista e um GET sai de novo; este fica preso até a desativação terminar.
  let soltar: () => void = () => {}
  const preso = new Promise<void>((r) => (soltar = r))
  servidor.use(
    http.get('/v1/admin/chaves', () => HttpResponse.json([])),
    http.get('/v1/admin/usuarios', async () => {
      const antes = contas()
      await preso
      return HttpResponse.json(antes)
    }),
  )
  await usuario.click(screen.getByRole('link', { name: 'Sistemas e chaves' }))
  await usuario.click(await screen.findByRole('link', { name: 'Usuários' }))
  await abrirMenu(usuario, 'Rui Prado')
  await usuario.click(await screen.findByRole('menuitem', { name: 'Desativar' }))
  await usuario.click(await screen.findByRole('button', { name: 'Confirmar desativação' }))
  await within(await linhaDe('Rui Prado')).findByText('Desativada')
  soltar()
  await new Promise((r) => setTimeout(r, 50))
  expect(within(await linhaDe('Rui Prado')).getByText('Desativada')).toBeTruthy()
})
