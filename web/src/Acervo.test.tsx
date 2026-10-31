import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { render } from './render-teste.tsx'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { AppShell } from '@mantine/core'
import { criarClienteDaApi } from './api.ts'
import Acervo from './Acervo.tsx'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { useRota } from './rotas.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'

interface JobApi {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  duracao_s: number | null
  programa: string | null
  data_exibicao: string | null
  enviado_por: { tipo: string; nome: string | null }
  criado_em: string
  atualizado_em: string
}

function job(extra: Partial<JobApi>): JobApi {
  return {
    id: 'j1',
    nome: 'clipe.mp4',
    estado: 'aguardando_upload',
    codigo_falha: null,
    duracao_s: null,
    programa: null,
    data_exibicao: null,
    enviado_por: { tipo: 'pessoa', nome: 'ana@redetv.com.br' },
    criado_em: '2026-10-29T15:00:00Z',
    atualizado_em: '2026-10-29T15:00:00Z',
    ...extra,
  }
}

let jobs: JobApi[] = []
let statusDaLista = 200
let programas: string[] | null = ['TV Fama']
const criacoes: unknown[] = []
const chamadas: string[] = []
const pedacosEnviados: number[] = []
const URL_UPLOAD = 'https://storage.exemplo/quarentena/novo?assinatura=x'
const SESSAO = 'https://storage.exemplo/sessao/novo'

