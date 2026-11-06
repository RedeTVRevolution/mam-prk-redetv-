import { QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import type { Job } from '../../jobs.ts'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { MandarParaLixeira } from './MandarParaLixeira.tsx'
import { podeIrParaALixeira, podeReprocessar } from './regras.ts'
import { Reprocessar } from './Reprocessar.tsx'

let outros: { id: string; nome: string; enviado_por: string }[] = []
const envios: unknown[] = []
const reprocessos: unknown[] = []

const servidor = setupServer(
  http.get('/v1/admin/lixeira/videos/:id/impacto', () =>
    HttpResponse.json({ decupagem: 1, correcoes: 37, arquivos: { copia_limpa: 1, proxy: 1, quadros: 1240 }, outros_jobs: outros }),
  ),
  http.post('/v1/admin/lixeira/videos/:id', async ({ params, request }) => {
    envios.push({ id: params.id, corpo: await request.json() })
    return HttpResponse.json({}, { status: 201 })
  }),
  http.post('/v1/jobs/:id/reprocessar', async ({ request }) => {
    reprocessos.push(await request.json())
    return HttpResponse.json({ id: 'j1', nome: 'TV Fama.mp4', estado: 'analisando', codigo_falha: null, criado_em: '2026-10-29T15:00:00Z' })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  servidor.resetHandlers()
  outros = []
  envios.length = 0
  reprocessos.length = 0
})
afterAll(() => servidor.close())

const VIDEO = { id: 'j1', nome: 'TV Fama.mp4' }

async function comApi(conteudo: React.ReactNode) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(
    <QueryClientProvider client={criarClienteDeConsultas()}>
      <ContextoDaApi.Provider value={criarClienteDaApi(auth, () => {})}>{conteudo}</ContextoDaApi.Provider>
    </QueryClientProvider>,
  )
}

test('a lixeira mostra o impacto, exige o motivo e manda o vídeo', async () => {
  const usuario = userEvent.setup()
  const aoMandar = vi.fn()
  await comApi(<MandarParaLixeira video={VIDEO} aoFechar={() => {}} aoMandar={aoMandar} />)
  const dialogo = within(await screen.findByRole('dialog'))
  expect(
    await dialogo.findByText(
      '1 vídeo, 1 decupagem, 37 correções, 1 cópia limpa, 1 proxy de reprodução, 1.240 quadros-chave. O arquivo original no storage da RedeTV não é tocado.',
    ),
  ).toBeTruthy()
  const botao = dialogo.getByRole('button', { name: 'Mandar para a lixeira' }) as HTMLButtonElement
  expect(botao.disabled).toBe(true)
  await usuario.type(dialogo.getByLabelText(/Motivo/), '   ')
  expect(botao.disabled).toBe(true)
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'duplicado')
  await usuario.click(botao)

  await waitFor(() => expect(aoMandar).toHaveBeenCalledWith(VIDEO))
  expect(envios).toEqual([{ id: 'j1', corpo: { motivo: 'duplicado' } }])
})

test('a lixeira avisa quando outro envio usa o mesmo processamento', async () => {
  outros = [{ id: 'j3', nome: 'x.mp4', enviado_por: 'sistema-x' }]
  await comApi(<MandarParaLixeira video={VIDEO} aoFechar={() => {}} aoMandar={() => {}} />)
  expect(await screen.findByText('Este arquivo também foi enviado por sistema-x; a decupagem continua para ele.')).toBeTruthy()
})

test('sem o impacto calculado, não manda para a lixeira', async () => {
  servidor.use(http.get('/v1/admin/lixeira/videos/:id/impacto', () => HttpResponse.json({ detail: 'x' }, { status: 500 })))
  const usuario = userEvent.setup()
  await comApi(<MandarParaLixeira video={VIDEO} aoFechar={() => {}} aoMandar={() => {}} />)
  const dialogo = within(await screen.findByRole('dialog'))
  expect(await dialogo.findByText(/calcular o que vai junto/)).toBeTruthy()
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'duplicado{Enter}')
  expect((dialogo.getByRole('button', { name: 'Mandar para a lixeira' }) as HTMLButtonElement).disabled).toBe(true)
  expect(envios).toEqual([])
})

