import { afterEach, expect, test, vi } from 'vitest'
import { escolherInterface, naInterfaceAtual } from './interface.ts'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  history.replaceState(null, '', '/')
})

test('sem escolha, abre a interface atual', () => {
  history.replaceState(null, '', '/acervo')
  expect(escolherInterface()).toBe('atual')
})

test('?interface=nova liga a nova, guarda a escolha e sai do endereço', () => {
  history.replaceState(null, '', '/acervo?programa=TV+Fama&interface=nova#topo')

  expect(escolherInterface()).toBe('nova')
  expect(location.pathname + location.search + location.hash).toBe('/acervo?programa=TV+Fama#topo')

  // A próxima carga, sem o parâmetro, continua na nova.
  history.replaceState(null, '', '/busca')
  expect(escolherInterface()).toBe('nova')
})

test('?interface=atual volta e também fica guardado', () => {
  localStorage.setItem('mam:interface', 'nova')
  history.replaceState(null, '', '/painel?interface=atual')

  expect(escolherInterface()).toBe('atual')
  expect(location.search).toBe('')
  history.replaceState(null, '', '/painel')
  expect(escolherInterface()).toBe('atual')
})

test('um valor desconhecido é ignorado e fica no endereço', () => {
  history.replaceState(null, '', '/acervo?interface=outra')
  expect(escolherInterface()).toBe('atual')
  expect(location.search).toBe('?interface=outra')
})

test('sem armazenamento no navegador, a escolha vale só para esta carga', () => {
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('cota', 'QuotaExceededError')
  })
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('bloqueado', 'SecurityError')
  })

  history.replaceState(null, '', '/acervo?interface=nova')
  expect(escolherInterface()).toBe('nova')
  history.replaceState(null, '', '/acervo')
  expect(escolherInterface()).toBe('atual')
})

test('o link para a interface atual mantém o caminho e a consulta', () => {
  history.replaceState(null, '', '/relatorios/marcas?de=2026-01-01')
  expect(naInterfaceAtual()).toBe('/relatorios/marcas?de=2026-01-01&interface=atual')
})
