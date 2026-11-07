import { onlineManager, QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { navegar, useRota } from '../../rotas.ts'
import { AtalhosProvider } from '../Atalhos.tsx'
import { Casca } from '../Casca.tsx'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { Acervo } from './Acervo.tsx'
import { usePaginas } from '../paginas.ts'
import { lembrarPosicao } from './useAcervo.ts'

interface JobApi {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  duracao_s: number | null
  programa: string | null
  data_exibicao: string | null
  enviado_por: { tipo: string; nome: string | null }
  capa_url?: string | null
  etapa_atual?: string | null
  indexacao?: { estado: string; em: string } | null
  etapas?: { nome: string; inicio: string; fim?: string | null }[]
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
// O cursor que a API não aceita mais (a lista dele venceu): 422.
let cursorVencido: string | null = null
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
    if (cursor && cursor === cursorVencido) return HttpResponse.json({ detail: 'Cursor inválido' }, { status: 422 })
    const limite = Number(url.searchParams.get('limite'))
    const inicio = cursor ? jobs.findIndex((j) => j.id === cursor) + 1 : 0
    const pagina = jobs.slice(inicio, inicio + limite)
    const ha = inicio + limite < jobs.length
    return HttpResponse.json(pagina, { headers: ha ? { 'X-Proximo-Cursor': pagina[pagina.length - 1].id } : {} })
  }),
  http.get('/v1/programas', () => (programas ? HttpResponse.json(programas) : new HttpResponse(null, { status: 500 }))),
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

// O jsdom não mede nada: a rolagem tem 1000 px de altura, e cada fileira da grade, 100 px.
const alturaOriginal = Object.getOwnPropertyDescriptor(Element.prototype, 'clientHeight')!
const offsetOriginal = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')!
beforeAll(() => {
  servidor.listen({ onUnhandledFrame: 'error' })
  Object.defineProperty(Element.prototype, 'clientHeight', { configurable: true, get: () => 1000 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute('data-index') ? 100 : 0
    },
  })
})
afterEach(() => {
  cleanup()
  history.replaceState(null, '', '/')
  localStorage.clear()
  servidor.resetHandlers()
  jobs = []
  statusDaLista = 200
  cursorVencido = null
  onlineManager.setOnline(true)
  programas = ['TV Fama']
  criacoes.length = 0
  chamadas.length = 0
  pedacosEnviados.length = 0
})
afterAll(() => {
  servidor.close()
  Object.defineProperty(Element.prototype, 'clientHeight', alturaOriginal)
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', offsetOriginal)
})

async function comSessao() {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return auth
}

function Tela({ permissoes, intervaloMs }: { permissoes: string[]; intervaloMs?: number }) {
  const rota = useRota()
  return (
    <Casca usuario={{ uid: 'u1', email: 'ana@redetv.com.br', papeis: [], permissoes }} rota={rota} aoSair={() => {}}>
      {rota.tipo === 'acervo' && <Acervo filtros={rota.filtros} permissoes={permissoes} intervaloMs={intervaloMs} />}
    </Casca>
  )
}

async function abrir(opcoes: { intervaloMs?: number; aoSessaoExpirada?: () => void; permissoes?: string[]; endereco?: string; consultas?: QueryClient } = {}) {
  history.replaceState(null, '', opcoes.endereco ?? '/acervo')
  const consultas = opcoes.consultas ?? criarClienteDeConsultas()
  // Sem a espera entre as tentativas: a falha aparece já.
  consultas.setDefaultOptions({ queries: { ...consultas.getDefaultOptions().queries, retryDelay: 0 } })
  const api = criarClienteDaApi(await comSessao(), opcoes.aoSessaoExpirada ?? (() => {}))
  render(
    <AtalhosProvider>
      <QueryClientProvider client={consultas}>
        <ContextoDaApi.Provider value={api}>
          <Tela permissoes={opcoes.permissoes ?? ['decupagem.ver', 'video.enviar']} intervaloMs={opcoes.intervaloMs} />
        </ContextoDaApi.Provider>
      </QueryClientProvider>
    </AtalhosProvider>,
  )
  return consultas
}

async function abrirEnvio(usuario: ReturnType<typeof userEvent.setup>) {
  await usuario.click(await screen.findByRole('button', { name: 'Enviar vídeo' }))
  return screen.findByRole('dialog')
}

function preencherData(dialogo: ReturnType<typeof within>) {
  fireEvent.change(dialogo.getByLabelText(/^Data de exibição/), { target: { value: '2026-10-28' } })
}

function mp4(nome = 'enviado.mp4') {
  const bytes = new Uint8Array(64)
  bytes.set(new TextEncoder().encode('ftypisom'), 4)
  return new File([bytes], nome, { type: 'video/mp4' })
}

const cartao = (nome: string) => screen.getByText(nome).closest('article') as HTMLElement
const ultimaChamada = () => new URLSearchParams(chamadas[chamadas.length - 1])

