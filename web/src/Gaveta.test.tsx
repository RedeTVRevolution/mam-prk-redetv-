import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, test, vi } from 'vitest'
import { type ClienteDoJob, ConflitoNaApi } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import type { ItemDaFila, ItemDoHistorico } from './decupagem.ts'
import { type AbaDaGaveta, Gaveta } from './Gaveta.tsx'
import { render } from './render-teste.tsx'

afterEach(cleanup)

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

function clienteFalso(extra: Partial<ClienteDoJob> = {}) {
  return {
    desfazer: vi.fn().mockResolvedValue(undefined),
    aprovar: vi.fn().mockResolvedValue(undefined),
    recusar: vi.fn().mockResolvedValue(undefined),
    reaplicar: vi.fn().mockResolvedValue(undefined),
    descartar: vi.fn().mockResolvedValue(undefined),
    ...extra,
  } as unknown as ClienteDoJob & Record<'desfazer' | 'aprovar' | 'recusar' | 'reaplicar' | 'descartar', ReturnType<typeof vi.fn>>
}

function Montada({
  historico = [correcao()],
  fila = [],
  podeAprovar = false,
  abaInicial = 'historico',
  api,
  aoMudar = () => {},
  aoSaltar = () => true,
}: {
  historico?: ItemDoHistorico[]
  fila?: ItemDaFila[]
  podeAprovar?: boolean
  abaInicial?: AbaDaGaveta
  api: ClienteDoJob
  aoMudar?: () => void
  aoSaltar?: (c: ItemDoHistorico) => boolean
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
        aoMudar={aoMudar}
        aoSaltar={aoSaltar}
      />
    </AtalhosProvider>
  )
}

const gaveta = () => within(screen.getByRole('dialog', { name: 'Correções do vídeo' }))

test('o histórico lista quem, quando, antes, depois, motivo e estado', () => {
  render(<Montada api={clienteFalso()} />)

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
  render(<Montada api={clienteFalso()} aoSaltar={aoSaltar} />)

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
      api={clienteFalso()}
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
  render(<Montada api={clienteFalso()} fila={[NA_FILA]} abaInicial="fila" aoSaltar={aoSaltar} />)

  await usuario.keyboard('{ArrowDown}{Enter}')

  expect(aoSaltar).not.toHaveBeenCalled()
})

test('desfazer é um clique, com o motivo do gesto, e recarrega', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso()
  const aoMudar = vi.fn()
  render(<Montada api={api} aoMudar={aoMudar} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Desfazer' }))

  await waitFor(() => expect(api.desfazer).toHaveBeenCalledWith('c1', 'correção desfeita pelo editor'))
  await waitFor(() => expect(aoMudar).toHaveBeenCalled())
})

test('desfazer que dá 409 avisa e recarrega', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso({ desfazer: vi.fn().mockRejectedValue(new ConflitoNaApi()) })
  const aoMudar = vi.fn()
  render(<Montada api={api} aoMudar={aoMudar} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Desfazer' }))

  expect((await gaveta().findByRole('alert')).textContent).toContain('já foi desfeita')
  expect(aoMudar).toHaveBeenCalled()
})

test('a correção desfeita e a reaplicada não oferecem Desfazer', () => {
  render(
    <Montada
      api={clienteFalso()}
      historico={[correcao({ id: 'c1', estado: 'desfeita' }), correcao({ id: 'c2', estado: 'reaplicada' })]}
    />,
  )

  expect(gaveta().queryByRole('button', { name: 'Desfazer' })).toBeNull()
})

test('a fila mostra os candidatos e reaplicar é um clique no candidato escolhido', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso()
  const aoMudar = vi.fn()
  render(<Montada api={api} fila={[NA_FILA]} abaInicial="fila" aoMudar={aoMudar} />)
  const g = gaveta()

  expect((g.getByRole('button', { name: 'Reaplicar' }) as HTMLButtonElement).disabled).toBe(true)
  await usuario.click(g.getByRole('combobox', { name: 'Candidato' }))
  expect(await screen.findByRole('option', { name: /Davi Lima/ })).toBeTruthy()
  await usuario.click(screen.getByRole('option', { name: /Carla Dias/ }))
  await usuario.click(g.getByRole('button', { name: 'Reaplicar' }))

  await waitFor(() => expect(api.reaplicar).toHaveBeenCalledWith('f1', 'p7', 'correção reaplicada pelo editor'))
  expect(aoMudar).toHaveBeenCalled()
})

