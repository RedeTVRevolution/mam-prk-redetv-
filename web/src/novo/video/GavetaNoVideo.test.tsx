import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { criarClienteDeConsultas } from '../consultas.ts'
import { abrirVideo, botaoDoTopo, rotasDoVideo, simularPlayer, type Usuario } from './abrir-teste.tsx'
import { correcaoDoHistorico, DECUPAGEM } from './curadoria-teste.ts'
import { chaveDoVideo } from './tipos.ts'

// A gaveta dentro da tela do vídeo: o botão Histórico, o salto ao item e o "Refazer à mão".

let historico: object[] = []
let decupagemAtual: object = DECUPAGEM
let fila: object[] = []
const pedidos = { historico: 0, fila: 0 }
/** As decisões que a gaveta enviou (caminho), os pedidos de aprovar a revisão e a resposta retida. */
let decisoes: string[] = []
let aprovacoesDaRevisao = 0
let reterDecisao: Promise<void> | null = null

async function decidir({ request }: { request: Request }) {
  decisoes.push(new URL(request.url).pathname)
  if (reterDecisao) await reterDecisao
  return HttpResponse.json({}, { status: 201 })
}

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 120, cortes_ms: [] }),
    () => decupagemAtual,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => {
    pedidos.historico += 1
    return HttpResponse.json(historico)
  }),
  http.get('/v1/jobs/j1/fila', () => {
    pedidos.fila += 1
    return HttpResponse.json(fila)
  }),
  http.post('/v1/jobs/j1/revisao/aprovar', () => {
    aprovacoesDaRevisao += 1
    return HttpResponse.json({ indexacao: 'pendente' }, { status: 202 })
  }),
  // Quem aprova correções também vê as comparações de passadas.
  http.get('/v1/jobs/j1/passadas', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/correcoes/:id/:acao', decidir),
  http.post('/v1/jobs/j1/fila/:id/:acao', decidir),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
  historico = []
  fila = []
  decupagemAtual = DECUPAGEM
  pedidos.historico = 0
  pedidos.fila = 0
  decisoes = []
  aprovacoesDaRevisao = 0
  reterDecisao = null
})
afterAll(() => servidor.close())

const gaveta = () => within(screen.getByRole('complementary', { name: 'Correções do vídeo' }))

const FILA_ESTRUTURAL = {
  id: 'f1',
  tipo: 'pauta.juntar',
  autor_email: 'bia@redetv.com.br',
  criada_em: '2026-10-30T15:00:00Z',
  motivo: 'pautas juntadas pelo editor',
  antes: null,
  depois: '{"ids":["x1","x2"],"titulo":"Eleição"}',
  antes_legivel: 'Eleição + Clima',
  depois_legivel: 'Eleição',
  candidatos: [],
}

async function abrir(permissoes = ['decupagem.editar']) {
  const usuario = userEvent.setup()
  const player = await abrirVideo({ permissoes })
  ;(document.activeElement as HTMLElement).blur()
  return { usuario, player }
}

