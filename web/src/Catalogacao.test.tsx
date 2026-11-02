import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import catalogo from './catalogo.fixture.json'
import type { Job } from './jobs.ts'
import { render } from './render-teste.tsx'
import Visualizador from './Visualizador.tsx'

const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      fontes_do_nome: ['rosto'],
      na_imagem: [{ inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' }],
      citada_na_fala: [{ inicio_ms: 30_000, fim_ms: 32_000 }],
      citada_no_texto: [],
    },
  ],
  planos: [{ id: 'pl1', ambiente: 'estúdio', plano_limpo: false, inicio_ms: 0, fim_ms: 5_000 }],
  comerciais: [{ id: 'c1', marca: 'Marca X', tipo: 'intervalo', inicio_ms: 40_000, fim_ms: 50_000 }],
  transcricao: [{ id: 'f1', locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [{ id: 't1', tipo: 'gc', texto: 'Leão Lobo, jurado', inicio_ms: 12_000, fim_ms: 15_000 }],
  objetos: [
    {
      id: 'o1',
      categoria: 'roupa',
      tipo: 'camisa',
      cor_base: ['azul'],
      cor: 'azul marinho',
      pessoa: 'p1',
      relacao: 'veste',
      ocorrencias: [{ inicio_ms: 10_000, fim_ms: 20_000 }],
    },
  ],
}

const JOB: Job = {
  id: 'j1',
  nome: 'FAMA.mp4',
  estado: 'concluido',
  codigo_falha: null,
  duracao_s: 120,
  criado_em: '2026-10-21T10:00:00Z',
}

const correcoes: Record<string, unknown>[] = []
let desfeitas: { id: string; motivo: unknown }[] = []
let historico: Record<string, unknown>[] = []
let decupagemAtual: typeof DECUPAGEM = DECUPAGEM
let pulsos: string[] = []

const servidor = setupServer(
  http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagemAtual)),
  http.get('/v1/jobs/j1/reproducao', () =>
    HttpResponse.json({ url: 'https://exemplo.test/v.mp4', expira_em: '2999-01-01T00:00:00Z' }),
  ),
  http.get('/v1/eu', () =>
    HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
  ),
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  http.get('/v1/jobs/j1/correcoes', () => HttpResponse.json(historico)),
  http.get('/v1/jobs/j1/fila', () => HttpResponse.json([])),
  http.post('/v1/jobs/j1/revisao/pulso', async ({ request }) => {
    pulsos.push(((await request.json()) as { evento: string }).evento)
    return new HttpResponse(null, { status: 204 })
  }),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcoes.push((await request.json()) as Record<string, unknown>)
    return HttpResponse.json({}, { status: 201 })
  }),
  http.post('/v1/jobs/j1/correcoes/:id/desfazer', async ({ request, params }) => {
    desfeitas.push({ id: String(params.id), motivo: ((await request.json()) as { motivo: unknown }).motivo })
    return HttpResponse.json({}, { status: 201 })
  }),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  correcoes.length = 0
  desfeitas = []
  pulsos = []
  historico = []
  decupagemAtual = DECUPAGEM
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(podeEditar: boolean) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/video/j1')
  render(
    <AtalhosProvider>
      <Visualizador api={criarClienteDaApi(auth, () => {})} job={JOB} t={null} podeEditar={podeEditar} />
    </AtalhosProvider>,
  )
  await screen.findByRole('group', { name: 'Pautas 1' })
  return userEvent.setup()
}

test('E liga e desliga o modo de catalogação, só para quem edita', async () => {
  const usuario = await abrir(true)
  expect(screen.queryByText('Catalogando')).toBeNull()

  await usuario.keyboard('e')
  expect(screen.getByText('Catalogando')).toBeTruthy()

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()
})

test('o modo de catalogação abre a sessão de revisão e sair do modo a fecha', async () => {
  const usuario = await abrir(true)
  expect(pulsos).toEqual([])

  await usuario.keyboard('e')
  await waitFor(() => expect(pulsos).toEqual(['inicio']))

  await usuario.keyboard('e')
  await waitFor(() => expect(pulsos).toEqual(['inicio', 'fim']))
})

test('sem decupagem.editar, E não faz nada e não está na lista do ?', async () => {
  const usuario = await abrir(false)

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  expect(within(lista).queryByText('Catalogar')).toBeNull()
  expect(within(lista).queryByText(/catalogação/i)).toBeNull()
})