test('a falha ao mandar fica no diálogo, em português', async () => {
  servidor.use(http.post('/v1/admin/lixeira/videos/:id', () => new HttpResponse(null, { status: 403 })))
  const usuario = userEvent.setup()
  const aoMandar = vi.fn()
  await comApi(<MandarParaLixeira video={VIDEO} aoFechar={() => {}} aoMandar={aoMandar} />)
  const dialogo = within(await screen.findByRole('dialog'))
  await dialogo.findByText(/^1 vídeo/)
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'duplicado{Enter}')

  expect(await dialogo.findByText('Você não tem permissão para isto.')).toBeTruthy()
  expect(aoMandar).not.toHaveBeenCalled()
})

test('quem pode mandar para a lixeira e reprocessar', () => {
  const job = (estado: string, extra: Partial<Job> = {}) => ({ id: 'a', nome: 'a', estado, codigo_falha: null, criado_em: '', ...extra }) as Job
  expect(podeIrParaALixeira(job('concluido'), ['lixeira.gerir'])).toBe(true)
  expect(podeIrParaALixeira(job('falhou'), ['lixeira.gerir'])).toBe(true)
  expect(podeIrParaALixeira(job('analisando'), ['lixeira.gerir'])).toBe(false)
  expect(podeIrParaALixeira(job('concluido'), ['decupagem.ver'])).toBe(false)
  expect(podeReprocessar(job('concluido'), ['video.reprocessar_etapa'])).toBe(true)
  expect(podeReprocessar(job('falhou'), ['video.reprocessar_etapa'])).toBe(false)
  expect(podeReprocessar(job('concluido', { etapa_atual: 'identificacao' }), ['video.reprocessar_etapa'])).toBe(false)
  expect(podeReprocessar(job('concluido'), ['video.reprocessar'])).toBe(false)
})

test('reprocessar exige o motivo, diz o impacto da etapa e manda a etapa escolhida', async () => {
  const usuario = userEvent.setup()
  const aoReprocessar = vi.fn()
  await comApi(<Reprocessar video={VIDEO} aoFechar={() => {}} aoReprocessar={aoReprocessar} />)
  const dialogo = within(await screen.findByRole('dialog'))
  expect(dialogo.getByText(/A Decupagem fica indisponível até a nova análise terminar/)).toBeTruthy()
  const botao = dialogo.getByRole('button', { name: 'Reprocessar' }) as HTMLButtonElement
  expect(botao.disabled).toBe(true)

  await usuario.click(dialogo.getByRole('radio', { name: /Quadros-chave/ }))
  expect(dialogo.getByText(/a Decupagem continua disponível/)).toBeTruthy()
  await usuario.type(dialogo.getByLabelText(/Motivo/), '  ')
  expect(botao.disabled).toBe(true)
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'quadros escuros')
  await usuario.click(botao)

  await waitFor(() => expect(aoReprocessar).toHaveBeenCalledWith(expect.objectContaining({ estado: 'analisando' }), 'quadros_chave'))
  expect(reprocessos).toEqual([{ etapa: 'quadros_chave', motivo: 'quadros escuros' }])
})

test('reprocessar mostra a recusa da API como veio, e a falha genérica com o código', async () => {
  servidor.use(http.post('/v1/jobs/:id/reprocessar', () => HttpResponse.json({ detail: 'O vídeo já está sendo processado' }, { status: 409 })))
  const usuario = userEvent.setup()
  await comApi(<Reprocessar video={VIDEO} aoFechar={() => {}} aoReprocessar={() => {}} />)
  const dialogo = within(await screen.findByRole('dialog'))
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'de novo')
  await usuario.click(dialogo.getByRole('button', { name: 'Reprocessar' }))
  expect(await dialogo.findByText('O vídeo já está sendo processado')).toBeTruthy()

  servidor.use(http.post('/v1/jobs/:id/reprocessar', () => new HttpResponse(null, { status: 503 })))
  await usuario.click(dialogo.getByRole('button', { name: 'Reprocessar' }))
  expect(await dialogo.findByText('Não foi possível reprocessar. Tente de novo em instantes.')).toBeTruthy()
  expect(dialogo.getByText('Código para o suporte: http_503')).toBeTruthy()
})
