import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from '../App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'

interface Chave {
  id: string
  sistema: string
  escopos: string[]
  criada_em: string
  revogada_em: string | null
}

const GESTOR = { uid: 'u1', email: 'ana@redetv.com.br', papeis: ['administrador'], permissoes: ['decupagem.ver', 'chaves.gerir'] }
const CHAVE_EM_TEXTO = 'rtv_segredo-que-so-aparece-uma-vez'

const chaves = (): Chave[] => [
  { id: 'k1', sistema: 'sistema-x', escopos: ['ler'], criada_em: '2026-10-01T12:00:00Z', revogada_em: null },
  { id: 'k2', sistema: 'sistema-y', escopos: ['criar', 'ler'], criada_em: '2026-09-01T12:00:00Z', revogada_em: '2026-10-28T15:00:00Z' },
]

let eu = GESTOR
let lista = chaves()
const chamadas: { caminho: string; corpo: unknown }[] = []

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(eu)),
  http.get('/v1/admin/chaves', () => HttpResponse.json(lista)),
  http.post('/v1/admin/chaves', async ({ request }) => {
    const corpo = (await request.json()) as { sistema: string; escopos: string[] }
    chamadas.push({ caminho: '/v1/admin/chaves', corpo })
    const nova: Chave = { id: 'k9', ...corpo, criada_em: '2026-11-03T12:00:00Z', revogada_em: null }
    lista = [nova, ...lista]
    return HttpResponse.json({ ...nova, chave: CHAVE_EM_TEXTO }, { status: 201 })
  }),
  http.post('/v1/admin/chaves/:id/revogar', ({ params }) => {
    chamadas.push({ caminho: `/v1/admin/chaves/${String(params.id)}/revogar`, corpo: null })
    return HttpResponse.json({ ...lista.find((c) => c.id === params.id)!, revogada_em: '2026-11-03T15:00:00Z' })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  eu = GESTOR
  lista = chaves()
  chamadas.length = 0
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

async function linhaDe(sistema: string) {
  const tabela = await screen.findByRole('table', { name: 'Chaves' })
  return within(tabela).getByRole('row', { name: new RegExp(sistema) })
}

test('a aba Sistemas e chaves lista sistema, escopos, id, data e situação; a revogada fica', async () => {
  await abrir('/admin/chaves')
  const x = await linhaDe('sistema-x')
  expect(within(x).getByText('ler')).toBeTruthy()
  expect(within(x).getByText('k1')).toBeTruthy()
  expect(within(x).getByText('01/10/2026')).toBeTruthy()
  expect(within(x).getByText('Ativa')).toBeTruthy()
  const y = await linhaDe('sistema-y')
  expect(within(y).getByText('Revogada em 28/10/2026')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Sistemas e chaves' }).getAttribute('href')).toBe('/admin/chaves')
})

test('sem chaves.gerir a aba não existe', async () => {
  eu = { ...GESTOR, permissoes: ['decupagem.ver'] }
  await abrir('/admin/chaves')
  expect(await screen.findByText('Página não encontrada.')).toBeTruthy()
})

test('emitir mostra a chave uma vez e depois de "Já guardei" ela não está em lugar nenhum', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/chaves')
  await linhaDe('sistema-x')
  await usuario.click(screen.getByRole('button', { name: 'Emitir chave' }))
  const dialogo = await screen.findByRole('dialog')
  expect(within(dialogo).getByText(/cria vídeos para decupar/)).toBeTruthy()
  await usuario.type(within(dialogo).getByLabelText('Sistema'), 'sistema-z')
  await usuario.click(within(dialogo).getByRole('checkbox', { name: /^criar/ }))
  await usuario.click(within(dialogo).getByRole('button', { name: 'Emitir chave' }))

  const campo = (await screen.findByLabelText('Chave')) as HTMLInputElement
  expect(campo.readOnly).toBe(true)
  expect(campo.value).toBe(CHAVE_EM_TEXTO)
  expect(screen.getByText('Guarde agora: ela não será mostrada de novo.')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Copiar' })).toBeTruthy()
  expect(chamadas[0]?.corpo).toEqual({ sistema: 'sistema-z', escopos: ['criar'] })

  // Só "Já guardei" fecha o diálogo.
  await usuario.keyboard('{Escape}')
  expect(screen.getByLabelText('Chave')).toBeTruthy()

  await usuario.click(screen.getByRole('button', { name: 'Já guardei' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.body.innerHTML).not.toContain(CHAVE_EM_TEXTO)
  expect(screen.queryByDisplayValue(CHAVE_EM_TEXTO)).toBeNull()
  const nova = await linhaDe('sistema-z')
  expect(within(nova).getByText('Ativa')).toBeTruthy()
})

test('enquanto a emissão está no ar o diálogo não fecha, e a chave aparece ao chegar', async () => {
  let responder: () => void = () => {}
  const resposta = new Promise<void>((r) => (responder = r))
  servidor.use(
    http.post('/v1/admin/chaves', async () => {
      await resposta
      return HttpResponse.json({ ...chaves()[0]!, id: 'k9', sistema: 'sistema-z', chave: CHAVE_EM_TEXTO }, { status: 201 })
    }),
  )
  const usuario = userEvent.setup()
  await abrir('/admin/chaves')
  await linhaDe('sistema-x')
  await usuario.click(screen.getByRole('button', { name: 'Emitir chave' }))
  const dialogo = await screen.findByRole('dialog')
  await usuario.type(within(dialogo).getByLabelText('Sistema'), 'sistema-z')
  await usuario.click(within(dialogo).getByRole('checkbox', { name: /^ler/ }))
  await usuario.click(within(dialogo).getByRole('button', { name: 'Emitir chave' }))

  await usuario.keyboard('{Escape}')
  expect(screen.getByRole('dialog')).toBeTruthy()
  expect((within(dialogo).getByRole('button', { name: 'Cancelar' }) as HTMLButtonElement).disabled).toBe(true)

  responder()
  expect(((await screen.findByLabelText('Chave')) as HTMLInputElement).value).toBe(CHAVE_EM_TEXTO)
})

test('revogar pede confirmação na linha, atualiza a situação e mantém a chave na lista', async () => {
  const usuario = userEvent.setup()
  await abrir('/admin/chaves')
  const x = await linhaDe('sistema-x')
  await usuario.click(within(x).getByRole('button', { name: 'Revogar a chave de sistema-x' }))
  expect(screen.getByText('Revogar a chave de sistema-x? Ela para de funcionar na hora.')).toBeTruthy()
  expect(chamadas).toHaveLength(0)
  await usuario.click(screen.getByRole('button', { name: 'Confirmar revogação' }))
  expect(await within(await linhaDe('sistema-x')).findByText('Revogada em 03/11/2026')).toBeTruthy()
  expect(chamadas[0]?.caminho).toBe('/v1/admin/chaves/k1/revogar')
})

test('a lista que ainda vinha do servidor não desfaz a revogação feita no meio', async () => {
  eu = { ...GESTOR, permissoes: [...GESTOR.permissoes, 'aprovacao.definir'] }
  const usuario = userEvent.setup()
  await abrir('/admin/chaves')
  await linhaDe('sistema-x')
  // Ao voltar à aba, o cache mostra a lista e um GET sai de novo; este fica preso até a revogação terminar.
  let soltar: () => void = () => {}
  const preso = new Promise<void>((r) => (soltar = r))
  servidor.use(
    http.get('/v1/admin/aprovacao', () => HttpResponse.json([])),
    http.get('/v1/admin/chaves', async () => {
      const antes = chaves()
      await preso
      return HttpResponse.json(antes)
    }),
  )
  await usuario.click(screen.getByRole('link', { name: 'Regras de aprovação' }))
  await usuario.click(await screen.findByRole('link', { name: 'Sistemas e chaves' }))
  await usuario.click(within(await linhaDe('sistema-x')).getByRole('button', { name: 'Revogar a chave de sistema-x' }))
  await usuario.click(screen.getByRole('button', { name: 'Confirmar revogação' }))
  expect(await within(await linhaDe('sistema-x')).findByText('Revogada em 03/11/2026')).toBeTruthy()
  soltar()
  await new Promise((r) => setTimeout(r, 50))
  expect(within(await linhaDe('sistema-x')).getByText('Revogada em 03/11/2026')).toBeTruthy()
})
