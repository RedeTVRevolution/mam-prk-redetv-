import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { render } from './render-teste.tsx'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from './api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import catalogo from './catalogo.fixture.json'
import Video from './Video.tsx'

// Segue o esquema 1.2 (api/decupagem.py).
const decupagem = {
  versao_esquema: '1.2',
  video: { sha256: 'a'.repeat(64), duracao_ms: 180_000 },
  programa: { resumo: 'Jornal', blocos: [] },
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'sério', inicio_ms: 30_000, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Ana Souza',
      origem: 'modelo',
      fontes_do_nome: ['rosto', 'gc'],
      na_imagem: [
        { inicio_ms: 5_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'apresentadora', visual: 'terno azul' },
      ],
      citada_na_fala: [{ inicio_ms: 65_000, fim_ms: 66_000 }],
      citada_no_texto: [{ inicio_ms: 70_000, fim_ms: 72_000, texto: '<b>Ana</b> no GC' }],
    },
  ],
  planos: [
    { id: 'pl1', ambiente: 'estúdio', plano_limpo: false, acao: null, inicio_ms: 0, fim_ms: 4_000 },
    { id: 'pl2', ambiente: 'rua', plano_limpo: true, acao: 'carro passa', objetos: ['carro', 'poste'], inicio_ms: 140_000, fim_ms: 150_000 },
  ],
  comerciais: [
    { id: 'com000', marca: 'Marca X', tipo: 'intervalo', evidencias: ['logo', 'fala'], inicio_ms: 90_000, fim_ms: 120_000 },
  ],
  transcricao: [{ id: 'fal000', locutor: 'Locutor', texto: 'Boa noite', inicio_ms: 1_000, fim_ms: 3_000 }],
  textos_na_tela: [{ id: 'txt000', inicio_ms: 125_000, fim_ms: 130_000, tipo: 'gc', texto: 'Ana Souza, apresentadora' }],
}

// A mesma decupagem no esquema 1.1: sem os campos novos e com a evidência do comercial em texto.
const decupagem11 = {
  ...decupagem,
  versao_esquema: '1.1',
  pautas: decupagem.pautas.map(({ tom: _tom, ...p }) => p),
  pessoas: decupagem.pessoas.map(({ fontes_do_nome: _f, ...p }) => ({
    ...p,
    na_imagem: p.na_imagem.map(({ papel: _p, visual: _v, ...a }) => a),
  })),
  comerciais: decupagem.comerciais.map(({ evidencias: _e, ...c }) => ({ ...c, evidencia: 'logo na tela' })),
  textos_na_tela: undefined,
}

const TOKEN = 'Bearer token-de-ana@redetv.com.br'
let statusDecupagem = 200
let corrigida = false
let correcaoRecebida: unknown = null
let correcoesRecebidas: { tipo: string }[] = []
let pautaCorrigida = false
let statusDoPost = 201
// A versão é o SHA-256 do JSON do modelo: correção não a muda, reprocessar sim.
let versaoAtual = 'v1'
let pedidosDeReproducao = 0
let links: { url: string; expira_em: string }[] = []

const item = (campos: Record<string, unknown>) => ({
  id: 'c1',
  job_id: 'j1',
  tipo: 'pessoa.renomear',
  item_id: 'p1',
  ancora: { versao: 'v1', tipo_do_item: 'pessoa' },
  autor_email: 'bia@redetv.com.br',
  criada_em: '2026-10-30T12:00:00Z',
  motivo: 'sobrenome completo',
  antes: 'Ana Souza',
  depois: 'Ana Souza Lima',
  antes_legivel: 'Ana Souza',
  depois_legivel: 'Ana Souza Lima',
  desfaz: null,
  estado: 'ativa',
  ...campos,
})
let desfeita = false
let desfazerDa409 = false
let desfazerRecebido: unknown = null
let pedidosDeHistorico = 0
let reaplicada = false
// Correção de Editor que espera o Curador; depois da decisão, segue aprovada ou recusada.
let aguardandoCurador = false
let decisaoDoCurador: { acao: string; corpo: unknown } | null = null
const handlersDoHistorico = [
  http.get('/v1/jobs/j1/correcoes', () => {
    pedidosDeHistorico += 1
    if (aguardandoCurador) {
      const estado = decisaoDoCurador === null ? 'pendente' : decisaoDoCurador.acao === 'aprovar' ? 'aprovada' : 'recusada'
      return HttpResponse.json([item({ estado, exige_aprovacao: true })])
    }
    if (reaplicada)
      return HttpResponse.json([
        item({ id: 'c1-resolvida', reaplica: 'c1', criada_em: '2026-10-30T13:00:00Z' }),
        item({ estado: 'reaplicada' }),
      ])
    return HttpResponse.json(
      desfeita
        ? [
            item({
              id: 'd1',
              tipo: 'desfazer',
              desfaz: 'c1',
              antes: 'Ana Souza Lima',
              depois: 'Ana Souza',
              antes_legivel: 'Ana Souza Lima',
              depois_legivel: 'Ana Souza',
              motivo: 'erro meu',
              criada_em: '2026-10-30T13:00:00Z',
            }),
            item({ estado: 'desfeita' }),
          ]
        : [item({})],
    )
  }),
  http.post('/v1/jobs/j1/correcoes/c1/:acao', async ({ request, params }) => {
    if (params.acao === 'desfazer') return undefined
    decisaoDoCurador = {
      acao: String(params.acao),
      corpo: params.acao === 'recusar' ? await request.json() : null,
    }
    if (params.acao === 'aprovar') corrigida = true
    return HttpResponse.json({ id: 'c1-decidida' }, { status: 201 })
  }),
  http.post('/v1/jobs/j1/correcoes/c1/desfazer', async ({ request }) => {
    desfazerRecebido = await request.json()
    // Simula outro Editor que desfez antes: o servidor já tem o desfazer.
    desfeita = true
    corrigida = false
    if (desfazerDa409) return new HttpResponse(null, { status: 409 })
    return HttpResponse.json({ id: 'd1' }, { status: 201 })
  }),
]

const itemDaFila = {
  ...item({ id: 'c1' }),
  ancora: { identidade: 'ana souza', inicio_ms: 5_000, fim_ms: 20_000 },
  candidatos: [
    { item_id: 'p7', nome: 'Carla Dias', inicio_ms: 4_000, fim_ms: 18_000 },
    { item_id: 'p8', nome: 'Davi Lima', inicio_ms: 10_000, fim_ms: 12_000 },
  ],
}
let fila: (typeof itemDaFila)[] = []
let pedidosDaFila = 0
let resolucaoRecebida: { acao: string; corpo: unknown } | null = null
let resolucaoDa409 = false
const handlersDaFila = [
  http.get('/v1/jobs/j1/fila', () => {
    pedidosDaFila += 1
    return HttpResponse.json(fila)
  }),
  http.post('/v1/jobs/j1/fila/c1/:acao', async ({ request, params }) => {
    resolucaoRecebida = { acao: String(params.acao), corpo: await request.json() }
    fila = []
    if (resolucaoDa409) return new HttpResponse(null, { status: 409 })
    if (params.acao === 'reaplicar') corrigida = true
    return HttpResponse.json({ id: 'c1-resolvida' }, { status: 201 })
  }),
]

