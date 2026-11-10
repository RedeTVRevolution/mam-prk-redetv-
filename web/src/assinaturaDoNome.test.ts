import { describe, expect, it } from 'vitest'
import tabela from '../../api/tests/assinatura_do_nome.json'
import { assinatura } from './assinaturaDoNome'

describe('assinatura do nome', () => {
  it.each(tabela.casos)('$entrada -> $chave', ({ entrada, cores, chave }) => {
    expect(assinatura(entrada, cores)).toBe(chave)
  })
})
