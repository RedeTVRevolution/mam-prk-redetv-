import { QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { lerResultado } from '../../resultadoDaBusca.ts'
import { useRota } from '../../rotas.ts'
import { AtalhosProvider } from '../Atalhos.tsx'
import { Casca } from '../Casca.tsx'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { Busca, Parecidos } from './Busca.tsx'

const momento = (inicio_ms: number, fim_ms: number, motivo: string, destaques: object[] = []) => ({
  tipo: 'objeto' as string,
  inicio_ms,
  fim_ms,
  motivo,
  destaques,
  quadro_url: null as string | null,
  quadro: null as string | null,
})

function video(id: string, momentos: ReturnType<typeof momento>[]) {
  return { job_id: id, nome: `${id}.mp4`, programa: 'TV Fama', data_exibicao: '2026-10-21', duracao_s: 2959, n_momentos: momentos.length, momentos }
}

const SEM_FACETAS = { programa: [], mes: [], pessoa: [], marca: [], tipo: [] }
const faceta = (valor: string, videos: number, rotulo = valor) => ({ valor, rotulo, videos })

function resultado(extra: object = {}) {
  return {
    entendida: { evidencias: ['imagem', 'objeto'], programa: null, desde: null, ate: null },
    videos: [
      video('v1', [momento(724_000, 731_000, 'Objeto: sandália vermelha · Mel Breia', [{ inicio: 8, fim: 16 }]), { ...momento(2_462_000, 2_490_000, "Fala: 'aquele sapato vermelho'"), tipo: 'fala' }]),
      video('v2', [momento(60_000, 65_000, 'Objeto: scarpin vermelho')]),
    ],
    sem_aparicoes: [],
    plano_b: false,
    facetas: SEM_FACETAS,
    ...extra,
  }
}

const plano = (inicio_ms: number, motivo: string, quadro: string) => ({ ...momento(inicio_ms, inicio_ms + 5_000, motivo), tipo: 'plano', quadro })
const DA_FOTO = resultado({
  entendida: { evidencias: ['imagem', 'objeto'], programa: null, desde: null, ate: null, visual: false, termo_da_foto: 'sandália vermelha' },
})
const PLANOS = resultado({
  entendida: { evidencias: ['imagem'], programa: null, desde: null, ate: null, visual: true },
  videos: [video('v1', [plano(724_000, 'Plano: rua molhada', 'quadros/plano-1.jpg'), plano(60_000, 'Plano: estúdio', 'quadros/plano-2.jpg')])],
})

interface JobApi {
  id: string
  estado: string
  indexacao?: { estado: string; em: string } | null
}
const agora = () => new Date().toISOString()
const job = (id: string, indexacao: string | null): JobApi => ({ id, estado: 'concluido', indexacao: indexacao ? { estado: indexacao, em: agora() } : null })

const buscas: URLSearchParams[] = []
const quadrosPedidos: string[] = []
const fotos: { params: URLSearchParams; arquivo: File | null }[] = []
const parecidos: URLSearchParams[] = []
let resposta: () => Response = () => HttpResponse.json(resultado())
let respostaDaFoto: () => Response = () => HttpResponse.json(DA_FOTO)
let respostaDosParecidos: () => Response = () => HttpResponse.json(PLANOS)
let jobs: JobApi[] = []
let pedidosDoAcervo: URLSearchParams[] = []

const servidor = setupServer(
  http.get('/v1/jobs', ({ request }) => {
    pedidosDoAcervo.push(new URL(request.url).searchParams)
    return HttpResponse.json(jobs.map((j) => ({ nome: `${j.id}.mp4`, codigo_falha: null, criado_em: agora(), atualizado_em: agora(), ...j })))
  }),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama', 'Leo Dias'])),
  http.get('/v1/jobs/:id/quadros/:arquivo', ({ params }) => {
    quadrosPedidos.push(`${params.id}/${params.arquivo}`)
    return HttpResponse.json({ url: `https://q.exemplo/${params.id}/${params.arquivo}`, expira_em: '2999-01-01T00:00:00Z' })
  }),
  http.get('/v1/busca', ({ request }) => {
    buscas.push(new URL(request.url).searchParams)
    return resposta()
  }),
  http.post('/v1/busca/imagem', async ({ request }) => {
    fotos.push({ params: new URL(request.url).searchParams, arquivo: (await request.formData()).get('arquivo') as File | null })
    return respostaDaFoto()
  }),
  http.get('/v1/busca/parecidos', ({ request }) => {
    parecidos.push(new URL(request.url).searchParams)
    return respostaDosParecidos()
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
  sessionStorage.clear()
  servidor.resetHandlers()
  buscas.length = 0
  quadrosPedidos.length = 0
  fotos.length = 0
  parecidos.length = 0
  jobs = []
  pedidosDoAcervo = []
  resposta = () => HttpResponse.json(resultado())
  respostaDaFoto = () => HttpResponse.json(DA_FOTO)
  respostaDosParecidos = () => HttpResponse.json(PLANOS)
})
afterAll(() => {
  servidor.close()
  Object.defineProperty(Element.prototype, 'clientHeight', alturaOriginal)
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', offsetOriginal)
})

function Tela() {
  const rota = useRota()
  return (
    <Casca usuario={{ uid: 'u1', email: 'ana@redetv.com.br', papeis: [], permissoes: ['decupagem.ver'] }} rota={rota} aoSair={() => {}}>
      {rota.tipo === 'busca' && <Busca consulta={rota.consulta} />}
      {rota.tipo === 'parecidos' && <Parecidos job={rota.job} plano={rota.plano} />}
    </Casca>
  )
}

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  const consultas = criarClienteDeConsultas()
  render(
    <AtalhosProvider>
      <QueryClientProvider client={consultas}>
        <ContextoDaApi.Provider value={criarClienteDaApi(auth, () => {})}>
          <Tela />
        </ContextoDaApi.Provider>
      </QueryClientProvider>
    </AtalhosProvider>,
  )
}

// O chip "Marca" (a evidência) e o filtro "Marca" têm o mesmo nome: o filtro é o de fora do grupo.
const filtro = (nome: string) => screen.getAllByRole('button', { name: nome }).find((b) => !b.closest('[role=group]'))!
const cena = (nome: RegExp) => screen.getByRole('link', { name: nome }).closest('article') as HTMLElement
const foto = () => new File([new Uint8Array([137, 80, 78, 71])], 'pista.png', { type: 'image/png' })

// Responde à busca só quando `liberar()` é chamada: o que a tela mostra no meio da espera.
function segurarABusca() {
  let liberar = () => {}
  const espera = new Promise<void>((r) => {
    liberar = r
  })
  servidor.use(
    http.get('/v1/busca', async ({ request }) => {
      buscas.push(new URL(request.url).searchParams)
      await espera
      return HttpResponse.json(resultado({ videos: [video('vB', [momento(1000, 2000, 'Objeto: balão')])] }))
    }),
  )
  return liberar
}

test('a URL reproduz a busca: q, ev, programa, ano e ordem vão à API', async () => {
  await abrir('/busca?q=sapato&ev=fala&ev=objeto&programa=TV+Fama&ano=2024&ordem=data')

  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
  const p = buscas[0]
  expect(p.get('q')).toBe('sapato')
  expect(p.getAll('ev')).toEqual(['fala', 'objeto'])
  expect(p.get('programa')).toBe('TV Fama')
  expect(p.get('desde')).toBe('2024-01-01')
  expect(p.get('ate')).toBe('2024-12-31')
  expect(p.get('ordem')).toBe('data')
  expect(p.get('limite')).toBe('20')
})

test('a caixa da busca aceita no máximo 300 caracteres, como a API', async () => {
  await abrir('/busca?q=sapato&ev=fala')
  await screen.findByText('3 momentos em 2 vídeos')

  const caixa = screen.getByRole('searchbox', { name: 'Buscar no conteúdo' })
  expect((caixa as HTMLInputElement).maxLength).toBe(300)
})

test('Enter na caixa da página vai a /busca?q= com a consulta nova', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato&ev=fala')
  await screen.findByText('3 momentos em 2 vídeos')
  const caixa = screen.getByRole('searchbox', { name: 'Buscar no conteúdo' })
  expect((caixa as HTMLInputElement).value).toBe('sapato')

  await usuario.clear(caixa)
  await usuario.type(caixa, 'sapato vermelho{Enter}')

  expect(location.pathname + location.search).toBe('/busca?q=sapato+vermelho')
  await waitFor(() => expect(buscas.at(-1)?.get('q')).toBe('sapato vermelho'))
})

