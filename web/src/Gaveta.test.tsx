import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { useState } from 'react'
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest'
import { type ClienteDoJob, criarClienteDaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import { AutenticadorFalso, CODIGO_TOTP_FALSO } from './auth/falso.ts'
import type { ItemDaFila, ItemDoHistorico } from './decupagem.ts'
import { type AbaDaGaveta, Gaveta } from './Gaveta.tsx'
import { render } from './render-teste.tsx'

/** Os pedidos que a gaveta fez, pelo HTTP: caminho e corpo. */
let pedidos: { caminho: string; corpo: unknown }[] = []

const registrar = async ({ request }: { request: Request }) => {
  const texto = await request.text()
  pedidos.push({ caminho: new URL(request.url).pathname, corpo: texto ? JSON.parse(texto) : null })
  return HttpResponse.json({}, { status: 201 })
}

const servidor = setupServer(
  http.post('/v1/jobs/j1/correcoes/:id/:acao', registrar),
  http.post('/v1/jobs/j1/fila/:id/:acao', registrar),
)
beforeAll(() => servidor.listen({ onUnhandledFrame: 'error' }))
beforeEach(() => {
  pedidos = []
})
afterEach(() => {
  servidor.resetHandlers()
  cleanup()
})
afterAll(() => servidor.close())

/** O próximo pedido ao caminho dá 409, como quando outra pessoa decidiu antes. */
const conflitoEm = (caminho: string) =>
  servidor.use(http.post(caminho, () => HttpResponse.json({ detail: 'conflito' }, { status: 409 }), { once: true }))

async function cliente(): Promise<ClienteDoJob> {
  const auth = new AutenticadorFalso([
    { email: 'ana@redetv.com.br', senha: 'senha-forte-1', totpCadastrado: true },
  ])
  await auth.entrar('ana@redetv.com.br', 'senha-forte-1')
  await auth.confirmarTotp(CODIGO_TOTP_FALSO)
  return criarClienteDaApi(auth, () => {}).job('j1')
}

const correcao = (extra: Partial<ItemDoHistorico> = {}): ItemDoHistorico => ({
  id: 'c1',
  tipo: 'pessoa.renomear',
  item_id: 'p1',
  ancora: { versao: 'v1', tipo_do_item: 'pessoa' },
  autor_email: 'bia@redetv.com.br',
  criada_em: '2026-10-30T15:00:00Z',
  motivo: 'sobrenome completo',
  antes: 'Ana Souza',
  depois: 'Ana Souza Lima',
  antes_legivel: 'Ana Souza',
  depois_legivel: 'Ana Souza Lima',
  na_busca: 'na_busca',
  estado: 'ativa',
  ...extra,
})

const NA_FILA: ItemDaFila = {
  id: 'f1',
  tipo: 'pessoa.renomear',
  autor_email: 'bia@redetv.com.br',
  criada_em: '2026-10-30T15:00:00Z',
  motivo: 'sobrenome completo',
  antes: 'Ana Souza',
  depois: 'Ana Souza Lima',
  antes_legivel: 'Ana Souza',
  depois_legivel: 'Ana Souza Lima',
  candidatos: [
    { item_id: 'p7', nome: 'Carla Dias', inicio_ms: 4_000, fim_ms: 18_000 },
    { item_id: 'p8', nome: 'Davi Lima', inicio_ms: 10_000, fim_ms: 12_000 },
  ],
}

function Montada({
  historico = [correcao()],
  fila = [],
  podeAprovar = false,
  abaInicial = 'historico',
  api,
  aoMudar = () => {},
  aoSaltar = () => true,
  falhaAoCarregar = false,
}: {
  historico?: ItemDoHistorico[]
  fila?: ItemDaFila[]
  podeAprovar?: boolean
  abaInicial?: AbaDaGaveta
  api: ClienteDoJob
  aoMudar?: () => void
  aoSaltar?: (c: ItemDoHistorico) => boolean
  falhaAoCarregar?: boolean
}) {
  const [aberta, setAberta] = useState(true)
  const [aba, setAba] = useState<AbaDaGaveta>(abaInicial)
  return (
    <AtalhosProvider>
      <Gaveta
        aberta={aberta}
        aba={aba}
        aoTrocarAba={setAba}
        aoFechar={() => setAberta(false)}
        historico={historico}
        fila={fila}
        podeAprovar={podeAprovar}
        api={api}
        catalogo={null}
        falhaAoCarregar={falhaAoCarregar}
        aoMudar={aoMudar}
        aoSaltar={aoSaltar}
      />
    </AtalhosProvider>
  )
}

const gaveta = () => within(screen.getByRole('dialog', { name: 'Correções do vídeo' }))

test('o histórico lista quem, quando, antes, depois, motivo e estado', async () => {
  render(<Montada api={await cliente()} />)

  const g = gaveta()
  expect(g.getByText('bia@redetv.com.br')).toBeTruthy()
  expect(g.getByText(/30\/10\/2026/)).toBeTruthy()
  expect(g.getByText('Ana Souza')).toBeTruthy()
  expect(g.getByText('Ana Souza Lima')).toBeTruthy()
  expect(g.getByText('sobrenome completo')).toBeTruthy()
  expect(g.getByText('ativa')).toBeTruthy()
  expect(g.getByRole('button', { name: 'Desfazer' })).toBeTruthy()
})

test('clicar na linha salta o player ao item; item que sumiu avisa', async () => {
  const usuario = userEvent.setup()
  const aoSaltar = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false)
  render(<Montada api={await cliente()} aoSaltar={aoSaltar} />)

  const linha = gaveta().getByRole('button', { name: /^Saltar ao item/ })
  await usuario.click(linha)
  expect(aoSaltar).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }))
  expect(gaveta().queryByRole('status')).toBeNull()

  await usuario.click(linha)
  expect(gaveta().getByRole('status').textContent).toBe('Este item não está mais na decupagem.')
})

