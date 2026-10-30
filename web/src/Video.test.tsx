import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { render } from './render-teste.tsx'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import Video from './Video.tsx'

// Segue o esquema 1.1 (api/decupagem.py).
const decupagem = {
  versao_esquema: '1.1',
  video: { sha256: 'a'.repeat(64), duracao_ms: 180_000 },
  programa: { resumo: 'Jornal', blocos: [] },
  pautas: [{ id: 'pa1', titulo: 'Eleição', resumo: 'Debate', inicio_ms: 30_000, fim_ms: 60_000 }],
  pessoas: [
    {
      id: 'p1',
      nome: 'Ana Souza',
      origem: 'modelo',
      na_imagem: [{ inicio_ms: 5_000, fim_ms: 20_000, evidencia: 'rosto' }],
      citada_na_fala: [{ inicio_ms: 65_000, fim_ms: 66_000 }],
      citada_no_texto: [{ inicio_ms: 70_000, fim_ms: 72_000, texto: '<b>Ana</b> no GC' }],
    },
  ],
  planos: [
    { id: 'pl1', ambiente: 'estúdio', plano_limpo: false, acao: null, inicio_ms: 0, fim_ms: 4_000 },
    { id: 'pl2', ambiente: 'rua', plano_limpo: true, acao: 'carro passa', inicio_ms: 140_000, fim_ms: 150_000 },
  ],
  comerciais: [
    { marca: 'Marca X', tipo: 'intervalo', evidencia: 'logo', inicio_ms: 90_000, fim_ms: 120_000 },
  ],
  transcricao: [{ locutor: 'Locutor', texto: 'Boa noite', inicio_ms: 1_000, fim_ms: 3_000 }],
}

const TOKEN = 'Bearer token-de-ana@redetv.com.br'
let statusDecupagem = 200
let corrigida = false
let correcaoRecebida: unknown = null
let links: { url: string; expira_em: string }[] = []
const servidor = setupServer(
  http.get('/v1/jobs/j1/reproducao', ({ request }) => {
    if (request.headers.get('Authorization') !== TOKEN) return new HttpResponse(null, { status: 401 })
    return HttpResponse.json(
      links.shift() ?? { url: 'https://storage.exemplo/proxy/j1', expira_em: '2999-01-01T00:00:00Z' },
    )
  }),
  http.get('/v1/jobs/j1/decupagem', ({ request }) => {
    if (request.headers.get('Authorization') !== TOKEN) return new HttpResponse(null, { status: 401 })
    const entregue = corrigida
      ? { ...decupagem, versao_decupagem: 'v2', pessoas: [{ ...decupagem.pessoas[0], nome: 'Ana Souza Lima', origem: 'revisao' }] }
      : { ...decupagem, versao_decupagem: 'v1' }
    return statusDecupagem === 200
      ? HttpResponse.json(entregue)
      : new HttpResponse(null, { status: statusDecupagem })
  }),
  http.post('/v1/jobs/j1/correcoes', async ({ request }) => {
    correcaoRecebida = await request.json()
    corrigida = true
    return HttpResponse.json({ id: 'c1', versao_decupagem: 'v1' }, { status: 201 })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  servidor.resetHandlers()
  statusDecupagem = 200
  corrigida = false
  correcaoRecebida = null
  links = []
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function abrir(job: { estado: string; codigo_falha?: string | null }, podeEditar = false) {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  render(
    <Video
      autenticador={auth}
      job={{ id: 'j1', nome: 'clipe.mp4', codigo_falha: null, ...job }}
      aoSessaoExpirada={() => {}}
      podeEditar={podeEditar}
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
  await usuario.click(screen.getByText('Marca X'))
  expect(player.currentTime).toBe(90)
})

test('aba Planos usa a ação, ou o ambiente se não houver, e salta', async () => {
  const usuario = userEvent.setup()
  await abrir({ estado: 'concluido' })
  const player = await jogador()
  await usuario.click(aba('Planos'))

  expect(screen.getByText('estúdio', { selector: 'span' })).toBeTruthy()
  expect(screen.getByText('rua · 02:20')).toBeTruthy()
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
  const fundo = () => fala.querySelector('.mantine-Paper-root')?.getAttribute('style') ?? ''
  expect(fundo()).not.toContain('red-9')
  await usuario.click(fala)
  expect(player.currentTime).toBe(1)
  irPara(player, 2)
  expect(fundo()).toContain('red-9')
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
  expect(correcaoRecebida).toEqual({
    tipo: 'pessoa.renomear',
    item_id: 'p1',
    valor: 'Ana Souza Lima',
    motivo: 'sobrenome completo',
    versao: 'v1',
  })
})

test('quem não tem decupagem.editar não vê o botão de corrigir', async () => {
  await abrir({ estado: 'concluido' }, false)
  const painel = within(await screen.findByLabelText('Decupagem'))

  expect(await painel.findAllByText('Ana Souza')).not.toHaveLength(0)
  expect(painel.queryByRole('button', { name: /Corrigir/ })).toBeNull()
})