test('sem termo a tela diz o que fazer e não busca, nem confere o aviso do #404', async () => {
  jobs = [job('a', 'pendente')]
  await abrir('/busca')
  expect(await screen.findByText(/Escreva acima o que procurar/)).toBeTruthy()
  await new Promise((r) => setTimeout(r, 50))
  expect(buscas).toHaveLength(0)
  expect(pedidosDoAcervo).toHaveLength(0)
  expect(screen.queryByText(/entrando na busca/)).toBeNull()
})

test('os chips ligados são os entendidos; mudar um refaz a busca pela URL', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  expect(screen.getByRole('button', { name: 'Na imagem' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: 'Fala' }).getAttribute('aria-pressed')).toBe('false')

  await usuario.click(screen.getByRole('button', { name: 'Fala' }))
  await usuario.click(screen.getByRole('button', { name: 'Marca' }))

  // Os chips seguem a URL: dois cliques seguidos ligam os dois, mesmo fora do entendido.
  expect(location.search).toBe('?q=sapato&ev=imagem&ev=objeto&ev=fala&ev=marca')
  await waitFor(() => expect(buscas.at(-1)?.getAll('ev')).toEqual(['imagem', 'objeto', 'fala', 'marca']))
  expect(screen.getByRole('button', { name: 'Marca' }).getAttribute('aria-pressed')).toBe('true')
})

