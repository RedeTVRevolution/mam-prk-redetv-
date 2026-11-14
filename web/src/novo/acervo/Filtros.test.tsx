import { IconTag } from '@tabler/icons-react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, test } from 'vitest'
import { Faceta } from './Filtros.tsx'

afterEach(cleanup)

const OPCOES = [
  { valor: 'a', rotulo: 'Alfa' },
  { valor: 'b', rotulo: 'Beta' },
  { valor: 'c', rotulo: 'Gama' },
]

/** A `Faceta` com o estado de fora, como as telas a usam; `valor` mostra o que ela devolveu. */
function Tela({ tudoMarcado, inicial = [] }: { tudoMarcado?: boolean; inicial?: string[] }) {
  const [valor, setValor] = useState(inicial)
  return (
    <>
      <Faceta rotulo="Letra" Icone={IconTag} opcoes={OPCOES} valor={valor} aoMudar={setValor} tudoMarcado={tudoMarcado} />
      <output aria-label="valor">{valor.join(',')}</output>
    </>
  )
}

const valor = () => screen.getByLabelText('valor').textContent

test('sem a opção, sem caixa marcada é "todos" e marcar soma, como sempre', async () => {
  const usuario = userEvent.setup()
  render(<Tela />)

  await usuario.click(screen.getByRole('button', { name: 'Letra' }))
  expect(screen.queryByRole('option', { name: 'Selecionar tudo' })).toBeNull()
  await usuario.click(screen.getByRole('option', { name: 'Alfa' }))
  await usuario.click(screen.getByRole('option', { name: 'Beta' }))

  expect(valor()).toBe('a,b')
  expect(screen.getByRole('button', { name: 'Letra: Letra: 2' })).toBeTruthy()
  // Desmarcar a última volta a "todos", sem trava.
  await usuario.click(screen.getByRole('option', { name: 'Alfa' }))
  await usuario.click(screen.getByRole('option', { name: 'Beta' }))
  expect(valor()).toBe('')
  expect(screen.getByRole('button', { name: 'Letra' })).toBeTruthy()
})

test('com tudo marcado: abre com tudo marcado e "Todos" no botão', async () => {
  const usuario = userEvent.setup()
  render(<Tela tudoMarcado />)

  await usuario.click(screen.getByRole('button', { name: 'Letra: Todos' }))

  const opcoes = await screen.findAllByRole('option')
  expect(opcoes.map((o) => [o.textContent, o.getAttribute('aria-checked')])).toEqual([
    ['Selecionar tudo', 'true'],
    ['Alfa', 'true'],
    ['Beta', 'true'],
    ['Gama', 'true'],
  ])
  expect(valor()).toBe('')
})

test('com tudo marcado: desmarcar devolve os marcados, e o resumo é "N de M", depois o nome', async () => {
  const usuario = userEvent.setup()
  render(<Tela tudoMarcado />)

  await usuario.click(screen.getByRole('button', { name: 'Letra: Todos' }))
  await usuario.click(await screen.findByRole('option', { name: 'Beta' }))
  expect(valor()).toBe('a,c')
  expect(screen.getByRole('button', { name: 'Letra: 2 de 3' })).toBeTruthy()
  expect(screen.getByRole('option', { name: 'Selecionar tudo' }).getAttribute('aria-checked')).toBe('false')

  await usuario.click(screen.getByRole('option', { name: 'Gama' }))
  expect(valor()).toBe('a')
  expect(screen.getByRole('button', { name: 'Letra: Alfa' })).toBeTruthy()
})

test('com tudo marcado: a última caixa marcada não se desmarca', async () => {
  const usuario = userEvent.setup()
  render(<Tela tudoMarcado inicial={['c']} />)

  await usuario.click(screen.getByRole('button', { name: 'Letra: Gama' }))
  await usuario.click(await screen.findByRole('option', { name: 'Gama' }))

  expect(valor()).toBe('c')
  expect(screen.getByRole('option', { name: 'Gama' }).getAttribute('aria-checked')).toBe('true')
})

test('com tudo marcado: Selecionar tudo e marcar a última caixa que faltava voltam a "todos"', async () => {
  const usuario = userEvent.setup()
  render(<Tela tudoMarcado inicial={['a', 'b']} />)

  await usuario.click(screen.getByRole('button', { name: 'Letra: 2 de 3' }))
  await usuario.click(await screen.findByRole('option', { name: 'Gama' }))
  expect(valor()).toBe('')

  await usuario.click(screen.getByRole('option', { name: 'Alfa' }))
  expect(valor()).toBe('b,c')
  await usuario.click(screen.getByRole('option', { name: 'Selecionar tudo' }))
  expect(valor()).toBe('')
})