const servidor = setupServer(
  http.get('/v1/correcoes/catalogo', () => HttpResponse.json(catalogo)),
  ...handlersDoHistorico,
  ...handlersDaFila,
  http.get('/v1/jobs/j1/reproducao', ({ request }) => {
    if (request.headers.get('Authorization') !== TOKEN) return new HttpResponse(null, { status: 401 })
    pedidosDeReproducao += 1
    return HttpResponse.json(
      links.shift() ?? { url: 'https://storage.exemplo/proxy/j1', expira_em: '2999-01-01T00:00:00Z' },
    )
  }),
  http.get('/v1/jobs/j1/decupagem', ({ request }) => {
    if (request.headers.get('Authorization') !== TOKEN) return new HttpResponse(null, { status: 401 })
    const base = pautaCorrigida
      ? {
          ...decupagem,
          pautas: [
            { ...decupagem.pautas[0], titulo: 'Eleição 2026', inicio_ms: 32_000, origem: 'revisao' },
          ],
        }
      : decupagem
    const entregue = corrigida
      ? { ...base, versao_decupagem: versaoAtual, pessoas: [{ ...decupagem.pessoas[0], nome: 'Ana Souza Lima', origem: 'revisao' }] }
      : { ...base, versao_decupagem: versaoAtual }
    return statusDecupagem === 200
      ? HttpResponse.json(entregue)
      : new HttpResponse(null, { status: statusDecupagem })
  }),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcaoRecebida = await request.json()
    correcoesRecebidas.push(correcaoRecebida as { tipo: string })
    if (statusDoPost !== 201) return new HttpResponse(null, { status: statusDoPost })
    if ((correcaoRecebida as { versao: string }).versao !== versaoAtual)
      return new HttpResponse(null, { status: 409 })
    if ((correcaoRecebida as { tipo: string }).tipo === 'pessoa.renomear') corrigida = true
    else pautaCorrigida = true
    return HttpResponse.json({ id: 'c1', versao_decupagem: versaoAtual }, { status: 201 })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  statusDecupagem = 200
  corrigida = false
  correcaoRecebida = null
  correcoesRecebidas = []
  pautaCorrigida = false
  statusDoPost = 201
  versaoAtual = 'v1'
  pedidosDeReproducao = 0
  desfeita = false
  desfazerDa409 = false
  desfazerRecebido = null
  pedidosDeHistorico = 0
  reaplicada = false
  aguardandoCurador = false
  decisaoDoCurador = null
  fila = []
  pedidosDaFila = 0
  resolucaoRecebida = null
  resolucaoDa409 = false
  links = []
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(
  job: { estado: string; codigo_falha?: string | null },
  podeEditar = false,
  podeAprovar = false,
) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(
    <Video
      api={criarClienteDaApi(auth, () => {})}
      job={{ id: 'j1', nome: 'clipe.mp4', codigo_falha: null, ...job }}
      podeEditar={podeEditar}
      podeAprovar={podeAprovar}
    />,
  )
}

async function jogador() {
  return (await screen.findByLabelText('Player')) as HTMLVideoElement
}

function irPara(player: HTMLVideoElement, segundos: number) {
  player.currentTime = segundos
  fireEvent.timeUpdate(player)
}

const aba = (nome: string) => screen.getByRole('radio', { name: nome })

test('mostra o player com o link assinado e o timecode atual / duração', async () => {
  await abrir({ estado: 'concluido' })

  const player = await jogador()
  expect(player.getAttribute('src')).toBe('https://storage.exemplo/proxy/j1')
  // Antes do metadata, a duração é o maior fim_ms da decupagem.
  expect(screen.getByText('00:00 / 02:30')).toBeTruthy()
  Object.defineProperty(player, 'duration', { value: 180, configurable: true })
  fireEvent.loadedMetadata(player)
  irPara(player, 75)
  expect(screen.getByText('01:15 / 03:00')).toBeTruthy()
})

test('aba Pessoas separa quem aparece de quem só é citado', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()

  const painel = within(screen.getByLabelText('Decupagem'))
  expect(painel.getByText('Aparecem na imagem')).toBeTruthy()
  expect(painel.getByText('Só citadas (não contam como tempo de tela)')).toBeTruthy()
  const quadro = painel.getByRole('button', { name: '00:05 · rosto' })
  expect(quadro.querySelector('video')?.getAttribute('src')).toBe(
    'https://storage.exemplo/proxy/j1#t=6',
  )
  await usuario.click(quadro)
  expect(player.currentTime).toBe(5)

  await usuario.click(painel.getByRole('button', { name: 'fala 01:05' }))
  expect(player.currentTime).toBe(65)
  await usuario.click(painel.getByRole('button', { name: 'texto 01:10' }))
  expect(player.currentTime).toBe(70)
})

test('aba Pessoas mostra as fontes do nome e o papel e o visual de cada aparição', async () => {
  await abrir({ estado: 'concluido' })
  await jogador()

  const painel = within(screen.getByLabelText('Decupagem'))
  const fontes = within(painel.getByLabelText('Fontes do nome de Ana Souza'))
  expect(fontes.getByText('rosto')).toBeTruthy()
  expect(fontes.getByText('GC')).toBeTruthy()
  expect(painel.getByText('apresentadora · terno azul')).toBeTruthy()
})

test('quem só é citado também mostra as fontes do nome', async () => {
  const citada = {
    id: 'p2',
    nome: 'Andréa Corazza',
    origem: 'modelo',
    fontes_do_nome: ['fala'],
    na_imagem: [],
    citada_na_fala: [{ inicio_ms: 100_000, fim_ms: 102_000 }],
    citada_no_texto: [],
  }
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({ ...decupagem, pessoas: [...decupagem.pessoas, citada] }),
    ),
  )
  await abrir({ estado: 'concluido' })
  await jogador()

  const painel = within(screen.getByLabelText('Decupagem'))
  const fontes = within(painel.getByLabelText('Fontes do nome de Andréa Corazza'))
  expect(fontes.getByText('fala')).toBeTruthy()
  // Quem aparece e também é citado mostra as fontes uma vez só.
  expect(painel.getAllByLabelText('Fontes do nome de Ana Souza')).toHaveLength(1)
})

test('aba Texto na tela lista tempo, tipo e texto, e salta', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(aba('Texto na tela'))

  const painel = within(screen.getByLabelText('Decupagem'))
  expect(painel.getByText('02:05 · gc')).toBeTruthy()
  await usuario.click(painel.getByText('Ana Souza, apresentadora'))
  expect(player.currentTime).toBe(125)
})

test('decupagem 1.1, sem os campos novos, abre e mostra a evidência em texto', async () => {
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagem11)))
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  await jogador()
  const painel = within(screen.getByLabelText('Decupagem'))

  expect(painel.getByRole('button', { name: '00:05 · rosto' })).toBeTruthy()
  expect(painel.queryByLabelText('Fontes do nome de Ana Souza')).toBeNull()
  expect(screen.queryByLabelText(/^Texto na tela /)).toBeNull()
  await usuario.click(aba('Marcas'))
  expect(painel.getByText('logo na tela')).toBeTruthy()
  await usuario.click(aba('Pautas'))
  expect(painel.getByText('Eleição')).toBeTruthy()
  expect(painel.queryByText('sério')).toBeNull()
  await usuario.click(aba('Texto na tela'))
  expect(painel.queryByText('Ana Souza, apresentadora')).toBeNull()
})

test('o texto da tela aparece escapado, nunca como HTML', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  await jogador()

  await usuario.hover(screen.getByRole('button', { name: 'texto 01:10' }))

  expect(await screen.findByText('<b>Ana</b> no GC')).toBeTruthy()
  expect(document.querySelector('b')).toBeNull()
})

test('aba Pautas salta o player e destaca a pauta em curso', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(aba('Pautas'))

  const pauta = screen.getByText('Eleição').closest('a, button') as HTMLElement
  expect(screen.getByText('00:30–01:00')).toBeTruthy()
  expect(within(pauta).getByText('sério')).toBeTruthy()
  expect(pauta.hasAttribute('data-active')).toBe(false)
  await usuario.click(pauta)
  expect(player.currentTime).toBe(30)
  irPara(player, 40)
  expect(pauta.hasAttribute('data-active')).toBe(true)
  irPara(player, 61)
  expect(pauta.hasAttribute('data-active')).toBe(false)
})

test('aba Marcas lista os comerciais e salta', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(aba('Marcas'))

  expect(screen.getByText('intervalo · 01:30')).toBeTruthy()
  const marca = screen.getByText('Marca X').closest('a, button') as HTMLElement
  expect(within(marca).getByText('logo')).toBeTruthy()
  expect(within(marca).getByText('fala')).toBeTruthy()
  await usuario.click(screen.getByText('Marca X'))
  expect(player.currentTime).toBe(90)
})

test('aba Planos usa a ação, ou o ambiente se não houver, e salta', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(aba('Planos'))

  expect(screen.getByText('estúdio', { selector: 'p' })).toBeTruthy()
  expect(screen.getByText('rua · 02:20')).toBeTruthy()
  expect(screen.getByText('carro, poste')).toBeTruthy()
  await usuario.click(screen.getByText('carro passa'))
  expect(player.currentTime).toBe(140)
})