const servidor = setupServer(
  http.get('/v1/jobs', ({ request }) => {
    const url = new URL(request.url)
    chamadas.push(url.search)
    if (statusDaLista !== 200) return new HttpResponse(null, { status: statusDaLista })
    const cursor = url.searchParams.get('cursor')
    const limite = Number(url.searchParams.get('limite'))
    const inicio = cursor ? jobs.findIndex((j) => j.id === cursor) + 1 : 0
    const pagina = jobs.slice(inicio, inicio + limite)
    const ha = inicio + limite < jobs.length
    return HttpResponse.json(pagina, {
      headers: ha ? { 'X-Proximo-Cursor': pagina[pagina.length - 1].id } : {},
    })
  }),
  http.get('/v1/jobs/:id', ({ params }) => {
    const achado = jobs.find((j) => j.id === params.id)
    return achado ? HttpResponse.json(achado) : new HttpResponse(null, { status: 404 })
  }),
  http.get('/v1/programas', () =>
    programas ? HttpResponse.json(programas) : new HttpResponse(null, { status: 500 }),
  ),
  http.post('/v1/jobs', async ({ request }) => {
    criacoes.push(await request.json())
    const novo = job({ id: 'novo', nome: 'enviado.mp4' })
    jobs = [novo, ...jobs]
    return HttpResponse.json({ ...novo, url_de_upload: URL_UPLOAD }, { status: 202 })
  }),
  http.post(URL_UPLOAD, () => new HttpResponse(null, { status: 201, headers: { Location: SESSAO } })),
  http.put(SESSAO, async ({ request }) => {
    pedacosEnviados.push((await request.arrayBuffer()).byteLength)
    return new HttpResponse(null, { status: 200 })
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  jobs = []
  statusDaLista = 200
  programas = ['TV Fama']
  criacoes.length = 0
  chamadas.length = 0
  pedacosEnviados.length = 0
  cleanup()
})
afterAll(() => servidor.close())

async function comSessao() {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

function mp4(nome = 'enviado.mp4') {
  const bytes = new Uint8Array(64)
  bytes.set(new TextEncoder().encode('ftypisom'), 4)
  return new File([bytes], nome, { type: 'video/mp4' })
}

function Tela({ api, podeEnviar, intervaloMs }: { api: ReturnType<typeof criarClienteDaApi>; podeEnviar: boolean; intervaloMs?: number }) {
  const rota = useRota()
  if (rota.tipo !== 'acervo') return null
  return <Acervo api={api} filtros={rota.filtros} podeEnviar={podeEnviar} intervaloMs={intervaloMs} />
}

async function abrir(
  opcoes: {
    intervaloMs?: number
    aoSessaoExpirada?: () => void
    podeEnviar?: boolean
    endereco?: string
  } = {},
) {
  history.replaceState(null, '', opcoes.endereco ?? '/acervo')
  render(
    <AtalhosProvider>
      <AppShell header={{ height: 44 }}>
        <Tela
          api={criarClienteDaApi(await comSessao(), opcoes.aoSessaoExpirada ?? (() => {}))}
          intervaloMs={opcoes.intervaloMs}
          podeEnviar={opcoes.podeEnviar ?? true}
        />
      </AppShell>
    </AtalhosProvider>,
  )
}

async function abrirEnvio(usuario: ReturnType<typeof userEvent.setup>) {
  await usuario.click(await screen.findByRole('button', { name: 'Enviar vídeo' }))
  return screen.findByRole('dialog')
}

const linha = (nome: string) => screen.getByText(nome).closest('tr') as HTMLElement
const ultimaChamada = () => new URLSearchParams(chamadas[chamadas.length - 1])

test('a tabela mostra nome, programa, data de exibição, duração, estado, quem enviou e quando', async () => {
  jobs = [
    job({
      id: 'a',
      nome: 'pronto.mp4',
      estado: 'concluido',
      programa: 'TV Fama',
      data_exibicao: '2026-10-28',
      duracao_s: 125,
    }),
    job({ id: 'b', nome: 'sem-data.mp4', estado: 'validando', enviado_por: { tipo: 'sistema', nome: 'ingest' } }),
  ]
  await abrir()

  const pronto = within(await waitFor(() => linha('pronto.mp4')))
  expect(pronto.getByText('TV Fama')).toBeTruthy()
  expect(pronto.getByText('28/10/2026')).toBeTruthy()
  expect(pronto.getByText('02:05')).toBeTruthy()
  expect(pronto.getByText('Concluído')).toBeTruthy()
  expect(pronto.getByText('ana@redetv.com.br')).toBeTruthy()
  // 15:00Z é 12:00 em São Paulo, o fuso fixado em vite.config.ts.
  expect(pronto.getByText('29/10/2026 12:00')).toBeTruthy()
  const semData = within(linha('sem-data.mp4'))
  expect(semData.getAllByText('—').length).toBeGreaterThanOrEqual(3)
  expect(semData.getByText('Em quarentena')).toBeTruthy()
  expect(semData.getByText('ingest')).toBeTruthy()
})

test('pede a primeira página com 50 por vez, do mais recente ao mais antigo', async () => {
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  expect(ultimaChamada().get('limite')).toBe('50')
  expect(ultimaChamada().get('ordem')).toBe('enviado')
})

test('a linha com falha mostra a frase em português, e o código só na dica', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'quebrado.mp4', estado: 'falhou', codigo_falha: 'codec_nao_suportado' })]
  await abrir()

  const falhou = within(await waitFor(() => linha('quebrado.mp4')))
  expect(falhou.getByText('Falhou')).toBeTruthy()
  const frase = falhou.getByText('O vídeo usa um codec que não aceitamos. Envie em H.264.')
  expect(screen.queryByText('codec_nao_suportado')).toBeNull()
  await usuario.hover(frase)
  expect(await screen.findByText(/codec_nao_suportado/)).toBeTruthy()
})

test('só a linha concluída abre o vídeo, por clique ou Enter', async () => {
  const usuario = userEvent.setup()
  jobs = [
    job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' }),
    job({ id: 'b', nome: 'andando.mp4', estado: 'analisando' }),
  ]
  await abrir()
  await screen.findByText('pronto.mp4')

  expect(screen.getByRole('link', { name: 'pronto.mp4' }).getAttribute('href')).toBe('/video/a')
  expect(screen.queryByRole('link', { name: 'andando.mp4' })).toBeNull()
  await usuario.click(screen.getByText('andando.mp4'))
  expect(location.pathname).toBe('/acervo')

  linha('pronto.mp4').focus()
  await usuario.keyboard('{Enter}')
  expect(location.pathname).toBe('/video/a')
})

test('clicar na linha concluída abre o vídeo', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido', programa: 'TV Fama' })]
  await abrir()

  await usuario.click(within(await waitFor(() => linha('pronto.mp4'))).getByText('TV Fama'))

  expect(location.pathname).toBe('/video/a')
})

