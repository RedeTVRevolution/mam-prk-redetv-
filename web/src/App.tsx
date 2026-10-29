import { useCallback, useEffect, useState } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import Login from './Login.tsx'

interface Eu {
  uid: string
  email: string
}

// Sem sessão não renderiza nada além do login e não chama a API.
type Sessao = { tipo: 'verificando' } | { tipo: 'sem_sessao' } | { tipo: 'ativa'; eu: Eu }

export default function App({ autenticador }: { autenticador: Autenticador }) {
  const [sessao, setSessao] = useState<Sessao>({ tipo: 'verificando' })

  const verificar = useCallback(async () => {
    try {
      const eu = await chamarApi<Eu>(autenticador, '/v1/eu')
      setSessao({ tipo: 'ativa', eu })
    } catch (erro) {
      if (!(erro instanceof SessaoExpirada)) throw erro
      await autenticador.sair()
      setSessao({ tipo: 'sem_sessao' })
    }
  }, [autenticador])

  useEffect(() => {
    // Sincroniza com o SDK de login, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void verificar()
  }, [verificar])

  async function sair() {
    await autenticador.sair()
    setSessao({ tipo: 'sem_sessao' })
  }

  if (sessao.tipo === 'verificando') return null
  if (sessao.tipo === 'sem_sessao') {
    return <Login autenticador={autenticador} aoEntrar={() => void verificar()} />
  }
  return (
    <main>
      <h1>Biblioteca</h1>
      <p>{sessao.eu.email}</p>
      <button type="button" onClick={() => void sair()}>
        Sair
      </button>
    </main>
  )
}