test('aba Fala destaca a fala em curso e salta', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(aba('Fala'))

  expect(screen.getByText('00:01 LOCUTOR')).toBeTruthy()
  const fala = screen.getByText('Boa noite').closest('button') as HTMLElement
  expect(fala.getAttribute('aria-current')).toBeNull()
  await usuario.click(fala)
  expect(player.currentTime).toBe(1)
  irPara(player, 2)
  expect(fala.getAttribute('aria-current')).toBe('true')
})

test('clicar numa ocorrência da linha do tempo leva o player ao início dela', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()

  await usuario.click(screen.getByLabelText('Pautas 00:30'))
  expect(player.currentTime).toBe(30)
  await usuario.click(screen.getByLabelText('Aparições 00:05'))
  expect(player.currentTime).toBe(5)
  await usuario.click(screen.getByLabelText('Menções 01:05'))
  expect(player.currentTime).toBe(65)
  await usuario.click(screen.getByLabelText('Menções 01:10'))
  expect(player.currentTime).toBe(70)
  await usuario.click(screen.getByLabelText('Comerciais 01:30'))
  expect(player.currentTime).toBe(90)
  await usuario.click(screen.getByLabelText('Planos 02:20'))
  expect(player.currentTime).toBe(140)
  await usuario.click(screen.getByLabelText('Fala 00:01'))
  expect(player.currentTime).toBe(1)
  await usuario.click(screen.getByLabelText('Texto na tela 02:05'))
  expect(player.currentTime).toBe(125)
})

test('ocorrências sobrepostas ficam no seu tempo, sem empurrar as seguintes', async () => {
  const pessoa = decupagem.pessoas[0]
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({
        ...decupagem,
        pessoas: [
          {
            ...pessoa,
            na_imagem: [
              { inicio_ms: 5_000, fim_ms: 20_000, evidencia: 'rosto' },
              { inicio_ms: 10_000, fim_ms: 15_000, evidencia: 'rosto' },
              { inicio_ms: 18_000, fim_ms: 25_000, evidencia: 'rosto' },
              { inicio_ms: 30_000, fim_ms: 40_000, evidencia: 'rosto' },
            ],
          },
        ],
      }),
    ),
  )
  await abrir({ estado: 'concluido' })
  await jogador()

  // Duração de 150 s (maior fim_ms): cada segundo vale 1/1,5 %.
  const valor = (secao: Element | null) => Number(secao?.getAttribute('aria-valuenow'))
  const largura = (rotulo: string) => valor(screen.getByLabelText(rotulo))
  const vaoAntes = (rotulo: string) => valor(screen.getByLabelText(rotulo).previousElementSibling)
  expect(largura('Aparições 00:05')).toBeCloseTo(15 / 1.5)
  // A de 10–15 s fica coberta pela de 5–20 s; a de 18–25 s só desenha o que sobra.
  expect(screen.queryByLabelText('Aparições 00:10')).toBeNull()
  expect(largura('Aparições 00:18')).toBeCloseTo(5 / 1.5)
  expect(vaoAntes('Aparições 00:30')).toBeCloseTo(5 / 1.5)
  expect(largura('Aparições 00:30')).toBeCloseTo(10 / 1.5)
})

test('sem duração no player, a linha do tempo segue a da decupagem', async () => {
  await abrir({ estado: 'concluido' })
  const player = await jogador()

  Object.defineProperty(player, 'duration', { value: Infinity, configurable: true })
  fireEvent.loadedMetadata(player)

  expect(screen.getByText('00:00 / 02:30')).toBeTruthy()
  expect(screen.getByRole('slider').getAttribute('aria-valuemax')).toBe('150000')
})

test('arrastar a cabeça de leitura move o player', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()

  screen.getByRole('slider').focus()
  await usuario.keyboard('{ArrowRight}')

  expect(player.currentTime).toBe(1)
})

test('o painel traz o botão de baixar e nenhum botão de voltar próprio', async () => {
  await abrir({ estado: 'concluido' })
  await jogador()

  expect(screen.queryByText('Voltar à Biblioteca')).toBeNull()
  expect(screen.getByLabelText('Baixar decupagem (JSON)')).toBeTruthy()
})

test('link expirado: o player pede outro e volta ao mesmo ponto', async () => {
  links = [
    { url: 'https://storage.exemplo/proxy/j1?v=1', expira_em: '2000-01-01T00:00:00Z' },
    { url: 'https://storage.exemplo/proxy/j1?v=2', expira_em: '2999-01-01T00:00:00Z' },
  ]
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(screen.getByLabelText('Pautas 00:30'))

  fireEvent.error(player)

  await waitFor(() => expect(player.getAttribute('src')).toBe('https://storage.exemplo/proxy/j1?v=2'))
  player.currentTime = 0
  fireEvent.loadedMetadata(player)
  expect(player.currentTime).toBe(30)
})

test('erro do player com link ainda válido não pede outro link', async () => {
  let pedidos = 0
  servidor.events.on('request:start', ({ request }) => {
    if (request.url.endsWith('/reproducao')) pedidos++
  })
  await abrir({ estado: 'concluido' })
  const player = await jogador()

  fireEvent.error(player)
  await new Promise((r) => setTimeout(r, 20))

  expect(pedidos).toBe(1)
  expect(player.getAttribute('src')).toBe('https://storage.exemplo/proxy/j1')
  servidor.events.removeAllListeners()
})

test('Job falhou mostra o código em vez do player, sem chamar a API', async () => {
  await abrir({ estado: 'falhou', codigo_falha: 'codec_nao_suportado' })

  expect((await screen.findByRole('alert')).textContent).toContain('codec_nao_suportado')
  expect(screen.queryByLabelText('Player')).toBeNull()
})

test('o botão baixa a decupagem em JSON', async () => {
  const usuario = userEvent.setup()
  const blobs: Blob[] = []
  URL.createObjectURL = (b: Blob | MediaSource) => {
    blobs.push(b as Blob)
    return 'blob:x'
  }
  URL.revokeObjectURL = () => {}
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await abrir({ estado: 'concluido' })
  await jogador()

  await usuario.click(screen.getByLabelText('Baixar decupagem (JSON)'))

  expect(clique).toHaveBeenCalledOnce()
  expect(JSON.parse(await blobs[0]!.text())).toEqual({ ...decupagem, versao_decupagem: 'v1' })
})

test('falha ao carregar o catálogo de correções mostra aviso', async () => {
  servidor.use(http.get('/v1/correcoes/catalogo', () => new HttpResponse(null, { status: 503 })))
  await abrir({ estado: 'concluido' })

  expect((await screen.findByRole('alert')).textContent).toContain('Não foi possível')
})

test('falha ao carregar mostra aviso', async () => {
  statusDecupagem = 503
  await abrir({ estado: 'concluido' })

  expect((await screen.findByRole('alert')).textContent).toContain('Não foi possível')
})

test('o Editor corrige o nome da pessoa pelo modal e vê o selo de revisão', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))

  await usuario.click((await painel.findAllByRole('button', { name: 'Corrigir Ana Souza' }))[0]!)
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Nome'))
  await usuario.type(modal.getByLabelText('Nome'), 'Ana Souza Lima')
  await usuario.type(modal.getByLabelText('Motivo'), 'sobrenome completo')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect((await painel.findAllByText('Ana Souza Lima')).length).toBeGreaterThan(0)
  expect(painel.getAllByText('revisado').length).toBeGreaterThan(0)
  // Só o painel recarrega: o player não pede outro link nem volta ao início.
  expect(pedidosDeReproducao).toBe(1)
  expect(correcaoRecebida).toEqual({
    tipo: 'pessoa.renomear',
    item_id: 'p1',
    valor: 'Ana Souza Lima',
    motivo: 'sobrenome completo',
    versao: 'v1',
  })
})