test('o botão Histórico abre a gaveta no lugar do inspetor, e a contagem vem da fila e das pendentes', async () => {
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br', 'pendente')]
  const { usuario } = await abrir(['decupagem.editar', 'correcao.aprovar'])

  // A contagem faz parte do nome acessível do botão, não só do selo.
  const botao = await screen.findByRole('button', { name: 'Histórico, 1 a resolver' })
  expect(botao.textContent).toBe('1')
  await usuario.click(botao)

  expect(botao.getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()
  expect(screen.getByLabelText('Player')).toBeTruthy()
  expect(await gaveta().findByRole('tab', { name: 'Aprovação (1)' })).toBeTruthy()

  await usuario.click(gaveta().getByRole('button', { name: 'Fechar' }))
  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
  expect(screen.getByRole('complementary', { name: 'Inspetor' })).toBeTruthy()
})

test('fechar a gaveta pelo botão ou pelo Esc devolve o foco ao botão Histórico', async () => {
  const { usuario } = await abrir()
  const botao = await screen.findByRole('button', { name: /^Histórico/ })

  await usuario.click(botao)
  await usuario.click(gaveta().getByRole('button', { name: 'Fechar' }))
  expect(document.activeElement).toBe(botao)

  ;(document.activeElement as HTMLElement).blur()
  await usuario.click(botao)
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
  expect(document.activeElement).toBe(botao)
})

test('clicar numa correção da gaveta salta o player ao item', async () => {
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br')]
  const { usuario, player } = await abrir()

  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await usuario.click(await gaveta().findByRole('button', { name: /^Saltar ao item/ }))

  expect(player.currentTime).toBe(10)
})

test('sem decupagem.editar não há botão Histórico nem pedido de histórico ou fila', async () => {
  await abrir(['decupagem.ver'])

  expect(screen.queryByRole('button', { name: /^Histórico/ })).toBeNull()
  expect(pedidos).toEqual({ historico: 0, fila: 0 })
})

test('com a gaveta aberta, as setas e o Enter são dela', async () => {
  const comercial = { ...correcaoDoHistorico('c2', 'bia@redetv.com.br', 'ativa', 'comercial.marca'), item_id: 'c1', ancora: { versao: 'v1', tipo_do_item: 'comercial' } }
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br'), comercial]
  const { usuario, player } = await abrir()
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await gaveta().findAllByRole('button', { name: /^Saltar ao item/ })

  // O foco no corpo da página: o Enter não é de nenhum botão.
  await usuario.click(document.body)
  await usuario.keyboard('{ArrowDown}{Enter}')

  // Um só salto, ao item da segunda correção (o comercial, em 40 s).
  await waitFor(() => expect(player.currentTime).toBe(40))
})

test('Refazer à mão, fora do modo de revisão, liga o modo e deixa marcar as pautas', async () => {
  fila = [FILA_ESTRUTURAL]
  const { usuario } = await abrir()
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await usuario.click(await gaveta().findByRole('tab', { name: /Fila de revisão/ }))

  await usuario.click(await gaveta().findByRole('button', { name: 'Refazer à mão' }))

  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
  expect(await screen.findByText('Marque as pautas (M) e junte (U), ou divida (D).')).toBeTruthy()
  await usuario.click(await screen.findByRole('button', { name: 'Marcar Eleição para juntar' }))
  expect(await screen.findByText('1 pauta marcada para juntar')).toBeTruthy()
})

test('Refazer à mão com o inspetor recolhido traz a lista de pautas de volta', async () => {
  fila = [FILA_ESTRUTURAL]
  const { usuario } = await abrir()
  await usuario.click(within(screen.getByRole('complementary', { name: 'Inspetor' })).getByRole('button', { name: 'Recolher o inspetor' }))
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await usuario.click(await gaveta().findByRole('tab', { name: /Fila de revisão/ }))

  await usuario.click(await gaveta().findByRole('button', { name: 'Refazer à mão' }))

  expect(await screen.findByRole('button', { name: 'Marcar Eleição para juntar' })).toBeTruthy()
})

test('o F2 com a gaveta aberta traz o formulário de volta ao inspetor', async () => {
  const { usuario } = await abrir()
  await usuario.keyboard('e')
  const secao = within(screen.getByRole('complementary', { name: 'Inspetor' })).getByRole('button', { name: /^Pautas \d+$/ })
  if (secao.getAttribute('aria-expanded') !== 'true') await usuario.click(secao)
  await usuario.click(await screen.findByRole('button', { name: /^Eleição, / }))
  await usuario.keyboard('{Escape}')
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  expect(screen.queryByRole('complementary', { name: 'Inspetor' })).toBeNull()
  ;(document.activeElement as HTMLElement).blur()

  await usuario.keyboard('{F2}')

  expect(await screen.findByRole('form', { name: 'Corrigir Eleição' })).toBeTruthy()
  expect(screen.queryByRole('complementary', { name: 'Correções do vídeo' })).toBeNull()
})

test('um histórico longo mostra 100 correções por vez, e "Mostrar mais" acrescenta o resto', async () => {
  historico = Array.from({ length: 130 }, (_, i) => ({ ...correcaoDoHistorico(`c${i}`, 'bia@redetv.com.br'), depois_legivel: `Pessoa ${i}` }))
  const { usuario } = await abrir()

  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await gaveta().findAllByRole('button', { name: /^Saltar ao item/ })
  expect(gaveta().getAllByRole('button', { name: /^Saltar ao item/ })).toHaveLength(100)

  await usuario.click(gaveta().getByRole('button', { name: 'Mostrar mais 30' }))

  expect(gaveta().getAllByRole('button', { name: /^Saltar ao item/ })).toHaveLength(130)
  expect(gaveta().queryByRole('button', { name: /^Mostrar mais/ })).toBeNull()
})

test('a seta para baixo além das 100 primeiras mostra a seguinte', async () => {
  historico = Array.from({ length: 130 }, (_, i) => ({ ...correcaoDoHistorico(`c${i}`, 'bia@redetv.com.br'), depois_legivel: `Pessoa ${i}` }))
  const { usuario } = await abrir()
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await gaveta().findAllByRole('button', { name: /^Saltar ao item/ })

  for (let i = 0; i < 100; i++) await usuario.keyboard('{ArrowDown}')

  expect(gaveta().getAllByRole('button', { name: /^Saltar ao item/ })).toHaveLength(101)
  // 100 teclas pelo userEvent passam de 5 s no runner do CI.
}, 20_000)

test('uma decupagem nova (reprocessar) traz o histórico e a fila de novo; a mesma decupagem recarregada não', async () => {
  const consultas = criarClienteDeConsultas()
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'], consultas })
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await waitFor(() => expect(pedidos).toMatchObject({ historico: 1, fila: 1 }))

  // A mesma versão, recarregada: o histórico e a fila já estão em dia.
  await consultas.invalidateQueries({ queryKey: chaveDoVideo('j1', 'decupagem') })
  await new Promise((r) => setTimeout(r, 100))
  expect(pedidos).toMatchObject({ historico: 1, fila: 1 })

  // A análise nova grava outra versão da decupagem, com a fila nova.
  decupagemAtual = { ...DECUPAGEM, versao_decupagem: 'v2' }
  fila = [{ id: 'f9', tipo: 'pauta.juntar', autor_email: 'bia@redetv.com.br', criada_em: '2026-10-30T15:00:00Z', motivo: 'm', antes: null, depois: '{}', antes_legivel: 'A', depois_legivel: 'B', candidatos: [] }]
  await consultas.invalidateQueries({ queryKey: chaveDoVideo('j1', 'decupagem') })

  await waitFor(() => expect(pedidos).toMatchObject({ historico: 2, fila: 2 }))
  expect(await gaveta().findByRole('tab', { name: 'Fila de revisão (1)' })).toBeTruthy()
})

// #744: enviar uma decisão da gaveta fora do Revisar liga o modo; aprovar a revisão espera a decisão em curso.

const FILA_COM_CANDIDATO = {
  ...FILA_ESTRUTURAL,
  id: 'f2',
  tipo: 'pessoa.renomear',
  antes: 'Ana Souza',
  depois: 'Ana Souza Lima',
  antes_legivel: 'Ana Souza',
  depois_legivel: 'Ana Souza Lima',
  candidatos: [{ item_id: 'p7', nome: 'Carla Dias', inicio_ms: 4_000, fim_ms: 18_000 }],
}

/** Uma correção em vigor (c1), uma pendente (c2) e uma na fila com candidato (f2); a gaveta aberta na aba. */
async function abrirGaveta(aba: RegExp) {
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br'), correcaoDoHistorico('c2', 'bia@redetv.com.br', 'pendente')]
  fila = [FILA_COM_CANDIDATO]
  const { usuario, player } = await abrir(['decupagem.editar', 'correcao.aprovar'])
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await usuario.click(await gaveta().findByRole('tab', { name: aba }))
  return { usuario, player }
}

const DECISOES: [string, RegExp, (u: Usuario) => Promise<void>, string][] = [
  ['Desfazer', /^Histórico/, (u) => u.click(gaveta().getAllByRole('button', { name: 'Desfazer' })[0]), '/v1/jobs/j1/correcoes/c1/desfazer'],
  [
    'Reaplicar',
    /Fila de revisão/,
    async (u) => {
      await u.selectOptions(gaveta().getByRole('combobox', { name: 'Candidato' }), 'p7')
      await u.click(gaveta().getByRole('button', { name: 'Reaplicar' }))
    },
    '/v1/jobs/j1/fila/f2/reaplicar',
  ],
  [
    'confirmar o Descartar',
    /Fila de revisão/,
    async (u) => {
      await u.click(gaveta().getByRole('button', { name: 'Descartar' }))
      await u.click(within(gaveta().getByRole('group', { name: 'Confirmar o descarte' })).getByRole('button', { name: 'Descartar' }))
    },
    '/v1/jobs/j1/fila/f2/descartar',
  ],
  ['Aprovar', /^Aprovação/, (u) => u.click(gaveta().getByRole('button', { name: 'Aprovar' })), '/v1/jobs/j1/correcoes/c2/aprovar'],
  [
    'Recusar pelo botão',
    /^Aprovação/,
    async (u) => {
      await u.click(gaveta().getByRole('button', { name: 'Recusar' }))
      await u.type(gaveta().getByLabelText('Motivo da recusa'), 'não confere')
      await u.click(gaveta().getByRole('button', { name: 'Recusar' }))
    },
    '/v1/jobs/j1/correcoes/c2/recusar',
  ],
  [
    'Recusar pelo Enter',
    /^Aprovação/,
    async (u) => {
      await u.click(gaveta().getByRole('button', { name: 'Recusar' }))
      await u.type(gaveta().getByLabelText('Motivo da recusa'), 'não confere{Enter}')
    },
    '/v1/jobs/j1/correcoes/c2/recusar',
  ],
]

test.each(DECISOES)('fora do Revisar, %s envia a decisão e liga o modo; a gaveta fica na mesma aba', async (_, aba, decidirNaGaveta, caminho) => {
  const { usuario } = await abrirGaveta(aba)
  expect(botaoDoTopo().textContent).toContain('Revisar')

  await decidirNaGaveta(usuario)

  await waitFor(() => expect(decisoes).toEqual([caminho]))
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')
  expect(gaveta().getByRole('tab', { name: aba }).getAttribute('aria-selected')).toBe('true')
  expect(aprovacoesDaRevisao).toBe(0)
})

test('ler, navegar, escolher, abrir confirmações e cancelar não ligam o modo nem enviam decisão', async () => {
  const { usuario, player } = await abrirGaveta(/^Histórico/)
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('{ArrowDown}{ArrowUp}')
  await usuario.click(gaveta().getAllByRole('button', { name: /^Saltar ao item/ })[0])
  expect(player.currentTime).toBe(10)

  await usuario.click(gaveta().getByRole('tab', { name: /Fila de revisão/ }))
  await usuario.selectOptions(gaveta().getByRole('combobox', { name: 'Candidato' }), 'p7')
  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))
  await usuario.click(gaveta().getByRole('button', { name: 'Cancelar' }))
  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))
  gaveta().getByRole('button', { name: 'Cancelar' }).focus()
  await usuario.keyboard('{Escape}')
  expect(gaveta().queryByRole('group', { name: 'Confirmar o descarte' })).toBeNull()

  await usuario.click(gaveta().getByRole('tab', { name: /^Aprovação/ }))
  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.click(gaveta().getByRole('button', { name: 'Cancelar' }))
  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'x{Escape}')
  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), '   {Enter}')
  await new Promise((r) => setTimeout(r, 50))

  expect(decisoes).toEqual([])
  expect(botaoDoTopo().textContent).toContain('Revisar')
  expect(botaoDoTopo().textContent).not.toContain('Aprovar Revisão')
})

