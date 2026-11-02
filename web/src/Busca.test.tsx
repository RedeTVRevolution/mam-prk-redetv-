import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { trechosDoMotivo } from './busca.ts'
import { render } from './render-teste.tsx'

const momento = (inicio_ms: number, fim_ms: number, motivo: string, destaques: object[] = []) => ({
  inicio_ms,
  fim_ms,
  motivo,
  destaques,
  quadro_url: null,
})

function video(id: string, momentos: ReturnType<typeof momento>[]) {
  return {
    job_id: id,
    nome: `${id}.mp4`,
    programa: 'TV Fama',
    data_exibicao: '2026-10-21',
    duracao_s: 2959,
    n_momentos: momentos.length,
    momentos,
  }
}

const SEM_FACETAS = { programa: [], mes: [], pessoa: [], marca: [], tipo: [] }

function resultado(extra: object = {}) {
  return {
    entendida: { evidencias: ['imagem', 'objeto'], programa: null, desde: null, ate: null },
    videos: [
      video('v1', [
        momento(724_000, 731_000, 'Objeto: sandália vermelha · Mel Breia', [{ inicio: 8, fim: 16 }]),
        momento(2_462_000, 2_490_000, "Fala: 'aquele sapato vermelho'"),
      ]),
      video('v2', [momento(60_000, 65_000, 'Objeto: scarpin vermelho')]),
    ],
    sem_aparicoes: [],
    plano_b: false,
    facetas: SEM_FACETAS,
    ...extra,
  }
}

const buscas: URLSearchParams[] = []
let resposta: () => Response = () => HttpResponse.json(resultado())

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes: ['decupagem.ver'] })),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json(['TV Fama', 'Leo Dias'])),
  http.get('/v1/jobs/:id', () => new HttpResponse(null, { status: 404 })),
  http.get('/v1/busca', ({ request }) => {
    buscas.push(new URL(request.url).searchParams)
    return resposta()
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  buscas.length = 0
  resposta = () => HttpResponse.json(resultado())
  cleanup()
})
afterAll(() => servidor.close())

async function abrir(endereco: string) {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', endereco)
  render(<App autenticador={auth} />)
}

test('a barra tem a caixa; / a foca no Acervo e, com o foco num campo, vira texto', async () => {
  const usuario = userEvent.setup()
  await abrir('/acervo')
  const caixa = await screen.findByRole('textbox', { name: 'Buscar no acervo' })

  await usuario.keyboard('/')
  expect(document.activeElement).toBe(caixa)
  expect((caixa as HTMLInputElement).value).toBe('')

  await usuario.keyboard('a/b')
  expect((caixa as HTMLInputElement).value).toBe('a/b')
})

test('/ foca a caixa também na tela do vídeo', async () => {
  const usuario = userEvent.setup()
  await abrir('/video/v1')
  const caixa = await screen.findByRole('textbox', { name: 'Buscar no acervo' })

  await usuario.keyboard('/')

  expect(document.activeElement).toBe(caixa)
})

test('a / aparece na lista de atalhos', async () => {
  const usuario = userEvent.setup()
  await abrir('/acervo')
  await screen.findByRole('textbox', { name: 'Buscar no acervo' })

  await usuario.keyboard('?')

  expect(await screen.findByText('Buscar no acervo', { selector: 'p' })).toBeTruthy()
})

test('Enter na caixa vai a /busca?q= e mostra o resultado', async () => {
  const usuario = userEvent.setup()
  await abrir('/acervo')
  await usuario.type(await screen.findByRole('textbox', { name: 'Buscar no acervo' }), 'sapato vermelho{Enter}')

  expect(location.pathname + location.search).toBe('/busca?q=sapato+vermelho')
  expect(await screen.findByText('3 momentos em 2 vídeos')).toBeTruthy()
  expect(buscas[0].get('q')).toBe('sapato vermelho')
})

test('a URL reproduz a busca: q, ev, programa, ano e ordem vão à API', async () => {
  await abrir('/busca?q=sapato&ev=fala&ev=objeto&programa=TV+Fama&ano=2024&ordem=data')

  await screen.findByText('3 momentos em 2 vídeos')

  const p = buscas[0]
  expect(p.get('q')).toBe('sapato')
  expect(p.getAll('ev')).toEqual(['fala', 'objeto'])
  expect(p.get('programa')).toBe('TV Fama')
  expect(p.get('desde')).toBe('2024-01-01')
  expect(p.get('ate')).toBe('2024-12-31')
  expect(p.get('ordem')).toBe('data')
})

