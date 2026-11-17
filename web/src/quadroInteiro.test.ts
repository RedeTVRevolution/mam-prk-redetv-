import { expect, test } from 'vitest'

// Vídeo 4:3 (acervo antigo): capas e quadros mostram o quadro inteiro, sobre fundo escuro.
// `object-cover` cortaria 25% da altura de um quadro 4:3 na caixa 16:9.
const fontes = import.meta.glob(['./**/*.tsx', '!./**/*.test.*'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('nenhuma imagem de capa ou quadro usa object-cover', () => {
  const infratores = Object.entries(fontes)
    .filter(([, texto]) => (texto.match(/<img[\s\S]*?\/>/g) ?? []).some((img) => img.includes('object-cover')))
    .map(([arquivo]) => arquivo)

  expect(Object.keys(fontes).length).toBeGreaterThan(20)
  expect(infratores).toEqual([])
})