test('o último chip ligado não se desliga', async () => {
  await abrir('/busca?q=sapato&ev=fala')
  await screen.findByText('3 momentos em 2 vídeos')
  expect((screen.getByRole('button', { name: 'Fala' }) as HTMLButtonElement).disabled).toBe(true)
  expect((screen.getByRole('button', { name: 'GC' }) as HTMLButtonElement).disabled).toBe(false)
})

test('cada momento é uma cena com o vídeo, o programa, a data, o instante e o motivo (#400)', async () => {
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')

  const primeira = cena(/^v1\.mp4 em 12:04$/)
  expect(within(primeira).getByText('TV Fama, 21/10/2026')).toBeTruthy()
  expect(within(primeira).getByText('12:04')).toBeTruthy()
  // Sem quadro, o tipo do momento ocupa o lugar dele.
  expect(within(primeira).getByText('Objeto')).toBeTruthy()
  expect(within(cena(/^v1\.mp4 em 41:02$/)).getByText('Fala')).toBeTruthy()
  expect(screen.getByRole('link', { name: /^v2\.mp4 em 01:00$/ })).toBeTruthy()
  // O motivo descreve o link.
  expect(screen.getByRole('link', { name: /^v1\.mp4 em 12:04$/, description: /Mel Breia/ })).toBeTruthy()
})

test('o destaque sai das posições e um <script> da API aparece como texto', async () => {
  resposta = () => HttpResponse.json(resultado({ videos: [video('v1', [momento(0, 1000, 'Fala: <script>alert(1)</script> sapato', [{ inicio: 6, fim: 14 }])])] }))
  await abrir('/busca?q=sapato')

  const marca = await screen.findByText('<script>')
  expect(marca.tagName).toBe('MARK')
  expect(document.querySelector('script')).toBeNull()
  expect(screen.getByText(/alert\(1\)/)).toBeTruthy()
})

test('o clique na cena abre o vídeo exatamente no início do momento, com o busca', async () => {
  const usuario = userEvent.setup()
  resposta = () => HttpResponse.json(resultado({ videos: [video('v1', [momento(6_540, 8_000, 'Objeto: calça vinho')])] }))
  await abrir('/busca?q=calça vinho')
  await screen.findByText('1 momento em 1 vídeo')

  await usuario.click(within(cena(/v1\.mp4/)).getByText('Objeto: calça vinho'))

  expect(location.pathname + location.search).toBe('/video/v1?t=6.54&busca=cal%C3%A7a+vinho')
})

