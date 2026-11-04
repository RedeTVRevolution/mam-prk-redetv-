import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import App from './App.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import { render } from './render-teste.tsx'

const RELATORIO = {
  desde: null,
  ate: null,
  usuario: null,
  total: { acessos: 7, usuarios_ativos: 2 },
  por_dia: [
    { dia: '2026-11-02', acessos: 3, usuarios_ativos: 2 },
    { dia: '2026-11-03', acessos: 4, usuarios_ativos: 1 },
  ],
  por_semana: [{ inicio: '2026-11-02', usuarios_ativos: 2 }],
  por_mes: [{ inicio: '2026-11-01', usuarios_ativos: 2 }],
  por_usuario: [
    { uid: 'u1', email: 'ana@redetv.com.br', acessos: 5, dias_ativos: 2, ultimo_acesso: '2026-11-03T15:00:00Z' },
    { uid: 'u2', email: null, acessos: 2, dias_ativos: 1, ultimo_acesso: null },
  ],
}

const VIDEOS = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  total: { enviados: 5, concluidos: 3, falhos: 1, horas_concluidas: 3.5, tempo_medio_s: 120 },
  por_dia: [{ dia: '2026-11-02', enviados: 5, concluidos: 3, falhos: 1, horas_concluidas: 3.5, tempo_medio_s: 120 }],
  por_programa: [{ programa: 'TV Fama', enviados: 5, concluidos: 3, falhos: 1, horas_concluidas: 3.5, tempo_medio_s: null }],
  por_usuario: [
    { quem_tipo: 'usuario', quem_id: 'u1', email: 'ana@redetv.com.br', enviados: 2, concluidos: 2, falhos: 0, horas_concluidas: 1, tempo_medio_s: 60 },
    { quem_tipo: 'sistema', quem_id: 'ingestao', email: null, enviados: 3, concluidos: 1, falhos: 1, horas_concluidas: 2.5, tempo_medio_s: null },
  ],
}

const BUSCAS = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  total: { buscas: 9, usuarios_que_buscam: 2, sem_resultado: 4 },
  por_dia: [{ dia: '2026-11-03', buscas: 9, usuarios_que_buscam: 2, sem_resultado: 4 }],
  por_usuario: [{ quem_tipo: 'usuario', quem_id: 'u1', email: 'ana@redetv.com.br', buscas: 9, sem_resultado: 4 }],
}

const REVISAO = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  correcoes: {
    total: 6,
    por_dia: [{ dia: '2026-11-02', correcoes: 6 }],
    por_tipo: [{ tipo: 'texto', correcoes: 4 }, { tipo: null, correcoes: 2 }],
    por_usuario: [{ quem_tipo: 'usuario', quem_id: 'u1', email: 'ana@redetv.com.br', correcoes: 6 }],
  },
  taxa_de_correcao: {
    por_tipo: [{ tipo: 'texto', correcoes: 4, itens: 32, taxa: 0.125 }],
    por_programa: [{ programa: null, correcoes: 4, itens: 32, taxa: null }],
  },
  tempo_de_revisao: {
    total: { minutos: 30, videos: 2, horas_de_video: 1.5, minutos_por_hora_de_video: 20 },
    por_pessoa: [{ uid: 'u1', email: 'ana@redetv.com.br', minutos: 30, videos: 2, horas_de_video: 1.5, minutos_por_hora_de_video: 20 }],
    por_programa: [{ programa: 'TV Fama', minutos: 30, videos: 2, horas_de_video: 1.5, minutos_por_hora_de_video: null }],
  },
}

const API = {
  desde: null,
  ate: null,
  usuario: null,
  total: { chamadas: 10, erros_do_cliente: 2, erros_do_servidor: 1, sistemas: 1, videos_enviados: 3 },
  por_dia: [{ dia: '2026-11-03', chamadas: 10, erros_do_cliente: 2, erros_do_servidor: 1, videos_enviados: 3 }],
  por_sistema: [{ quem_tipo: 'sistema', quem_id: 'ingestao', chamadas: 10, erros_do_cliente: 2, erros_do_servidor: 1, videos_enviados: 3 }],
  por_rota: [{ metodo: 'POST', rota: '/v1/jobs', chamadas: 10, erros_do_cliente: 2, erros_do_servidor: 1 }],
}

