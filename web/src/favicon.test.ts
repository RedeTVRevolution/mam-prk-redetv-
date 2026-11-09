import { expect, test } from 'vitest'
import html from '../index.html?raw'

const icones = import.meta.glob<string>('../public/*', { query: '?raw', import: 'default', eager: true })

test('a página aponta o favicon para um arquivo público existente, inclusive nas rotas internas', () => {
  const pagina = new DOMParser().parseFromString(html, 'text/html')
  const endereco = pagina.querySelector('link[rel="icon"]')?.getAttribute('href')

  expect(endereco).toMatch(/^\/[^?#]+$/)
  expect(icones[`../public${endereco}`]?.trim()).toBeTruthy()
})