test('↓ de fora da grade foca a primeira cena, as setas andam entre elas e Enter abre o vídeo no tempo', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  screen.getByRole('button', { name: 'Fala' }).focus()

  await usuario.keyboard('{ArrowDown}')
  expect(document.activeElement?.getAttribute('href')).toBe('/video/v1?t=724&busca=sapato')
  // 800 px de largura dão 3 colunas de cenas de 240 px: as três na mesma fileira.
  await usuario.keyboard('{ArrowRight}')
  await waitFor(() => expect(document.activeElement?.getAttribute('href')).toBe('/video/v1?t=2462&busca=sapato'))
  await usuario.keyboard('{ArrowRight}')
  await waitFor(() => expect(document.activeElement?.getAttribute('href')).toBe('/video/v2?t=60&busca=sapato'))
  await usuario.keyboard('{ArrowLeft}')
  await waitFor(() => expect(document.activeElement?.getAttribute('href')).toBe('/video/v1?t=2462&busca=sapato'))

  await usuario.keyboard('{Enter}')

  expect(location.pathname + location.search).toBe('/video/v1?t=2462&busca=sapato')
})

test('o vídeo aberto daqui recebe o resultado para andar com N e Shift+N', async () => {
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  await waitFor(() => expect(lerResultado('sapato')?.map((v) => v.job_id)).toEqual(['v1', 'v2']))
})

test('o vazio honesto traz a contagem de menções e o botão liga Citada e Fala', async () => {
  const usuario = userEvent.setup()
  resposta = () => HttpResponse.json(resultado({ videos: [], sem_aparicoes: [{ pessoa_id: 'p1', nome: 'Sabrina Sato', mencoes_na_fala: 12, mencoes_na_tela: 0 }] }))
  await abrir('/busca?q=Sabrina+Sato')

  expect(await screen.findByText('Nenhuma aparição de Sabrina Sato. 12 menções na fala.')).toBeTruthy()
  expect(screen.queryByText(/Nenhum momento encontrado/)).toBeNull()

  await usuario.click(screen.getByRole('button', { name: 'Ver as menções' }))

  expect(location.search).toContain('ev=citada')
  expect(location.search).toContain('ev=fala')
})

test('sem nenhum momento a tela diz o termo e sugere tirar um filtro', async () => {
  resposta = () => HttpResponse.json(resultado({ videos: [] }))
  await abrir('/busca?q=xyz')
  expect(await screen.findByText('Nenhum momento encontrado para “xyz”. Tente outras palavras ou tire um filtro.')).toBeTruthy()
})

test('429 e tempo esgotado têm mensagem própria, com a ação', async () => {
  resposta = () => new HttpResponse(null, { status: 429 })
  await abrir('/busca?q=sapato')
  expect((await screen.findByRole('alert')).textContent).toContain('Muitas buscas seguidas. Espere alguns segundos.')
  cleanup()

  resposta = () => new HttpResponse(null, { status: 504 })
  await abrir('/busca?q=sapato')
  const alerta = await screen.findByRole('alert')
  expect(alerta.textContent).toContain('A busca demorou demais. Tente uma consulta mais específica.')
  resposta = () => HttpResponse.json(resultado())
  await userEvent.setup().click(within(alerta).getByRole('button', { name: 'Tentar de novo' }))
  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
})

test('termo novo com resultado na tela mostra o carregando e tira o resultado anterior (#396)', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=microfone')
  await screen.findByText('3 momentos em 2 vídeos')
  const liberar = segurarABusca()

  const caixa = screen.getByRole('searchbox', { name: 'Buscar no conteúdo' })
  await usuario.clear(caixa)
  await usuario.type(caixa, 'balão{Enter}')

  expect(await screen.findByRole('status', { name: 'Buscando' })).toBeTruthy()
  expect(screen.queryByText('3 momentos em 2 vídeos')).toBeNull()
  expect(screen.queryByRole('link', { name: /v1\.mp4/ })).toBeNull()

  liberar()
  expect(await screen.findByText('1 momento em 1 vídeo')).toBeTruthy()
  expect(screen.queryByRole('status', { name: 'Buscando' })).toBeNull()
})