test('as setas movem a linha selecionada', async () => {
  const usuario = userEvent.setup()
  jobs = [
    job({ id: 'a', nome: 'um.mp4', estado: 'concluido' }),
    job({ id: 'b', nome: 'dois.mp4', estado: 'concluido' }),
  ]
  await abrir()
  await screen.findByText('um.mp4')

  await usuario.tab()
  await usuario.tab()
  await usuario.tab()
  await usuario.tab()
  await usuario.tab()
  await usuario.tab()
  await usuario.tab()
  linha('um.mp4').focus()
  await usuario.keyboard('{ArrowDown}')
  expect(document.activeElement).toBe(linha('dois.mp4'))
  expect(linha('dois.mp4').getAttribute('aria-selected')).toBe('true')
  expect(linha('um.mp4').getAttribute('aria-selected')).toBe('false')
  await usuario.keyboard('{ArrowUp}')
  expect(document.activeElement).toBe(linha('um.mp4'))
})

test('as teclas da tabela aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.keyboard('?')

  expect(await screen.findByText('Na tabela: mover a linha selecionada')).toBeTruthy()
})

test('a busca por nome espera 300 ms, vai à API e à URL', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')
  const antes = chamadas.length

  await usuario.type(screen.getByLabelText('Buscar por nome'), 'fama')
  expect(chamadas.length).toBe(antes)

  await waitFor(() => expect(location.search).toBe('?q=fama'))
  await waitFor(() => expect(ultimaChamada().get('q')).toBe('fama'))
  // Uma chamada só, e não uma por letra.
  expect(chamadas.length).toBe(antes + 1)
})

test('cada filtro muda a chamada à API e a URL', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.click(await screen.findByRole('combobox', { name: 'Programa' }))
  await usuario.click(await screen.findByRole('option', { name: 'TV Fama' }))
  await waitFor(() => expect(ultimaChamada().get('programa')).toBe('TV Fama'))

  fireEvent.change(screen.getByLabelText('Exibido de'), { target: { value: '2026-10-01' } })
  await waitFor(() => expect(ultimaChamada().get('exibicao_de')).toBe('2026-10-01'))
  fireEvent.change(screen.getByLabelText('Exibido até'), { target: { value: '2026-10-31' } })
  await waitFor(() => expect(ultimaChamada().get('exibicao_ate')).toBe('2026-10-31'))

  await usuario.click(screen.getByRole('checkbox', { name: 'Decupando' }))
  await usuario.click(screen.getByRole('checkbox', { name: 'Falhou' }))
  await waitFor(() => expect(ultimaChamada().getAll('estado')).toEqual(['analisando', 'falhou']))

  expect(location.search).toBe(
    '?programa=TV+Fama&de=2026-10-01&ate=2026-10-31&estado=analisando&estado=falhou',
  )
})

test('abrir a URL com filtros restaura a tela', async () => {
  await abrir({
    endereco: '/acervo?q=fama&programa=TV+Fama&de=2026-10-01&ate=2026-10-31&estado=falhou&ordem=exibicao',
  })
  await screen.findByText('Nenhum vídeo com esses filtros.')

  const p = ultimaChamada()
  expect([p.get('q'), p.get('programa'), p.get('exibicao_de'), p.get('exibicao_ate'), p.get('ordem')]).toEqual([
    'fama',
    'TV Fama',
    '2026-10-01',
    '2026-10-31',
    'exibicao',
  ])
  expect(p.getAll('estado')).toEqual(['falhou'])
  expect((screen.getByLabelText('Buscar por nome') as HTMLInputElement).value).toBe('fama')
  expect((screen.getByLabelText('Exibido de') as HTMLInputElement).value).toBe('2026-10-01')
  expect((screen.getByRole('checkbox', { name: 'Falhou' }) as HTMLInputElement).checked).toBe(true)
  await waitFor(() =>
    expect((screen.getByRole('combobox', { name: 'Programa' }) as HTMLInputElement).value).toBe('TV Fama'),
  )
})

