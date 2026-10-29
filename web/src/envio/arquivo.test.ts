import { expect, test } from 'vitest'
import { TAMANHO_MAXIMO_BYTES, validarArquivo } from './arquivo.ts'

function mp4(opcoes: { nome?: string; tipo?: string; marca?: string; tamanho?: number } = {}) {
  const { nome = 'clipe.mp4', tipo = 'video/mp4', marca = 'isom', tamanho } = opcoes
  const cabecalho = new Uint8Array(12)
  cabecalho.set([0, 0, 0, 0x18], 0)
  cabecalho.set(new TextEncoder().encode('ftyp'), 4)
  cabecalho.set(new TextEncoder().encode(marca), 8)
  const arquivo = new File([cabecalho], nome, { type: tipo })
  if (tamanho !== undefined) Object.defineProperty(arquivo, 'size', { value: tamanho })
  return arquivo
}

test('aceita um MP4 com extensão, tipo, tamanho e ftyp certos', async () => {
  expect(await validarArquivo(mp4())).toBeNull()
})

test.each([
  ['extensão errada', mp4({ nome: 'clipe.mov' })],
  ['tipo errado', mp4({ tipo: 'video/quicktime' })],
  ['tamanho acima do máximo', mp4({ tamanho: TAMANHO_MAXIMO_BYTES + 1 })],
  ['arquivo vazio', new File([], 'clipe.mp4', { type: 'video/mp4' })],
  ['sem ftyp', new File([new Uint8Array(12)], 'clipe.mp4', { type: 'video/mp4' })],
  ['marca fora da lista', mp4({ marca: 'qt  ' })],
])('recusa na hora: %s', async (_motivo, arquivo) => {
  expect(await validarArquivo(arquivo)).toEqual(expect.any(String))
})