test('trocar a ordem mantém a lista e mostra o "Atualizando" até a resposta (#396)', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  const liberar = segurarABusca()

  await usuario.click(screen.getByRole('button', { name: 'Ordenar por relevância' }))
  await usuario.click(await screen.findByRole('menuitemradio', { name: 'Data de exibição' }))

  expect(location.search).toBe('?q=sapato&ordem=data')
  expect(await screen.findByRole('status', { name: 'Atualizando' })).toBeTruthy()
  expect(screen.getByText('3 momentos em 2 vídeos')).toBeTruthy()
  expect(screen.queryByRole('status', { name: 'Buscando' })).toBeNull()

  liberar()
  expect(await screen.findByText('1 momento em 1 vídeo')).toBeTruthy()
  expect(screen.queryByRole('status', { name: 'Atualizando' })).toBeNull()
  expect(buscas.at(-1)?.get('ordem')).toBe('data')
})

test('limpar o ano tira o período que a API entendeu', async () => {
  const usuario = userEvent.setup()
  resposta = () => HttpResponse.json(resultado({ entendida: { evidencias: ['objeto'], programa: null, desde: '2020-03-01', ate: '2024-12-31' } }))
  await abrir('/busca?q=vestido')
  await screen.findByText('3 momentos em 2 vídeos')
  expect(screen.getByRole('button', { name: 'Ano: 01/03/2020 a 31/12/2024' })).toBeTruthy()

  await usuario.click(screen.getByRole('button', { name: 'Limpar ano' }))

  expect(location.search).toBe('?q=vestido&ano=todos')
  await waitFor(() => expect(buscas.at(-1)?.get('sem_periodo')).toBe('true'))
})

test('o programa entendido aparece escolhido; escolher outro ano zera o mês', async () => {
  const usuario = userEvent.setup()
  resposta = () => HttpResponse.json(resultado({ entendida: { evidencias: ['objeto'], programa: 'TV Fama', desde: '2025-01-01', ate: '2025-12-31' } }))
  await abrir('/busca?q=vestido&mes=2025-05')
  await screen.findByText('3 momentos em 2 vídeos')
  expect(screen.getByRole('button', { name: 'Programa: TV Fama' })).toBeTruthy()

  await usuario.click(screen.getByRole('button', { name: 'Ano: 2025' }))
  await usuario.click(await screen.findByRole('option', { name: '2024' }))

  expect(location.search).toBe('?q=vestido&ano=2024')
})

test('o GC longo vem encurtado, com "ver mais" e "ver menos", sem abrir o vídeo', async () => {
  const usuario = userEvent.setup()
  const longo = `GC: ${'PARTICIPAÇÃO VÁLIDA DAS 0H DE 27/04 ATÉ 15H DE 25/11/2025, EXCLUSIVA PARA AS '.repeat(3)}`
  resposta = () => HttpResponse.json(resultado({ videos: [video('v1', [momento(9_000, 12_000, longo), momento(14_000, 15_000, 'GC: BOLÃO')])] }))
  await abrir('/busca?q=bolão')
  const verMais = await screen.findByRole('button', { name: 'ver mais' })
  expect(screen.getAllByRole('button', { name: /ver (mais|menos)/ })).toHaveLength(1)
  expect(verMais.getAttribute('aria-expanded')).toBe('false')

  await usuario.click(verMais)

  expect(screen.getByRole('button', { name: 'ver menos' }).getAttribute('aria-expanded')).toBe('true')
  expect(location.pathname).toBe('/busca')
})

test('as facetas trazem a contagem; escolher filtra pela URL e as contagens se atualizam', async () => {
  const usuario = userEvent.setup()
  resposta = () => {
    const programa = buscas[buscas.length - 1].get('programa')
    return HttpResponse.json(
      resultado({
        facetas: programa
          ? { ...SEM_FACETAS, programa: [faceta(programa, 1)], marca: [faceta('Adidas', 1)] }
          : {
              programa: [faceta('TV Fama', 8), faceta('Leo Dias', 2)],
              mes: [faceta('2024-05', 7, '05/2024')],
              pessoa: [faceta('p1', 5, 'Sabrina Sato')],
              marca: [faceta('Nike', 4), faceta('Adidas', 1)],
              tipo: [faceta('fala', 6, 'Fala')],
            },
      }),
    )
  }
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')

  await usuario.click(screen.getByRole('button', { name: 'Programa' }))
  const leo = await screen.findByRole('option', { name: /Leo Dias/ })
  expect(leo.textContent).toContain('2')
  await usuario.click(leo)

  expect(location.search).toContain('programa=Leo+Dias')
  await waitFor(() => expect(buscas.at(-1)?.get('programa')).toBe('Leo Dias'))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Pessoa' })).toBeNull())
  await usuario.click(filtro('Marca'))
  expect((await screen.findByRole('option', { name: /Adidas/ })).textContent).toContain('1')
  expect(screen.queryByRole('option', { name: /Nike/ })).toBeNull()
})