test('"Limpar filtros" só aparece com filtro, e volta à lista sem eles', async () => {
  const usuario = userEvent.setup()
  await abrir({ endereco: '/acervo?estado=falhou' })
  await screen.findByText('Nenhum vídeo com esses filtros.')

  const limpar = screen.getAllByRole('button', { name: 'Limpar filtros' })
  expect(limpar.length).toBe(2)
  await usuario.click(limpar[0])

  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
  expect(location.search).toBe('')
  expect(screen.queryByRole('button', { name: 'Limpar filtros' })).toBeNull()
  expect(ultimaChamada().getAll('estado')).toEqual([])
})

test('a ordem muda pelo cabeçalho e fica na URL; o padrão é Enviado em', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'um.mp4' })]
  await abrir()
  await screen.findByText('um.mp4')
  const enviado = screen.getByRole('columnheader', { name: 'Enviado em' })
  const exibicao = screen.getByRole('columnheader', { name: 'Data de exibição' })
  expect(enviado.getAttribute('aria-sort')).toBe('descending')
  expect(exibicao.getAttribute('aria-sort')).toBe('none')

  await usuario.click(within(exibicao).getByRole('button'))

  await waitFor(() => expect(ultimaChamada().get('ordem')).toBe('exibicao'))
  expect(location.search).toBe('?ordem=exibicao')
  expect(screen.getByRole('columnheader', { name: 'Data de exibição' }).getAttribute('aria-sort')).toBe('descending')
  expect(screen.getByRole('columnheader', { name: 'Enviado em' }).getAttribute('aria-sort')).toBe('none')
})