test('o cartão mostra nome, programa, data de exibição, duração, estado, quem enviou e quando', async () => {
  jobs = [
    job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido', programa: 'TV Fama', data_exibicao: '2026-10-28', duracao_s: 125 }),
    job({ id: 'b', nome: 'sem-data.mp4', estado: 'validando', enviado_por: { tipo: 'sistema', nome: 'ingest' } }),
  ]
  await abrir()

  const pronto = within(await waitFor(() => cartao('pronto.mp4')))
  expect(pronto.getByText('TV Fama, exibido em 28/10/2026')).toBeTruthy()
  expect(pronto.getByText('02:05')).toBeTruthy()
  expect(pronto.getByText('Concluído')).toBeTruthy()
  // 15:00Z é 12:00 em São Paulo, o fuso fixado em vite.config.ts.
  expect(pronto.getByText('Enviado em 29/10/2026 12:00 por ana@redetv.com.br')).toBeTruthy()
  const semData = within(cartao('sem-data.mp4'))
  expect(semData.getByText('Sem programa, sem data de exibição')).toBeTruthy()
  expect(semData.getByText('Em quarentena')).toBeTruthy()
  expect(semData.getByText(/por ingest$/)).toBeTruthy()
})

test('pede a primeira página com 50 por vez, do mais recente ao mais antigo', async () => {
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  expect(ultimaChamada().get('limite')).toBe('50')
  expect(ultimaChamada().get('ordem')).toBe('enviado')
})

test('o cartão com falha mostra a frase em português, e o código só na dica', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'quebrado.mp4', estado: 'falhou', codigo_falha: 'codec_nao_suportado' })]
  await abrir()

  const falhou = within(await waitFor(() => cartao('quebrado.mp4')))
  expect(falhou.getByText('Falhou')).toBeTruthy()
  const frase = falhou.getByText('O vídeo usa um codec que não aceitamos. Envie em H.264.')
  expect(screen.queryByText(/codec_nao_suportado/)).toBeNull()
  await usuario.hover(frase)
  expect((await screen.findAllByText(/codec_nao_suportado/)).length).toBeGreaterThan(0)
})

test('só o vídeo concluído ou com falha abre, pelo link, pelo clique no cartão ou por Enter', async () => {
  const usuario = userEvent.setup()
  jobs = [
    job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido', programa: 'TV Fama' }),
    job({ id: 'b', nome: 'andando.mp4', estado: 'analisando' }),
    job({ id: 'c', nome: 'quebrado.mp4', estado: 'falhou', codigo_falha: 'analise_falhou' }),
  ]
  await abrir()
  await screen.findByText('pronto.mp4')

  expect(screen.getByRole('link', { name: 'pronto.mp4' }).getAttribute('href')).toBe('/video/a')
  expect(screen.queryByRole('link', { name: 'andando.mp4' })).toBeNull()
  expect(screen.getByRole('link', { name: 'quebrado.mp4' }).getAttribute('href')).toBe('/video/c')
  await usuario.click(within(cartao('andando.mp4')).getByText('Decupando'))
  expect(location.pathname).toBe('/acervo')

  await usuario.click(within(cartao('pronto.mp4')).getByText(/^TV Fama/))
  expect(location.pathname).toBe('/video/a')

  act(() => navegar('/acervo'))
  ;(await screen.findByRole('link', { name: 'quebrado.mp4' })).focus()
  await usuario.keyboard('{Enter}')
  expect(location.pathname).toBe('/video/c')
})

test('as setas andam entre os vídeos', async () => {
  const usuario = userEvent.setup()
  jobs = ['um', 'dois', 'tres'].map((n) => job({ id: n, nome: `${n}.mp4`, estado: 'concluido' }))
  await abrir()
  await screen.findByText('um.mp4')
  // 800 px de largura dão 2 colunas de cartões de 260 px.
  screen.getByRole('link', { name: 'um.mp4' }).focus()

  await usuario.keyboard('{ArrowRight}')
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('link', { name: 'dois.mp4' })))
  await usuario.keyboard('{ArrowLeft}')
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('link', { name: 'um.mp4' })))
  await usuario.keyboard('{ArrowDown}')
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('link', { name: 'tres.mp4' })))
})

test('as teclas do acervo e o envio aparecem na lista do ?', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.keyboard('?')

  expect(await screen.findByText('No acervo: ir ao vídeo ao lado')).toBeTruthy()
  expect(screen.getByText('Enviar vídeo', { selector: 'dt' })).toBeTruthy()
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

test('o espaço digitado no fim da busca fica na caixa depois da espera', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')
  const caixa = screen.getByLabelText('Buscar por nome') as HTMLInputElement

  await usuario.type(caixa, 'clipe ')
  await waitFor(() => expect(location.search).toBe('?q=clipe'))
  await usuario.type(caixa, 'dois')

  expect(caixa.value).toBe('clipe dois')
  await waitFor(() => expect(location.search).toBe('?q=clipe+dois'))
})

