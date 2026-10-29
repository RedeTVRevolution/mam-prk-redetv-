import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import App from './App.tsx'

test('mostra o nome da aplicação', () => {
  render(<App />)

  expect(screen.getByRole('heading', { name: 'MAM RedeTV' })).toBeTruthy()
})