test('o Editor corrige título, resumo e tempos da pauta pelo modal e vê o selo', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Título'))
  await usuario.type(modal.getByLabelText('Título'), 'Eleição 2026')
  await usuario.clear(modal.getByLabelText('Resumo'))
  await usuario.type(modal.getByLabelText('Resumo'), 'Debate completo')
  await usuario.clear(modal.getByLabelText('Início (mm:ss)'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '00:32')
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste da pauta')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect(await painel.findByText('Eleição 2026')).toBeTruthy()
  expect(painel.getByText('revisado')).toBeTruthy()
  expect(painel.getByText('00:32–01:00')).toBeTruthy()
  expect(correcoesRecebidas).toEqual([
    { tipo: 'pauta.titulo', valor: 'Eleição 2026', item_id: 'pa1', motivo: 'ajuste da pauta', versao: 'v1' },
    { tipo: 'pauta.resumo', valor: 'Debate completo', item_id: 'pa1', motivo: 'ajuste da pauta', versao: 'v1' },
    { tipo: 'item.tempos', valor: '32000-60000', item_id: 'pa1', motivo: 'ajuste da pauta', versao: 'v1' },
  ])
})

test('o modal da pauta só envia o que mudou e não salva início depois do fim', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste')
  const salvar = modal.getByRole('button', { name: 'Salvar' }) as HTMLButtonElement
  expect(salvar.disabled).toBe(true)

  await usuario.clear(modal.getByLabelText('Início (mm:ss)'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '02:00')

  expect(modal.getByText('O início não pode vir depois do fim.')).toBeTruthy()
  expect(salvar.disabled).toBe(true)
  await usuario.clear(modal.getByLabelText('Início (mm:ss)'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '00:31')
  expect(salvar.disabled).toBe(false)
  await usuario.click(salvar)
  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toMatchObject({ tipo: 'item.tempos', valor: '31000-60000' })
})

test('tempos recusados pela API (422) mostram o aviso no modal da pauta', async () => {
  statusDoPost = 422
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Fim (mm:ss)'))
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '99:00')
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste')

  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect((await modal.findByRole('alert')).textContent).toContain('duração do vídeo')
})

test('mudar só o início da pauta mantém os milissegundos do fim', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({
        ...decupagem,
        versao_decupagem: 'v1',
        pautas: [{ ...decupagem.pautas[0], inicio_ms: 30_250, fim_ms: 60_500 }],
      }),
    ),
  )
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Início (mm:ss)'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '00:31')
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste')

  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toMatchObject({ tipo: 'item.tempos', valor: '31000-60500' })
})

test('depois de uma falha no meio, salvar de novo não reenvia o que já foi gravado', async () => {
  servidor.use(
    http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
      const corpo = (await request.json()) as { tipo: string; valor: string }
      correcoesRecebidas.push(corpo)
      if (corpo.tipo === 'item.tempos' && corpo.valor.endsWith('-5940000'))
        return new HttpResponse(null, { status: 422 })
      pautaCorrigida = true
      return HttpResponse.json({ id: 'c1', versao_decupagem: 'v1' }, { status: 201 })
    }),
  )
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Título'))
  await usuario.type(modal.getByLabelText('Título'), 'Eleição 2026')
  await usuario.clear(modal.getByLabelText('Fim (mm:ss)'))
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '99:00')
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))
  expect((await modal.findByRole('alert')).textContent).toContain('duração do vídeo')

  await usuario.clear(modal.getByLabelText('Fim (mm:ss)'))
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '01:10')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect(await painel.findByText('Eleição 2026')).toBeTruthy()
  expect(correcoesRecebidas.map((c) => c.tipo)).toEqual(['pauta.titulo', 'item.tempos', 'item.tempos'])
})

test('apagar o resumo da pauta não deixa salvar', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Resumo'))
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste')

  expect(modal.getByText('O resumo não pode ficar vazio')).toBeTruthy()
  expect((modal.getByRole('button', { name: 'Salvar' }) as HTMLButtonElement).disabled).toBe(true)
})

test('o histórico mostra um título com hífen como texto, e os tempos como mm:ss', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/correcoes', () =>
      HttpResponse.json([
        item({ id: 'c2', tipo: 'pauta.titulo', item_id: 'pa1', antes: 'Eleição', depois: '2018-2022', antes_legivel: 'Eleição', depois_legivel: '2018-2022' }),
        item({ id: 'c3', tipo: 'item.tempos', item_id: 'pa1', antes: '30000-60000', depois: '32000-60000', antes_legivel: '00:30–01:00', depois_legivel: '00:32–01:00' }),
      ]),
    ),
  )
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)

  expect(await gaveta.findByText('2018-2022')).toBeTruthy()
  expect(gaveta.getByText('00:32–01:00')).toBeTruthy()
})

test('o histórico mostra o tom com acento e o tom livre antigo como veio', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/correcoes', () =>
      HttpResponse.json([item({ id: 'c2', tipo: 'pauta.tom', item_id: 'pa1', antes: 'tenso', depois: 'analise', antes_legivel: 'tenso', depois_legivel: 'análise' })]),
    ),
  )
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)

  expect(await gaveta.findByText('análise')).toBeTruthy()
  expect(gaveta.getByText('tenso')).toBeTruthy()
})

test('quem não tem decupagem.editar não vê o botão de corrigir a pauta', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, false)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))

  expect(await painel.findByText('Eleição')).toBeTruthy()
  expect(painel.queryByRole('button', { name: /Corrigir/ })).toBeNull()
})

test('quem não tem decupagem.editar não vê o botão de corrigir', async () => {
  await abrir({ estado: 'concluido' }, false)
  const painel = within(await screen.findByLabelText('Decupagem'))

  expect(await painel.findAllByText('Ana Souza')).not.toHaveLength(0)
  expect(painel.queryByRole('button', { name: /Corrigir/ })).toBeNull()
})

test('correção sobre versão desatualizada recarrega o painel e salva na segunda tentativa', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  versaoAtual = 'v2'

  await usuario.click((await painel.findAllByRole('button', { name: 'Corrigir Ana Souza' }))[0]!)
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Nome'))
  await usuario.type(modal.getByLabelText('Nome'), 'Ana Souza Lima')
  await usuario.type(modal.getByLabelText('Motivo'), 'sobrenome completo')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect((await modal.findByRole('alert')).textContent).toContain('foi recarregada')
  await waitFor(() =>
    expect((modal.getByRole('button', { name: 'Salvar' }) as HTMLButtonElement).disabled).toBe(false),
  )
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect((await painel.findAllByText('Ana Souza Lima')).length).toBeGreaterThan(0)
  expect(correcaoRecebida).toMatchObject({ versao: 'v2' })
})

async function abrirHistorico(usuario: ReturnType<typeof userEvent.setup>) {
  await abrir({ estado: 'concluido' }, true)
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  return within(await screen.findByRole('dialog', { name: 'Histórico' }))
}

test('o histórico liga a reaplicação à original, que fica reaplicada e sem desfazer', async () => {
  reaplicada = true
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)

  expect(await gaveta.findByText(/^Reaplica a correção de /)).toBeTruthy()
  expect(gaveta.getByText('reaplicada')).toBeTruthy()
  expect(gaveta.getAllByRole('button', { name: 'Desfazer' })).toHaveLength(1)
})

test('a gaveta de histórico lista quem, quando, antes, depois e motivo', async () => {
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)

  expect(await gaveta.findByText('bia@redetv.com.br')).toBeTruthy()
  expect(gaveta.getByText('Ana Souza')).toBeTruthy()
  expect(gaveta.getByText('Ana Souza Lima')).toBeTruthy()
  expect(gaveta.getByText('sobrenome completo')).toBeTruthy()
  expect(gaveta.getByText(/30\/10\/2026/)).toBeTruthy()
  expect(gaveta.getByRole('button', { name: 'Desfazer' })).toBeTruthy()
})

test('desfazer pede o motivo, grava e recarrega histórico e decupagem', async () => {
  corrigida = true
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)
  const painel = within(screen.getByLabelText('Decupagem'))
  expect((await painel.findAllByText('Ana Souza Lima')).length).toBeGreaterThan(0)

  await usuario.click(await gaveta.findByRole('button', { name: 'Desfazer' }))
  const modal = within(await screen.findByRole('dialog', { name: 'Desfazer correção' }))
  const confirmar = modal.getByRole('button', { name: 'Confirmar' }) as HTMLButtonElement
  expect(confirmar.disabled).toBe(true)
  await usuario.type(modal.getByLabelText('Motivo'), 'erro meu')
  await usuario.click(confirmar)

  await waitFor(() => expect(desfazerRecebido).toEqual({ motivo: 'erro meu' }))
  expect(await gaveta.findByText('desfeita')).toBeTruthy()
  expect(gaveta.getByText('erro meu')).toBeTruthy()
  // A correção desfeita e o próprio desfazer não oferecem "Desfazer".
  expect(gaveta.queryByRole('button', { name: 'Desfazer' })).toBeNull()
  await waitFor(() => expect(painel.queryByText('Ana Souza Lima')).toBeNull())
  expect(painel.getAllByText('Ana Souza').length).toBeGreaterThan(0)
})