test('estado desconhecido na URL sai do filtro', async () => {
  await abrir({ endereco: '/acervo?estado=inventado&estado=falhou' })
  await screen.findByText('Nenhum vídeo com esses filtros.')

  expect(ultimaChamada().getAll('estado')).toEqual(['falhou'])
})

test('cada filtro muda a chamada à API e a URL', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.click(screen.getByRole('button', { name: 'Programa' }))
  await usuario.click(await screen.findByRole('option', { name: 'TV Fama' }))
  await waitFor(() => expect(ultimaChamada().get('programa')).toBe('TV Fama'))

  await usuario.click(screen.getByRole('button', { name: 'Exibição' }))
  fireEvent.change(await screen.findByLabelText('Exibido de'), { target: { value: '2026-10-01' } })
  await waitFor(() => expect(ultimaChamada().get('exibicao_de')).toBe('2026-10-01'))
  fireEvent.change(screen.getByLabelText('Exibido até'), { target: { value: '2026-10-31' } })
  await waitFor(() => expect(ultimaChamada().get('exibicao_ate')).toBe('2026-10-31'))
  await usuario.keyboard('{Escape}')

  await usuario.click(screen.getByRole('button', { name: 'Estado' }))
  await usuario.click(await screen.findByRole('option', { name: 'Decupando' }))
  await usuario.click(screen.getByRole('option', { name: 'Falhou' }))
  await waitFor(() => expect(ultimaChamada().getAll('estado')).toEqual(['analisando', 'falhou']))
  expect(screen.getByRole('option', { name: 'Falhou' }).getAttribute('aria-checked')).toBe('true')

  expect(location.search).toBe('?programa=TV+Fama&de=2026-10-01&ate=2026-10-31&estado=analisando&estado=falhou')
})

test('um filtro curto, sem campo de busca, se escolhe só pelo teclado', async () => {
  const usuario = userEvent.setup()
  await abrir()
  await screen.findByText('Nenhum vídeo enviado ainda.')

  await usuario.click(screen.getByRole('button', { name: 'Estado' }))
  await screen.findByRole('option', { name: 'Decupando' })
  await usuario.keyboard('{ArrowDown}{Enter}')
  await waitFor(() => expect(ultimaChamada().getAll('estado')).toHaveLength(1))
})