test('"Carregar mais" traz a página seguinte, pelo cursor, e some na última', async () => {
  const usuario = userEvent.setup()
  jobs = Array.from({ length: 55 }, (_, i) => job({ id: `j${i}`, nome: `video-${i}.mp4`, estado: 'concluido' }))
  await abrir()
  await screen.findByText('video-0.mp4')
  expect(screen.queryByText('video-50.mp4')).toBeNull()

  await usuario.click(screen.getByRole('button', { name: 'Carregar mais' }))

  expect(await screen.findByText('video-54.mp4')).toBeTruthy()
  expect(ultimaChamada().get('cursor')).toBe('j49')
  expect(screen.getByText('video-0.mp4')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Carregar mais' })).toBeNull()
})

test('só as linhas em andamento são consultadas de novo, e a lista não é recarregada', async () => {
  jobs = [
    job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' }),
    job({ id: 'b', nome: 'andando.mp4', estado: 'validando' }),
  ]
  const detalhes: string[] = []
  servidor.use(
    http.get('/v1/jobs/:id', ({ params }) => {
      detalhes.push(String(params.id))
      return HttpResponse.json(jobs.find((j) => j.id === params.id))
    }),
  )
  await abrir({ intervaloMs: 20 })
  await screen.findByText('andando.mp4')
  const listagens = chamadas.length

  jobs = [jobs[0], job({ id: 'b', nome: 'andando.mp4', estado: 'concluido' })]

  await waitFor(() => expect(within(linha('andando.mp4')).getByText('Concluído')).toBeTruthy())
  expect(new Set(detalhes)).toEqual(new Set(['b']))
  expect(chamadas.length).toBe(listagens)
})

test('com a aba escondida, ninguém é consultado', async () => {
  jobs = [job({ id: 'b', nome: 'andando.mp4', estado: 'validando' })]
  let consultas = 0
  servidor.use(
    http.get('/v1/jobs/:id', () => {
      consultas++
      return HttpResponse.json(jobs[0])
    }),
  )
  const visibilidade = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  try {
    await abrir({ intervaloMs: 10 })
    await screen.findByText('andando.mp4')
    await new Promise((r) => setTimeout(r, 80))
    expect(consultas).toBe(0)
  } finally {
    visibilidade.mockRestore()
  }
})

test('sem vídeos, a lista vazia diz isso; com filtros, diz que nenhum casou', async () => {
  await abrir()
  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
  cleanup()

  await abrir({ endereco: '/acervo?q=nada' })
  expect(await screen.findByText('Nenhum vídeo com esses filtros.')).toBeTruthy()
})

test('um 401 na lista avisa que a sessão expirou', async () => {
  statusDaLista = 401
  const aoSessaoExpirada = vi.fn()

  await abrir({ aoSessaoExpirada })

  await waitFor(() => expect(aoSessaoExpirada).toHaveBeenCalled())
})

test('se a lista não carrega, mostra o erro e deixa tentar de novo', async () => {
  const usuario = userEvent.setup()
  statusDaLista = 503
  await abrir()
  await screen.findByText('Não foi possível carregar o acervo.')

  statusDaLista = 200
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
})

test('sem a permissão de enviar, o botão não aparece mas os vídeos sim', async () => {
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' })]
  await abrir({ podeEnviar: false })

  expect(await screen.findByText('pronto.mp4')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Enviar vídeo' })).toBeNull()
})

test('o diálogo de envio recusa na hora o arquivo que não é MP4, sem chamar a API', async () => {
  const usuario = userEvent.setup({ applyAccept: false })
  await abrir()
  await abrirEnvio(usuario)

  await usuario.upload(screen.getByLabelText('Arquivo MP4'), mp4('filme.mov'))

  expect((await screen.findByRole('alert')).textContent).toContain('.mp4')
  expect(criacoes).toEqual([])
})

test('envia o MP4 com programa e data de exibição, e o vídeo aparece no topo da tabela', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')
  const dialogo = within(await abrirEnvio(usuario))

  await usuario.click(await dialogo.findByRole('combobox', { name: 'Programa' }))
  await usuario.click(await screen.findByRole('option', { name: 'TV Fama' }))
  fireEvent.change(dialogo.getByLabelText('Data de exibição (opcional)'), { target: { value: '2026-10-28' } })
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect(await dialogo.findByText(/Envio concluído/)).toBeTruthy()
  expect(criacoes).toEqual([
    { nome: 'enviado.mp4', tamanho_bytes: 64, tipo: 'video/mp4', programa: 'TV Fama', data_exibicao: '2026-10-28' },
  ])
  expect(pedacosEnviados).toEqual([64])
  const topo = await waitFor(() => {
    const primeira = document.querySelector<HTMLElement>('tbody tr')
    if (!primeira) throw new Error('a tabela ainda não apareceu')
    return primeira
  })
  expect(within(topo).getByText('enviado.mp4')).toBeTruthy()
  expect(within(topo).getByText('Aguardando envio')).toBeTruthy()
})

test('sem programa nem data, o corpo da criação leva só o arquivo', async () => {
  const usuario = userEvent.setup()
  programas = null
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))

  expect(dialogo.queryByRole('combobox', { name: 'Programa' })).toBeNull()
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect(await dialogo.findByText(/Envio concluído/)).toBeTruthy()
  expect(criacoes).toEqual([{ nome: 'enviado.mp4', tamanho_bytes: 64, tipo: 'video/mp4' }])
})

test('o envio mostra o progresso e trava o arquivo até terminar', async () => {
  let liberar = () => {}
  servidor.use(
    http.put(SESSAO, async () => {
      await new Promise<void>((resolve) => (liberar = resolve))
      return new HttpResponse(null, { status: 200 })
    }),
  )
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))
  const campo = dialogo.getByLabelText('Arquivo MP4') as HTMLInputElement

  await usuario.upload(campo, mp4())
  await dialogo.findByLabelText('Progresso do envio')

  expect(campo.disabled).toBe(true)
  liberar()
  await dialogo.findByText(/Envio concluído/)
  expect(campo.disabled).toBe(false)
})

test('data de exibição no futuro vira uma mensagem em português com a ação', async () => {
  servidor.use(
    http.post('/v1/jobs', () => HttpResponse.json({ detail: 'Data de exibição no futuro' }, { status: 422 })),
  )
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))

  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect((await dialogo.findByRole('alert')).textContent).toContain('data de exibição não pode ser no futuro')
})

test('uma falha ao criar o Job vira mensagem em português', async () => {
  servidor.use(http.post('/v1/jobs', () => new HttpResponse(null, { status: 500 })))
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))

  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect((await dialogo.findByRole('alert')).textContent).toContain('Não foi possível enviar o vídeo')
})
