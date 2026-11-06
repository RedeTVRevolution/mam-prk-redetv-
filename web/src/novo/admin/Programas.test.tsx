import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from '../App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'

const EDITOR = { uid: 'u1', email: 'rui@redetv.com.br', papeis: ['editor'], permissoes: ['decupagem.ver', 'programas.editar'] }
const CONSULTA = { uid: 'u1', email: 'eva@redetv.com.br', papeis: ['consulta'], permissoes: ['decupagem.ver'] }

let eu = EDITOR
let lista = [{ id: 'p1', nome: 'TV Fama', perfil: 'Famosos', pessoas: [{ pessoa_id: 'x1', nome: 'Nelson Rubens', apelidos: [], papel: 'apresentador' }] }]
const chamadas: { metodo: string; caminho: string; corpo: unknown }[] = []

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(eu)),
  http.get('/v1/catalogo/pessoas', () => HttpResponse.json([{ id: 'x2', nome: 'Sabrina Sato', rotulo: 'Sabrina Sato', a_revisar: false }])),
  http.get('/v1/admin/programas', () => HttpResponse.json(lista)),
  http.post('/v1/admin/programas', async ({ request }) => {
    const corpo = (await request.json()) as { nome: string; perfil: string; pessoas: { pessoa_id: string; papel: string }[] }
    chamadas.push({ metodo: 'POST', caminho: '/v1/admin/programas', corpo })
    lista = [...lista, { id: 'p2', nome: corpo.nome, perfil: corpo.perfil, pessoas: [{ pessoa_id: 'x2', nome: 'Sabrina Sato', apelidos: [], papel: corpo.pessoas[0]?.papel ?? '' }] }]
    return HttpResponse.json(lista.at(-1), { status: 201 })
  }),
  http.get('/v1/admin/programas/:id/impacto', () => HttpResponse.json({ videos: 3 })),
  http.delete('/v1/admin/programas/:id', ({ params }) => {
    chamadas.push({ metodo: 'DELETE', caminho: `/v1/admin/programas/${params.id as string}`, corpo: null })
    lista = lista.filter((p) => p.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  servidor.resetHandlers()
  window.history.replaceState(null, '', '/')
  eu = EDITOR
  chamadas.length = 0
  lista = [{ id: 'p1', nome: 'TV Fama', perfil: 'Famosos', pessoas: [{ pessoa_id: 'x1', nome: 'Nelson Rubens', apelidos: [], papel: 'apresentador' }] }]
})
afterAll(() => servidor.close())

async function abrir() {
  const auth = new AutenticadorFalso([{ email: 'rui@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('rui@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/admin')
  render(<App autenticador={auth} />)
}

test('o Editor vê só a aba Programas e a lista', async () => {
  await abrir()
  expect(await screen.findByText('TV Fama')).toBeTruthy()
  const abas = within(screen.getByRole('navigation', { name: 'Abas da administração' }))
  expect(abas.getAllByRole('link').map((a) => a.textContent)).toEqual(['Programas'])
  expect(screen.getByText('Nelson Rubens (apresentador)')).toBeTruthy()
})

test('quem só consulta não vê a administração', async () => {
  eu = CONSULTA
  await abrir()
  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
})

test('cria um programa com uma pessoa do catálogo e o papel dela', async () => {
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Novo programa' }))
  await u.type(screen.getByLabelText('Nome'), 'Hoje em Dia')
  await u.type(screen.getByRole('combobox', { name: 'Incluir pessoa do catálogo' }), 'Sab')
  await u.click(await screen.findByRole('option', { name: 'Sabrina Sato' }))
  await u.type(screen.getByLabelText('Papel de Sabrina Sato'), 'âncora')
  await u.click(screen.getByRole('button', { name: 'Gravar' }))
  expect(await screen.findByText('Hoje em Dia')).toBeTruthy()
  expect(chamadas[0].corpo).toEqual({ nome: 'Hoje em Dia', perfil: '', pessoas: [{ pessoa_id: 'x2', papel: 'âncora' }] })
})

test('apagar mostra quantos vídeos usam o programa e pede confirmação', async () => {
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Apagar TV Fama' }))
  expect(await screen.findByText(/3 vídeos usam este programa/)).toBeTruthy()
  expect(chamadas).toEqual([])
  await u.click(screen.getByRole('button', { name: 'Apagar programa' }))
  expect(await screen.findByText('Nenhum programa cadastrado.')).toBeTruthy()
  expect(chamadas[0]).toMatchObject({ metodo: 'DELETE', caminho: '/v1/admin/programas/p1' })
})

test('a pessoa entra pelo teclado, e quem não está no catálogo é criada com os apelidos', async () => {
  const pessoasCriadas: unknown[] = []
  servidor.use(
    http.post('/v1/admin/programas/pessoas', async ({ request }) => {
      const corpo = (await request.json()) as { nome: string; apelidos: string[] }
      pessoasCriadas.push(corpo)
      return HttpResponse.json({ pessoa_id: 'x3', nome: corpo.nome, apelidos: corpo.apelidos, papel: '' }, { status: 201 })
    }),
  )
  const u = userEvent.setup()
  await abrir()
  await u.click(await screen.findByRole('button', { name: 'Novo programa' }))
  const campo = screen.getByRole('combobox', { name: 'Incluir pessoa do catálogo' })
  await u.type(campo, 'Sab')
  await screen.findByRole('option', { name: 'Sabrina Sato' })
  await u.keyboard('{ArrowDown}{Enter}')
  expect(screen.getByLabelText('Papel de Sabrina Sato')).toBeTruthy()
  expect(screen.getByRole('dialog')).toBeTruthy()
  await u.type(campo, 'Ana Hickmann')
  await u.type(screen.getByLabelText('Apelidos (separados por vírgula)'), 'Ana, Hickmann')
  await u.click(screen.getByRole('button', { name: 'Criar pessoa «Ana Hickmann»' }))
  expect(await screen.findByLabelText('Papel de Ana Hickmann')).toBeTruthy()
  expect(pessoasCriadas).toEqual([{ nome: 'Ana Hickmann', apelidos: ['Ana', 'Hickmann'] }])
  await u.click(screen.getByRole('button', { name: 'Tirar Sabrina Sato' }))
  expect(screen.queryByLabelText('Papel de Sabrina Sato')).toBeNull()
})