test('abrir a URL com filtros restaura a tela', async () => {
  await abrir({ endereco: '/acervo?q=fama&programa=TV+Fama&de=2026-10-01&ate=2026-10-31&estado=falhou&ordem=exibicao' })
  await screen.findByText('Nenhum vídeo com esses filtros.')

  const p = ultimaChamada()
  expect([p.get('q'), p.get('programa'), p.get('exibicao_de'), p.get('exibicao_ate'), p.get('ordem')]).toEqual(['fama', 'TV Fama', '2026-10-01', '2026-10-31', 'exibicao'])
  expect(p.getAll('estado')).toEqual(['falhou'])
  expect((screen.getByLabelText('Buscar por nome') as HTMLInputElement).value).toBe('fama')
  expect(screen.getByRole('button', { name: 'Programa: TV Fama' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Estado: Falhou' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Exibição: 01/10/2026 a 31/10/2026' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Ordenar por data de exibição' })).toBeTruthy()
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

test('o X do filtro limpa só aquele filtro', async () => {
  const usuario = userEvent.setup()
  await abrir({ endereco: '/acervo?estado=falhou&programa=TV+Fama' })
  await screen.findByText('Nenhum vídeo com esses filtros.')

  await usuario.click(screen.getByRole('button', { name: 'Limpar estado' }))

  await waitFor(() => expect(location.search).toBe('?programa=TV+Fama'))
})

test('a ordem muda pelo menu e fica na URL; o padrão é a data de envio', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'um.mp4' })]
  await abrir()
  await screen.findByText('um.mp4')

  await usuario.click(screen.getByRole('button', { name: 'Ordenar por data de envio' }))
  await usuario.click(await screen.findByRole('menuitemradio', { name: 'Data de exibição' }))

  await waitFor(() => expect(ultimaChamada().get('ordem')).toBe('exibicao'))
  expect(location.search).toBe('?ordem=exibicao')
  expect(screen.getByRole('button', { name: 'Ordenar por data de exibição' })).toBeTruthy()
})

test('rolar até o fim traz a página seguinte, pelo cursor, e para na última', async () => {
  jobs = Array.from({ length: 55 }, (_, i) => job({ id: `j${i}`, nome: `video-${i}.mp4`, estado: 'concluido' }))
  await abrir()
  await screen.findByText('video-0.mp4')
  // 10 fileiras de 100 px à vista (2 colunas), com 3 de folga: a página seguinte ainda não foi pedida.
  expect(screen.queryByText('video-49.mp4')).toBeNull()
  expect(chamadas).toHaveLength(1)

  const rolagem = screen.getByText('video-0.mp4').closest('.overflow-y-auto') as HTMLElement
  rolagem.scrollTop = 2000
  fireEvent.scroll(rolagem)

  expect(await screen.findByText('video-54.mp4')).toBeTruthy()
  expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toEqual([null, 'j49'])
  expect(document.querySelectorAll('[data-esqueleto]').length).toBe(0)
})

test('o 422 do cursor da volta recomeça do topo, e rolar segue pedindo a página seguinte', async () => {
  jobs = Array.from({ length: 160 }, (_, i) => job({ id: `j${i}`, nome: `video-${i}.mp4`, estado: 'concluido' }))
  const consultas = await abrir()
  await screen.findByText('video-0.mp4')
  const rolar = (px: number) => {
    const rolagem = screen.getAllByText(/^video-\d+\.mp4$/)[0].closest('.overflow-y-auto') as HTMLElement
    rolagem.scrollTop = px
    fireEvent.scroll(rolagem)
  }
  rolar(2000)
  await waitFor(() => expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toContain('j49'))
  rolar(4500)
  await waitFor(() => expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toContain('j99'))
  const chave = consultas.getQueryCache().findAll({ queryKey: ['acervo'] })[0].queryHash
  cleanup()
  // Saiu para o vídeo 120 (página do cursor j99); na volta o cache venceu, e a lista do cursor também.
  lembrarPosicao(consultas, chave, 120)
  consultas.removeQueries({ queryKey: ['acervo'] })
  cursorVencido = 'j99'
  chamadas.length = 0

  await abrir({ consultas })
  await screen.findByText('video-0.mp4')
  expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toEqual(['j99', null])
  rolar(2000)
  await waitFor(() => expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toEqual(['j99', null, 'j49']))
})

test('a volta do acervo sobrevive a outra lista no meio (acervo, vídeo, parecidos, volta, volta)', async () => {
  jobs = Array.from({ length: 160 }, (_, i) => job({ id: `j${i}`, nome: `video-${i}.mp4`, estado: 'concluido' }))
  const consultas = await abrir()
  await screen.findByText('video-0.mp4')
  const rolar = (px: number) => {
    const rolagem = screen.getAllByText(/^video-\d+\.mp4$/)[0].closest('.overflow-y-auto') as HTMLElement
    rolagem.scrollTop = px
    fireEvent.scroll(rolagem)
  }
  rolar(2000)
  await waitFor(() => expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toContain('j49'))
  rolar(4500)
  await waitFor(() => expect(chamadas.map((c) => new URLSearchParams(c).get('cursor'))).toContain('j99'))
  const chave = consultas.getQueryCache().findAll({ queryKey: ['acervo'] })[0].queryHash
  cleanup()
  lembrarPosicao(consultas, chave, 120)

  // Do vídeo para os parecidos, outra lista, e a volta ao vídeo: ela guarda a posição dela.
  const parecidos = renderHook(
    () => usePaginas({ chave: ['parecidos', 'v1', 3], pedir: async () => [1, 2], proximo: () => null, itens: (ps: number[][]) => ps.flat(), tamanho: (p: number[]) => p.length }),
    { wrapper: ({ children }) => <QueryClientProvider client={consultas}>{children}</QueryClientProvider> },
  )
  await waitFor(() => expect(parecidos.result.current.quantidade).toBe(2))
  lembrarPosicao(consultas, parecidos.result.current.chave, 1)
  parecidos.unmount()

  // De volta ao acervo, com o cache vencido: recomeça na página do vídeo 120 (o jsdom não rola até ela).
  consultas.removeQueries({ queryKey: ['acervo'] })
  chamadas.length = 0
  await abrir({ consultas })
  await waitFor(() => expect(chamadas.length).toBeGreaterThan(0))
  expect(new URLSearchParams(chamadas[0]).get('cursor')).toBe('j99')
})

test('sem rede, o acervo mostra o esqueleto, não a lista vazia, e carrega quando a rede volta', async () => {
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' })]
  onlineManager.setOnline(false)
  await abrir()
  expect(await screen.findByRole('status', { name: 'Carregando o acervo' })).toBeTruthy()
  await new Promise((r) => setTimeout(r, 50))
  expect(screen.queryByText('Nenhum vídeo enviado ainda.')).toBeNull()
  expect(chamadas).toEqual([])

  act(() => onlineManager.setOnline(true))
  expect(await screen.findByText('pronto.mp4')).toBeTruthy()
  expect(screen.queryByRole('status', { name: 'Carregando o acervo' })).toBeNull()
})

test('grade ou lista fica guardada no navegador', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'um.mp4', estado: 'concluido' })]
  await abrir()
  await screen.findByText('um.mp4')

  await usuario.click(screen.getByRole('button', { name: 'Lista' }))

  expect(screen.getByRole('button', { name: 'Lista' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.queryByRole('article')).toBeNull()
  expect(screen.getByText('um.mp4')).toBeTruthy()
  cleanup()
  await abrir()
  await screen.findByText('um.mp4')
  expect(screen.getByRole('button', { name: 'Lista' }).getAttribute('aria-pressed')).toBe('true')
})