test('descartar da fila é um clique e a fila vazia avisa', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso()
  render(<Montada api={api} fila={[NA_FILA]} abaInicial="fila" />)

  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))

  await waitFor(() => expect(api.descartar).toHaveBeenCalledWith('f1', 'correção descartada pelo editor'))
  cleanup()
  render(<Montada api={api} fila={[]} abaInicial="fila" />)
  expect(gaveta().getByText('Nada na fila.')).toBeTruthy()
})

test('resolver que dá 409 avisa e recarrega a fila', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso({ descartar: vi.fn().mockRejectedValue(new ConflitoNaApi()) })
  const aoMudar = vi.fn()
  render(<Montada api={api} fila={[NA_FILA]} abaInicial="fila" aoMudar={aoMudar} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Descartar' }))

  expect((await gaveta().findByRole('alert')).textContent).toContain('não está mais na fila')
  expect(aoMudar).toHaveBeenCalled()
})

test('as abas mostram a contagem da fila e da aprovação, e Aprovação só vale para quem aprova', () => {
  const pendente = correcao({ id: 'c2', estado: 'pendente' })
  const { unmount } = render(<Montada api={clienteFalso()} historico={[pendente]} fila={[NA_FILA]} />)
  expect(gaveta().getByRole('tab', { name: 'Fila de revisão (1)' })).toBeTruthy()
  expect(gaveta().queryByRole('tab', { name: /Aprovação/ })).toBeNull()
  unmount()

  render(<Montada api={clienteFalso()} historico={[pendente]} podeAprovar />)
  expect(gaveta().getByRole('tab', { name: 'Aprovação (1)' })).toBeTruthy()
})

test('o Curador aprova num clique', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso()
  const aoMudar = vi.fn()
  render(
    <Montada
      api={api}
      historico={[correcao({ id: 'c2', estado: 'pendente' })]}
      podeAprovar
      abaInicial="aprovacao"
      aoMudar={aoMudar}
    />,
  )

  await usuario.click(gaveta().getByRole('button', { name: 'Aprovar' }))

  await waitFor(() => expect(api.aprovar).toHaveBeenCalledWith('c2'))
  expect(aoMudar).toHaveBeenCalled()
})

test('recusar pede o motivo na linha: sem motivo nada é enviado, com motivo envia', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso()
  render(
    <Montada
      api={api}
      historico={[correcao({ id: 'c2', estado: 'pendente' })]}
      podeAprovar
      abaInicial="aprovacao"
    />,
  )

  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  const recusar = gaveta().getByRole('button', { name: 'Recusar' }) as HTMLButtonElement
  expect(recusar.disabled).toBe(true)
  await usuario.keyboard('{Enter}')
  expect(api.recusar).not.toHaveBeenCalled()

  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'não confere')
  await usuario.click(recusar)

  await waitFor(() => expect(api.recusar).toHaveBeenCalledWith('c2', 'não confere'))
})

test('Enter no campo recusa; Cancelar e Esc voltam sem enviar e sem fechar a gaveta', async () => {
  const usuario = userEvent.setup()
  const api = clienteFalso()
  render(
    <Montada
      api={api}
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
  expect(api.recusar).not.toHaveBeenCalled()

  await usuario.click(gaveta().getByRole('button', { name: 'Recusar' }))
  await usuario.type(gaveta().getByLabelText('Motivo da recusa'), 'errada{Enter}')
  await waitFor(() => expect(api.recusar).toHaveBeenCalledWith('c2', 'errada'))
})

test('Fechar fecha a gaveta, e o Esc também', async () => {
  const usuario = userEvent.setup()
  const { unmount } = render(<Montada api={clienteFalso()} />)

  await usuario.click(gaveta().getByRole('button', { name: 'Fechar' }))
  expect(screen.queryByRole('dialog', { name: 'Correções do vídeo' })).toBeNull()
  unmount()

  render(<Montada api={clienteFalso()} />)
  await usuario.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Correções do vídeo' })).toBeNull()
})