const CUSTO = {
  desde: null,
  ate: null,
  programa: null,
  usuario: null,
  moeda: 'BRL',
  total: { custo: 150, custo_dos_jobs: 100, custo_sem_dono: 50, videos: 2, horas_de_video: 4, custo_por_hora: 25 },
  por_mes: [{ mes: '2026-11', custo: 150, custo_dos_jobs: 100, custo_sem_dono: 50, videos: 2, horas_de_video: 4, custo_por_hora: 25 }],
  por_quem: [{ quem_tipo: 'usuario', quem_id: 'u1', email: 'ana@redetv.com.br', custo: 100, videos: 2, horas_de_video: 4, custo_por_hora: 25 }],
  por_etapa: [{ etapa: 'analise', custo: 100 }],
  sem_dono_por_servico: [{ servico: 'Cloud Run', custo: 50 }],
}

const pedidos: URLSearchParams[] = []
let permissoes = ['decupagem.ver', 'painel.ver']
let resposta: () => Response = () => HttpResponse.json(RELATORIO)

const servidor = setupServer(
  http.get('/v1/eu', () => HttpResponse.json({ uid: 'u1', email: 'ana@redetv.com.br', permissoes })),
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json([])),
  http.get('/v1/painel/filtros', () =>
    HttpResponse.json({ programas: ['TV Fama'], usuarios: [{ uid: 'u1', email: 'ana@redetv.com.br' }] }),
  ),
  http.get('/v1/painel/acessos', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') {
      return new HttpResponse('dia,acessos\n2026-11-02,3\n', { headers: { 'Content-Type': 'text/csv' } })
    }
    return resposta()
  }),
  http.get('/v1/painel/videos', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') return new HttpResponse('dia,enviados\n', { headers: { 'Content-Type': 'text/csv' } })
    return HttpResponse.json(VIDEOS)
  }),
  http.get('/v1/painel/revisao', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') return new HttpResponse('indicador\n', { headers: { 'Content-Type': 'text/csv' } })
    return HttpResponse.json(REVISAO)
  }),
  http.get('/v1/painel/api', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') return new HttpResponse('dia\n', { headers: { 'Content-Type': 'text/csv' } })
    return HttpResponse.json(API)
  }),
  http.get('/v1/painel/custo', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') return new HttpResponse('mes\n', { headers: { 'Content-Type': 'text/csv' } })
    return HttpResponse.json(CUSTO)
  }),
  http.get('/v1/painel/buscas', ({ request }) => {
    const p = new URL(request.url).searchParams
    pedidos.push(p)
    if (p.get('formato') === 'csv') return new HttpResponse('dia,buscas\n', { headers: { 'Content-Type': 'text/csv' } })
    return HttpResponse.json(BUSCAS)
  }),
)

beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  history.replaceState(null, '', '/')
  servidor.resetHandlers()
  pedidos.length = 0
  permissoes = ['decupagem.ver', 'painel.ver']
  resposta = () => HttpResponse.json(RELATORIO)
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

test('a aba Acessos mostra o total, os dias e os usuários', async () => {
  await abrir('/painel/acessos')

  const dias = await screen.findByRole('table', { name: 'Acessos por dia' })
  expect(within(dias).getAllByRole('row').slice(1).map((l) => within(l).getAllByRole('cell').map((c) => c.textContent))).toEqual([
    ['02/11/2026', '3', '2'],
    ['03/11/2026', '4', '1'],
  ])
  const usuarios = screen.getByRole('table', { name: 'Acessos por usuário' })
  const linhas = within(usuarios).getAllByRole('row').slice(1)
  expect(within(linhas[0]).getAllByRole('cell').slice(0, 3).map((c) => c.textContent)).toEqual(['ana@redetv.com.br', '5', '2'])
  // Sem e-mail, aparece o uid.
  expect(within(linhas[1]).getAllByRole('cell')[0].textContent).toBe('u2')
  expect(screen.getByText('Logins no período').nextSibling?.textContent).toBe('7')
  expect(screen.getByRole('img', { name: /Logins por dia: 02\/11, 3; 03\/11, 4/ })).toBeTruthy()
  const semanas = screen.getByRole('table', { name: 'Usuários ativos por semana' })
  expect(within(semanas).getAllByRole('cell').map((c) => c.textContent)).toEqual(['02/11/2026', '2'])
  const meses = screen.getByRole('table', { name: 'Usuários ativos por mês' })
  expect(within(meses).getAllByRole('cell').map((c) => c.textContent)).toEqual(['11/2026', '2'])
})