function andamentoQueConta(pedidos: string[][]) {
  return http.get('/v1/jobs/andamento', ({ request }) => {
    const ids = new URL(request.url).searchParams.get('ids')!.split(',')
    pedidos.push(ids)
    return HttpResponse.json(jobs.filter((j) => ids.includes(j.id)))
  })
}

test('só os vídeos em andamento são consultados de novo, e a lista não é pedida de novo', async () => {
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' }), job({ id: 'b', nome: 'andando.mp4', estado: 'validando' })]
  const pedidos: string[][] = []
  servidor.use(andamentoQueConta(pedidos))
  await abrir({ intervaloMs: 20 })
  await screen.findByText('andando.mp4')
  const listagens = chamadas.length

  jobs = [jobs[0], job({ id: 'b', nome: 'andando.mp4', estado: 'concluido' })]

  await waitFor(() => expect(within(cartao('andando.mp4')).getByText('Concluído')).toBeTruthy())
  expect(new Set(pedidos.flat())).toEqual(new Set(['b']))
  expect(chamadas.length).toBe(listagens)
})

test('concluído com etapas ainda rodando aparece "Finalizando" e é consultado até a indexação acabar', async () => {
  const agora = new Date().toISOString()
  const haSeteHoras = new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString()
  const pendente = { estado: 'pendente', em: agora }
  jobs = [
    job({ id: 'a', nome: 'rodando.mp4', estado: 'concluido', etapa_atual: 'identificacao', indexacao: pendente }),
    job({ id: 'b', nome: 'entre.mp4', estado: 'concluido', etapa_atual: null, indexacao: pendente }),
    job({ id: 'e', nome: 'corrigido.mp4', estado: 'concluido', indexacao: { estado: 'indexado', em: agora }, etapas: [{ nome: 'identificacao', inicio: agora, fim: agora }] }),
    job({ id: 'c', nome: 'falhou.mp4', estado: 'concluido', indexacao: pendente, etapas: [{ nome: 'indexacao', inicio: agora, fim: agora }] }),
    job({ id: 'd', nome: 'preso.mp4', estado: 'concluido', etapa_atual: 'identificacao', indexacao: { estado: 'pendente', em: haSeteHoras }, etapas: [{ nome: 'identificacao', inicio: haSeteHoras }] }),
  ]
  const pedidos: string[][] = []
  servidor.use(andamentoQueConta(pedidos))
  await abrir({ intervaloMs: 20 })
  await screen.findByText('rodando.mp4')
  expect(within(cartao('rodando.mp4')).getByText('Finalizando')).toBeTruthy()
  expect(within(cartao('entre.mp4')).getByText('Finalizando')).toBeTruthy()
  expect(within(cartao('corrigido.mp4')).getByText('Finalizando')).toBeTruthy()
  expect(within(cartao('falhou.mp4')).getByText('Concluído')).toBeTruthy()
  expect(within(cartao('preso.mp4')).getByText('Concluído')).toBeTruthy()

  jobs = [job({ ...jobs[0], etapa_atual: null, indexacao: { estado: 'indexado', em: agora }, etapas: [{ nome: 'indexacao', inicio: agora, fim: agora }] }), ...jobs.slice(1)]

  await waitFor(() => expect(within(cartao('rodando.mp4')).getByText('Concluído')).toBeTruthy())
  expect(new Set(pedidos.flat())).toEqual(new Set(['a', 'b', 'e']))
  // Uma rodada, um pedido: os três vão juntos já na primeira.
  expect([...pedidos[0]].sort()).toEqual(['a', 'b', 'e'])
})

test('a consulta de um vídeo em andamento mantém a capa da lista', async () => {
  const pendente = { estado: 'pendente', em: new Date().toISOString() }
  jobs = [job({ id: 'a', nome: 'rodando.mp4', estado: 'concluido', etapa_atual: 'inventario_de_objetos', indexacao: pendente, capa_url: '/capa-a.jpg' })]
  let consultas = 0
  servidor.use(
    http.get('/v1/jobs/andamento', () => {
      consultas++
      return HttpResponse.json([{ ...jobs[0], capa_url: undefined }])
    }),
  )
  await abrir({ intervaloMs: 20 })
  await screen.findByText('rodando.mp4')
  await waitFor(() => expect(consultas).toBeGreaterThan(1))
  expect(document.querySelector('img[src="/capa-a.jpg"]')).toBeTruthy()
})

test('o vídeo que termina sem capa na lista ganha a capa do detalhe, sem recarregar a lista', async () => {
  jobs = [job({ id: 'a', nome: 'andando.mp4', estado: 'validando' })]
  const detalhes: string[] = []
  servidor.use(
    andamentoQueConta([]),
    http.get('/v1/jobs/a', () => {
      detalhes.push('a')
      return HttpResponse.json({ ...jobs[0], capa_url: '/capa-a.jpg' })
    }),
  )
  await abrir({ intervaloMs: 20 })
  await screen.findByText('andando.mp4')
  const listagens = chamadas.length

  jobs = [job({ id: 'a', nome: 'andando.mp4', estado: 'concluido' })]

  await waitFor(() => expect(document.querySelector('img[src="/capa-a.jpg"]')).toBeTruthy())
  expect(detalhes).toEqual(['a'])
  expect(chamadas.length).toBe(listagens)
})