test('os chips ligados são os entendidos; mudar um refaz a busca pela URL', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  expect(screen.getByRole('button', { name: 'Na imagem' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByRole('button', { name: 'Fala' }).getAttribute('aria-pressed')).toBe('false')

  await usuario.click(screen.getByRole('button', { name: 'Fala' }))

  expect(location.search).toBe('?q=sapato&ev=imagem&ev=objeto&ev=fala')
  await waitFor(() => expect(buscas.at(-1)?.getAll('ev')).toEqual(['imagem', 'objeto', 'fala']))
})

test('o resultado vem agrupado por vídeo, com programa, data, duração e momentos', async () => {
  await abrir('/busca?q=sapato')

  const grupo = await screen.findByRole('region', { name: 'v1.mp4' })

  expect(within(grupo).getByText('TV Fama · 21/10/2026 · 49:19')).toBeTruthy()
  expect(within(grupo).getByText('2 momentos')).toBeTruthy()
  expect(within(grupo).getByText('12:04–12:11')).toBeTruthy()
  expect(within(grupo).getByRole('img', { name: 'Posição dos momentos no vídeo' })).toBeTruthy()
})

test('o destaque sai das posições e um <script> da API aparece como texto', async () => {
  resposta = () =>
    HttpResponse.json(
      resultado({
        videos: [video('v1', [momento(0, 1000, 'Fala: <script>alert(1)</script> sapato', [{ inicio: 6, fim: 14 }])])],
      }),
    )
  await abrir('/busca?q=sapato')

  const marca = await screen.findByText('<script>')
  expect(marca.tagName).toBe('MARK')
  expect(document.querySelector('script')).toBeNull()
  expect(screen.getByText(/alert\(1\)/)).toBeTruthy()
})

test('trechosDoMotivo conta caracteres, não unidades UTF-16, e ignora posição fora do texto', () => {
  expect(
    trechosDoMotivo('😀 ab', [
      { inicio: 2, fim: 4 },
      { inicio: 3, fim: 99 },
    ]),
  ).toEqual([
    { texto: '😀 ', destacado: false },
    { texto: 'ab', destacado: true },
  ])
})

test('↓ e ↑ atravessam os grupos e Enter abre o vídeo no tempo, com o busca', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')

  await usuario.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
  const selecionado = document.querySelector('[aria-current="true"]')
  expect(selecionado?.getAttribute('href')).toBe('/video/v2?t=60&busca=sapato')
  await usuario.keyboard('{ArrowUp}')
  expect(document.querySelector('[aria-current="true"]')?.getAttribute('href')).toBe('/video/v1?t=2462&busca=sapato')

  await usuario.keyboard('{Enter}')

  expect(location.pathname + location.search).toBe('/video/v1?t=2462&busca=sapato')
})

test('o clique no momento abre o vídeo no tempo', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await usuario.click(await screen.findByRole('link', { name: /12:04–12:11/ }))

  expect(location.pathname + location.search).toBe('/video/v1?t=724&busca=sapato')
})

test('o vazio honesto traz a contagem de menções e o botão liga Citada e Fala', async () => {
  const usuario = userEvent.setup()
  resposta = () =>
    HttpResponse.json(
      resultado({
        videos: [],
        sem_aparicoes: [{ pessoa_id: 'p1', nome: 'Sabrina Sato', mencoes_na_fala: 12, mencoes_na_tela: 0 }],
      }),
    )
  await abrir('/busca?q=Sabrina+Sato')

  expect(await screen.findByText('Nenhuma aparição de Sabrina Sato. 12 menções na fala.')).toBeTruthy()
  expect(screen.queryByText(/Nenhum momento encontrado/)).toBeNull()

  await usuario.click(screen.getByRole('button', { name: 'Ver as menções' }))

  expect(location.search).toContain('ev=citada')
  expect(location.search).toContain('ev=fala')
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
  expect(within(alerta).getByRole('button', { name: 'Tentar de novo' })).toBeTruthy()
})

