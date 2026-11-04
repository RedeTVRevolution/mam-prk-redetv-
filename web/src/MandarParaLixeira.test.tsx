import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'

const job = (id: string, nome: string, estado: string) => ({
  id,
  nome,
  estado,
  codigo_falha: null,
  duracao_s: null,
  programa: null,
  data_exibicao: null,
  enviado_por: { tipo: 'pessoa', nome: 'ana@redetv.com.br' },
  criado_em: '2026-10-29T15:00:00Z',
  atualizado_em: '2026-10-29T15:00:00Z',
})

let eu = { uid: 'u1', email: 'ana@redetv.com.br', papeis: [], permissoes: ['decupagem.ver', 'lixeira.gerir'] }
let jobs = [job('j1', 'TV Fama.mp4', 'concluido'), job('j2', 'andando.mp4', 'processando')]
let outros: { id: string; nome: string; enviado_por: string }[] = []
const envios: unknown[] = []

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json(eu)),
  http.get('/v1/jobs', () => HttpResponse.json(jobs)),
  http.get('/v1/programas', () => HttpResponse.json([])),
  http.get('/v1/admin/lixeira/videos/:id/impacto', () =>
    HttpResponse.json({ decupagem: 1, correcoes: 37, arquivos: { copia_limpa: 1, proxy: 1, quadros: 1240 }, outros_jobs: outros }),
  ),
  http.post('/v1/admin/lixeira/videos/:id', async ({ params, request }) => {
    envios.push({ id: params.id, corpo: await request.json() })
    jobs = jobs.filter((j) => j.id !== params.id)
    return HttpResponse.json({}, { status: 201 })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  eu = { uid: 'u1', email: 'ana@redetv.com.br', papeis: [], permissoes: ['decupagem.ver', 'lixeira.gerir'] }
  jobs = [job('j1', 'TV Fama.mp4', 'concluido'), job('j2', 'andando.mp4', 'processando')]
  outros = []
  envios.length = 0
  cleanup()
})
afterAll(() => servidor.close())

async function abrir() {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/acervo')
  render(<App autenticador={auth} />)
}

test('o diálogo mostra o impacto, exige o motivo e manda o vídeo para a lixeira', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(await screen.findByRole('button', { name: 'Ações de TV Fama.mp4' }))
  await usuario.click(await screen.findByRole('menuitem', { name: /Mandar para a lixeira/ }))
  const dialogo = await screen.findByRole('dialog')
  expect(
    await within(dialogo).findByText(
      '1 vídeo, 1 decupagem, 37 correções, 1 cópia limpa, 1 proxy de reprodução, 1.240 quadros-chave. O arquivo original no storage da RedeTV não é tocado.',
    ),
  ).toBeTruthy()
  const botao = within(dialogo).getByRole('button', { name: 'Mandar para a lixeira' }) as HTMLButtonElement
  expect(botao.disabled).toBe(true)
  await usuario.type(within(dialogo).getByLabelText(/Motivo/), '   ')
  expect(botao.disabled).toBe(true)
  await usuario.type(within(dialogo).getByLabelText(/Motivo/), 'duplicado')
  await usuario.click(botao)
  expect(envios).toEqual([{ id: 'j1', corpo: { motivo: 'duplicado' } }])
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(await screen.findByText('TV Fama.mp4 foi para a lixeira.')).toBeTruthy()
  await waitFor(() => expect(screen.queryByRole('link', { name: 'TV Fama.mp4' })).toBeNull())
})

test('avisa quando outro envio usa o mesmo processamento', async () => {
  outros = [{ id: 'j3', nome: 'x.mp4', enviado_por: 'sistema-x' }]
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(await screen.findByRole('button', { name: 'Ações de TV Fama.mp4' }))
  await usuario.click(await screen.findByRole('menuitem', { name: /Mandar para a lixeira/ }))
  expect(await screen.findByText('Este arquivo também foi enviado por sistema-x; a decupagem continua para ele.')).toBeTruthy()
})

test('sem lixeira.gerir não há menu; vídeo em andamento não vai para a lixeira', async () => {
  eu = { ...eu, permissoes: ['decupagem.ver'] }
  await abrir()
  await screen.findByText('andando.mp4')
  expect(screen.queryByRole('button', { name: /^Ações de/ })).toBeNull()
  cleanup()
  eu = { ...eu, permissoes: ['decupagem.ver', 'lixeira.gerir'] }
  await abrir()
  await screen.findByText('andando.mp4')
  expect(screen.queryByRole('button', { name: 'Ações de andando.mp4' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Ações de TV Fama.mp4' })).toBeTruthy()
})

test('sem o impacto calculado, não manda para a lixeira', async () => {
  servidor.use(http.get('/v1/admin/lixeira/videos/:id/impacto', () => HttpResponse.json({ detail: 'x' }, { status: 500 })))
  const usuario = userEvent.setup()
  await abrir()
  await usuario.click(await screen.findByRole('button', { name: 'Ações de TV Fama.mp4' }))
  await usuario.click(await screen.findByRole('menuitem', { name: /Mandar para a lixeira/ }))
  const dialogo = await screen.findByRole('dialog')
  expect(await within(dialogo).findByText(/calcular o que vai junto/)).toBeTruthy()
  await usuario.type(within(dialogo).getByLabelText(/Motivo/), 'duplicado{Enter}')
  expect((within(dialogo).getByRole('button', { name: 'Mandar para a lixeira' }) as HTMLButtonElement).disabled).toBe(true)
  expect(envios).toEqual([])
})
