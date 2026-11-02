import { useEffect, useState } from 'react'
import type { ClienteDoJob } from './api.ts'
import type { ResumoDaPassada } from './passadas.ts'

/** As passadas de comparação do Job; lista vazia quando não há, ou quando a pessoa não pode vê-las. */
export function usePassadas(api: ClienteDoJob, ativo: boolean): ResumoDaPassada[] {
  const [passadas, setPassadas] = useState<ResumoDaPassada[]>([])
  useEffect(() => {
    if (!ativo) return
    let vivo = true
    api.passadas().then(
      (lista) => {
        if (vivo) setPassadas(lista)
      },
      () => {},
    )
    return () => {
      vivo = false
    }
  }, [api, ativo])
  return passadas
}