test('"Mais vídeos" pede mais, até o teto da API', async () => {
  const usuario = userEvent.setup()
  const muitos = Array.from({ length: 20 }, (_, i) => video(`v${i}`, [momento(0, 1000, 'Objeto: x')]))
  resposta = () => HttpResponse.json(resultado({ videos: muitos }))
  await abrir('/busca?q=x')

  await usuario.click(await screen.findByRole('button', { name: 'Mais vídeos' }))

  await waitFor(() => expect(buscas.at(-1)?.get('limite')).toBe('40'))
})

test('trocar a ordem refaz a busca com ordem=data', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')

  await usuario.click(screen.getByRole('combobox', { name: 'Ordenar' }))
  await usuario.click(await screen.findByRole('option', { name: 'Ordenar: Data de exibição' }))

  expect(location.search).toBe('?q=sapato&ordem=data')
})

test('com o foco noutro campo do Acervo, / vira texto e não pula para a caixa', async () => {
  const usuario = userEvent.setup()
  await abrir('/acervo')
  const filtro = await screen.findByRole('textbox', { name: 'Buscar por nome' })

  await usuario.type(filtro, 'a/b')

  expect(document.activeElement).toBe(filtro)
  expect((filtro as HTMLInputElement).value).toBe('a/b')
})

test('Enter abre o momento selecionado mesmo com o foco num chip', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')
  screen.getByRole('button', { name: 'Fala' }).focus()

  await usuario.keyboard('{ArrowDown}{Enter}')

  expect(location.pathname + location.search).toBe('/video/v1?t=724&busca=sapato')
})

test('os chips seguem a URL: dois cliques seguidos ligam os dois, mesmo fora do entendido', async () => {
  const usuario = userEvent.setup()
  await abrir('/busca?q=sapato')
  await screen.findByText('3 momentos em 2 vídeos')

  await usuario.click(screen.getByRole('button', { name: 'Fala' }))
  await usuario.click(screen.getByRole('button', { name: 'Marca' }))

  expect(location.search).toBe('?q=sapato&ev=imagem&ev=objeto&ev=fala&ev=marca')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Marca' }).getAttribute('aria-pressed')).toBe('true'))
})

test('"Todos os anos" tira o período que a API entendeu', async () => {
  const usuario = userEvent.setup()
  resposta = () =>
    HttpResponse.json(
      resultado({ entendida: { evidencias: ['objeto'], programa: null, desde: '2020-03-01', ate: '2024-12-31' } }),
    )
  await abrir('/busca?q=vestido')
  await screen.findByText('3 momentos em 2 vídeos')
  const ano = screen.getByRole('combobox', { name: 'Ano' }) as HTMLInputElement
  expect(ano.value).toBe('01/03/2020 a 31/12/2024')

  await usuario.click(ano)
  await usuario.click(await screen.findByRole('option', { name: 'Todos os anos' }))

  expect(location.search).toBe('?q=vestido&ano=todos')
  await waitFor(() => expect(buscas.at(-1)?.get('sem_periodo')).toBe('true'))
})

test('o clique abre o Visualizador exatamente no início do momento, com os milissegundos', async () => {
  const usuario = userEvent.setup()
  resposta = () =>
    HttpResponse.json(resultado({ videos: [video('v1', [momento(6_540, 8_000, 'Objeto: calça vinho')])] }))
  await abrir('/busca?q=calça vinho')
  await usuario.click(await screen.findByRole('link', { name: /Objeto: calça vinho/ }))

  expect(location.pathname + location.search).toBe('/video/v1?t=6.54&busca=cal%C3%A7a+vinho')
})

test('o GC longo vem encurtado, com "ver mais" e "ver menos"', async () => {
  const usuario = userEvent.setup()
  const longo = `GC: ${'PARTICIPAÇÃO VÁLIDA DAS 0H DE 27/04 ATÉ 15H DE 25/11/2025, EXCLUSIVA PARA AS '.repeat(3)}`
  resposta = () =>
    HttpResponse.json(
      resultado({ videos: [video('v1', [momento(9_000, 12_000, longo), momento(14_000, 15_000, 'GC: BOLÃO')])] }),
    )
  await abrir('/busca?q=bolão')
  const verMais = await screen.findByRole('button', { name: 'ver mais' })
  // Só o longo tem o botão.
  expect(screen.getAllByRole('button', { name: /ver (mais|menos)/ })).toHaveLength(1)
  expect(verMais.getAttribute('aria-expanded')).toBe('false')

  await usuario.click(verMais)

  expect(screen.getByRole('button', { name: 'ver menos' }).getAttribute('aria-expanded')).toBe('true')
  // Abrir o texto não abre o vídeo.
  expect(location.pathname).toBe('/busca')
})