test('↑ ↓ movem a seleção e Enter salta ao item selecionado', async () => {
  const usuario = userEvent.setup()
  const aoSaltar = vi.fn().mockReturnValue(true)
  render(
    <Montada
      api={await cliente()}
      historico={[correcao({ id: 'c1' }), correcao({ id: 'c2' }), correcao({ id: 'c3' })]}
      aoSaltar={aoSaltar}
    />,
  )

  await usuario.keyboard('{ArrowDown}{ArrowDown}{ArrowUp}{Enter}')

  expect(aoSaltar).toHaveBeenCalledTimes(1)
  expect(aoSaltar).toHaveBeenCalledWith(expect.objectContaining({ id: 'c2' }))
})

test('as setas não agem com a gaveta na fila', async () => {
  const usuario = userEvent.setup()
  const aoSaltar = vi.fn().mockReturnValue(true)
  render(<Montada api={await cliente()} fila={[NA_FILA]} abaInicial="fila" aoSaltar={aoSaltar} />)

  await usuario.keyboard('{ArrowDown}{Enter}')

  expect(aoSaltar).not.toHaveBeenCalled()
})

test('desfazer é um clique, com o motivo do gesto, e recarrega', async () => {
  const usuario = userEvent.setup()
  const aoMudar = vi.fn()
  render(<Montada api={await cliente()} aoMudar={aoMudar} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Desfazer' }))

  await waitFor(() => expect(aoMudar).toHaveBeenCalled())
  expect(pedidos).toEqual([
    { caminho: '/v1/jobs/j1/correcoes/c1/desfazer', corpo: { motivo: 'correção desfeita pelo editor' } },
  ])
})

test('desfazer que dá 409 avisa e recarrega', async () => {
  const usuario = userEvent.setup()
  conflitoEm('/v1/jobs/j1/correcoes/c1/desfazer')
  const aoMudar = vi.fn()
  render(<Montada api={await cliente()} aoMudar={aoMudar} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Desfazer' }))

  expect((await gaveta().findByRole('alert')).textContent).toContain('já foi desfeita')
  expect(aoMudar).toHaveBeenCalled()
})

test('a correção desfeita e a reaplicada não oferecem Desfazer', async () => {
  render(
    <Montada
      api={await cliente()}
      historico={[correcao({ id: 'c1', estado: 'desfeita' }), correcao({ id: 'c2', estado: 'reaplicada' })]}
    />,
  )

  expect(gaveta().queryByRole('button', { name: 'Desfazer' })).toBeNull()
})

test('a fila mostra os candidatos e reaplicar é um clique no candidato escolhido', async () => {
  const usuario = userEvent.setup()
  const aoMudar = vi.fn()
  render(<Montada api={await cliente()} fila={[NA_FILA]} abaInicial="fila" aoMudar={aoMudar} />)
  const g = gaveta()

  expect((g.getByRole('button', { name: 'Reaplicar' }) as HTMLButtonElement).disabled).toBe(true)
  await usuario.click(g.getByRole('combobox', { name: 'Candidato' }))
  expect(await screen.findByRole('option', { name: /Davi Lima/ })).toBeTruthy()
  await usuario.click(screen.getByRole('option', { name: /Carla Dias/ }))
  await usuario.click(g.getByRole('button', { name: 'Reaplicar' }))

  await waitFor(() => expect(aoMudar).toHaveBeenCalled())
  expect(pedidos).toEqual([
    {
      caminho: '/v1/jobs/j1/fila/f1/reaplicar',
      corpo: { item_id: 'p7', motivo: 'correção reaplicada pelo editor' },
    },
  ])
})

test('descartar da fila pede confirmação na linha; Cancelar volta; a fila vazia avisa', async () => {
  const usuario = userEvent.setup()
  const api = await cliente()
  render(<Montada api={api} fila={[NA_FILA]} abaInicial="fila" />)

  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))
  const confirmacao = within(gaveta().getByRole('group', { name: 'Confirmar o descarte' }))
  await usuario.click(confirmacao.getByRole('button', { name: 'Cancelar' }))
  expect(gaveta().queryByRole('group', { name: 'Confirmar o descarte' })).toBeNull()
  expect(pedidos).toEqual([])

  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))
  await usuario.click(
    within(gaveta().getByRole('group', { name: 'Confirmar o descarte' })).getByRole('button', { name: 'Descartar' }),
  )

  await waitFor(() =>
    expect(pedidos).toEqual([
      { caminho: '/v1/jobs/j1/fila/f1/descartar', corpo: { motivo: 'correção descartada pelo editor' } },
    ]),
  )
  cleanup()
  render(<Montada api={api} fila={[]} abaInicial="fila" />)
  expect(gaveta().getByText('Nada na fila.')).toBeTruthy()
})