test('as facetas de mês, pessoa, marca e tipo vão à API; o X as tira', async () => {
  const usuario = userEvent.setup()
  resposta = () =>
    HttpResponse.json(
      resultado({
        facetas: { ...SEM_FACETAS, mes: [faceta('2024-02', 3, '02/2024')], pessoa: [faceta('p1', 5, 'Sabrina Sato')], marca: [faceta('Nike', 4)], tipo: [faceta('texto_na_tela', 2, 'GC')] },
      }),
    )
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  for (const [rotulo, valor] of [
    ['Data de exibição', '02/2024'],
    ['Pessoa', 'Sabrina Sato'],
    ['Marca', 'Nike'],
    ['Tipo de momento', 'GC'],
  ]) {
    await usuario.click(filtro(rotulo))
    await usuario.click(await screen.findByRole('option', { name: new RegExp(valor) }))
  }

  await waitFor(() => expect(buscas.at(-1)?.get('tipo')).toBe('texto_na_tela'))
  const p = buscas.at(-1)!
  expect(p.get('desde')).toBe('2024-02-01')
  expect(p.get('ate')).toBe('2024-02-29')
  expect(p.get('pessoa')).toBe('p1')
  expect(p.get('marca')).toBe('Nike')

  await usuario.click(screen.getByRole('button', { name: 'Limpar marca' }))
  await waitFor(() => expect(buscas.at(-1)?.get('marca')).toBeNull())
})

test('o botão "Busca visual" liga o modo pela URL, e só os planos ficam na grade', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=pista+molhada')
  await screen.findByText('3 momentos em 2 vídeos')
  expect(buscas[0].has('visual')).toBe(false)
  resposta = () =>
    HttpResponse.json({
      ...PLANOS,
      // A fala que o texto livre trouxe fica fora da grade.
      videos: [video('v1', [...PLANOS.videos[0].momentos, { ...momento(5_000, 6_000, 'Fala: a pista'), tipo: 'fala' }])],
    })

  await usuario.click(screen.getByRole('button', { name: 'Busca visual' }))

  expect(location.search).toBe('?q=pista+molhada&modo=visual')
  await waitFor(() => expect(buscas.at(-1)?.get('visual')).toBe('true'))
  expect(await screen.findByText('2 momentos em 1 vídeo')).toBeTruthy()
  expect(screen.queryByText('Fala: a pista')).toBeNull()
  expect(screen.getByRole('button', { name: 'Busca visual' }).getAttribute('aria-pressed')).toBe('true')
})

test('modo visual sem o vetor do quadro avisa e mostra a busca comum', async () => {
  resposta = () => HttpResponse.json(resultado({ entendida: { evidencias: ['imagem'], programa: null, desde: null, ate: null, visual: false } }))
  await abrir('/busca?q=pista&modo=visual')

  expect(await screen.findByText(/busca visual não está disponível/i)).toBeTruthy()
  expect(screen.getByText('3 momentos em 2 vídeos')).toBeTruthy()
})

test('o quadro vem da rota do quadro do vídeo, uma vez por arquivo', async () => {
  resposta = () => HttpResponse.json(PLANOS)
  await abrir('/busca?q=rua')
  await screen.findByText('2 momentos em 1 vídeo')

  const primeira = cena(/em 12:04/)
  await waitFor(() => expect(primeira.querySelector('img')?.getAttribute('src')).toBe('https://q.exemplo/v1/plano-1.jpg'))
  expect([...new Set(quadrosPedidos)].toSorted()).toEqual(['v1/plano-1.jpg', 'v1/plano-2.jpg'])
})

