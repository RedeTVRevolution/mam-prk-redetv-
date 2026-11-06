import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import catalogo from '../../catalogo.fixture.json'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'
import { correcaoDoHistorico, DECUPAGEM as BASE } from './curadoria-teste.ts'

// A paridade da seção Sugestões com o Sugestoes.test.tsx da interface antiga.

const DECUPAGEM = {
  ...BASE,
  pessoas: [
    {
      ...BASE.pessoas[0],
      nome: 'Não identificado 1',
      na_imagem: [
        { inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' },
        { inicio_ms: 60_000, fim_ms: 70_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' },
      ],
    },
  ],
}

const SUGESTOES = () => [
  {
    id: 's1',
    tipo: 'identificar_pessoa',
    inicio_ms: 211_000,
    fim_ms: 261_000,
    pergunta: 'É Leão Lobo?',
    contexto: 'GC às 03:31: LEÃO LOBO · colunista',
    correcao: { tipo: 'pessoa.renomear', item_id: 'p1', valor: 'Leão Lobo' },
    depois: [],
  },
  {
    id: 's2',
    tipo: 'tipo_novo_do_servidor',
    inicio_ms: 300_000,
    fim_ms: 330_000,
    pergunta: 'Acrescentar vestido vermelho?',
    contexto: 'Visual cita uma peça fora dos objetos',
    correcao: { tipo: 'objeto.acrescentar', item_id: '', valor: 'vestido vermelho' },
    depois: [],
  },
]

let lista: Record<string, unknown>[] = []
let aceitas: { id: string; corpo: unknown }[] = []
let recusadas: string[] = []

const servidor = setupServer(
  ...rotasDoVideo(
    () => ({ duracao_s: 600, cortes_ms: [] }),
    () => DECUPAGEM,
  ),
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] })),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json([])),
  http.get('/v1/jobs/j1/sugestoes', () => HttpResponse.json(lista)),
  http.post('/v1/jobs/j1/sugestoes/:id/aceitar', async ({ request, params }) => {
    const texto = await request.text()
    aceitas.push({ id: String(params.id), corpo: texto ? JSON.parse(texto) : null })
    lista = lista.filter((s) => s.id !== params.id)
    return HttpResponse.json({ id: 'c1', ids: ['c1'] }, { status: 201 })
  }),
  http.post('/v1/jobs/j1/sugestoes/:id/recusar', ({ params }) => {
    recusadas.push(String(params.id))
    lista = lista.filter((s) => s.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),
  http.get('/v1/catalogo/pessoas', () =>
    HttpResponse.json([{ id: 'cat-sabrina', nome: 'Sabrina Sato', rotulo: 'Sabrina Sato (apresentadora)', a_revisar: false }]),
  ),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
beforeEach(() => {
  lista = SUGESTOES()
  aceitas = []
  recusadas = []
})
afterEach(() => {
  servidor.resetHandlers()
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir() {
  const player = await abrirVideo({ permissoes: ['decupagem.editar'] })
  ;(document.activeElement as HTMLElement).blur()
  return { usuario: userEvent.setup(), player }
}

async function catalogar() {
  const aberto = await abrir()
  await aberto.usuario.keyboard('e')
  await screen.findByRole('button', { name: /Sugestões \(2\)/ })
  return aberto
}

test('com as sugestões abertas, a seção mostra a pergunta, o trecho e o contexto', async () => {
  await catalogar()
  expect(screen.getByText('É Leão Lobo?')).toBeTruthy()
  expect(screen.getByText('03:31–04:21')).toBeTruthy()
  expect(screen.getByText('GC às 03:31: LEÃO LOBO · colunista')).toBeTruthy()
})

test('S aceita a sugestão em foco, ela some e a contagem diminui; a linha diz a quantas aparições vale', async () => {
  const { usuario } = await catalogar()
  await usuario.keyboard('s')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: null }]))
  await screen.findByRole('button', { name: /Sugestões \(1\)/ })
  expect(screen.queryByText('É Leão Lobo?')).toBeNull()
  expect(await screen.findByText('Vale para as 2 aparições de Leão Lobo neste vídeo.')).toBeTruthy()
})

test('X recusa a sugestão em foco', async () => {
  const { usuario } = await catalogar()
  await usuario.keyboard('x')
  await waitFor(() => expect(recusadas).toEqual(['s1']))
  await screen.findByRole('button', { name: /Sugestões \(1\)/ })
})

