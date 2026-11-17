import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from '../App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'

const CURADOR = { uid: 'u1', email: 'cris@redetv.com.br', papeis: ['curador'], permissoes: ['decupagem.ver', 'catalogo.fundir'] }
const EDITOR = { uid: 'u2', email: 'rui@redetv.com.br', papeis: ['editor'], permissoes: ['decupagem.ver', 'programas.editar'] }

const INICIAL = [
  { id: 'm1', nome: 'Magalu', apelidos: ['Magazine Luiza'] },
  { id: 'm2', nome: 'UNIFAEL', apelidos: [] as string[] },
  { id: 'm3', nome: 'UniAefel', apelidos: [] as string[] },
]
let eu = CURADOR
let lista = INICIAL
const chamadas: { metodo: string; caminho: string; corpo: unknown }[] = []

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(eu)),
  http.get('/v1/catalogo/marcas/cadastro', () => HttpResponse.json(lista)),
  http.post('/v1/catalogo/marcas/cadastro', async ({ request }) => {
    const corpo = (await request.json()) as { nome: string; apelidos: string[] }
    chamadas.push({ metodo: 'POST', caminho: '/v1/catalogo/marcas/cadastro', corpo })
    lista = [...lista, { id: 'm9', ...corpo }]
    return HttpResponse.json(lista.at(-1), { status: 201 })
  }),
  http.put('/v1/catalogo/marcas/:id/apelidos', async ({ request, params }) => {
    const corpo = (await request.json()) as { apelidos: string[] }
    chamadas.push({ metodo: 'PUT', caminho: `/v1/catalogo/marcas/${params.id as string}/apelidos`, corpo })
    lista = lista.map((m) => (m.id === params.id ? { ...m, apelidos: corpo.apelidos } : m))
    return HttpResponse.json(lista.find((m) => m.id === params.id))
  }),
  http.post('/v1/catalogo/marcas/:id/juntar', async ({ request, params }) => {
    const corpo = (await request.json()) as { outra_id: string }
    chamadas.push({ metodo: 'POST', caminho: `/v1/catalogo/marcas/${params.id as string}/juntar`, corpo })
    const outra = lista.find((m) => m.id === corpo.outra_id)!
    lista = lista.filter((m) => m.id !== outra.id).map((m) => (m.id === params.id ? { ...m, apelidos: [...m.apelidos, outra.nome] } : m))
    return HttpResponse.json(lista.find((m) => m.id === params.id))
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  servidor.resetHandlers()
  window.history.replaceState(null, '', '/')
  eu = CURADOR
  lista = INICIAL
  chamadas.length = 0
})
afterAll(() => servidor.close())