test('rolar até o fim traz a página seguinte pelo X-Proximo-Cursor (#426)', async () => {
  const muitos = Array.from({ length: 30 }, (_, i) => video(`v${i}`, [momento(0, 1000, `Objeto: item ${i}`)]))
  resposta = () => {
    const cursor = buscas.at(-1)!.get('cursor')
    const inicio = cursor ? 20 : 0
    return HttpResponse.json(resultado({ videos: muitos.slice(inicio, inicio + 20) }), { headers: cursor ? {} : { 'X-Proximo-Cursor': 'abc.20' } })
  }
  await abrir('/busca?q=item')
  expect(await screen.findByText('Mais de 20 momentos')).toBeTruthy()

  const rolagem = screen.getByRole('link', { name: /^v0\.mp4/ }).closest('.overflow-y-auto') as HTMLElement
  rolagem.scrollTop = 3000
  fireEvent.scroll(rolagem)

  expect(await screen.findByText('30 momentos em 30 vídeos')).toBeTruthy()
  expect(buscas.map((p) => p.get('cursor'))).toEqual([null, 'abc.20'])
})

test('vídeos concluídos com a indexação pendente mostram o aviso com a contagem (#404)', async () => {
  jobs = [job('a', 'pendente'), job('b', 'pendente'), job('c', 'indexado'), job('d', 'falhou')]
  await abrir('/busca?q=sapato')
  expect(await screen.findByText('2 vídeos ainda estão entrando na busca e podem não aparecer aqui.')).toBeTruthy()
  expect(pedidosDoAcervo[0].getAll('estado')).toEqual(['concluido'])
})

test('um vídeo entrando na busca leva o aviso no singular (#404)', async () => {
  jobs = [job('a', 'pendente'), job('d', 'falhou')]
  await abrir('/busca?q=sapato')
  expect(await screen.findByText('1 vídeo ainda está entrando na busca e pode não aparecer aqui.')).toBeTruthy()
})

test('com tudo indexado (ou a indexação que falhou) não há aviso (#404)', async () => {
  jobs = [job('c', 'indexado'), job('d', 'falhou')]
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  await waitFor(() => expect(pedidosDoAcervo).toHaveLength(1))
  expect(screen.queryByText(/entrando na busca/)).toBeNull()
})

// A busca por imagem

test('escolher a foto manda o arquivo em multipart e mostra as cenas e o termo que o modelo deu', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())

  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
  expect(fotos).toHaveLength(1)
  expect(fotos[0].arquivo?.size).toBe(4)
  expect(fotos[0].params.get('limite')).toBe('20')
  expect(screen.getByText(/Buscando por:/).textContent).toBe('Buscando por: sandália vermelha')
  // Como na busca por texto, voltam momentos de todos os tipos, não só planos.
  expect(screen.getByText(/aquele sapato vermelho/)).toBeTruthy()
  // A grade abre o vídeo sem o termo.
  expect(screen.getByRole('link', { name: /^v1\.mp4 em 12:04$/ }).getAttribute('href')).toBe('/video/v1?t=724')
  expect(screen.getByText('pista.png')).toBeTruthy()
})

test('arrastar a foto para a página também busca', async () => {
  await abrir('/busca')
  const alvo = await screen.findByText(/Escreva acima/)
  fireEvent.dragOver(alvo, { dataTransfer: { types: ['Files'], files: [] } })
  fireEvent.drop(alvo, { dataTransfer: { types: ['Files'], files: [foto()] } })

  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
  expect(fotos).toHaveLength(1)
})

test('o programa e o período da tela vão junto, e mudar o filtro busca de novo com a mesma foto', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=pista&programa=TV+Fama&ano=2026')
  await screen.findByText('3 momentos em 2 vídeos')
  await usuario.upload(screen.getByLabelText('Foto para buscar'), foto())
  await screen.findByText('3 momentos em 2 vídeos')
  expect(fotos[0].params.get('programa')).toBe('TV Fama')
  expect(fotos[0].params.get('desde')).toBe('2026-01-01')
  expect(fotos[0].params.get('ate')).toBe('2026-12-31')
  expect(fotos[0].params.has('q')).toBe(false)
  // Com a foto, os chips da busca por texto saem.
  expect(screen.queryByRole('group', { name: 'Tipo de evidência' })).toBeNull()

  await usuario.click(screen.getByRole('button', { name: 'Programa: TV Fama' }))
  await usuario.click(await screen.findByRole('option', { name: 'Leo Dias' }))

  await waitFor(() => expect(fotos).toHaveLength(2))
  expect(fotos[1].params.get('programa')).toBe('Leo Dias')
  expect(fotos[1].arquivo?.size).toBe(4)
})

