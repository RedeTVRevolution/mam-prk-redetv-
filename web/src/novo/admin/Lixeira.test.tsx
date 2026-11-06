import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from '../App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'

interface Item {
  tipo: string
  id: string
  nome: string
  enviado_por: string
  enviado_em: string
  motivo: string
  dias_ate_a_purga: number
}

const ADMIN = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['administrador'], permissoes: ['decupagem.ver', 'lixeira.gerir'] }

const itens = (): Item[] => [
  { tipo: 'video', id: 'j1', nome: 'TV Fama 21/10/2026.mp4', enviado_por: 'ana@redetv.com.br', enviado_em: '2026-10-28T17:02:00Z', motivo: 'duplicado', dias_ate_a_purga: 26 },
  { tipo: 'pessoa', id: 'p1', nome: 'Sabrina S.', enviado_por: 'rui@redetv.com.br', enviado_em: '2026-10-27T12:40:00Z', motivo: 'fundida', dias_ate_a_purga: 1 },
  { tipo: 'marca', id: 'm1', nome: 'Marca Z', enviado_por: 'rui@redetv.com.br', enviado_em: '2026-10-20T12:40:00Z', motivo: 'errada', dias_ate_a_purga: 0 },
]

const IMPACTO_DO_VIDEO = {
  decupagem: 1,
  correcoes: 37,
  arquivos: { copia_limpa: 1, proxy: 1, quadros: 1240 },
  outros_jobs: [{ id: 'j2', nome: 'outro.mp4', enviado_por: 'sistema-x' }],
}

let lista = itens()
let login = false
const chamadas: { caminho: string; corpo: unknown }[] = []

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(ADMIN)),
  http.get('/v1/admin/lixeira', () => HttpResponse.json(lista)),
  http.get('/v1/admin/lixeira/videos/:id/impacto', () => HttpResponse.json(IMPACTO_DO_VIDEO)),
  http.get('/v1/admin/lixeira/pessoas/:id/impacto', () =>
    HttpResponse.json({ aparicoes_que_perdem_o_nome: 4, fotos_apagadas: 3 }),
  ),
  http.post('/v1/admin/lixeira/:tipo/:id/restaurar', ({ params }) => {
    chamadas.push({ caminho: `${String(params.tipo)}/${String(params.id)}/restaurar`, corpo: null })
    lista = lista.filter((i) => i.id !== params.id)
    return HttpResponse.json({ id: params.id, nome: 'x' })
  }),
  http.post('/v1/admin/lixeira/:tipo/:id/purgar', async ({ params, request }) => {
    const corpo = await request.json()
    chamadas.push({ caminho: `${String(params.tipo)}/${String(params.id)}/purgar`, corpo })
    if (login) return HttpResponse.json({ detail: 'login_recente_exigido' }, { status: 403 })
    lista = lista.filter((i) => i.id !== params.id)
    return HttpResponse.json({ id: params.id, nome: 'x' })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  sessionStorage.clear()
  servidor.resetHandlers()
  lista = itens()
  login = false
  chamadas.length = 0
  cleanup()
})
afterAll(() => servidor.close())

function autenticador() {
  return new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
}

async function abrir(auth = autenticador()) {
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/admin/lixeira')
  render(<App autenticador={auth} />)
}

async function linhaDe(nome: string) {
  const tabela = await screen.findByRole('table', { name: 'Lixeira' })
  return within(tabela).getByRole('row', { name: new RegExp(nome.replace('.', '\\.')) })
}

test('a tabela mostra item, tipo, quem, quando, a purga em palavras e o motivo', async () => {
  await abrir()
  const v = await linhaDe('TV Fama')
  expect(within(v).getByText('Vídeo')).toBeTruthy()
  expect(within(v).getByText('ana@redetv.com.br')).toBeTruthy()
  expect(within(v).getByText('em 26 dias')).toBeTruthy()
  expect(within(v).getByText('duplicado')).toBeTruthy()
  expect(within(await linhaDe('Sabrina')).getByText('em 1 dia')).toBeTruthy()
  expect(within(await linhaDe('Marca Z')).getByText('hoje')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Lixeira' }).getAttribute('href')).toBe('/admin/lixeira')
})

test('o filtro por tipo traz Tudo e os tipos que a API devolveu', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await linhaDe('Sabrina')
  const tipo = screen.getByRole('combobox', { name: 'Tipo' })
  const opcoes = within(tipo).getAllByRole('option').map((o) => o.textContent)
  expect(opcoes).toEqual(['Tudo', 'Vídeo', 'Pessoa', 'Marca'])
  await usuario.selectOptions(tipo, 'Pessoa')
  expect(screen.queryByRole('row', { name: /TV Fama/ })).toBeNull()
  expect(await linhaDe('Sabrina')).toBeTruthy()
})

