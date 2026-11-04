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
