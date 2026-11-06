import { expect, test } from 'vitest'
import { CORES_DE_OBJETO } from './cores.ts'

// Veio do tema.test.ts da interface antiga: o `CorBase` do `decupagem.ts` sai das chaves deste mapa.
test('toda cor base do objeto tem a sua cor no mapa', () => {
  expect(Object.keys(CORES_DE_OBJETO).sort()).toEqual(
    ['vermelho', 'laranja', 'amarelo', 'verde', 'azul', 'roxo', 'rosa', 'marrom', 'bege', 'preto', 'branco', 'cinza', 'dourado', 'prateado', 'estampado'].sort(),
  )
})