test('com decupagem.editar, a lista do ? traz os atalhos da catalogação', async () => {
  const usuario = await abrir(true)

  await usuario.keyboard('?')
  const lista = await screen.findByRole('dialog')
  for (const acao of [
    /Ligar e desligar o modo de catalogação/,
    /Desfazer a última correção/,
    /Corrigir o item em foco/,
    /Não é isto/,
  ])
    expect(within(lista).getByText(acao)).toBeTruthy()
  await waitFor(() => expect(within(lista).getByRole('table', { name: 'Catalogação' })).toBeTruthy())
})

function correcaoDoHistorico(id: string, autor: string, estado = 'ativa', tipo = 'pessoa.renomear') {
  return {
    id,
    tipo,
    estado,
    item_id: 'p1',
    ancora: { versao: 'v1', tipo_do_item: 'pessoa' },
    criada_em: '2026-10-31T12:00:00Z',
    motivo: 'nome corrigido',
    autor_email: autor,
    antes_legivel: 'Não identificado',
    depois_legivel: 'Leão Lobo',
  }
}

test('Ctrl+Z desfaz a última correção do próprio editor e avisa', async () => {
  servidor.use(
    http.get('/v1/eu', () =>
      HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.editar'] }),
    ),
  )
  historico = [
    correcaoDoHistorico('c3', 'outro@redetv.com.br'),
    correcaoDoHistorico('c2', 'ana@redetv.com.br', 'desfeita'),
    correcaoDoHistorico('c1', 'ana@redetv.com.br'),
  ]
  const usuario = await abrir(true)
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  expect(await screen.findByText('Desfeito: Renomear pessoa (Leão Lobo → Não identificado)')).toBeTruthy()
  expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }])
})

test('Ctrl+Z pula a correção pendente, que a API não desfaz, e desfaz a aprovada', async () => {
  historico = [
    correcaoDoHistorico('c2', 'ana@redetv.com.br', 'pendente'),
    correcaoDoHistorico('c1', 'ana@redetv.com.br', 'aprovada'),
  ]
  const usuario = await abrir(true)
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}z{/Control}')

  await waitFor(() => expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }]))
})

test('Ctrl+Shift+Z não desfaz', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir(true)
  await usuario.keyboard('e')

  await usuario.keyboard('{Control>}{Shift>}z{/Shift}{/Control}')

  expect(desfeitas).toEqual([])
})

test('Ctrl+Z fora do modo de catalogação não desfaz nada', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir(true)

  await usuario.keyboard('{Control>}z{/Control}')

  expect(desfeitas).toEqual([])
})

test('o botão Catalogar liga e desliga o modo como o E, com a dica Catalogar (E)', async () => {
  const usuario = await abrir(true)
  const botao = screen.getByRole('button', { name: 'Catalogar' })
  expect(botao.getAttribute('aria-pressed')).toBe('false')

  await usuario.hover(botao)
  expect(await screen.findByText('Catalogar (E)')).toBeTruthy()

  await usuario.click(botao)
  expect(screen.getByText('Catalogando')).toBeTruthy()
  expect(botao.getAttribute('aria-pressed')).toBe('true')

  await usuario.keyboard('e')
  expect(screen.queryByText('Catalogando')).toBeNull()
  expect(botao.getAttribute('aria-pressed')).toBe('false')
})

test('sem decupagem.editar, o botão Catalogar não aparece', async () => {
  await abrir(false)
  expect(screen.queryByRole('button', { name: 'Catalogar' })).toBeNull()
})

test('o botão Desfazer faz o mesmo que o Ctrl+Z, com a dica que mostra Ctrl+Z', async () => {
  historico = [correcaoDoHistorico('c1', 'ana@redetv.com.br')]
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))

  const botao = screen.getByRole('button', { name: 'Desfazer' })
  await waitFor(() => expect((botao as HTMLButtonElement).disabled).toBe(false))
  await usuario.hover(botao)
  expect(await screen.findByText('Desfazer a última correção (Ctrl+Z)')).toBeTruthy()

  await usuario.click(botao)

  expect(await screen.findByText('Desfeito: Renomear pessoa (Leão Lobo → Não identificado)')).toBeTruthy()
  expect(desfeitas).toEqual([{ id: 'c1', motivo: 'correção desfeita pelo editor' }])
})

test('o botão Desfazer fica desabilitado sem correção do editor para desfazer', async () => {
  historico = [correcaoDoHistorico('c1', 'outro@redetv.com.br')]
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))

  const botao = screen.getByRole('button', { name: 'Desfazer' })
  await waitFor(() => expect((botao as HTMLButtonElement).disabled).toBe(true))
})