test('sem a decupagem na tela (reprocessando), a decisão liga o modo, e aprovar a revisão espera a decupagem', async () => {
  historico = [correcaoDoHistorico('c1', 'bia@redetv.com.br')]
  const consultas = criarClienteDeConsultas()
  const usuario = userEvent.setup()
  await abrirVideo({ permissoes: ['decupagem.editar'], consultas })
  await usuario.click(await screen.findByRole('button', { name: /^Histórico/ }))
  await gaveta().findByRole('button', { name: 'Desfazer' })
  // Como a reprocessagem pela análise: o Job volta a analisar e a decupagem sai da tela até a nova chegar.
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => new Promise<never>(() => {})))
  act(() => {
    consultas.removeQueries({ queryKey: chaveDoVideo('j1', 'decupagem') })
    consultas.setQueryData(chaveDoVideo('j1', 'job'), (j: object) => ({ ...j, estado: 'analisando', etapa_atual: 'analise' }))
  })
  expect(await screen.findByText(/em andamento/)).toBeTruthy()
  // O Job conclui, e o GET da decupagem nova fica pendente.
  act(() => consultas.setQueryData(chaveDoVideo('j1', 'job'), (j: object) => ({ ...j, estado: 'concluido', etapa_atual: null })))
  await waitFor(() => expect(screen.queryByText(/em andamento/)).toBeNull())

  await usuario.click(gaveta().getByRole('button', { name: 'Desfazer' }))

  await waitFor(() => expect(decisoes).toEqual(['/v1/jobs/j1/correcoes/c1/desfazer']))
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')
  // Sem a decupagem não há onde gravar um trecho: as ferramentas dele esperam, como os atalhos I, O e A.
  expect(screen.queryByRole('group', { name: 'Ferramentas do trecho' })).toBeNull()
  await usuario.click(botaoDoTopo())
  expect(await screen.findByText('Espere a decupagem carregar para revisar ou aprovar a revisão.')).toBeTruthy()
  expect(aprovacoesDaRevisao).toBe(0)
})