test('tipo ou tamanho errado: a mensagem da API aparece em português', async () => {
  respostaDaFoto = () => HttpResponse.json({ detail: 'Envie uma imagem JPEG ou PNG válida' }, { status: 422 })
  const usuario = userEvent.setup({ applyAccept: false })
  await abrir('/busca')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), new File(['x'], 'a.gif', { type: 'image/gif' }))

  expect((await screen.findByRole('alert')).textContent).toContain('Envie uma imagem JPEG ou PNG válida')
})

test('com o modelo da consulta fora a tela diz que a busca por imagem não está disponível', async () => {
  respostaDaFoto = () => HttpResponse.json({ detail: 'x' }, { status: 503 })
  const usuario = userEvent.setup()
  await abrir('/busca')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())

  expect((await screen.findByRole('alert')).textContent).toContain('A busca por imagem não está disponível agora')
})

test('sem momentos para o termo a tela avisa, e Limpar esquece a foto', async () => {
  respostaDaFoto = () => HttpResponse.json({ ...DA_FOTO, videos: [] })
  const usuario = userEvent.setup()
  await abrir('/busca')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())

  expect((await screen.findByRole('status')).textContent).toContain('Nenhum momento encontrado para “sandália vermelha”. Tire um filtro, tente outra foto ou digite o que procura.')

  await usuario.click(screen.getByRole('button', { name: 'Limpar' }))
  expect(screen.queryByText(/Nenhum momento encontrado/)).toBeNull()
  expect(screen.queryByText('pista.png')).toBeNull()
  expect(screen.getByText(/Escreva acima/)).toBeTruthy()
})

test('um texto novo depois da foto sai da foto e busca o texto', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca')
  await usuario.upload(await screen.findByLabelText('Foto para buscar'), foto())
  await screen.findByText('3 momentos em 2 vídeos')

  await usuario.type(screen.getByRole('searchbox', { name: 'Buscar no conteúdo' }), 'pista{Enter}')

  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
  expect(buscas.map((p) => p.get('q'))).toEqual(['pista'])
  expect(screen.queryByText('pista.png')).toBeNull()
  expect(fotos).toHaveLength(1)
})

test('Enter com o mesmo texto da URL depois da foto também sai da foto e busca o texto', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=pista')
  await screen.findByText('3 momentos em 2 vídeos')
  await usuario.upload(screen.getByLabelText('Foto para buscar'), foto())
  await screen.findByText('3 momentos em 2 vídeos')

  await usuario.type(screen.getByRole('searchbox', { name: 'Buscar no conteúdo' }), '{Enter}')

  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
  expect(screen.queryByText('pista.png')).toBeNull()
  expect(fotos).toHaveLength(1)
})

// Os planos parecidos

test('os planos parecidos vêm em grade, com a volta ao vídeo', async () => {
  await abrir('/busca/parecidos?job=v9&plano=3')

  expect(await screen.findByText('2 planos parecidos em 1 vídeo')).toBeTruthy()
  expect(parecidos[0].get('job')).toBe('v9')
  expect(parecidos[0].get('plano')).toBe('3')
  expect(parecidos[0].get('limite')).toBe('50')
  expect(screen.getByRole('link', { name: 'Voltar ao vídeo' }).getAttribute('href')).toBe('/video/v9')
  expect(screen.getByRole('link', { name: /^v1\.mp4 em 12:04$/ }).getAttribute('href')).toBe('/video/v1?t=724')
})

test('plano sem vetor do quadro: o 404 tem mensagem própria', async () => {
  respostaDosParecidos = () => new HttpResponse(null, { status: 404 })
  await abrir('/busca/parecidos?job=v9&plano=3')
  expect((await screen.findByRole('alert')).textContent).toContain('Este plano não tem vetor do quadro')
})

test('sem planos parecidos a tela diz isso', async () => {
  respostaDosParecidos = () => HttpResponse.json({ ...PLANOS, videos: [] })
  await abrir('/busca/parecidos?job=v9&plano=3')
  expect(await screen.findByText('Nenhum plano parecido.')).toBeTruthy()
})