async function catalogarPauta() {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Eleição, 00:00 a 01:00/ }))
  await usuario.keyboard('e')
  return usuario
}

test('F2 → editar → Enter grava a correção com o motivo preenchido, sem diálogo', async () => {
  const usuario = await catalogarPauta()

  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  expect(screen.queryByRole('dialog')).toBeNull()
  const titulo = within(formulario).getByLabelText('Título')
  expect(document.activeElement).toBe(titulo)
  expect((within(formulario).getByLabelText('Motivo (opcional)') as HTMLInputElement).value).toBe('')

  await usuario.clear(titulo)
  await usuario.type(titulo, 'Eleição 2026')
  expect((within(formulario).getByLabelText('Motivo (opcional)') as HTMLInputElement).value).toBe(
    'título da pauta corrigido pelo editor',
  )
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pauta.titulo',
    item_id: 'pa1',
    valor: 'Eleição 2026',
    motivo: 'título da pauta corrigido pelo editor',
    versao: 'v1',
  })
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
})

test('o motivo apagado vale o do gesto; o motivo escrito vale como escrito', async () => {
  const usuario = await catalogarPauta()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  const titulo = within(formulario).getByLabelText('Título')
  await usuario.type(titulo, ' II')
  const motivo = within(formulario).getByLabelText('Motivo (opcional)')
  await usuario.clear(motivo)
  await usuario.type(motivo, 'a emissora mudou o nome')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ motivo: 'a emissora mudou o nome' })
})

test('Esc cancela a correção e não grava nada', async () => {
  const usuario = await catalogarPauta()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')

  await usuario.keyboard('{Escape}')

  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toEqual([])
})

test('F2 fora do modo de catalogação não abre o formulário', async () => {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Eleição, 00:00 a 01:00/ }))

  await usuario.keyboard('{F2}')

  expect(screen.queryByRole('form')).toBeNull()
})

test('um 409 mostra a mensagem do servidor e recarrega a decupagem', async () => {
  let cargas = 0
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () => {
      cargas += 1
      return HttpResponse.json(decupagemAtual)
    }),
    http.post('/v1/jobs/j1/correcoes', () =>
      HttpResponse.json({ detail: 'A decupagem mudou. Confira e corrija de novo.' }, { status: 409 }),
    ),
  )
  const usuario = await catalogarPauta()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')
  const antes = cargas

  await usuario.keyboard('{Enter}')

  expect(await screen.findByText('A decupagem mudou. Confira e corrija de novo.')).toBeTruthy()
  await waitFor(() => expect(cargas).toBeGreaterThan(antes))
})

test('um 422 fica no formulário, com a mensagem do servidor', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/correcoes', () =>
      HttpResponse.json({ detail: 'O título é longo demais.' }, { status: 422 }),
    ),
  )
  const usuario = await catalogarPauta()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Eleição/ })
  await usuario.type(within(formulario).getByLabelText('Título'), ' II')

  await usuario.keyboard('{Enter}')

  expect((await within(formulario).findByRole('alert')).textContent).toBe('O título é longo demais.')
  expect(screen.getByRole('form', { name: /Corrigir Eleição/ })).toBeTruthy()
})

async function selecionarAparicao() {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leão Lobo, 1 aparição/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leão Lobo, 00:10 a 00:20/ }))
  await usuario.keyboard('e')
  return usuario
}

test('Del pede a confirmação na linha; Esc desiste e Enter grava o "não é esta pessoa"', async () => {
  const usuario = await selecionarAparicao()

  await usuario.keyboard('{Delete}')
  expect(await screen.findByText('Remover Leão Lobo desta aparição?')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByText('Remover Leão Lobo desta aparição?')).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.keyboard('{Delete}')
  await screen.findByText('Remover Leão Lobo desta aparição?')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'pessoa.nao_e',
    item_id: 'p1',
    ocorrencia: { lista: 'na_imagem', inicio_ms: 10_000, fim_ms: 20_000 },
    motivo: 'pessoa removida desta aparição pelo editor',
  })
})

test('as alças aparecem na linha do tempo e movem os tempos de 0,1 s em 0,1 s', async () => {
  const usuario = await selecionarAparicao()
  await usuario.keyboard('{F2}')
  await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })

  const inicio = screen.getByRole('slider', { name: 'Início do item' })
  expect(inicio.getAttribute('aria-valuetext')).toBe('00:10')
  inicio.focus()
  await usuario.keyboard('{ArrowRight}{ArrowRight}{ArrowRight}')
  expect(screen.getByRole('slider', { name: 'Início do item' }).getAttribute('aria-valuenow')).toBe('10300')

  screen.getByRole('slider', { name: 'Fim do item' }).focus()
  await usuario.keyboard('{Shift>}{ArrowRight}{/Shift}')
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'item.tempos', tipo_do_item: 'pessoa', valor: '10300-21000' })
})