test('dentro do Revisar, a decisão não muda o modo', async () => {
  const { usuario } = await abrirGaveta(/^Histórico/)
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('e')
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')

  await usuario.click(gaveta().getAllByRole('button', { name: 'Desfazer' })[0])

  await waitFor(() => expect(decisoes).toEqual(['/v1/jobs/j1/correcoes/c1/desfazer']))
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')
  expect(aprovacoesDaRevisao).toBe(0)
})

test('com a decisão retida, Aprovar Revisão (botão e E) espera, mesmo com a gaveta fechada e reaberta', async () => {
  let liberar = () => {}
  reterDecisao = new Promise<void>((r) => (liberar = r))
  const { usuario } = await abrirGaveta(/^Aprovação/)
  await usuario.click(gaveta().getByRole('button', { name: 'Aprovar' }))
  await waitFor(() => expect(decisoes).toEqual(['/v1/jobs/j1/correcoes/c2/aprovar']))

  await usuario.click(gaveta().getByRole('button', { name: 'Fechar' }))
  await usuario.click(screen.getByRole('button', { name: /^Histórico/ }))
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('e')
  expect(await screen.findByText('Espere a correção ser gravada para aprovar a revisão.')).toBeTruthy()
  await usuario.click(botaoDoTopo())
  expect(aprovacoesDaRevisao).toBe(0)
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')

  liberar()
  await waitFor(() => expect(pedidos.historico).toBeGreaterThan(1))
  await usuario.click(botaoDoTopo())
  await waitFor(() => expect(aprovacoesDaRevisao).toBe(1))
  expect(botaoDoTopo().textContent).not.toContain('Aprovar Revisão')
})