test('desfazer que dá 409 avisa e recarrega histórico e decupagem', async () => {
  corrigida = true
  desfazerDa409 = true
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)
  const painel = within(screen.getByLabelText('Decupagem'))

  await usuario.click(await gaveta.findByRole('button', { name: 'Desfazer' }))
  const modal = within(await screen.findByRole('dialog', { name: 'Desfazer correção' }))
  await usuario.type(modal.getByLabelText('Motivo'), 'erro meu')
  await usuario.click(modal.getByRole('button', { name: 'Confirmar' }))

  expect(await modal.findByRole('alert')).toBeTruthy()
  expect(await gaveta.findByText('desfeita')).toBeTruthy()
  await waitFor(() => expect(painel.queryByText('Ana Souza Lima')).toBeNull())
})

test('o item com correção pendente mostra o selo', async () => {
  aguardandoCurador = true
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))

  expect((await painel.findAllByText('aguardando Curador')).length).toBeGreaterThan(0)
})

test('a pendente de outra versão da decupagem não põe o selo', async () => {
  aguardandoCurador = true
  versaoAtual = 'v2'
  await abrir({ estado: 'concluido' }, true)
  await screen.findByLabelText('Decupagem')
  await waitFor(() => expect(pedidosDeHistorico).toBeGreaterThan(0))

  expect(screen.queryByText('aguardando Curador')).toBeNull()
})

test('o Curador aprova na gaveta e a correção entra na decupagem', async () => {
  aguardandoCurador = true
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true, true)
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  const gaveta = within(await screen.findByRole('dialog', { name: 'Histórico' }))
  const painel = within(screen.getByLabelText('Decupagem'))

  expect(await gaveta.findByText('pendente')).toBeTruthy()
  expect(gaveta.queryByRole('button', { name: 'Desfazer' })).toBeNull()
  await usuario.click(gaveta.getByRole('button', { name: 'Aprovar' }))

  await waitFor(() => expect(decisaoDoCurador?.acao).toBe('aprovar'))
  expect(await gaveta.findByText('aprovada')).toBeTruthy()
  expect((await painel.findAllByText('Ana Souza Lima')).length).toBeGreaterThan(0)
  // O selo sai só quando o histórico, pedido depois da decupagem nova, chega.
  await waitFor(() => expect(painel.queryAllByText('aguardando Curador')).toHaveLength(0))
  // A aprovada é uma correção como as outras: dá para desfazer.
  expect(gaveta.getByRole('button', { name: 'Desfazer' })).toBeTruthy()
})

test('o Curador recusa pedindo o motivo, e a correção segue fora da decupagem', async () => {
  aguardandoCurador = true
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true, true)
  await usuario.click(await screen.findByRole('button', { name: 'Histórico' }))
  const gaveta = within(await screen.findByRole('dialog', { name: 'Histórico' }))

  await usuario.click(await gaveta.findByRole('button', { name: 'Recusar' }))
  const modal = within(await screen.findByRole('dialog', { name: 'Recusar correção' }))
  const confirmar = modal.getByRole('button', { name: 'Confirmar' }) as HTMLButtonElement
  expect(confirmar.disabled).toBe(true)
  await usuario.type(modal.getByLabelText('Motivo'), 'não confere')
  await usuario.click(confirmar)

  await waitFor(() => expect(decisaoDoCurador).toEqual({ acao: 'recusar', corpo: { motivo: 'não confere' } }))
  expect(await gaveta.findByText('recusada')).toBeTruthy()
  expect(gaveta.queryByRole('button', { name: 'Aprovar' })).toBeNull()
  expect(
    within(screen.getByLabelText('Decupagem')).queryByText('Ana Souza Lima'),
  ).toBeNull()
})

test('o Editor vê a pendente na gaveta, sem Aprovar nem Recusar', async () => {
  aguardandoCurador = true
  const usuario = userEvent.setup()
  const gaveta = await abrirHistorico(usuario)

  expect(await gaveta.findByText('pendente')).toBeTruthy()
  expect(gaveta.queryByRole('button', { name: 'Aprovar' })).toBeNull()
  expect(gaveta.queryByRole('button', { name: 'Recusar' })).toBeNull()
})

test('quem não tem decupagem.editar não vê o botão Histórico nem pede o histórico', async () => {
  pedidosDeHistorico = 0
  await abrir({ estado: 'concluido' }, false)
  await screen.findByLabelText('Decupagem')

  expect(screen.queryByRole('button', { name: 'Histórico' })).toBeNull()
  expect(pedidosDeHistorico).toBe(0)
})


test('selo "N na fila" abre o painel com antes, depois e candidatos', async () => {
  fila = [itemDaFila]
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)

  await usuario.click(await screen.findByRole('button', { name: '1 na fila' }))
  const painel = within(await screen.findByRole('dialog', { name: 'Fila de revisão' }))

  expect(painel.getByText('Ana Souza')).toBeTruthy()
  expect(painel.getByText('Ana Souza Lima')).toBeTruthy()
  expect(painel.getByText('sobrenome completo')).toBeTruthy()
  expect(painel.getByText('bia@redetv.com.br')).toBeTruthy()
  await usuario.click(painel.getByRole('combobox', { name: 'Candidato' }))
  expect(await painel.findByRole('option', { name: /Carla Dias/ })).toBeTruthy()
  expect(painel.getByRole('option', { name: /Davi Lima/ })).toBeTruthy()
})

test('sem fila não há selo', async () => {
  await abrir({ estado: 'concluido' }, true)
  await screen.findByLabelText('Decupagem')
  await waitFor(() => expect(pedidosDaFila).toBeGreaterThan(0))

  expect(screen.queryByRole('button', { name: /na fila/ })).toBeNull()
})

test('quem não tem decupagem.editar não vê o selo nem pede a fila', async () => {
  fila = [itemDaFila]
  await abrir({ estado: 'concluido' }, false)
  await screen.findByLabelText('Decupagem')

  expect(screen.queryByRole('button', { name: /na fila/ })).toBeNull()
  expect(pedidosDaFila).toBe(0)
})

async function abrirFila(usuario: ReturnType<typeof userEvent.setup>) {
  fila = [itemDaFila]
  await abrir({ estado: 'concluido' }, true)
  await usuario.click(await screen.findByRole('button', { name: '1 na fila' }))
  return within(await screen.findByRole('dialog', { name: 'Fila de revisão' }))
}

test('reaplicar no candidato escolhido pede o motivo, tira da fila e recarrega a decupagem', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirFila(usuario)
  const decupagemNaTela = within(screen.getByLabelText('Decupagem'))

  const reaplicar = painel.getByRole('button', { name: 'Reaplicar' }) as HTMLButtonElement
  expect(reaplicar.disabled).toBe(true)
  await usuario.click(painel.getByRole('combobox', { name: 'Candidato' }))
  await usuario.click(await painel.findByRole('option', { name: /Carla Dias/ }))
  await usuario.type(painel.getByLabelText('Motivo'), 'é a mesma pessoa')
  await usuario.click(reaplicar)

  await waitFor(() =>
    expect(resolucaoRecebida).toEqual({
      acao: 'reaplicar',
      corpo: { item_id: 'p7', motivo: 'é a mesma pessoa' },
    }),
  )
  expect(await painel.findByText('Nada na fila.')).toBeTruthy()
  expect((await decupagemNaTela.findAllByText('Ana Souza Lima')).length).toBeGreaterThan(0)
  expect(screen.queryByRole('button', { name: /na fila/ })).toBeNull()
})

test('descartar pede o motivo e tira da fila', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirFila(usuario)

  const descartar = painel.getByRole('button', { name: 'Descartar' }) as HTMLButtonElement
  expect(descartar.disabled).toBe(true)
  await usuario.type(painel.getByLabelText('Motivo'), 'não vale mais')
  await usuario.click(descartar)

  await waitFor(() =>
    expect(resolucaoRecebida).toEqual({ acao: 'descartar', corpo: { motivo: 'não vale mais' } }),
  )
  expect(await painel.findByText('Nada na fila.')).toBeTruthy()
})