test('resolver que dá 409 avisa e recarrega a fila', async () => {
  const usuario = userEvent.setup()
  conflitoEm('/v1/jobs/j1/fila/f1/descartar')
  const aoMudar = vi.fn()
  render(<Montada api={await cliente()} fila={[NA_FILA]} abaInicial="fila" aoMudar={aoMudar} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))
  await usuario.click(
    within(gaveta().getByRole('group', { name: 'Confirmar o descarte' })).getByRole('button', { name: 'Descartar' }),
  )

  expect((await gaveta().findByRole('alert')).textContent).toContain('não está mais na fila')
  expect(aoMudar).toHaveBeenCalled()
})

test('as abas mostram a contagem da fila e da aprovação, e Aprovação só vale para quem aprova', async () => {
  const pendente = correcao({ id: 'c2', estado: 'pendente' })
  const { unmount } = render(<Montada api={await cliente()} historico={[pendente]} fila={[NA_FILA]} />)
  expect(gaveta().getByRole('tab', { name: 'Fila de revisão (1)' })).toBeTruthy()
  expect(gaveta().queryByRole('tab', { name: /Aprovação/ })).toBeNull()
  unmount()

  render(<Montada api={await cliente()} historico={[pendente]} podeAprovar />)
  expect(gaveta().getByRole('tab', { name: 'Aprovação (1)' })).toBeTruthy()
})

test('o Curador aprova num clique', async () => {
  const usuario = userEvent.setup()
  const aoMudar = vi.fn()
  render(
    <Montada
      api={await cliente()}
      historico={[correcao({ id: 'c2', estado: 'pendente' })]}
      podeAprovar
      abaInicial="aprovacao"
      aoMudar={aoMudar}
    />,
  )

  await usuario.click(gaveta().getByRole('button', { name: 'Aprovar' }))

  await waitFor(() => expect(aoMudar).toHaveBeenCalled())
  expect(pedidos).toEqual([{ caminho: '/v1/jobs/j1/correcoes/c2/aprovar', corpo: null }])
})

test('recusar pede o motivo na linha: sem motivo nada é enviado, com motivo envia', async () => {
  const usuario = userEvent.setup()
  render(
    <Montada
      api={await cliente()}
      historico={[correcao({ id: 'c2', estado: 'pendente' })]}
      podeAprovar
      abaInicial="aprovacao"
    />,
  )

  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  const recusar = gaveta().getByRole('button', { name: 'Recusar' }) as HTMLButtonElement
  expect(recusar.disabled).toBe(true)
  await usuario.keyboard('{Enter}')
  expect(pedidos).toEqual([])

  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'não confere')
  await usuario.click(recusar)

  await waitFor(() =>
    expect(pedidos).toEqual([{ caminho: '/v1/jobs/j1/correcoes/c2/recusar', corpo: { motivo: 'não confere' } }]),
  )
})