test.each([
  ['conflito (409)', 409, 'Essa correção não está mais pendente. O histórico foi recarregado.'],
  ['erro genérico', 500, 'Não foi possível aprovar a correção. Tente de novo em instantes.'],
])('com a decisão falhando por %s, o modo e a aba ficam, o bloqueio sai e nenhuma aprovação vai', async (_, status, aviso) => {
  servidor.use(http.post('/v1/jobs/j1/correcoes/c2/aprovar', () => HttpResponse.json({ detail: 'x' }, { status }), { once: true }))
  const { usuario } = await abrirGaveta(/^Aprovação/)

  await usuario.click(gaveta().getByRole('button', { name: 'Aprovar' }))

  expect(await gaveta().findByText(aviso)).toBeTruthy()
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')
  expect(gaveta().getByRole('tab', { name: /^Aprovação/ }).getAttribute('aria-selected')).toBe('true')
  expect(aprovacoesDaRevisao).toBe(0)

  await usuario.click(botaoDoTopo())
  await waitFor(() => expect(aprovacoesDaRevisao).toBe(1))
})

test('fluxo completo: duas decisões fora do modo, nenhuma aprovação entre elas, e aprovar envia um pedido só', async () => {
  const { usuario } = await abrirGaveta(/^Aprovação/)
  await usuario.click(gaveta().getByRole('button', { name: 'Aprovar' }))
  await waitFor(() => expect(decisoes).toHaveLength(1))
  await usuario.click(gaveta().getByRole('tab', { name: /^Histórico/ }))
  await usuario.click(gaveta().getAllByRole('button', { name: 'Desfazer' })[0])
  await waitFor(() => expect(decisoes).toEqual(['/v1/jobs/j1/correcoes/c2/aprovar', '/v1/jobs/j1/correcoes/c1/desfazer']))
  expect(aprovacoesDaRevisao).toBe(0)
  expect(botaoDoTopo().textContent).toContain('Aprovar Revisão')

  await usuario.click(botaoDoTopo())

  await waitFor(() => expect(aprovacoesDaRevisao).toBe(1))
  await new Promise((r) => setTimeout(r, 50))
  expect(aprovacoesDaRevisao).toBe(1)
})