test('o vídeo que termina sem capa (falhou) não repete o pedido do detalhe', async () => {
  jobs = [job({ id: 'a', nome: 'andando.mp4', estado: 'validando' })]
  let detalhes = 0
  let rodadas = 0
  servidor.use(
    http.get('/v1/jobs/andamento', () => {
      rodadas++
      return HttpResponse.json(jobs)
    }),
    http.get('/v1/jobs/a', () => {
      detalhes++
      return HttpResponse.json({ ...jobs[0], capa_url: null })
    }),
  )
  await abrir({ intervaloMs: 20 })
  await screen.findByText('andando.mp4')

  jobs = [job({ id: 'a', nome: 'andando.mp4', estado: 'falhou', codigo_falha: 'erro_interno' })]

  await waitFor(() => expect(detalhes).toBe(1))
  const antes = rodadas
  await new Promise((r) => setTimeout(r, 100))
  expect(detalhes).toBe(1)
  expect(rodadas).toBe(antes)
})

test('com a aba escondida, ninguém é consultado', async () => {
  jobs = [job({ id: 'b', nome: 'andando.mp4', estado: 'validando' })]
  let consultas = 0
  servidor.use(
    http.get('/v1/jobs/andamento', ({ request }) => {
      if (new URL(request.url).searchParams.get('ids')!.split(',').includes('b')) consultas++
      return HttpResponse.json([jobs[0]])
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

test('o vídeo que a rota de andamento omite (lixeira ou sumiu) sai da lista', async () => {
  jobs = [job({ id: 'a', nome: 'ficou.mp4', estado: 'validando' }), job({ id: 'b', nome: 'sumiu.mp4', estado: 'validando' })]
  servidor.use(http.get('/v1/jobs/andamento', () => HttpResponse.json([{ ...jobs[0], estado: 'concluido' }])))
  await abrir({ intervaloMs: 20 })
  await screen.findByText('sumiu.mp4')

  await waitFor(() => expect(screen.queryByText('sumiu.mp4')).toBeNull())
  expect(within(cartao('ficou.mp4')).getByText('Concluído')).toBeTruthy()
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
  expect(screen.getByText('Código para o suporte: http_503')).toBeTruthy()

  statusDaLista = 200
  await usuario.click(screen.getByRole('button', { name: 'Tentar de novo' }))

  expect(await screen.findByText('Nenhum vídeo enviado ainda.')).toBeTruthy()
})

test('a miniatura mostra a capa do vídeo; sem capa fica o retângulo', async () => {
  jobs = [
    job({ id: 'a', nome: 'com-capa.mp4', estado: 'concluido', capa_url: 'https://storage.exemplo/quadros/a/plano-1.jpg?x=1' }),
    job({ id: 'b', nome: 'sem-planos.mp4', estado: 'concluido', capa_url: null }),
  ]
  await abrir()

  const comCapa = await waitFor(() => cartao('com-capa.mp4'))
  expect(comCapa.querySelector('img')?.getAttribute('src')).toBe('https://storage.exemplo/quadros/a/plano-1.jpg?x=1')
  expect(cartao('sem-planos.mp4').querySelector('img')).toBeNull()
})

// ---------- o menu de cada vídeo ----------

test('o menu traz a lixeira só com lixeira.gerir e no estado que a API aceita; reprocessar só no concluído', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' }), job({ id: 'b', nome: 'andando.mp4', estado: 'validando' })]
  await abrir({ permissoes: ['decupagem.ver'] })
  await usuario.click(await screen.findByRole('button', { name: 'Ações de pronto.mp4' }))
  expect(await screen.findByRole('menuitem', { name: 'Copiar o link' })).toBeTruthy()
  expect(screen.queryByRole('menuitem', { name: /lixeira/ })).toBeNull()
  expect(screen.queryByRole('menuitem', { name: /Reprocessar/ })).toBeNull()
  // Em andamento, sem permissão: não há o que fazer, e nem o botão aparece.
  expect(screen.queryByRole('button', { name: 'Ações de andando.mp4' })).toBeNull()
  cleanup()

  await abrir({ permissoes: ['decupagem.ver', 'lixeira.gerir', 'video.reprocessar_etapa'] })
  await usuario.click(await screen.findByRole('button', { name: 'Ações de pronto.mp4' }))
  expect(await screen.findByRole('menuitem', { name: /Mandar para a lixeira/ })).toBeTruthy()
  expect(screen.getByRole('menuitem', { name: /Reprocessar/ })).toBeTruthy()
  await usuario.keyboard('{Escape}')
  expect(screen.queryByRole('button', { name: 'Ações de andando.mp4' })).toBeNull()
})

test('mandar para a lixeira pelo menu tira o vídeo da tela e avisa', async () => {
  const usuario = userEvent.setup()
  const envios: unknown[] = []
  servidor.use(
    http.get('/v1/admin/lixeira/videos/:id/impacto', () => HttpResponse.json({ decupagem: 1, correcoes: 0, arquivos: { copia_limpa: 1, proxy: 1, quadros: 10 }, outros_jobs: [] })),
    http.post('/v1/admin/lixeira/videos/:id', async ({ params, request }) => {
      envios.push({ id: params.id, corpo: await request.json() })
      return HttpResponse.json({}, { status: 201 })
    }),
  )
  jobs = [job({ id: 'a', nome: 'TV Fama.mp4', estado: 'concluido' }), job({ id: 'b', nome: 'outro.mp4', estado: 'concluido' })]
  const listagens = () => chamadas.length
  await abrir({ permissoes: ['decupagem.ver', 'lixeira.gerir'] })
  await usuario.click(await screen.findByRole('button', { name: 'Ações de TV Fama.mp4' }))
  await usuario.click(await screen.findByRole('menuitem', { name: /Mandar para a lixeira/ }))
  const dialogo = within(await screen.findByRole('dialog'))
  await dialogo.findByText(/^1 vídeo, 1 decupagem/)
  const antes = listagens()
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'duplicado{Enter}')

  expect(await screen.findByText('TV Fama.mp4 foi para a lixeira.')).toBeTruthy()
  expect(envios).toEqual([{ id: 'a', corpo: { motivo: 'duplicado' } }])
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByText('TV Fama.mp4')).toBeNull()
  expect(screen.getByText('outro.mp4')).toBeTruthy()
  expect(listagens()).toBe(antes)
})

test('reprocessar pelo menu põe o vídeo em andamento', async () => {
  const usuario = userEvent.setup()
  const pedidos: unknown[] = []
  servidor.use(
    http.post('/v1/jobs/:id/reprocessar', async ({ request }) => {
      pedidos.push(await request.json())
      return HttpResponse.json({ ...jobs[0], estado: 'analisando', etapa_atual: 'analise', capa_url: undefined })
    }),
    http.get('/v1/jobs/andamento', () => HttpResponse.json([])),
  )
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido', capa_url: '/capa-a.jpg' })]
  await abrir({ permissoes: ['decupagem.ver', 'video.reprocessar_etapa'], intervaloMs: 60_000 })
  await usuario.click(await screen.findByRole('button', { name: 'Ações de pronto.mp4' }))
  await usuario.click(await screen.findByRole('menuitem', { name: /Reprocessar/ }))
  const dialogo = within(await screen.findByRole('dialog'))
  await usuario.click(dialogo.getByRole('radio', { name: /Identificação/ }))
  await usuario.type(dialogo.getByLabelText(/Motivo/), 'rostos novos')
  await usuario.click(dialogo.getByRole('button', { name: 'Reprocessar' }))

  expect(await screen.findByText('pronto.mp4: reprocessando a partir da etapa Identificação.')).toBeTruthy()
  expect(pedidos).toEqual([{ etapa: 'identificacao', motivo: 'rostos novos' }])
  expect(within(cartao('pronto.mp4')).getByText('Decupando')).toBeTruthy()
  expect(document.querySelector('img[src="/capa-a.jpg"]')).toBeTruthy()
})

// ---------- o envio, na casca ----------

test('sem a permissão de enviar, o botão não aparece mas os vídeos sim', async () => {
  jobs = [job({ id: 'a', nome: 'pronto.mp4', estado: 'concluido' })]
  await abrir({ permissoes: ['decupagem.ver'] })

  expect(await screen.findByText('pronto.mp4')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Enviar vídeo' })).toBeNull()
})

test('o diálogo de envio recusa na hora o arquivo que não é MP4, sem chamar a API', async () => {
  const usuario = userEvent.setup({ applyAccept: false })
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))
  preencherData(dialogo)

  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4('filme.mov'))

  expect((await dialogo.findByRole('alert')).textContent).toContain('.mp4')
  expect(criacoes).toEqual([])
})