test('acrescentar aparição na linha da pessoa', async () => {
  const usuario = await selecionarAparicao()

  await usuario.click(screen.getByRole('button', { name: 'Acrescentar aparição de Leão Lobo' }))
  const formulario = await screen.findByRole('form', { name: 'Acrescentar aparição de Leão Lobo' })
  await usuario.type(within(formulario).getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.acrescentar_aparicao', item_id: 'p1' })
  expect(JSON.parse(String(correcoes[0].valor))).toMatchObject({ evidencia: 'rosto' })
})

async function abrirAlcas() {
  const usuario = await selecionarAparicao()
  await usuario.keyboard('{F2}')
  await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })
  return usuario
}

test('Enter grava os tempos das alças', async () => {
  const usuario = await abrirAlcas()
  screen.getByRole('slider', { name: 'Início do item' }).focus()
  await usuario.keyboard('{ArrowRight}{ArrowRight}')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'item.tempos', valor: '10200-20000' })
})

test('Esc descarta os tempos das alças', async () => {
  const usuario = await abrirAlcas()
  screen.getByRole('slider', { name: 'Início do item' }).focus()
  await usuario.keyboard('{ArrowRight}{Escape}')

  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toEqual([])
})

test('arrastar uma alça e clicar em Salvar grava os tempos novos; Cancelar descarta', async () => {
  const usuario = await abrirAlcas()
  const alca = () => screen.getByRole('slider', { name: 'Início do item' })
  const arrastar = async () => {
    const trilha = alca().parentElement as HTMLElement
    trilha.getBoundingClientRect = () => ({ left: 0, width: 1000 }) as DOMRect
    await usuario.pointer([
      { keys: '[MouseLeft>]', target: alca(), coords: { clientX: 0 } },
      { target: alca(), coords: { clientX: 120 } },
      { keys: '[/MouseLeft]', target: alca() },
    ])
  }

  await arrastar()
  const novo = Number(alca().getAttribute('aria-valuenow'))
  expect(novo).not.toBe(10_000)

  await usuario.click(screen.getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.keyboard('{F2}')
  await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })
  await arrastar()
  await usuario.click(screen.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'item.tempos', valor: `${novo}-20000` })
})

test('cada alça tem a dica com as teclas', async () => {
  await abrirAlcas()
  for (const nome of ['Início do item', 'Fim do item']) {
    expect(screen.getByRole('slider', { name: nome }).getAttribute('title')).toBe(
      'Arraste, ou use ← → (0,1 s) e Shift (1 s)',
    )
  }
})