async function abrir(caminho = '/admin/marcas') {
  const auth = new AutenticadorFalso([{ email: 'cris@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('cris@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', caminho)
  render(<App autenticador={auth} />)
}

test('o Curador vê a aba Marcas, com as marcas e os apelidos', async () => {
  await abrir('/admin')
  expect(await screen.findByText('Magalu')).toBeTruthy()
  const abas = within(screen.getByRole('navigation', { name: 'Abas da administração' }))
  expect(abas.getAllByRole('link').map((a) => a.textContent)).toEqual(['Marcas'])
  expect(screen.getByText('Magazine Luiza')).toBeTruthy()
  expect(screen.getByText('3 marcas')).toBeTruthy()
})

test('quem não tem catalogo.fundir não abre a aba', async () => {
  eu = EDITOR
  await abrir()
  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
})

test('o filtro mostra só as marcas cujo nome ou apelido tem o texto', async () => {
  const u = userEvent.setup()
  await abrir()
  await screen.findByText('Magalu')
  await u.type(screen.getByRole('searchbox', { name: 'Filtrar marcas' }), 'magazine')
  expect(screen.getByText('Magalu')).toBeTruthy()
  expect(screen.queryByText('UNIFAEL')).toBeNull()
})

test('cria uma marca com apelidos separados por vírgula', async () => {
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Nova marca' }))
  await u.type(screen.getByLabelText('Nome'), 'Casas Bahia')
  await u.type(screen.getByLabelText('Apelidos (separados por vírgula)'), 'Cs Bahia, CB')
  await u.click(screen.getByRole('button', { name: 'Gravar' }))
  expect(await screen.findByText('Casas Bahia')).toBeTruthy()
  expect(chamadas[0].corpo).toEqual({ nome: 'Casas Bahia', apelidos: ['Cs Bahia', 'CB'] })
})

test('o 409 da criação mostra a mensagem da API', async () => {
  servidor.use(http.post('/v1/catalogo/marcas/cadastro', () => HttpResponse.json({ detail: 'UniAefel já é a marca UniAefel: use Juntar' }, { status: 409 })))
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Nova marca' }))
  await u.type(screen.getByLabelText('Nome'), 'UniAefel')
  await u.click(screen.getByRole('button', { name: 'Gravar' }))
  expect((await screen.findByRole('alert')).textContent).toContain('UniAefel já é a marca UniAefel: use Juntar')
})

test('acrescenta e tira apelidos de uma marca', async () => {
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Editar apelidos de Magalu' }))
  await u.click(screen.getByRole('button', { name: 'Tirar Magazine Luiza' }))
  await u.type(screen.getByLabelText('Novo apelido'), 'Magazine Lu{Enter}')
  expect(screen.getByRole('button', { name: 'Tirar Magazine Lu' })).toBeTruthy()
  await u.click(screen.getByRole('button', { name: 'Gravar' }))
  expect(await screen.findByText('Magazine Lu')).toBeTruthy()
  expect(chamadas[0]).toEqual({ metodo: 'PUT', caminho: '/v1/catalogo/marcas/m1/apelidos', corpo: { apelidos: ['Magazine Lu'] } })
})

test('o apelido digitado e não acrescentado também entra ao gravar', async () => {
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Editar apelidos de UNIFAEL' }))
  await u.type(screen.getByLabelText('Novo apelido'), 'Uni Fael')
  await u.click(screen.getByRole('button', { name: 'Gravar' }))
  await screen.findByText('Uni Fael')
  expect(chamadas[0].corpo).toEqual({ apelidos: ['Uni Fael'] })
})

test('o 409 dos apelidos mostra a mensagem e mantém o diálogo aberto', async () => {
  servidor.use(http.put('/v1/catalogo/marcas/:id/apelidos', () => HttpResponse.json({ detail: 'UniAefel já é a marca UniAefel: use Juntar' }, { status: 409 })))
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Editar apelidos de UNIFAEL' }))
  await u.type(screen.getByLabelText('Novo apelido'), 'UniAefel')
  await u.click(screen.getByRole('button', { name: 'Gravar' }))
  expect((await screen.findByRole('alert')).textContent).toContain('use Juntar')
  expect(screen.getByRole('dialog')).toBeTruthy()
})

test('juntar pede confirmação e a outra marca vira apelido desta', async () => {
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Juntar a UNIFAEL' }))
  // A própria marca não está entre as opções.
  const escolha = screen.getByLabelText('Marca a juntar')
  expect(within(escolha).queryByRole('option', { name: 'UNIFAEL' })).toBeNull()
  await u.selectOptions(escolha, 'UniAefel')
  expect(screen.getByText(/UniAefel deixa de existir e passa a ser apelido de UNIFAEL/)).toBeTruthy()
  expect(chamadas).toEqual([])
  await u.click(screen.getByRole('button', { name: 'Juntar marcas' }))
  expect(await screen.findByText('2 marcas')).toBeTruthy()
  // UniAefel já não é uma linha: só aparece como apelido de UNIFAEL.
  expect(screen.getAllByRole('row')).toHaveLength(3)
  expect(within(screen.getByRole('row', { name: /UNIFAEL/ })).getByText('UniAefel')).toBeTruthy()
  expect(chamadas[0]).toEqual({ metodo: 'POST', caminho: '/v1/catalogo/marcas/m2/juntar', corpo: { outra_id: 'm3' } })
})

test('o 409 do juntar (outra na lixeira) mostra a mensagem', async () => {
  servidor.use(http.post('/v1/catalogo/marcas/:id/juntar', () => HttpResponse.json({ detail: 'UniAefel está na lixeira: restaure antes de juntar' }, { status: 409 })))
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Juntar a UNIFAEL' }))
  await u.selectOptions(screen.getByLabelText('Marca a juntar'), 'UniAefel')
  await u.click(screen.getByRole('button', { name: 'Juntar marcas' }))
  expect((await screen.findByRole('alert')).textContent).toContain('restaure antes de juntar')
})