test('resolver que dá 409 avisa e recarrega a fila', async () => {
  resolucaoDa409 = true
  const usuario = userEvent.setup()
  const painel = await abrirFila(usuario)

  await usuario.type(painel.getByLabelText('Motivo'), 'não vale mais')
  await usuario.click(painel.getByRole('button', { name: 'Descartar' }))

  expect((await painel.findByRole('alert')).textContent).toContain('não está mais na fila')
  expect(await painel.findByText('Nada na fila.')).toBeTruthy()
})

test('o Editor corrige marca, tipo e tempos do comercial pelo modal', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Marcas'))

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir comercial Marca X' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Marca'))
  await usuario.type(modal.getByLabelText('Marca'), 'Marca Y')
  await usuario.click(modal.getByRole('combobox', { name: 'Tipo' }))
  await usuario.click(await modal.findByRole('option', { name: 'marca_incidental' }))
  await usuario.clear(modal.getByLabelText('Início (mm:ss)'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '01:35')
  await usuario.type(modal.getByLabelText('Motivo'), 'ajuste')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(3))
  expect(correcoesRecebidas).toEqual([
    { tipo: 'comercial.marca', valor: 'Marca Y', item_id: 'com000', motivo: 'ajuste', versao: 'v1' },
    { tipo: 'comercial.tipo', valor: 'marca_incidental', item_id: 'com000', motivo: 'ajuste', versao: 'v1' },
    {
      tipo: 'item.tempos',
      tipo_do_item: 'comercial',
      valor: '95000-120000',
      item_id: 'com000',
      motivo: 'ajuste',
      versao: 'v1',
    },
  ])
})

test('o Editor acrescenta um comercial pelo modal', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Marcas'))

  await usuario.click(await painel.findByRole('button', { name: 'Acrescentar comercial' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Marca'), 'Loja Sol')
  await usuario.click(modal.getByRole('combobox', { name: 'Tipo' }))
  await usuario.click(await modal.findByRole('option', { name: 'merchan_apresentador' }))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '00:20')
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '00:22')
  await usuario.type(modal.getByLabelText('Motivo'), 'faltou')
  // Sem evidência marcada, não salva.
  expect(modal.getByRole('button', { name: 'Salvar' }).hasAttribute('disabled')).toBe(true)
  await usuario.click(modal.getByLabelText('produto'))
  await usuario.click(modal.getByLabelText('fala'))
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  const [enviada] = correcoesRecebidas as unknown as { tipo: string; valor: string; item_id: string }[]
  expect(enviada.tipo).toBe('comercial.acrescentar')
  expect(enviada.item_id).toBe('')
  expect(JSON.parse(enviada.valor)).toEqual({
    marca: 'Loja Sol',
    tipo: 'merchan_apresentador',
    inicio_ms: 20_000,
    fim_ms: 22_000,
    evidencias: ['fala', 'produto'],
  })
})

test('quem não edita não vê os botões de comercial', async () => {
  await abrir({ estado: 'concluido' }, false)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await userEvent.setup().click(aba('Marcas'))

  expect(await painel.findByText('Marca X')).toBeTruthy()
  expect(painel.queryByRole('button', { name: 'Acrescentar comercial' })).toBeNull()
  expect(painel.queryByRole('button', { name: /Corrigir comercial/ })).toBeNull()
})

async function abrirPessoas(usuario: ReturnType<typeof userEvent.setup>) {
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pessoas'))
  return painel
}

async function escolherNoMenu(
  usuario: ReturnType<typeof userEvent.setup>,
  painel: ReturnType<typeof within>,
  rotulo: string,
  item: string,
) {
  await usuario.click(await painel.findByRole('button', { name: rotulo }))
  await usuario.click(await within(await screen.findByRole('menu')).findByRole('menuitem', { name: item }))
  return within(await screen.findByRole('dialog'))
}

const OCORRENCIA_NA_IMAGEM = { lista: 'na_imagem', inicio_ms: 5_000, fim_ms: 20_000 }

test('o Editor marca "não é esta pessoa" numa aparição', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  const modal = await escolherNoMenu(usuario, painel, 'Ações de Ana Souza em 00:05', 'Não é esta pessoa')
  await usuario.type(modal.getByLabelText('Motivo'), 'outra pessoa')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toEqual({
    tipo: 'pessoa.nao_e',
    item_id: 'p1',
    ocorrencia: OCORRENCIA_NA_IMAGEM,
    valor: 'Não identificado',
    motivo: 'outra pessoa',
    versao: 'v1',
  })
})

test('o Editor troca aparição por menção', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  const modal = await escolherNoMenu(
    usuario,
    painel,
    'Ações de Ana Souza em 00:05',
    'Só é citada (não aparece)',
  )
  await usuario.type(modal.getByLabelText('Motivo'), 'só falaram dela')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toEqual({
    tipo: 'pessoa.aparicao_para_mencao',
    item_id: 'p1',
    ocorrencia: OCORRENCIA_NA_IMAGEM,
    valor: 'citada_na_fala',
    motivo: 'só falaram dela',
    versao: 'v1',
  })
})

test('virar aparição exige evidência', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  const modal = await escolherNoMenu(
    usuario,
    painel,
    'Ações de Ana Souza em 01:05',
    'Aparece na imagem',
  )
  await usuario.type(modal.getByLabelText('Motivo'), 'aparece')
  expect(modal.getByRole('button', { name: 'Salvar' }).hasAttribute('disabled')).toBe(true)
  await usuario.type(modal.getByLabelText('Evidência'), 'rosto no canto')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toEqual({
    tipo: 'pessoa.mencao_para_aparicao',
    item_id: 'p1',
    ocorrencia: { lista: 'citada_na_fala', inicio_ms: 65_000, fim_ms: 66_000 },
    valor: 'rosto no canto',
    motivo: 'aparece',
    versao: 'v1',
  })
})

test('o Editor acrescenta aparição numa pessoa nova', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  await usuario.click(painel.getAllByRole('button', { name: 'Acrescentar aparição' })[0])
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Nome'), 'Davi Lima')
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '00:30')
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '00:40')
  await usuario.type(modal.getByLabelText('Evidência'), 'de terno')
  await usuario.type(modal.getByLabelText('Motivo'), 'faltou')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  const [enviada] = correcoesRecebidas as unknown as { tipo: string; valor: string; item_id: string }[]
  expect(enviada.tipo).toBe('pessoa.acrescentar_aparicao')
  expect(enviada.item_id).toBe('')
  expect(JSON.parse(enviada.valor)).toEqual({
    inicio_ms: 30_000,
    fim_ms: 40_000,
    evidencia: 'de terno',
    nome: 'Davi Lima',
  })
})

test('o Editor acrescenta aparição numa pessoa existente', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  await usuario.click(await painel.findByRole('button', { name: 'Acrescentar aparição de Ana Souza' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '00:30')
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '00:40')
  await usuario.type(modal.getByLabelText('Evidência'), 'de terno')
  await usuario.type(modal.getByLabelText('Motivo'), 'faltou')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect((correcoesRecebidas[0] as unknown as { item_id: string }).item_id).toBe('p1')
})

test('quem não edita não vê o menu das ocorrências', async () => {
  await abrir({ estado: 'concluido' }, false)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await userEvent.setup().click(aba('Pessoas'))

  expect((await painel.findAllByText('Ana Souza')).length).toBeGreaterThan(0)
  expect(painel.queryByRole('button', { name: /Ações de/ })).toBeNull()
  expect(painel.queryByRole('button', { name: /Acrescentar aparição/ })).toBeNull()
})

