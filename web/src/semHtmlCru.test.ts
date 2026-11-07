import { expect, test } from 'vitest'

// Texto de usuário vai à tela só como texto do React (#473): nada de HTML montado à mão.
const fontes = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.*'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('nenhum dangerouslySetInnerHTML, innerHTML, outerHTML, srcdoc nem document.write em web/src', () => {
  const infratores = Object.entries(fontes)
    .filter(([, texto]) => /dangerouslySetInnerHTML|(inner|outer)HTML|insertAdjacentHTML|createContextualFragment|srcdoc|document\.write/i.test(texto))
    .map(([arquivo]) => arquivo)

  expect(Object.keys(fontes).length).toBeGreaterThan(50)
  expect(infratores).toEqual([])
})