test('os filtros vão à API e ao endereço, e o programa nunca vai em acessos', async () => {
  await abrir('/painel/acessos?programa=TV+Fama&usuario=u1&de=2026-10-01&ate=2026-10-31')

  await screen.findByRole('table', { name: 'Acessos por dia' })

  expect(pedidos[0].get('usuario')).toBe('u1')
  expect(pedidos[0].get('desde')).toBe('2026-10-01')
  expect(pedidos[0].get('ate')).toBe('2026-10-31')
  expect(pedidos[0].has('programa')).toBe(false)
  // O programa da URL fica para as outras abas; aqui o seletor, desligado, diz "todos".
  const programa = screen.getByRole('combobox', { name: 'Programa' }) as HTMLInputElement
  expect(programa.disabled).toBe(true)
  expect(programa.value).toBe('Todos os programas')

  fireEvent.change(screen.getByLabelText('Até'), { target: { value: '2026-10-15' } })

  await waitFor(() => expect(pedidos.at(-1)?.get('ate')).toBe('2026-10-15'))
  expect(location.search).toContain('ate=2026-10-15')
})

test('período invertido mostra o aviso e não chama a API', async () => {
  await abrir('/painel/acessos?de=2026-11-10&ate=2026-11-01')

  expect(await screen.findByText(/O período começa depois de terminar/)).toBeTruthy()
  expect(pedidos).toHaveLength(0)
  expect((screen.getByRole('button', { name: 'Baixar CSV' }) as HTMLButtonElement).disabled).toBe(true)
})