test('acrescentar aparição grava e cancela pelos botões, sem tecla nenhuma', async () => {
  const usuario = await selecionarAparicao()
  await usuario.click(screen.getByRole('button', { name: 'Acrescentar aparição de Leão Lobo' }))
  let formulario = await screen.findByRole('form', { name: 'Acrescentar aparição de Leão Lobo' })
  await usuario.type(within(formulario).getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.click(within(formulario).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.click(screen.getByRole('button', { name: 'Acrescentar aparição de Leão Lobo' }))
  formulario = await screen.findByRole('form', { name: 'Acrescentar aparição de Leão Lobo' })
  await usuario.type(within(formulario).getByLabelText('Evidência na imagem'), 'rosto')
  await usuario.click(within(formulario).getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.acrescentar_aparicao', item_id: 'p1' })
})

test('o item corrigido mostra onde a correção está na busca, e o pendente, "aguardando o Curador"', async () => {
  historico = [
    {
      ...correcaoDoHistorico('c1', 'ana@redetv.com.br', 'ativa', 'pauta.titulo'),
      item_id: 'pa1',
      ancora: { versao: 'v1', tipo_do_item: 'pauta' },
      criada_em: '2026-10-31T12:00:00Z',
      motivo: 'título corrigido',
      na_busca: 'na_busca',
    },
    {
      ...correcaoDoHistorico('c2', 'ana@redetv.com.br', 'pendente', 'comercial.marca'),
      item_id: 'c1',
      ancora: { versao: 'v1', tipo_do_item: 'comercial' },
      criada_em: '2026-10-31T12:01:00Z',
      motivo: 'marca certa',
    },
  ]
  const usuario = await abrir(true)

  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  expect(await screen.findByText('na busca')).toBeTruthy()
  await usuario.click(screen.getByRole('tab', { name: /Comerciais/ }))
  expect(await screen.findByText('aguardando o Curador')).toBeTruthy()
})

/** A lixeira da linha selecionada: as das outras linhas ficam transparentes. */
function lixeiraDaLinhaSelecionada() {
  const visiveis = screen
    .getAllByRole('button', { name: 'Não é isto: Leão Lobo' })
    .filter((b) => b.parentElement?.style.opacity === '1')
  expect(visiveis).toHaveLength(1)
  return visiveis[0]
}

async function catalogarSemSelecionar() {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  const linha = await screen.findByRole('button', { name: /^Eleição, 00:00 a 01:00/ })
  await usuario.keyboard('e')
  return { usuario, linha }
}

test('o duplo clique na linha abre o mesmo formulário do F2', async () => {
  const { usuario, linha } = await catalogarSemSelecionar()

  await usuario.dblClick(linha)

  expect(await screen.findByRole('form', { name: /Corrigir Eleição/ })).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('o lápis aparece ao passar o mouse, com a dica Corrigir (F2), e abre o formulário', async () => {
  const { usuario, linha } = await catalogarSemSelecionar()
  const lapis = screen.getByRole('button', { name: 'Corrigir Eleição' })
  // A pauta não tem "não é isto".
  expect(screen.queryByRole('button', { name: /^Não é isto/ })).toBeNull()
  expect(lapis.parentElement?.style.opacity).toBe('0')

  await usuario.hover(linha)
  await waitFor(() => expect(lapis.parentElement?.style.opacity).toBe('1'))
  await usuario.hover(lapis)
  expect(await screen.findByText('Corrigir (F2)')).toBeTruthy()
  await usuario.click(lapis)

  expect(await screen.findByRole('form', { name: /Corrigir Eleição/ })).toBeTruthy()
})

test('o lápis aparece com a linha selecionada, e não existe fora do modo de catalogação', async () => {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Pautas/ }))
  const linha = await screen.findByRole('button', { name: /^Eleição, 00:00 a 01:00/ })
  await usuario.click(linha)
  expect(screen.queryByRole('button', { name: 'Corrigir Eleição' })).toBeNull()

  await usuario.keyboard('e')
  const lapis = await screen.findByRole('button', { name: 'Corrigir Eleição' })
  expect(lapis.parentElement?.style.opacity).toBe('1')
})

test('a lixeira abre a confirmação do Del, e Cancelar e Remover funcionam com o clique', async () => {
  const usuario = await selecionarAparicao()

  await usuario.click(lixeiraDaLinhaSelecionada())
  const confirmacao = await screen.findByRole('group', { name: 'Confirmar a remoção' })
  expect(within(confirmacao).getByText('Remover Leão Lobo desta aparição?')).toBeTruthy()
  expect(screen.queryByRole('dialog')).toBeNull()

  await usuario.click(within(confirmacao).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('group', { name: 'Confirmar a remoção' })).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.click(lixeiraDaLinhaSelecionada())
  const outra = await screen.findByRole('group', { name: 'Confirmar a remoção' })
  await usuario.click(within(outra).getByRole('button', { name: 'Remover' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'pessoa.nao_e', item_id: 'p1' })
})

test('Enter com o foco no Cancelar da confirmação cancela, sem remover', async () => {
  const usuario = await selecionarAparicao()
  await usuario.keyboard('{Delete}')
  const confirmacao = await screen.findByRole('group', { name: 'Confirmar a remoção' })

  within(confirmacao).getByRole('button', { name: 'Cancelar' }).focus()
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(screen.queryByRole('group', { name: 'Confirmar a remoção' })).toBeNull())
  expect(correcoes).toEqual([])
})

test('Del com o foco num botão do formulário não troca a correção aberta pela remoção', async () => {
  const usuario = await selecionarAparicao()
  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir Leão Lobo/ })

  within(formulario).getByRole('button', { name: 'Cancelar' }).focus()
  await usuario.keyboard('{Delete}')

  expect(screen.getByRole('form', { name: /Corrigir Leão Lobo/ })).toBeTruthy()
  expect(screen.queryByRole('group', { name: 'Confirmar a remoção' })).toBeNull()
})

