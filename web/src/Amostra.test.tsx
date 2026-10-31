import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Amostra from './Amostra.tsx'
import { render } from './render-teste.tsx'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

test('a amostra renderiza sem chamar a API', () => {
  const buscar = vi.spyOn(globalThis, 'fetch')
  render(<Amostra />)

  expect(screen.getByRole('heading', { name: 'Sistema visual' })).toBeTruthy()
  expect(buscar).not.toHaveBeenCalled()
})

test('mostra as seções que o humano avalia', () => {
  render(<Amostra />)

  for (const secao of [
    'Cores',
    'Tipografia',
    'Espaçamentos',
    'Componentes',
    'Acervo',
    'Linha do tempo',
    'Painel',
  ]) {
    expect(screen.getByRole('heading', { name: secao })).toBeTruthy()
  }
})

test('a paleta mostra o contraste de cada texto sobre o fundo', () => {
  render(<Amostra />)

  const tabela = screen.getByRole('table', { name: 'Contraste dos textos' })
  const secundario = within(tabela).getByRole('row', { name: /Texto secundário/ })
  // #A0A5AE sobre #141518, pela fórmula da WCAG.
  expect(secundario.textContent).toContain('7,4:1')
})

test('o acervo de exemplo tem 30 vídeos e uma falha explicada em português', () => {
  render(<Amostra />)

  const acervo = screen.getByRole('table', { name: 'Acervo' })
  expect(within(acervo).getAllByRole('row')).toHaveLength(31)
  expect(within(acervo).getByText(/codec que não aceitamos/)).toBeTruthy()
})

test('a linha do tempo tem as sete faixas, com contagem e nome acessível', () => {
  render(<Amostra />)

  const linha = screen.getByRole('region', { name: 'Linha do tempo' })
  for (const faixa of [
    'Pautas',
    'Aparições',
    'Menções',
    'Objetos',
    'Comerciais',
    'Fala',
    'Texto na tela',
  ]) {
    expect(within(linha).getByText(faixa)).toBeTruthy()
  }
  expect(within(linha).getByLabelText('Aparição de Leão Lobo, 03:31 a 04:21')).toBeTruthy()
  expect(within(linha).getByLabelText(/Trecho sem decupagem/)).toBeTruthy()
})

test('o painel destaca o item atual', () => {
  render(<Amostra />)

  const painel = screen.getByRole('region', { name: 'Painel' })
  const atual = within(painel)
    .getAllByRole('button')
    .filter((b) => b.getAttribute('aria-current') === 'true')
  expect(atual).toHaveLength(1)
})