test('envia o MP4 com programa e data de exibição, e o vídeo aparece no topo do acervo', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'antigo.mp4', estado: 'concluido' })]
  await abrir()
  await screen.findByText('antigo.mp4')
  const dialogo = within(await abrirEnvio(usuario))

  await usuario.selectOptions(await dialogo.findByRole('combobox', { name: 'Programa' }), 'TV Fama')
  preencherData(dialogo)
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect(await dialogo.findByText(/Envio concluído/)).toBeTruthy()
  expect(criacoes).toEqual([{ nome: 'enviado.mp4', tamanho_bytes: 64, tipo: 'video/mp4', programa: 'TV Fama', data_exibicao: '2026-10-28' }])
  expect(pedacosEnviados).toEqual([64])
  await waitFor(() => expect(document.querySelector('article')?.textContent).toContain('enviado.mp4'))
  expect(within(cartao('enviado.mp4')).getByText('Aguardando envio')).toBeTruthy()
})

test('sem data de exibição o envio não chama a API e a tela diz o que falta', async () => {
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))
  expect((dialogo.getByLabelText(/^Data de exibição/) as HTMLInputElement).required).toBe(true)

  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect((await dialogo.findByRole('alert')).textContent).toContain('Informe a data de exibição')
  expect(criacoes).toEqual([])
  expect(pedacosEnviados).toEqual([])

  preencherData(dialogo)
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect(await dialogo.findByText(/Envio concluído/)).toBeTruthy()
  expect(dialogo.queryByRole('alert')).toBeNull()
  expect(criacoes).toHaveLength(1)
})

