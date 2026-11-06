import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, expect, test, vi } from 'vitest'
import type { Job } from '../../jobs.ts'
import { abrirVideo, rotasDoVideo, simularPlayer } from './abrir-teste.tsx'

// O diálogo de reprocessar é da fase 2a; aqui um substituto chama o `aoReprocessar` que a tela
// entrega a ele, como o diálogo fará: o que se testa é o acompanhamento da tela depois do pedido.
vi.mock('./dialogos.tsx', () => ({
  DialogosDoVideo: ({ aberto, job, aoReprocessar }: { aberto: string | null; job: Job; aoReprocessar: (j: Job, etapa: string) => void }) =>
    aberto === 'reprocessar' ? (
      <div role="dialog" data-state="open" aria-label="Reprocessar">
        <button type="button" onClick={() => aoReprocessar({ ...job, estado: 'analisando', etapa_atual: 'analise' }, 'analise')}>
          Pela análise
        </button>
        <button type="button" onClick={() => aoReprocessar({ ...job, etapa_atual: 'identificacao', indexacao: { estado: 'pendente', em: new Date().toISOString() } }, 'identificacao')}>
          Pela identificação
        </button>
      </div>
    ) : null,
}))

const DECUPAGEM = { pautas: [{ id: 'pa1', titulo: 'Eleição', inicio_ms: 0, fim_ms: 60_000 }], pessoas: [], planos: [], comerciais: [], transcricao: [], textos_na_tela: [] }
const AGORA = new Date().toISOString()

let cargas = 0
let respostas: Partial<Job>[] = []
const servidor = setupServer(
  ...rotasDoVideo(
    () => respostas.shift() ?? {},
    () => {
      cargas += 1
      return DECUPAGEM
    },
  ),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
simularPlayer()
afterEach(() => {
  servidor.resetHandlers()
  cargas = 0
  respostas = []
  history.replaceState(null, '', '/')
  cleanup()
  vi.restoreAllMocks()
})
afterAll(() => servidor.close())

async function reprocessar(botao: string) {
  const usuario = userEvent.setup()
  await usuario.click(screen.getByRole('button', { name: 'Mais ações' }))
  await usuario.click(await within(await screen.findByRole('menu')).findByRole('menuitem', { name: /Reprocessar…/ }))
  await usuario.click(await screen.findByRole('button', { name: botao }))
}

test('pela análise, avisa que a decupagem está sendo refeita, tira a antiga e a traz de volta no fim', async () => {
  await abrirVideo({ permissoes: ['video.reprocessar_etapa'], acompanhamentoMs: 20 })
  expect(cargas).toBe(1)
  // Duas respostas com a análise rodando; depois, o Job concluído.
  respostas = [{ estado: 'analisando', etapa_atual: 'analise' }, { estado: 'analisando', etapa_atual: 'analise' }]

  await reprocessar('Pela análise')

  expect(await screen.findByText(/Reprocessando: Análise em andamento\. A Decupagem está sendo refeita/)).toBeTruthy()
  expect(screen.queryByRole('group', { name: /^Pautas/ })).toBeNull()
  await waitFor(() => expect(screen.queryByText(/em andamento/)).toBeNull())
  expect(await screen.findByRole('group', { name: 'Pautas 1' })).toBeTruthy()
  expect(cargas).toBe(2)
})

test('por uma etapa depois da análise, acompanha até a indexação terminar e então recarrega a decupagem', async () => {
  await abrirVideo({ permissoes: ['video.reprocessar_etapa'], acompanhamentoMs: 20 })
  // Entre a identificação e os quadros, sem etapa em andamento mas com a indexação pendente.
  respostas = [
    { etapa_atual: 'identificacao', indexacao: { estado: 'pendente', em: AGORA } },
    { etapa_atual: null, indexacao: { estado: 'pendente', em: AGORA } },
  ]

  await reprocessar('Pela identificação')

  expect(await screen.findByText(/Reprocessando: Identificação em andamento\./)).toBeTruthy()
  await waitFor(() => expect(screen.queryByText(/em andamento/)).toBeNull())
  await waitFor(() => expect(cargas).toBe(2))
  expect(screen.getByRole('group', { name: 'Pautas 1' })).toBeTruthy()
})
