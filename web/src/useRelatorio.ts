import { useCallback, useEffect, useState } from 'react'
import { codigoDoErro, PedidoInvalido, SessaoExpirada } from './api.ts'
import { baixarArquivo } from './baixar.ts'

// O estado que as telas de Relatórios têm em comum: a carga com erro e nova tentativa, e o CSV.

export type Carga<T> =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; relatorio: T }
  | { tipo: 'erro'; mensagem: string; codigo: string }

/** Busca o relatório de novo sempre que `buscar` muda (isto é, quando os filtros do endereço mudam). */
export function useRelatorio<T>(buscar: () => Promise<T>) {
  const [carga, setCarga] = useState<Carga<T>>({ tipo: 'carregando' })
  const carregar = useCallback(() => {
    let atual = true
    setCarga({ tipo: 'carregando' })
    buscar()
      .then((relatorio) => atual && setCarga({ tipo: 'pronta', relatorio }))
      .catch((erro: unknown) => {
        if (!atual || erro instanceof SessaoExpirada) return
        const mensagem =
          erro instanceof PedidoInvalido
            ? erro.message
            : 'Não foi possível montar o relatório agora. Tente de novo.'
        setCarga({ tipo: 'erro', mensagem, codigo: codigoDoErro(erro) })
      })
    return () => {
      atual = false
    }
  }, [buscar])

  // Busca na API, um sistema externo.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => carregar(), [carregar])
  return { carga, carregar }
}

/** "Baixar CSV": pede o arquivo e o entrega; `falhou` acende o alerta da tela. */
export function useBaixarCsv(arquivo: string, pedir: () => Promise<Blob>) {
  const [falhou, setFalhou] = useState(false)
  async function baixar() {
    setFalhou(false)
    try {
      baixarArquivo(arquivo, await pedir())
    } catch (e) {
      if (!(e instanceof SessaoExpirada)) setFalhou(true)
    }
  }
  return { baixar, falhou }
}