test('quem só é citada também tem o botão de acrescentar aparição', async () => {
  const beto = {
    id: 'p2',
    nome: 'Beto Lima',
    origem: 'modelo',
    na_imagem: [],
    citada_na_fala: [{ inicio_ms: 80_000, fim_ms: 81_000 }],
    citada_no_texto: [],
  }
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({ ...decupagem, pessoas: [...decupagem.pessoas, beto], versao_decupagem: 'v1' }),
    ),
  )
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  await usuario.click(await painel.findByRole('button', { name: 'Acrescentar aparição de Beto Lima' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '01:20')
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '01:21')
  await usuario.type(modal.getByLabelText('Evidência'), 'rosto')
  await usuario.type(modal.getByLabelText('Motivo'), 'aparece também')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect((correcoesRecebidas[0] as unknown as { item_id: string }).item_id).toBe('p2')
  expect(painel.getAllByRole('button', { name: 'Acrescentar aparição de Ana Souza' })).toHaveLength(1)
})

test('corrigir tempos sem mudar nada não salva', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)
  const modal = await escolherNoMenu(usuario, painel, 'Ações de Ana Souza em 00:05', 'Corrigir tempos')
  await usuario.type(modal.getByLabelText('Motivo'), 'conferi')

  expect(modal.getByRole('button', { name: 'Salvar' }).hasAttribute('disabled')).toBe(true)
})

test('o Editor corrige descrição e plano limpo do plano em um modal', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Planos'))

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir plano estúdio 00:00' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Ambiente'))
  await usuario.type(modal.getByLabelText('Ambiente'), 'redação')
  await usuario.type(modal.getByLabelText('Ação'), 'repórter ao vivo')
  await usuario.type(modal.getByLabelText('Objetos (separados por vírgula)'), 'mesa, câmera')
  await usuario.click(modal.getByLabelText('Plano limpo'))
  await usuario.type(modal.getByLabelText('Motivo'), 'plano errado')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(2))
  expect(correcoesRecebidas).toEqual([
    {
      tipo: 'plano.descricao',
      valor: JSON.stringify({
        ambiente: 'redação',
        acao: 'repórter ao vivo',
        objetos: ['mesa', 'câmera'],
      }),
      item_id: 'pl1',
      motivo: 'plano errado',
      versao: 'v1',
    },
    { tipo: 'plano.limpo', valor: 'true', item_id: 'pl1', motivo: 'plano errado', versao: 'v1' },
  ])
})

test('o modal do plano só envia o que mudou e exige o motivo', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Planos'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir plano rua 02:20' }))
  const modal = within(await screen.findByRole('dialog'))
  const salvar = modal.getByRole('button', { name: 'Salvar' }) as HTMLButtonElement
  expect(salvar.disabled).toBe(true)

  await usuario.click(modal.getByLabelText('Plano limpo'))
  expect(salvar.disabled).toBe(true)
  await usuario.type(modal.getByLabelText('Motivo'), 'não era limpo')
  await usuario.click(salvar)

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toMatchObject({
    tipo: 'plano.limpo',
    valor: 'false',
    item_id: 'pl2',
  })
})

test('o Editor corrige o texto e o locutor da fala', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Fala'))

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir fala 00:01' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Texto'))
  await usuario.type(modal.getByLabelText('Texto'), 'Boa noite, Brasil')
  await usuario.clear(modal.getByLabelText('Locutor'))
  await usuario.type(modal.getByLabelText('Locutor'), 'Maria')
  await usuario.type(modal.getByLabelText('Motivo'), 'ouvi de novo')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toEqual({
    tipo: 'fala.texto',
    valor: JSON.stringify({ texto: 'Boa noite, Brasil', locutor: 'Maria' }),
    item_id: 'fal000',
    motivo: 'ouvi de novo',
    versao: 'v1',
  })
})

test('plano e fala revisados ganham o selo e sem permissão não há botão de corrigir', async () => {
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({
        ...decupagem,
        versao_decupagem: 'v1',
        planos: [{ ...decupagem.planos[0], origem: 'revisao', plano_limpo: true }],
        transcricao: [{ ...decupagem.transcricao[0], origem: 'revisao' }],
      }),
    ),
  )
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const painel = within(await screen.findByLabelText('Decupagem'))

  await usuario.click(aba('Planos'))
  expect(await painel.findByText('revisado')).toBeTruthy()
  expect(painel.getByText('limpo')).toBeTruthy()
  expect(painel.queryByRole('button', { name: /Corrigir plano/ })).toBeNull()
  await usuario.click(aba('Fala'))
  expect(await painel.findByText('revisado')).toBeTruthy()
  expect(painel.queryByRole('button', { name: /Corrigir fala/ })).toBeNull()
})

test('422 no plano mostra o aviso no modal', async () => {
  statusDoPost = 422
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Planos'))
  await usuario.click(await painel.findByRole('button', { name: 'Corrigir plano estúdio 00:00' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByLabelText('Plano limpo'))
  await usuario.type(modal.getByLabelText('Motivo'), 'm')

  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  expect((await modal.findByRole('alert')).textContent).toContain('não foi encontrado')
})

async function selecionarNaLinha(
  usuario: ReturnType<typeof userEvent.setup>,
  rotulo: string,
  podeEditar = true,
) {
  await abrir({ estado: 'concluido' }, podeEditar)
  const player = await jogador()
  await usuario.click(await screen.findByLabelText(rotulo))
  return player
}

const alca = (borda: 'Início' | 'Fim') => screen.getByRole('slider', { name: `${borda} da ocorrência` })

test('as setas movem a alça 100 ms, Shift move 1 s, e Enter grava item.tempos', async () => {
  const usuario = userEvent.setup()
  const player = await selecionarNaLinha(usuario, 'Pautas 00:30')

  const inicio = alca('Início')
  inicio.focus()
  fireEvent.keyDown(inicio, { key: 'ArrowRight' })
  fireEvent.keyDown(inicio, { key: 'ArrowRight', shiftKey: true })
  expect(inicio.getAttribute('aria-valuenow')).toBe('31100')
  expect(player.currentTime).toBe(31.1)
  fireEvent.keyDown(alca('Início'), { key: 'Enter' })

  const modal = within(await screen.findByRole('dialog'))
  expect(modal.getByText('Antes: 00:30.000–01:00.000')).toBeTruthy()
  expect(modal.getByText('Depois: 00:31.100–01:00.000')).toBeTruthy()
  expect(modal.getByRole('button', { name: 'Salvar' }).hasAttribute('disabled')).toBe(true)
  await usuario.type(modal.getByLabelText('Motivo'), 'corte tardio')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toEqual({
    tipo: 'item.tempos',
    item_id: 'pa1',
    valor: '31100-60000',
    motivo: 'corte tardio',
    versao: 'v1',
  })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  // Com a decupagem recarregada (o mock devolve a pauta corrigida em 00:32), a seleção antiga
  // deixa de valer, as alças somem e selecionar de novo parte do intervalo novo.
  await waitFor(() => expect(screen.queryByRole('slider', { name: 'Início da ocorrência' })).toBeNull())
  await usuario.click(await screen.findByLabelText('Pautas 00:32'))
  expect(alca('Início').getAttribute('aria-valuenow')).toBe('32000')
})

test('cancelar o modal devolve a ocorrência ao intervalo anterior', async () => {
  const usuario = userEvent.setup()
  await selecionarNaLinha(usuario, 'Pautas 00:30')

  fireEvent.keyDown(alca('Fim'), { key: 'ArrowLeft', shiftKey: true })
  expect(alca('Fim').getAttribute('aria-valuenow')).toBe('59000')
  fireEvent.keyDown(alca('Fim'), { key: 'Enter' })
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByRole('button', { name: 'Cancelar' }))

  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(alca('Fim').getAttribute('aria-valuenow')).toBe('60000')
  expect(correcoesRecebidas).toHaveLength(0)
})

test('arrastar a alça leva o player ao tempo dela e soltar abre o modal', async () => {
  const usuario = userEvent.setup()
  const player = await selecionarNaLinha(usuario, 'Pautas 00:30')

  const inicio = alca('Início')
  // 150 s de linha do tempo em 1500 px: 10 px por segundo.
  vi.spyOn(inicio.parentElement as HTMLElement, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    width: 1500,
  } as DOMRect)
  fireEvent.pointerDown(inicio, { pointerId: 1, clientX: 300 })
  fireEvent.pointerMove(inicio, { pointerId: 1, clientX: 450 })
  expect(player.currentTime).toBe(45)
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.pointerUp(inicio, { pointerId: 1, clientX: 450 })

  const modal = within(await screen.findByRole('dialog'))
  expect(modal.getByText('Depois: 00:45.000–01:00.000')).toBeTruthy()
})

