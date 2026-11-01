import fonteDaApi from '../../api/jobs.py?raw'
import { expect, test } from 'vitest'
import { FRASES_DE_FALHA, fraseDaFalha } from './falhas.ts'

// Os códigos saem do `CodigoDeFalha` de api/jobs.py: um código novo sem frase quebra aqui.
function codigosDaApi(): string[] {
  const bloco = /^CodigoDeFalha = Literal\[([^\]]*)\]/m.exec(fonteDaApi)?.[1] ?? ''
  return [...bloco.matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
}

test('todo código de falha da API tem uma frase em português, sem o código dentro', () => {
  const codigos = codigosDaApi()
  expect(codigos.length).toBeGreaterThan(0)
  for (const codigo of codigos) {
    const frase = fraseDaFalha(codigo)
    expect(frase, codigo).toBe(FRASES_DE_FALHA[codigo])
    expect(frase).not.toContain('_')
  }
})

test('o mapa não tem código que a API não conhece', () => {
  expect(Object.keys(FRASES_DE_FALHA).sort()).toEqual(codigosDaApi().sort())
})

test('um código desconhecido cai numa frase genérica', () => {
  expect(fraseDaFalha('outra_coisa')).not.toContain('outra_coisa')
})