test('a confirmação e o formulário mostram os atalhos nas dicas dos botões', async () => {
  const usuario = await selecionarAparicao()
  await usuario.click(lixeiraDaLinhaSelecionada())
  const confirmacao = await screen.findByRole('group', { name: 'Confirmar a remoção' })

  await usuario.hover(within(confirmacao).getByRole('button', { name: 'Remover' }))
  expect(await screen.findByText('Enter')).toBeTruthy()
  await usuario.hover(within(confirmacao).getByRole('button', { name: 'Cancelar' }))
  expect(await screen.findByText('Esc')).toBeTruthy()
})

/** Abre o formulário pelo lápis da linha, com o mouse: a aba, o modo e o lápis (o `n`-ésimo da aba). */
async function corrigirPeloLapis(aba: RegExp, titulo: string, n = 0) {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))
  await usuario.click(screen.getByRole('tab', { name: aba }))
  await usuario.click(screen.getAllByRole('button', { name: `Corrigir ${titulo}` })[n])
  const formulario = within(await screen.findByRole('form', { name: new RegExp(`Corrigir ${titulo}`) }))
  return { usuario, formulario }
}

async function salvarComOMouse(usuario: ReturnType<typeof userEvent.setup>, formulario: ReturnType<typeof within>) {
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
}

test('pelo clique: resumo e tom da pauta', async () => {
  const { usuario, formulario } = await corrigirPeloLapis(/Pautas/, 'Eleição')
  await usuario.type(formulario.getByLabelText('Resumo'), ' na TV')
  await usuario.selectOptions(formulario.getByLabelText('Tom'), 'polemico')
  await salvarComOMouse(usuario, formulario)

  expect(correcoes.map((c) => [c.tipo, c.valor])).toEqual([
    ['pauta.resumo', 'Debate na TV'],
    ['pauta.tom', 'polemico'],
  ])
})

test('pelo clique: tipo do comercial', async () => {
  const { usuario, formulario } = await corrigirPeloLapis(/Comerciais/, 'Marca X')
  await usuario.selectOptions(formulario.getByLabelText('Tipo'), 'testemunhal')
  await salvarComOMouse(usuario, formulario)

  expect(correcoes).toMatchObject([{ tipo: 'comercial.tipo', item_id: 'c1', valor: 'testemunhal' }])
})

test('pelo clique: papel e visual da aparição, as fontes do nome e a aparição que vira menção', async () => {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leão Lobo, 1 aparição/ }))
  // A aparição vem antes da menção na lista da pessoa.
  await usuario.click(screen.getAllByRole('button', { name: 'Corrigir Leão Lobo' })[0])
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Leão Lobo/ }))
  await usuario.clear(formulario.getByLabelText('Papel na cena'))
  await usuario.type(formulario.getByLabelText('Papel na cena'), 'convidado')
  await usuario.click(formulario.getByRole('checkbox', { name: 'rosto' }))
  await usuario.click(formulario.getByRole('checkbox', { name: 'GC' }))
  await salvarComOMouse(usuario, formulario)

  expect(correcoes.map((c) => [c.tipo, c.valor])).toEqual([
    ['pessoa.fontes_do_nome', JSON.stringify(['gc'])],
    ['aparicao.papel_visual', JSON.stringify({ papel: 'convidado', visual: 'barba' })],
  ])

  correcoes.length = 0
  await usuario.click(screen.getAllByRole('button', { name: 'Corrigir Leão Lobo' })[0])
  const deNovo = within(await screen.findByRole('form', { name: /Corrigir Leão Lobo/ }))
  await usuario.selectOptions(deNovo.getByLabelText('Aparição ou menção'), 'citada_na_fala')
  await salvarComOMouse(usuario, deNovo)

  expect(correcoes).toMatchObject([
    { tipo: 'pessoa.aparicao_para_mencao', valor: 'citada_na_fala', ocorrencia: { lista: 'na_imagem' } },
  ])
})

test('pelo clique: a menção que vira aparição, com a evidência', async () => {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('button', { name: 'Catalogar' }))
  await usuario.click(screen.getByRole('tab', { name: /Pessoas/ }))
  await usuario.click(await screen.findByRole('button', { name: /^Leão Lobo, 1 aparição/ }))
  await usuario.click(screen.getAllByRole('button', { name: 'Corrigir Leão Lobo' })[1])
  const formulario = within(await screen.findByRole('form', { name: /Corrigir Leão Lobo/ }))
  await usuario.selectOptions(formulario.getByLabelText('Aparição ou menção'), 'na_imagem')
  await usuario.type(formulario.getByLabelText('Evidência na imagem'), 'rosto')
  await salvarComOMouse(usuario, formulario)

  expect(correcoes).toMatchObject([
    { tipo: 'pessoa.mencao_para_aparicao', valor: 'rosto', ocorrencia: { lista: 'citada_na_fala' } },
  ])
})

