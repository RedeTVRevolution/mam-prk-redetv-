import { useCallback, useEffect, useState } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import Biblioteca from './Biblioteca.tsx'
import Login from './Login.tsx'
import Video, { type JobAberto } from './Video.tsx'

interface Usuario {
  uid: string
  email: string
}

// Sem sessão não renderiza nada além do login e não chama a API.
type Sessao =
  | { tipo: 'verificando' }
  | { tipo: 'sem_sessao' }
  | { tipo: 'api_indisponivel' }
  | { tipo: 'ativa'; usuario: Usuario }

export default function App({ autenticador }: { autenticador: Autenticador }) {
  const [sessao, setSessao] = useState<Sessao>({ tipo: 'verificando' })
  // Muda a cada saída, para o login recomeçar do zero (inclusive após um 401 logo depois do TOTP).
  const [saidas, setSaidas] = useState(0)
  const [aberto, setAberto] = useState<JobAberto | null>(null)

  const sair = useCallback(async () => {
    await autenticador.sair()
    setSessao({ tipo: 'sem_sessao' })
    setSaidas((n) => n + 1)
    setAberto(null)
  }, [autenticador])

  const verificar = useCallback(async () => {
    try {
      const usuario = await chamarApi<Usuario>(autenticador, '/v1/eu')
      setSessao({ tipo: 'ativa', usuario })
    } catch (erro) {
      if (erro instanceof SessaoExpirada) await sair()
      else setSessao({ tipo: 'api_indisponivel' })
    }
  }, [autenticador, sair])

  useEffect(() => {
    // Sincroniza com o SDK de login, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void verificar()
  }, [verificar])

  function reverificar() {
    setSessao({ tipo: 'verificando' })
    void verificar()
  }

  if (sessao.tipo === 'verificando') return null
  if (sessao.tipo === 'sem_sessao') {
    return <Login key={saidas} autenticador={autenticador} aoEntrar={reverificar} />
  }
  if (sessao.tipo === 'api_indisponivel') {
    return (
      <main>
        <p role="alert">Não foi possível falar com a API.</p>
        <button type="button" onClick={reverificar}>
          Tentar de novo
        </button>
        <button type="button" onClick={() => void sair()}>
          Sair
        </button>
      </main>
    )
  }
  return (
    <main>
      <h1>{aberto ? 'Vídeo' : 'Biblioteca'}</h1>
      <p>{sessao.usuario.email}</p>
      <button type="button" onClick={() => void sair()}>
        Sair
      </button>
      {aberto ? (
        <Video
          autenticador={autenticador}
          job={aberto}
          aoVoltar={() => setAberto(null)}
          aoSessaoExpirada={() => void sair()}
        />
      ) : (
        <Biblioteca
          autenticador={autenticador}
          aoSessaoExpirada={() => void sair()}
          aoAbrir={setAberto}
        />
      )}
    </main>
  )
}