const faceta = (valor: string, videos: number, rotulo = valor) => ({ valor, rotulo, videos })

test('as facetas aparecem ao lado dos resultados com a contagem; clicar filtra e as contagens se atualizam', async () => {
  const usuario = userEvent.setup()
  resposta = () => {
    const programa = buscas[buscas.length - 1].get('programa')
    return HttpResponse.json(
      resultado({
        facetas: programa
          ? { ...SEM_FACETAS, programa: [faceta(programa, 1)], marca: [faceta('Adidas', 1)] }
          : {
              programa: [faceta('TV Fama', 8), faceta('Leo Dias', 2)],
              mes: [faceta('2024-05', 7, '05/2024'), faceta('2024-04', 3, '04/2024')],
              pessoa: [faceta('p1', 5, 'Sabrina Sato')],
              marca: [faceta('Nike', 4), faceta('Adidas', 1)],
              tipo: [faceta('fala', 6, 'Fala'), faceta('objeto', 4, 'Objeto')],
            },
      }),
    )
  }
  await abrir('/busca?q=sapato')
  const lateral = await screen.findByRole('complementary', { name: 'Facetas' })

  const leo = within(within(lateral).getByRole('region', { name: 'Programa' })).getByRole('button', {
    name: /Leo Dias/,
  })
  expect(leo.textContent).toContain('2')
  expect(within(lateral).getByRole('button', { name: /05\/2024/ }).textContent).toContain('7')
  expect(within(lateral).getByRole('button', { name: /Sabrina Sato/ }).textContent).toContain('5')
  expect(within(lateral).getByRole('button', { name: /Nike/ }).textContent).toContain('4')
  expect(within(lateral).getByRole('button', { name: /Fala/ }).textContent).toContain('6')

  await usuario.click(leo)

  await waitFor(() => expect(buscas[buscas.length - 1].get('programa')).toBe('Leo Dias'))
  expect(location.search).toContain('programa=Leo+Dias')
  const depois = await screen.findByRole('complementary', { name: 'Facetas' })
  await waitFor(() => expect(within(depois).queryByRole('button', { name: /Nike/ })).toBeNull())
  expect(within(depois).getByRole('button', { name: /Adidas/ }).textContent).toContain('1')
  expect(
    within(depois)
      .getByRole('button', { name: /Leo Dias/ })
      .getAttribute('aria-pressed'),
  ).toBe('true')
})

test('clicar nas facetas de mês, pessoa, marca e tipo manda o filtro à API; clicar de novo o tira', async () => {
  const usuario = userEvent.setup()
  resposta = () =>
    HttpResponse.json(
      resultado({
        facetas: {
          ...SEM_FACETAS,
          mes: [faceta('2024-02', 3, '02/2024')],
          pessoa: [faceta('p1', 5, 'Sabrina Sato')],
          marca: [faceta('Nike', 4)],
          tipo: [faceta('texto_na_tela', 2, 'GC')],
        },
      }),
    )
  await abrir('/busca?q=sapato')
  await usuario.click(await screen.findByRole('button', { name: /02\/2024/ }))
  await usuario.click(await screen.findByRole('button', { name: /Sabrina Sato/ }))
  await usuario.click(await screen.findByRole('button', { name: /Nike/ }))
  await usuario.click(within(await screen.findByRole('complementary', { name: 'Facetas' })).getByRole('button', { name: /GC/ }))

  await waitFor(() => expect(buscas[buscas.length - 1].get('tipo')).toBe('texto_na_tela'))
  const p = buscas[buscas.length - 1]
  expect(p.get('desde')).toBe('2024-02-01')
  expect(p.get('ate')).toBe('2024-02-29')
  expect(p.get('pessoa')).toBe('p1')
  expect(p.get('marca')).toBe('Nike')

  await usuario.click(await screen.findByRole('button', { name: /Nike/ }))

  await waitFor(() => expect(buscas[buscas.length - 1].get('marca')).toBeNull())
})