test('sem programa, o corpo da criação leva o arquivo e a data', async () => {
  const usuario = userEvent.setup()
  programas = null
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))

  expect(dialogo.queryByRole('combobox', { name: 'Programa' })).toBeNull()
  preencherData(dialogo)
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect(await dialogo.findByText(/Envio concluído/)).toBeTruthy()
  expect(criacoes).toEqual([{ nome: 'enviado.mp4', tamanho_bytes: 64, tipo: 'video/mp4', data_exibicao: '2026-10-28' }])
})

test('o envio mostra o progresso, trava o arquivo e não fecha até terminar', async () => {
  let liberar = () => {}
  let chegou = false
  servidor.use(
    http.put(SESSAO, async () => {
      chegou = true
      await new Promise<void>((resolve) => (liberar = resolve))
      return new HttpResponse(null, { status: 200 })
    }),
  )
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))
  const campo = dialogo.getByLabelText('Arquivo MP4') as HTMLInputElement

  preencherData(dialogo)
  await usuario.upload(campo, mp4())
  await dialogo.findByRole('progressbar', { name: 'Progresso do envio' })

  expect(campo.disabled).toBe(true)
  expect(dialogo.queryByRole('button', { name: 'Fechar' })).toBeNull()
  await usuario.keyboard('{Escape}')
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.pointerDown(document.body)
  expect(screen.getByRole('dialog')).toBeTruthy()
  // A barra aparece antes do PUT: só ele chegando há o que liberar.
  await waitFor(() => expect(chegou).toBe(true))
  liberar()
  await dialogo.findByText(/Envio concluído/)
  expect(campo.disabled).toBe(false)
})

test('dois arquivos soltos seguidos criam um Job só', async () => {
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))
  preencherData(dialogo)
  const area = dialogo.getByLabelText('Arquivo MP4').closest('label')!

  fireEvent.drop(area, { dataTransfer: { files: [mp4('um.mp4')] } })
  fireEvent.drop(area, { dataTransfer: { files: [mp4('dois.mp4')] } })

  await dialogo.findByText(/Envio concluído/)
  expect(criacoes).toEqual([expect.objectContaining({ nome: 'um.mp4' })])
})

test('U não abre o envio num campo de texto nem com um menu aberto', async () => {
  const usuario = userEvent.setup()
  jobs = [job({ id: 'a', nome: 'um.mp4' })]
  await abrir()
  await screen.findByText('um.mp4')

  await usuario.type(screen.getByLabelText('Buscar por nome'), 'u')
  await usuario.click(screen.getByRole('button', { name: 'Ordenar por data de envio' }))
  await screen.findByRole('menu')
  await usuario.keyboard('u')

  expect(screen.queryByRole('dialog')).toBeNull()
})

test('data de exibição no futuro vira uma mensagem em português com a ação', async () => {
  servidor.use(http.post('/v1/jobs', () => HttpResponse.json({ detail: 'Data de exibição no futuro' }, { status: 422 })))
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))

  preencherData(dialogo)
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect((await dialogo.findByRole('alert')).textContent).toContain('data de exibição não pode ser no futuro')
})

test('uma falha ao criar o Job vira mensagem em português', async () => {
  servidor.use(http.post('/v1/jobs', () => new HttpResponse(null, { status: 500 })))
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))

  preencherData(dialogo)
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())

  expect((await dialogo.findByRole('alert')).textContent).toContain('Não foi possível enviar o vídeo')
})

test('reabrir o diálogo começa um envio novo, sem o aviso do anterior; U também abre', async () => {
  const usuario = userEvent.setup()
  await abrir()
  const dialogo = within(await abrirEnvio(usuario))
  preencherData(dialogo)
  await usuario.upload(dialogo.getByLabelText('Arquivo MP4'), mp4())
  await dialogo.findByText(/Envio concluído/)

  await usuario.click(dialogo.getByRole('button', { name: 'Fechar' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await usuario.keyboard('u')
  const reaberto = within(await screen.findByRole('dialog'))

  expect(reaberto.queryByText(/Envio concluído/)).toBeNull()
  expect((reaberto.getByLabelText(/^Data de exibição/) as HTMLInputElement).value).toBe('')
})