test('lixeira vazia diz que está vazia', async () => {
  lista = []
  await abrir()
  expect(await screen.findByText('A lixeira está vazia.')).toBeTruthy()
})

test('restaurar pede confirmação na própria linha', async () => {
  const usuario = userEvent.setup()
  await abrir()
  const linha = await linhaDe('Sabrina')
  await usuario.click(within(linha).getByRole('button', { name: /^Restaurar/ }))
  expect(chamadas).toEqual([])
  await usuario.click(await screen.findByRole('button', { name: 'Confirmar restauração' }))
  expect(await screen.findByText(/Sabrina S\. voltou/)).toBeTruthy()
  expect(chamadas).toEqual([{ caminho: 'pessoas/p1/restaurar', corpo: null }])
  expect(screen.queryByRole('row', { name: /Sabrina/ })).toBeNull()
})

test('Purgar só habilita com o nome exato e mostra o impacto', async () => {
  const usuario = userEvent.setup()
  await abrir()
  const linha = await linhaDe('Sabrina')
  await usuario.click(within(linha).getByRole('button', { name: /^Purgar agora/ }))
  const dialogo = await screen.findByRole('dialog')
  expect(await within(dialogo).findByText(/3 fotos de rosto/)).toBeTruthy()
  const botao = within(dialogo).getByRole('button', { name: 'Purgar' }) as HTMLButtonElement
  expect(botao.disabled).toBe(true)
  const campo = within(dialogo).getByLabelText(/Digite o nome/)
  await usuario.type(campo, 'sabrina s.')
  expect(botao.disabled).toBe(true)
  await usuario.clear(campo)
  await usuario.type(campo, 'Sabrina S.')
  expect(botao.disabled).toBe(false)
  await usuario.click(botao)
  expect(await screen.findByText('Sabrina S. saiu de vez da lixeira.')).toBeTruthy()
  expect(chamadas[0]).toEqual({ caminho: 'pessoas/p1/purgar', corpo: { nome: 'Sabrina S.' } })
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('login_recente_exigido explica, leva ao login e volta ao diálogo da lixeira', async () => {
  const usuario = userEvent.setup()
  login = true
  await abrir()
  const linha = await linhaDe('TV Fama')
  await usuario.click(within(linha).getByRole('button', { name: /^Purgar agora/ }))
  let dialogo = await screen.findByRole('dialog')
  expect(await within(dialogo).findByText(/1\.240 quadros/)).toBeTruthy()
  await usuario.type(within(dialogo).getByLabelText(/Digite o nome/), 'TV Fama 21/10/2026.mp4')
  await usuario.click(within(dialogo).getByRole('button', { name: 'Purgar' }))
  expect(await within(dialogo).findByText(/login recente/i)).toBeTruthy()

  login = false
  await usuario.click(within(dialogo).getByRole('button', { name: 'Entrar de novo' }))
  await usuario.type(await screen.findByLabelText(/^E-mail/), 'ana@redetv.com.br')
  await usuario.type(screen.getByLabelText(/^Senha/), 'senha-forte-1')
  await usuario.click(screen.getByRole('button', { name: 'Entrar' }))
  const campo = await screen.findByLabelText('Código do autenticador')
  await usuario.type(campo, CODIGO_TOTP_FALSO)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar' }))

  expect(location.pathname).toBe('/admin/lixeira')
  dialogo = await screen.findByRole('dialog')
  expect(within(dialogo).getByRole('heading', { name: 'Purgar TV Fama 21/10/2026.mp4' })).toBeTruthy()
})

test('a volta do login avisa quando o item já saiu da lixeira', async () => {
  sessionStorage.setItem('mam:purga-pendente', JSON.stringify({ tipo: 'video', id: 'sumiu' }))
  await abrir()
  expect(await screen.findByText('O item que você ia purgar não está mais na lixeira.')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(sessionStorage.getItem('mam:purga-pendente')).toBeNull()
})