test('↑ ↓ trocam a sugestão em foco e S aceita a escolhida', async () => {
  const { usuario } = await catalogar()
  await usuario.click(screen.getByRole('group', { name: 'É Leão Lobo?' }))
  await usuario.keyboard('{ArrowDown}')
  await usuario.keyboard('s')
  await waitFor(() => expect(aceitas.map((a) => a.id)).toEqual(['s2']))
})

test('clicar numa sugestão a põe em foco para as teclas', async () => {
  const { usuario } = await catalogar()
  await usuario.click(screen.getByText('Acrescentar vestido vermelho?'))
  await usuario.keyboard('x')
  await waitFor(() => expect(recusadas).toEqual(['s2']))
})

test('R abre o autocompletar, o nome escolhido e Enter aceitam com o nome dado', async () => {
  const { usuario } = await catalogar()
  await usuario.keyboard('r')
  const campo = await screen.findByRole('combobox', { name: 'Outro nome' })
  await usuario.type(campo, 'Sabrin')
  await usuario.click(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' }))
  expect((campo as HTMLInputElement).value).toBe('Sabrina Sato')
  await usuario.type(campo, '{Enter}')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: { valor: 'Sabrina Sato' } }]))
})

test('R, nome digitado e Enter aceitam; Esc cancela sem aceitar', async () => {
  const { usuario } = await catalogar()
  await usuario.keyboard('r')
  await usuario.type(await screen.findByRole('combobox', { name: 'Outro nome' }), 'X{Escape}')
  expect(screen.queryByRole('combobox', { name: 'Outro nome' })).toBeNull()
  expect(aceitas).toEqual([])
  await usuario.keyboard('r')
  await usuario.type(await screen.findByRole('combobox', { name: 'Outro nome' }), 'Ana{Enter}')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: { valor: 'Ana' } }]))
})

test('os botões Aceitar e Recusar fazem o mesmo que S e N', async () => {
  const { usuario } = await catalogar()
  await usuario.click(within(screen.getByRole('group', { name: 'É Leão Lobo?' })).getByRole('button', { name: 'Aceitar' }))
  await waitFor(() => expect(aceitas.map((a) => a.id)).toEqual(['s1']))
  await usuario.click(within(screen.getByRole('group', { name: 'Acrescentar vestido vermelho?' })).getByRole('button', { name: 'Recusar' }))
  await waitFor(() => expect(recusadas).toEqual(['s2']))
  await waitFor(() => expect(screen.queryByRole('button', { name: /Sugestões/ })).toBeNull())
})

test('Outro nome, clique na opção e Salvar aceitam com o nome dado', async () => {
  const { usuario } = await catalogar()
  await usuario.click(within(screen.getByRole('group', { name: 'É Leão Lobo?' })).getByRole('button', { name: 'Outro nome' }))
  await usuario.type(await screen.findByRole('combobox', { name: 'Outro nome' }), 'Sabrin')
  await usuario.click(await screen.findByRole('option', { name: 'Sabrina Sato (apresentadora)' }))
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(aceitas).toEqual([{ id: 's1', corpo: { valor: 'Sabrina Sato' } }]))
})

test('uma sugestão que não é de nome pede o valor num campo de texto livre', async () => {
  lista = [SUGESTOES()[1]]
  const { usuario } = await abrir()
  await usuario.keyboard('e')
  await screen.findByText('Acrescentar vestido vermelho?')
  await usuario.keyboard('r')
  await usuario.type(await screen.findByLabelText('Outro valor'), 'vestido azul{Enter}')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's2', corpo: { valor: 'vestido azul' } }]))
})

test('um tipo de sugestão que a tela não conhece aparece e se resolve', async () => {
  lista = [SUGESTOES()[1]]
  const { usuario } = await abrir()
  await usuario.keyboard('e')
  expect(await screen.findByText('Acrescentar vestido vermelho?')).toBeTruthy()
  await usuario.keyboard('s')
  await waitFor(() => expect(aceitas).toEqual([{ id: 's2', corpo: null }]))
  await waitFor(() => expect(screen.queryByText('Acrescentar vestido vermelho?')).toBeNull())
})

test('a seção recolhe e abre', async () => {
  const { usuario } = await catalogar()
  await usuario.click(screen.getByRole('button', { name: /Sugestões \(2\)/ }))
  expect(screen.queryByText('É Leão Lobo?')).toBeNull()
  await usuario.click(screen.getByRole('button', { name: /Sugestões \(2\)/ }))
  expect(screen.getByText('É Leão Lobo?')).toBeTruthy()
})

