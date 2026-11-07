import { useEffect, useState } from 'react'

/** Pausa depois da última tecla para consultar o autocompletar de nomes (#484). */
export const ATRASO_DO_AUTOCOMPLETAR_MS = 250

/** O `valor` só muda `ms` depois da última mudança: digitar rápido vira uma consulta só. */
export function useValorAtrasado<T>(valor: T, ms = ATRASO_DO_AUTOCOMPLETAR_MS): T {
  const [atrasado, setAtrasado] = useState(valor)
  useEffect(() => {
    const espera = setTimeout(() => setAtrasado(valor), ms)
    return () => clearTimeout(espera)
  }, [valor, ms])
  return atrasado
}
