import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, expect, test, vi } from 'vitest'
import { criarClienteDaApi } from '../../api.ts'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from '../../auth/falso.ts'
import { useRota } from '../../rotas.ts'
import { AtalhosProvider } from '../Atalhos.tsx'
import { Casca } from '../Casca.tsx'
import { ContextoDaApi, criarClienteDeConsultas } from '../consultas.ts'
import { Busca } from './Busca.tsx'

// A lista de anos nasce quando o módulo é importado: o navegador em UTC e o relógio às 23h30 de
// 31/12 em São Paulo (já 1º/1 em UTC) precisam valer antes dos imports acima.
vi.hoisted(() => {
  ;(globalThis as { process?: { env: Record<string, string> } }).process!.env.TZ = 'UTC'
  vi.useFakeTimers({ now: new Date('2027-01-01T02:30:00Z'), toFake: ['Date'] })
})

const servidor = setupServer(
  http.get('/v1/jobs', () => HttpResponse.json([])),
  http.get('/v1/programas', () => HttpResponse.json([])),
  http.get('/v1/busca', () =>
    HttpResponse.json({
      entendida: { evidencias: ['objeto'], programa: null, desde: null, ate: null },
      videos: [],
      sem_aparicoes: [],
      plano_b: false,
      facetas: { programa: [], mes: [], pessoa: [], marca: [], tipo: [] },
    }),
  ),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
afterAll(() => servidor.close())

function Tela() {
  const rota = useRota()
  return (
    <Casca usuario={{ uid: 'u1', email: 'ana@redetv.com.br', papeis: [], permissoes: ['decupagem.ver'] }} rota={rota} aoSair={() => {}}>
      {rota.tipo === 'busca' && <Busca consulta={rota.consulta} />}
    </Casca>
  )
}

test('com o navegador em UTC, a lista de anos da Busca começa no ano de São Paulo', async () => {
  const auth = new AutenticadorFalso([{ email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true }])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  history.replaceState(null, '', '/busca?q=vestido')
  render(
    <AtalhosProvider>
      <QueryClientProvider client={criarClienteDeConsultas()}>
        <ContextoDaApi.Provider value={criarClienteDaApi(auth, () => {})}>
          <Tela />
        </ContextoDaApi.Provider>
      </QueryClientProvider>
    </AtalhosProvider>,
  )
  expect(new Date().getFullYear()).toBe(2027)

  await userEvent.setup().click(await screen.findByRole('button', { name: 'Ano' }))

  const anos = (await screen.findAllByRole('option')).map((o) => o.textContent)
  expect(anos[0]).toBe('2026')
})