test('fora do modo de catalogação não há seção, e S, N e R não fazem nada', async () => {
  const { usuario } = await abrir()
  await usuario.keyboard('snr')
  expect(screen.queryByText('É Leão Lobo?')).toBeNull()
  expect(screen.queryByRole('button', { name: /Sugestões/ })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Aceitar' })).toBeNull()
  expect(aceitas).toEqual([])
  expect(recusadas).toEqual([])
})

test('sem sugestões a seção não aparece', async () => {
  lista = []
  const { usuario } = await abrir()
  await usuario.keyboard('e')
  await screen.findByText('Catalogando')
  await new Promise((r) => setTimeout(r, 50))
  expect(screen.queryByRole('button', { name: /Sugestões/ })).toBeNull()
})

test('S, N, R e as setas da seção aparecem na lista de atalhos', async () => {
  const { usuario } = await catalogar()
  await usuario.keyboard('?')
  const grupo = within(within(await screen.findByRole('dialog')).getByRole('region', { name: 'Sugestões' }))
  for (const acao of ['Sugestão em foco: aceitar', 'Sugestão em foco: recusar', 'Sugestão em foco: outro nome', 'Na seção Sugestões: trocar a sugestão em foco'])
    expect(grupo.getByText(acao)).toBeTruthy()
})

test('clicar no trecho salta o player ao começo dele', async () => {
  const { usuario, player } = await catalogar()
  await usuario.click(screen.getByRole('button', { name: 'Saltar a 03:31' }))
  expect(player.currentTime).toBe(211)
})

test('a sugestão que já foi decidida avisa e sai da lista', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/sugestoes/:id/aceitar', () => {
      lista = lista.filter((s) => s.id !== 's1')
      return HttpResponse.json({ detail: 'Sugestão não encontrada' }, { status: 404 })
    }),
  )
  const { usuario } = await catalogar()
  await usuario.keyboard('s')
  expect((await screen.findByRole('alert')).textContent).toContain('Esta sugestão já foi decidida')
  await screen.findByRole('button', { name: /Sugestões \(1\)/ })
})

test('uma falha da API diz o que fazer e dá o código para o suporte', async () => {
  servidor.use(http.post('/v1/jobs/j1/sugestoes/:id/recusar', () => new HttpResponse(null, { status: 500 })))
  const { usuario } = await catalogar()
  await usuario.keyboard('x')
  const alerta = await screen.findByRole('alert')
  expect(alerta.textContent).toContain('Não foi possível recusar a sugestão. Tente de novo.')
  expect(alerta.textContent).toContain('Código para o suporte: http_500')
})

test('o foco segue a sugestão, não a posição, quando a lista vem de novo em outra ordem', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/sugestoes/:id/recusar', () => {
      lista = [...lista].reverse()
      return new HttpResponse(null, { status: 500 })
    }),
  )
  const { usuario } = await catalogar()
  await usuario.click(screen.getByText('Acrescentar vestido vermelho?'))
  await usuario.keyboard('x')
  await screen.findByRole('alert')
  // A lista veio de novo invertida: a sugestão escolhida agora é a primeira.
  await waitFor(() =>
    expect(within(document.querySelector('[data-sugestoes]') as HTMLElement).getAllByRole('group')[0].getAttribute('aria-label')).toBe('Acrescentar vestido vermelho?'),
  )
  await waitFor(() => expect(screen.getByRole('group', { name: 'Acrescentar vestido vermelho?' }).getAttribute('aria-current')).toBe('true'))
})

test('aceitar uma sugestão recarrega a decupagem', async () => {
  let cargas = 0
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => {
      cargas += 1
      return HttpResponse.json(DECUPAGEM)
    }),
  )
  const { usuario } = await catalogar()
  const antes = cargas
  await usuario.keyboard('s')
  await waitFor(() => expect(cargas).toBeGreaterThan(antes))
})

test('aceitar com S e desfazer com Ctrl+Z traz a sugestão de volta', async () => {
  let historico: object[] = []
  servidor.use(
    http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json(historico)),
    http.post('/v1/jobs/j1/correcoes/:id/desfazer', () => {
      historico = []
      lista = SUGESTOES()
      return HttpResponse.json({ id: 'c2' }, { status: 201 })
    }),
    http.post('/v1/jobs/j1/sugestoes/:id/aceitar', ({ params }) => {
      lista = lista.filter((x) => x.id !== params.id)
      historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
      return HttpResponse.json({ id: 'c1', ids: ['c1'] }, { status: 201 })
    }),
  )
  const { usuario } = await catalogar()
  await usuario.keyboard('s')
  await screen.findByRole('button', { name: /Sugestões \(1\)/ })

  await usuario.keyboard('{Control>}z{/Control}')

  expect(await screen.findByRole('button', { name: /Sugestões \(2\)/ })).toBeTruthy()
})
