import { afterAll, beforeAll } from 'vitest'

/**
 * O jsdom não mede nada: sem altura, a área que rola não mostra linha nenhuma da lista virtual, e
 * linhas de altura 0 confundem a conta de quais estão à vista. Aqui a área tem `altura` e cada
 * elemento mede `linha`: com os valores de partida, as 60 primeiras linhas cabem à vista.
 */
export function comAlturaNaRolagem(altura = 2400, linha = 40) {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => altura })
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => linha })
  })
  // Volta a valer o do jsdom, que fica no protótipo de cima.
  afterAll(() => {
    delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight
    delete (HTMLElement.prototype as { offsetHeight?: number }).offsetHeight
  })
}
