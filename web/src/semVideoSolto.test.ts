import { expect, test } from 'vitest'

// Um `<video>` por miniatura não serve para uma lista de momentos (#162): o quadro vem do JPEG.
// O player do Visualizador é o único `<video>` da tela, e o da tela do vídeo na interface nova.
const PERMITIDOS = ['./Visualizador.tsx', './novo/video/Video.tsx']

const fontes = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.*'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('nenhum <video nem #t= em web/src fora do player', () => {
  const infratores = Object.entries(fontes)
    .filter(([arquivo]) => !PERMITIDOS.includes(arquivo))
    .filter(([, texto]) => /<video|#t=/.test(texto))
    .map(([arquivo]) => arquivo)

  expect(Object.keys(fontes).length).toBeGreaterThan(10)
  expect(infratores).toEqual([])
})