test('o gesto cancelado encerra o arraste: a alça não segue o ponteiro sem botão', async () => {
  const usuario = userEvent.setup()
  const player = await selecionarNaLinha(usuario, 'Pautas 00:30')

  const inicio = alca('Início')
  vi.spyOn(inicio.parentElement as HTMLElement, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    width: 1500,
  } as DOMRect)
  fireEvent.pointerDown(inicio, { pointerId: 1, clientX: 300 })
  fireEvent.pointerMove(inicio, { pointerId: 1, clientX: 400 })
  fireEvent.pointerCancel(inicio, { pointerId: 1 })
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByRole('button', { name: 'Cancelar' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

  fireEvent.pointerMove(alca('Início'), { pointerId: 1, clientX: 500 })
  expect(alca('Início').getAttribute('aria-valuenow')).toBe('30000')
  expect(player.currentTime).toBe(40)
})

test('a alça de uma aparição grava item.tempos com a ocorrência da pessoa', async () => {
  const usuario = userEvent.setup()
  await selecionarNaLinha(usuario, 'Aparições 00:05')

  fireEvent.keyDown(alca('Fim'), { key: 'ArrowRight', shiftKey: true })
  fireEvent.keyDown(alca('Fim'), { key: 'Enter' })
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Motivo'), 'saiu depois')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toEqual({
    tipo: 'item.tempos',
    tipo_do_item: 'pessoa',
    item_id: 'p1',
    ocorrencia: OCORRENCIA_NA_IMAGEM,
    valor: '5000-21000',
    motivo: 'saiu depois',
    versao: 'v1',
  })
})

test('a alça de um comercial grava item.tempos do comercial', async () => {
  const usuario = userEvent.setup()
  await selecionarNaLinha(usuario, 'Comerciais 01:30')

  fireEvent.keyDown(alca('Início'), { key: 'ArrowLeft' })
  fireEvent.keyDown(alca('Início'), { key: 'Enter' })
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Motivo'), 'começou antes')
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcoesRecebidas[0]).toMatchObject({
    tipo: 'item.tempos',
    tipo_do_item: 'comercial',
    item_id: 'com000',
    valor: '89900-120000',
  })
})

test('planos e falas não têm alças, e a Consulta não vê as alças', async () => {
  const usuario = userEvent.setup()
  await selecionarNaLinha(usuario, 'Planos 00:00')
  expect(screen.queryByRole('slider', { name: 'Início da ocorrência' })).toBeNull()
  cleanup()

  await selecionarNaLinha(usuario, 'Pautas 00:30', false)
  expect(screen.queryByRole('slider', { name: 'Início da ocorrência' })).toBeNull()
  expect(screen.queryByRole('slider', { name: 'Fim da ocorrência' })).toBeNull()
})

async function salvarCampo(usuario: ReturnType<typeof userEvent.setup>, motivo: string) {
  const modal = within(await screen.findByRole('dialog'))
  await usuario.type(modal.getByLabelText('Motivo'), motivo)
  await usuario.click(modal.getByRole('button', { name: 'Salvar' }))
}

test('o Editor corrige o tom da pauta pelo modal', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir tom da pauta Eleição' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByRole('combobox', { name: 'Tom' }))
  await usuario.click(await modal.findByRole('option', { name: 'polêmico' }))
  await salvarCampo(usuario, 'tom errado')

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcaoRecebida).toEqual({
    tipo: 'pauta.tom',
    item_id: 'pa1',
    valor: 'polemico',
    motivo: 'tom errado',
    versao: 'v1',
  })
})

test('a aba Pautas mostra o tom com acento e o tom livre de decupagem antiga como veio', async () => {
  const usuario = userEvent.setup()
  servidor.use(
    http.get('/v1/jobs/j1/decupagem', () =>
      HttpResponse.json({
        ...decupagem,
        versao_decupagem: 'v1',
        pautas: [
          ...decupagem.pautas,
          { id: 'pa2', titulo: 'Debate', resumo: 'x', tom: 'descontraido', inicio_ms: 0, fim_ms: 1000 },
        ],
      }),
    ),
  )
  await abrir({ estado: 'concluido' })
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Pautas'))

  expect(await painel.findByText('descontraído')).toBeTruthy()
  expect(painel.getByText('sério')).toBeTruthy()
})

test('o Editor troca as fontes do nome, inclusive para nenhuma', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir fontes do nome de Ana Souza' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByLabelText('fala'))
  await usuario.click(modal.getByLabelText('rosto'))
  await usuario.click(modal.getByLabelText('GC'))
  await salvarCampo(usuario, 'só pela fala')

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcaoRecebida).toEqual({
    tipo: 'pessoa.fontes_do_nome',
    item_id: 'p1',
    valor: '["fala"]',
    motivo: 'só pela fala',
    versao: 'v1',
  })
})

test('o Editor corrige papel e visual de uma aparição; vazio vira null', async () => {
  const usuario = userEvent.setup()
  const painel = await abrirPessoas(usuario)

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir papel na cena e visual de Ana Souza 00:05' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.clear(modal.getByLabelText('Papel na cena'))
  await usuario.clear(modal.getByLabelText('Visual'))
  await usuario.type(modal.getByLabelText('Papel na cena'), 'repórter')
  await salvarCampo(usuario, 'papel errado')

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcaoRecebida).toEqual({
    tipo: 'aparicao.papel_visual',
    item_id: 'p1',
    ocorrencia: OCORRENCIA_NA_IMAGEM,
    valor: '{"papel":"repórter","visual":null}',
    motivo: 'papel errado',
    versao: 'v1',
  })
})

test('o Editor corrige o tipo e o texto de um texto na tela', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Texto na tela'))

  await usuario.click(await painel.findByRole('button', { name: 'Corrigir texto na tela Ana Souza, apresentadora' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByRole('combobox', { name: 'Tipo' }))
  await usuario.click(await modal.findByRole('option', { name: 'tarja' }))
  await usuario.clear(modal.getByLabelText('Texto'))
  await usuario.type(modal.getByLabelText('Texto'), 'Ana Souza, repórter')
  await salvarCampo(usuario, 'leitura errada')

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcaoRecebida).toEqual({
    tipo: 'texto_na_tela.texto',
    item_id: 'txt000',
    valor: '{"tipo":"tarja","texto":"Ana Souza, repórter"}',
    motivo: 'leitura errada',
    versao: 'v1',
  })
})

test('o Editor acrescenta um texto na tela com tempos, tipo e texto', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))
  await usuario.click(aba('Texto na tela'))

  await usuario.click(await painel.findByRole('button', { name: 'Acrescentar texto na tela' }))
  const modal = within(await screen.findByRole('dialog'))
  await usuario.click(modal.getByRole('combobox', { name: 'Tipo' }))
  await usuario.click(await modal.findByRole('option', { name: 'placar' }))
  await usuario.type(modal.getByLabelText('Texto'), 'BRA 2 x 1 ARG')
  await usuario.type(modal.getByLabelText('Início (mm:ss)'), '01:00')
  await usuario.type(modal.getByLabelText('Fim (mm:ss)'), '01:10')
  await salvarCampo(usuario, 'não foi lido')

  await waitFor(() => expect(correcoesRecebidas).toHaveLength(1))
  expect(correcaoRecebida).toEqual({
    tipo: 'texto_na_tela.acrescentar',
    item_id: '',
    valor: '{"inicio_ms":60000,"fim_ms":70000,"tipo":"placar","texto":"BRA 2 x 1 ARG"}',
    motivo: 'não foi lido',
    versao: 'v1',
  })
})

test('na decupagem 1.1 e sem edição não há botões dos campos novos', async () => {
  servidor.use(http.get('/v1/jobs/j1/decupagem', () => HttpResponse.json(decupagem11)))
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' }, true)
  const painel = within(await screen.findByLabelText('Decupagem'))

  expect(painel.queryByRole('button', { name: /Corrigir fontes do nome/ })).toBeNull()
  expect(painel.queryByRole('button', { name: /Corrigir papel na cena e visual/ })).toBeNull()
  await usuario.click(aba('Pautas'))
  expect(painel.queryByRole('button', { name: /Corrigir tom/ })).toBeNull()
})