test('pelo clique: descrição do plano e plano limpo', async () => {
  const { usuario, formulario } = await corrigirPeloLapis(/Planos/, 'estúdio')
  await usuario.type(formulario.getByLabelText('Objetos (separados por vírgula)'), 'mesa, copo')
  await usuario.click(formulario.getByRole('checkbox', { name: 'Plano limpo' }))
  await salvarComOMouse(usuario, formulario)

  expect(correcoes.map((c) => c.tipo)).toEqual(['plano.descricao', 'plano.limpo'])
})

test('pelo clique: texto e locutor da fala', async () => {
  const { usuario, formulario } = await corrigirPeloLapis(/Transcrição/, 'Boa noite')
  await usuario.clear(formulario.getByLabelText('Locutor'))
  await usuario.type(formulario.getByLabelText('Locutor'), 'Bia')
  await salvarComOMouse(usuario, formulario)

  expect(correcoes).toMatchObject([
    { tipo: 'fala.texto', item_id: 'f1', valor: JSON.stringify({ texto: 'Boa noite', locutor: 'Bia' }) },
  ])
})

test('pelo clique: texto na tela', async () => {
  const { usuario, formulario } = await corrigirPeloLapis(/Textos na tela/, 'Leão Lobo, jurado')
  await usuario.selectOptions(formulario.getByLabelText('Tipo'), 'tarja')
  await salvarComOMouse(usuario, formulario)

  expect(correcoes.map((c) => c.tipo)).toEqual(['texto_na_tela.texto'])
})

async function selecionarObjeto() {
  const usuario = await abrir(true)
  await usuario.click(screen.getByRole('tab', { name: /Objetos/ }))
  await usuario.click(await screen.findByRole('button', { name: /^camisa, 1 ocorrência/ }))
  await usuario.click(await screen.findByRole('button', { name: /^camisa, 00:10 a 00:20/ }))
  await usuario.keyboard('e')
  return usuario
}

const linhaDoObjeto = () => screen.getByRole('button', { name: /^camisa, 00:10 a 00:20/ })

test('objeto: F2 abre o formulário e Enter grava objeto.atributos', async () => {
  const usuario = await selecionarObjeto()

  await usuario.keyboard('{F2}')
  const formulario = await screen.findByRole('form', { name: /Corrigir camisa/ })
  const marca = within(formulario).getByLabelText('Marca')
  await usuario.type(marca, 'Lacoste')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'objeto.atributos',
    item_id: 'o1',
    motivo: 'atributos do objeto corrigidos pelo editor',
    versao: 'v1',
  })
  expect(JSON.parse(correcoes[0].valor as string)).toEqual({
    tipo: 'camisa',
    cor_base: ['azul'],
    cor: 'azul marinho',
    detalhe: null,
    marca: 'Lacoste',
  })
})

test('objeto: o duplo clique e o lápis abrem o formulário, e o dono vira "em cena" pelo clique', async () => {
  const usuario = await selecionarObjeto()
  await usuario.dblClick(linhaDoObjeto())
  const formulario = await screen.findByRole('form', { name: /Corrigir camisa/ })
  await usuario.click(within(formulario).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())

  await usuario.click(screen.getByRole('button', { name: 'Corrigir camisa' }))
  const outro = await screen.findByRole('form', { name: /Corrigir camisa/ })
  await usuario.selectOptions(within(outro).getByLabelText('Dono'), 'Em cena')
  await usuario.click(within(outro).getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'objeto.dono', item_id: 'o1' })
  expect(JSON.parse(correcoes[0].valor as string)).toEqual({ pessoa: null, relacao: null })
})

test('objeto: Del pede "Este objeto não está na imagem?"; Esc não grava e Enter grava objeto.nao_existe', async () => {
  const usuario = await selecionarObjeto()

  await usuario.keyboard('{Delete}')
  expect(await screen.findByText('Este objeto não está na imagem?')).toBeTruthy()
  await usuario.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByText('Este objeto não está na imagem?')).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.keyboard('{Delete}')
  await screen.findByText('Este objeto não está na imagem?')
  await usuario.keyboard('{Enter}')

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({
    tipo: 'objeto.nao_existe',
    item_id: 'o1',
    valor: 'nao_existe',
    motivo: 'objeto removido da imagem pelo editor',
  })
})