test('Enter no campo recusa; Cancelar e Esc voltam sem enviar e sem fechar a gaveta', async () => {
  const usuario = userEvent.setup()
  render(
    <Montada
      api={await cliente()}
      historico={[correcao({ id: 'c2', estado: 'pendente' })]}
      podeAprovar
      abaInicial="aprovacao"
    />,
  )

  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'x')
  await usuario.click(gaveta().getByRole('button', { name: 'Cancelar' }))
  expect(gaveta().queryByLabelText('Motivo da recusa')).toBeNull()

  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'x{Escape}')
  expect(gaveta().queryByLabelText('Motivo da recusa')).toBeNull()
  expect(screen.getByRole('dialog', { name: 'Correções do vídeo' })).toBeTruthy()
  expect(pedidos).toEqual([])

  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'errada{Enter}')
  await waitFor(() =>
    expect(pedidos).toEqual([{ caminho: '/v1/jobs/j1/correcoes/c2/recusar', corpo: { motivo: 'errada' } }]),
  )
})

test('Fechar fecha a gaveta, e o Esc também', async () => {
  const usuario = userEvent.setup()
  const { unmount } = render(<Montada api={await cliente()} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Fechar' }))
  expect(screen.queryByRole('dialog', { name: 'Correções do vídeo' })).toBeNull()
  unmount()

  render(<Montada api={await cliente()} />)
  await usuario.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Correções do vídeo' })).toBeNull()
})

test('o Esc usado por outro elemento não fecha a gaveta', async () => {
  const usuario = userEvent.setup()
  render(
    <>
      <input
        aria-label="Campo de fora"
        onKeyDown={(e) => {
          if (e.key === 'Escape') e.preventDefault()
        }}
      />
      <Montada api={await cliente()} />
    </>,
  )

  await usuario.click(screen.getByRole('textbox', { name: 'Campo de fora' }))
  await usuario.keyboard('{Escape}')
  expect(screen.getByRole('dialog', { name: 'Correções do vídeo' })).toBeTruthy()
})

test('as setas com o histórico vazio não perdem a seleção quando ele chega', async () => {
  const usuario = userEvent.setup()
  const aoSaltar = vi.fn().mockReturnValue(true)
  const api = await cliente()
  function Chegando() {
    const [historico, setHistorico] = useState<ItemDoHistorico[]>([])
    return (
      <>
        <button type="button" onClick={() => setHistorico([correcao({ id: 'c1' }), correcao({ id: 'c2' })])}>
          Chegar
        </button>
        <Montada api={api} historico={historico} aoSaltar={aoSaltar} />
      </>
    )
  }
  render(<Chegando />)

  await usuario.keyboard('{ArrowDown}')
  await usuario.click(screen.getByRole('button', { name: 'Chegar' }))
  // O foco sai do botão de fora para o Enter ser o atalho, não o clique dele.
  ;(document.activeElement as HTMLElement).blur()
  await usuario.keyboard('{Enter}')

  expect(aoSaltar).toHaveBeenCalledWith(expect.objectContaining({ id: 'c1' }))
})

test('um segundo clique enquanto a decisão anda não manda outro pedido', async () => {
  const usuario = userEvent.setup()
  let soltar = () => {}
  servidor.use(
    http.post(
      '/v1/jobs/j1/correcoes/c2/aprovar',
      async (pedido) => {
        await new Promise<void>((r) => {
          soltar = r
        })
        return registrar(pedido)
      },
      { once: true },
    ),
  )
  const aoMudar = vi.fn()
  render(
    <Montada
      api={await cliente()}
      historico={[correcao({ id: 'c2', estado: 'pendente' }), correcao({ id: 'c3', estado: 'pendente' })]}
      podeAprovar
      abaInicial="aprovacao"
      aoMudar={aoMudar}
    />,
  )

  const [primeiro, segundo] = gaveta().getAllByRole('button', { name: 'Aprovar' })
  await usuario.click(primeiro)
  await usuario.click(segundo)
  soltar()

  await waitFor(() => expect(aoMudar).toHaveBeenCalledTimes(1))
  expect(pedidos).toEqual([{ caminho: '/v1/jobs/j1/correcoes/c2/aprovar', corpo: null }])
})

test('a falha ao carregar o histórico avisa e Tentar de novo recarrega', async () => {
  const usuario = userEvent.setup()
  const aoMudar = vi.fn()
  render(<Montada api={await cliente()} falhaAoCarregar aoMudar={aoMudar} />)

  expect(gaveta().getByRole('alert').textContent).toContain('Não foi possível carregar o histórico')
  await usuario.click(gaveta().getByRole('button', { name: 'Tentar de novo' }))
  expect(aoMudar).toHaveBeenCalled()
})