test('Baixar CSV pede o formato csv com os mesmos filtros', async () => {
  const usuario = userEvent.setup()
  const criar = vi.fn(() => 'blob:csv')
  Object.assign(URL, { createObjectURL: criar, revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/painel/acessos?usuario=u1')
  await screen.findByRole('table', { name: 'Acessos por dia' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  const csv = pedidos.find((p) => p.get('formato') === 'csv')
  expect(csv?.get('usuario')).toBe('u1')
  expect(csv?.has('programa')).toBe(false)
  expect(criar).toHaveBeenCalled()
  clique.mockRestore()
})

test('o link Painel só aparece com painel.ver', async () => {
  await abrir('/acervo')
  expect(await screen.findByRole('link', { name: 'Painel' })).toBeTruthy()

  cleanup()
  permissoes = ['decupagem.ver']
  await abrir('/acervo')
  await screen.findByRole('link', { name: 'Relatórios › Tempo de tela' })
  expect(screen.queryByRole('link', { name: 'Painel' })).toBeNull()
})

test('quem só tem painel.ver entra pelo painel, não pelo acervo', async () => {
  permissoes = ['painel.ver']
  await abrir('/')

  await screen.findByRole('table', { name: 'Acessos por dia' })
  expect(location.pathname).toBe('/painel')
})

test('sem acesso nenhum, a tela diz isso', async () => {
  resposta = () => HttpResponse.json({ ...RELATORIO, por_dia: [], por_usuario: [] })
  await abrir('/painel/acessos')

  expect(await screen.findByText('Nenhum acesso neste filtro.')).toBeTruthy()
})

const linhasDe = (t: HTMLElement) =>
  within(t).getAllByRole('row').slice(1).map((l) => within(l).getAllByRole('cell').map((c) => c.textContent))

test('a aba Vídeos mostra os totais e as tabelas por dia, programa e usuário', async () => {
  await abrir('/painel/videos')

  const dias = await screen.findByRole('table', { name: 'Vídeos por dia' })
  expect(linhasDe(dias)[0].slice(0, 5)).toEqual(['02/11/2026', '5', '3', '1', '3,5'])
  expect(screen.getAllByText('Enviados')[0].nextSibling?.textContent).toBe('5')
  expect(screen.getByText('Horas de vídeo concluídas').nextSibling?.textContent).toBe('3,5')
  expect(linhasDe(screen.getByRole('table', { name: 'Vídeos por programa' }))[0][0]).toBe('TV Fama')
  // Sem tempo médio, um traço.
  expect(linhasDe(screen.getByRole('table', { name: 'Vídeos por programa' }))[0][5]).toBe('—')
  const quem = linhasDe(screen.getByRole('table', { name: 'Vídeos por usuário' }))
  expect(quem.map((l) => l[0])).toEqual(['ana@redetv.com.br', 'ingestao (sistema)'])
})

test('Vídeos manda o programa à API e recusa programa e usuário juntos', async () => {
  await abrir('/painel/videos?programa=TV+Fama')
  await screen.findByRole('table', { name: 'Vídeos por dia' })
  expect(pedidos[0].get('programa')).toBe('TV Fama')

  cleanup()
  pedidos.length = 0
  await abrir('/painel/videos?programa=TV+Fama&usuario=u1')
  expect(await screen.findByText(/Escolha o programa ou o usuário, não os dois/)).toBeTruthy()
  expect(pedidos).toHaveLength(0)
})

test('a aba Buscas mostra os totais, o dia e o usuário', async () => {
  await abrir('/painel/buscas')

  const dias = await screen.findByRole('table', { name: 'Buscas por dia' })
  expect(linhasDe(dias)).toEqual([['03/11/2026', '9', '2', '4']])
  expect(screen.getByText('Buscas sem resultado').nextSibling?.textContent).toBe('4')
  expect(linhasDe(screen.getByRole('table', { name: 'Buscas por usuário' }))).toEqual([['ana@redetv.com.br', '9', '4']])
})

test('Buscas com filtro de programa mostra traço onde a API não sabe quem buscou', async () => {
  servidor.use(
    http.get('/v1/painel/buscas', () =>
      HttpResponse.json({
        ...BUSCAS,
        programa: 'TV Fama',
        total: { ...BUSCAS.total, usuarios_que_buscam: null },
        por_dia: [{ ...BUSCAS.por_dia[0], usuarios_que_buscam: null }],
        por_usuario: [],
      }),
    ),
  )
  await abrir('/painel/buscas?programa=TV+Fama')

  const dias = await screen.findByRole('table', { name: 'Buscas por dia' })
  expect(linhasDe(dias)).toEqual([['03/11/2026', '9', '—', '4']])
  expect(screen.queryByRole('table', { name: 'Buscas por usuário' })).toBeNull()
})

test('Baixar CSV em Vídeos pede o formato csv', async () => {
  const usuario = userEvent.setup()
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:csv'), revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/painel/videos?usuario=u1')
  await screen.findByRole('table', { name: 'Vídeos por dia' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  expect(pedidos.find((p) => p.get('formato') === 'csv')?.get('usuario')).toBe('u1')
  clique.mockRestore()
})

test('as abas do painel levam de uma para outra', async () => {
  const usuario = userEvent.setup()
  await abrir('/painel/acessos?usuario=u1')
  await screen.findByRole('table', { name: 'Acessos por dia' })

  await usuario.click(screen.getByRole('tab', { name: 'Buscas' }))

  await screen.findByRole('table', { name: 'Buscas por dia' })
  expect(location.pathname).toBe('/painel/buscas')
  expect(location.search).toContain('usuario=u1')
})

test('a aba Revisão mostra correções, taxa e minutos de revisão', async () => {
  await abrir('/painel/revisao')

  expect(linhasDe(await screen.findByRole('table', { name: 'Correções por dia' }))).toEqual([['02/11/2026', '6']])
  expect(linhasDe(screen.getByRole('table', { name: 'Correções por tipo' }))).toEqual([['texto', '4'], ['Sem tipo', '2']])
  expect(linhasDe(screen.getByRole('table', { name: 'Correções por usuário' }))).toEqual([['ana@redetv.com.br', '6']])
  expect(linhasDe(screen.getByRole('table', { name: 'Taxa de correção por tipo' }))).toEqual([['texto', '4', '32', '12,5%']])
  expect(linhasDe(screen.getByRole('table', { name: 'Taxa de correção por programa' }))).toEqual([['Sem programa', '4', '32', '—']])
  expect(linhasDe(screen.getByRole('table', { name: 'Revisão por pessoa' }))).toEqual([['ana@redetv.com.br', '30', '2', '1,5', '20']])
  expect(linhasDe(screen.getByRole('table', { name: 'Revisão por programa' }))).toEqual([['TV Fama', '30', '2', '1,5', '—']])
  expect(screen.getAllByText('Correções')[0].nextSibling?.textContent).toBe('6')
})

test('Revisão aceita programa e usuário juntos e os manda à API', async () => {
  await abrir('/painel/revisao?programa=TV+Fama&usuario=u1')

  await screen.findByRole('table', { name: 'Correções por dia' })
  expect(pedidos[0].get('programa')).toBe('TV Fama')
  expect(pedidos[0].get('usuario')).toBe('u1')
})

test('Baixar CSV em Revisão pede o formato csv com programa e usuário', async () => {
  const usuario = userEvent.setup()
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:csv'), revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/painel/revisao?programa=TV+Fama&usuario=u1')
  await screen.findByRole('table', { name: 'Correções por dia' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  const csv = pedidos.find((p) => p.get('formato') === 'csv')
  expect(csv?.get('programa')).toBe('TV Fama')
  expect(csv?.get('usuario')).toBe('u1')
  clique.mockRestore()
})

test('Revisão só com a taxa mostra a taxa', async () => {
  servidor.use(
    http.get('/v1/painel/revisao', () =>
      HttpResponse.json({
        ...REVISAO,
        correcoes: { total: 0, por_dia: [], por_tipo: [], por_usuario: [] },
        tempo_de_revisao: { ...REVISAO.tempo_de_revisao, por_pessoa: [], por_programa: [] },
      }),
    ),
  )
  await abrir('/painel/revisao')

  expect(linhasDe(await screen.findByRole('table', { name: 'Taxa de correção por tipo' }))).toEqual([['texto', '4', '32', '12,5%']])
  expect((screen.getByRole('button', { name: 'Baixar CSV' }) as HTMLButtonElement).disabled).toBe(false)
})

test('Revisão sem nada no filtro diz que não há correção nem revisão', async () => {
  servidor.use(
    http.get('/v1/painel/revisao', () =>
      HttpResponse.json({
        ...REVISAO,
        correcoes: { total: 0, por_dia: [], por_tipo: [], por_usuario: [] },
        taxa_de_correcao: { por_tipo: [], por_programa: [] },
        tempo_de_revisao: { ...REVISAO.tempo_de_revisao, por_pessoa: [], por_programa: [] },
      }),
    ),
  )
  await abrir('/painel/revisao')

  expect(await screen.findByText('Nenhuma correção nem revisão neste filtro.')).toBeTruthy()
})

test('a aba API mostra o total, o dia, o sistema e a rota, e nunca manda programa', async () => {
  await abrir('/painel/api?programa=TV+Fama&usuario=ingestao')

  expect(linhasDe(await screen.findByRole('table', { name: 'API por dia' }))).toEqual([['03/11/2026', '10', '2', '1', '3']])
  expect(linhasDe(screen.getByRole('table', { name: 'API por sistema' }))).toEqual([['ingestao (sistema)', '10', '2', '1', '3']])
  expect(linhasDe(screen.getByRole('table', { name: 'API por rota' }))).toEqual([['POST /v1/jobs', '10', '2', '1']])
  expect(screen.getByText('Vídeos enviados pela API').nextSibling?.textContent).toBe('3')
  expect(pedidos[0].has('programa')).toBe(false)
  expect(pedidos[0].get('usuario')).toBe('ingestao')
  expect((screen.getByRole('combobox', { name: 'Programa' }) as HTMLInputElement).disabled).toBe(true)
})

test('Baixar CSV na aba API pede o formato csv sem programa', async () => {
  const usuario = userEvent.setup()
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:csv'), revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/painel/api?programa=TV+Fama')
  await screen.findByRole('table', { name: 'API por dia' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  expect(pedidos.find((p) => p.get('formato') === 'csv')?.has('programa')).toBe(false)
  clique.mockRestore()
})

const REAL = (n: string) => `R$\u00a0${n}`

test('a aba Custo mostra o total, o mês, o usuário, a etapa e o custo sem dono, e manda o programa', async () => {
  await abrir('/painel/custo?programa=TV+Fama')

  expect(linhasDe(await screen.findByRole('table', { name: 'Custo por mês' }))).toEqual([
    ['11/2026', REAL('150,00'), REAL('100,00'), REAL('50,00'), '2', '4', REAL('25,00')],
  ])
  expect(linhasDe(screen.getByRole('table', { name: 'Custo por usuário' }))[0].slice(0, 2)).toEqual(['ana@redetv.com.br', REAL('100,00')])
  expect(linhasDe(screen.getByRole('table', { name: 'Custo por etapa' }))).toEqual([['analise', REAL('100,00')]])
  expect(linhasDe(screen.getByRole('table', { name: 'Custo sem dono por serviço' }))).toEqual([['Cloud Run', REAL('50,00')]])
  expect(screen.getByText('Custo por hora de vídeo').nextSibling?.textContent).toBe(REAL('25,00'))
  expect(pedidos[0].get('programa')).toBe('TV Fama')
})

test('Baixar CSV na aba Custo pede o formato csv', async () => {
  const usuario = userEvent.setup()
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:csv'), revokeObjectURL: vi.fn() })
  const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  await abrir('/painel/custo')
  await screen.findByRole('table', { name: 'Custo por mês' })

  await usuario.click(screen.getByRole('button', { name: 'Baixar CSV' }))

  await waitFor(() => expect(clique).toHaveBeenCalled())
  expect(pedidos.some((p) => p.get('formato') === 'csv')).toBe(true)
  clique.mockRestore()
})