test('objeto: a lixeira abre a confirmação, e Cancelar e Remover funcionam com o clique', async () => {
  const usuario = await selecionarObjeto()

  await usuario.click(screen.getByRole('button', { name: 'Não é isto: camisa' }))
  const confirmacao = await screen.findByRole('group', { name: 'Confirmar a remoção' })
  expect(within(confirmacao).getByText('Este objeto não está na imagem?')).toBeTruthy()
  await usuario.click(within(confirmacao).getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('group', { name: 'Confirmar a remoção' })).toBeNull())
  expect(correcoes).toEqual([])

  await usuario.click(screen.getByRole('button', { name: 'Não é isto: camisa' }))
  const outra = await screen.findByRole('group', { name: 'Confirmar a remoção' })
  await usuario.click(within(outra).getByRole('button', { name: 'Remover' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(correcoes[0]).toMatchObject({ tipo: 'objeto.nao_existe', item_id: 'o1' })
})

async function abrirOFormularioDoObjeto() {
  const usuario = await selecionarObjeto()
  await usuario.keyboard('{F2}')
  const formulario = within(await screen.findByRole('form', { name: /Corrigir camisa/ }))
  return { usuario, formulario, grupo: formulario.getByRole('group', { name: 'Cor base (até 2)' }) }
}

const corMarcada = (grupo: HTMLElement, nome: string) =>
  within(grupo).getByRole('button', { name: nome }).getAttribute('aria-pressed') === 'true'

function focarNaCor(grupo: HTMLElement, nome: string) {
  act(() => within(grupo).getByRole('button', { name: nome }).focus())
}

test('objeto: a cor base marca e desmarca pela tecla, com o foco no grupo das cores', async () => {
  const { usuario, formulario, grupo } = await abrirOFormularioDoObjeto()
  expect(corMarcada(grupo, 'azul')).toBe(true)

  focarNaCor(grupo, 'azul')
  await usuario.keyboard('v')
  expect(corMarcada(grupo, 'vermelho')).toBe(true)
  await usuario.keyboard('z')
  expect(corMarcada(grupo, 'azul')).toBe(false)
  await usuario.click(formulario.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoes).toHaveLength(1))
  expect(JSON.parse(correcoes[0].valor as string).cor_base).toEqual(['vermelho'])
})

test('objeto: a cor base pelo clique recusa a terceira e diz por quê; desmarcar libera a vaga', async () => {
  const { usuario, grupo } = await abrirOFormularioDoObjeto()

  await usuario.click(within(grupo).getByRole('button', { name: 'verde' }))
  expect(corMarcada(grupo, 'verde')).toBe(true)
  await usuario.click(within(grupo).getByRole('button', { name: 'roxo' }))
  expect(corMarcada(grupo, 'roxo')).toBe(false)
  expect((await screen.findByRole('alert')).textContent).toMatch(/no máximo 2/i)

  await usuario.click(within(grupo).getByRole('button', { name: 'azul' }))
  await usuario.click(within(grupo).getByRole('button', { name: 'roxo' }))
  expect(corMarcada(grupo, 'roxo')).toBe(true)
  expect(screen.queryByRole('alert')).toBeNull()
})

test('objeto: a terceira cor pela tecla também não marca', async () => {
  const { usuario, grupo } = await abrirOFormularioDoObjeto()
  focarNaCor(grupo, 'azul')
  await usuario.keyboard('v')
  await usuario.keyboard('l')
  expect(corMarcada(grupo, 'laranja')).toBe(false)
  expect(screen.getByRole('alert').textContent).toMatch(/no máximo 2/i)
})

test('objeto: as letras das cores não agem com o foco num campo de texto', async () => {
  const { usuario, formulario, grupo } = await abrirOFormularioDoObjeto()
  const detalhe = formulario.getByLabelText('Detalhe')
  await usuario.click(detalhe)
  await usuario.keyboard('vl')

  expect((detalhe as HTMLInputElement).value).toBe('vl')
  expect(corMarcada(grupo, 'vermelho')).toBe(false)
  expect(corMarcada(grupo, 'laranja')).toBe(false)
})

test('objeto: as teclas das cores entram na lista do ?', async () => {
  const { usuario, grupo } = await abrirOFormularioDoObjeto()
  focarNaCor(grupo, 'azul')
  await usuario.keyboard('?')
  const tabela = await screen.findByRole('table', { name: 'Cor base do objeto' })
  expect(within(tabela).getByText('V')).toBeTruthy()
  expect(within(tabela).getByText('Marcar ou desmarcar vermelho')).toBeTruthy()
})
