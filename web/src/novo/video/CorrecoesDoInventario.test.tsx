import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// Corrigir os objetos do plano (#740) no Revisar: o grupo inteiro ou um objeto só.

const CAIXA = { quadro: 'quadros/plano-0-0.jpg', x: 0.1, y: 0.2, largura: 0.3, altura: 0.4 }
const relogio = (id: string, cor: string) => ({ id, nome: 'relógio de parede', categoria: 'decoracao', cor, caixas: [CAIXA], destaque: 2 })

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [],
  pessoas: [],
  planos: [
    { id: 'pl1', ambiente: 'Estúdio', inicio_ms: 0, fim_ms: 30_000, inventario: [relogio('pl1:0', 'branco')] },
    { id: 'pl2', ambiente: 'Externa', inicio_ms: 30_000, fim_ms: 60_000, inventario: [relogio('pl2:0', 'branco'), relogio('pl2:1', 'preto')] },
  ],
  comerciais: [],
  transcricao: [],
  textos_na_tela: [],
  objetos: [],
}

const correcoes: Record<string, unknown>[] = []
let aprovacoesDaRevisao = 0

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => DECUPAGEM,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.post('/v1/jobs/quadros', async ({ request }) => {
    const { quadros } = (await request.json()) as { quadros: { arquivo: string }[] }
    return HttpResponse.json(quadros.map((q) => ({ ...q, url: `https://exemplo.test/${q.arquivo}`, expira_em: '2999-01-01T00:00:00Z' })))
  }),
  http.post('/v1/jobs/j1/revisao/aprovar', () => {
    aprovacoesDaRevisao += 1
    return HttpResponse.json({ indexacao: 'pendente' }, { status: 202 })
  }),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  correcoes.length = 0
  aprovacoesDaRevisao = 0
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

const inspetor = () => within(screen.getByRole('complementary', { name: 'Inspetor' }))

/** Abre a seção Objetos e o grupo do relógio; `revisando` liga o modo de revisão (E). */
async function abrir({ revisando = true } = {}) {
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'] })
  ;(document.activeElement as HTMLElement).blur()
  if (revisando) await usuario.keyboard('e')
  await usuario.click(inspetor().getByRole('button', { name: /^Objetos \d+$/ }))
  await usuario.click(await inspetor().findByRole('button', { name: /^relógio de parede .*2 planos$/ }))
  return usuario
}

test('Não é isto no grupo mostra quantos objetos e planos e grava todos num pedido só', async () => {
  const usuario = await abrir()
  await usuario.click(within(inspetor().getByRole('group', { name: 'Corrigir todos: relógio de parede' })).getByRole('button', { name: 'Não é isto' }))
  expect(await screen.findByText('Estes 3 objetos, em 2 planos, não estão na imagem?')).toBeTruthy()
  await usuario.click(screen.getByRole('button', { name: 'Remover' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'inventario.nao_existe', item_id: '', item_ids: ['pl1:0', 'pl2:0', 'pl2:1'], valor: 'nao_existe', versao: 'v1' })
})

test('a cor de um objeto só vai pelo id dele, e mudar o nome do grupo guarda a cor de cada um', async () => {
  const usuario = await abrir()
  await usuario.click(inspetor().getByRole('button', { name: 'relógio de parede · preto · Externa · 00:30' }))
  await usuario.click(within(inspetor().getByRole('group', { name: 'Corrigir este: relógio de parede' })).getByRole('button', { name: 'Corrigir cor e marca' }))
  const formulario = await screen.findByRole('form', { name: 'Corrigir cor e marca de 1 objeto, em 1 plano' })
  await usuario.selectOptions(within(formulario).getByLabelText('Cor'), 'branco')
  await usuario.click(within(formulario).getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'inventario.cor_marca', item_id: 'pl2:1', valor: JSON.stringify({ cor: 'branco' }) })
  expect(correcoes[0].item_ids).toBeUndefined()

  await usuario.click(within(inspetor().getByRole('group', { name: 'Corrigir todos: relógio de parede' })).getByRole('button', { name: 'Corrigir nome' }))
  const nome = await screen.findByRole('form', { name: 'Corrigir nome de 3 objetos, em 2 planos' })
  const campo = within(nome).getByLabelText('Nome')
  await usuario.clear(campo)
  await usuario.type(campo, 'relógio')
  await usuario.click(within(nome).getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(correcoes).toHaveLength(2))
  expect(correcoes[1]).toMatchObject({
    tipo: 'inventario.nome',
    item_ids: ['pl1:0', 'pl2:0', 'pl2:1'],
    valor: JSON.stringify({ nome: 'relógio', categoria: 'decoracao' }),
  })
}, 15_000)

test('fora do Revisar, os objetos do plano não têm botões de correção', async () => {
  const usuario = await abrir({ revisando: false })
  await usuario.click(inspetor().getByRole('button', { name: 'relógio de parede · preto · Externa · 00:30' }))
  expect(await inspetor().findByTestId('caixa-do-objeto')).toBeTruthy()
  expect(inspetor().queryByRole('button', { name: 'Não é isto' })).toBeNull()
  expect(inspetor().queryByRole('group', { name: /^Corrigir todos/ })).toBeNull()
})

test('recolher a seção Objetos descarta a correção aberta do grupo, que não trava o Aprovar Revisão', async () => {
  const usuario = await abrir()
  await usuario.click(within(inspetor().getByRole('group', { name: 'Corrigir todos: relógio de parede' })).getByRole('button', { name: 'Corrigir nome' }))
  await screen.findByRole('form', { name: 'Corrigir nome de 3 objetos, em 2 planos' })

  await usuario.click(inspetor().getByRole('button', { name: /^Objetos \d+$/ }))
  await usuario.click(inspetor().getByRole('button', { name: /^Objetos \d+$/ }))
  expect(screen.queryByRole('form')).toBeNull()

  await usuario.click(screen.getByRole('button', { name: 'Aprovar Revisão' }))
  await waitFor(() => expect(aprovacoesDaRevisao).toBe(1))
})
