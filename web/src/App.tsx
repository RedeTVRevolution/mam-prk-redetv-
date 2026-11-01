import {
  Alert,
  AppShell,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { criarClienteDaApi, SessaoExpirada } from './api.ts'
import { AtalhosProvider } from './AtalhosProvider.tsx'
import type { Autenticador } from './auth/autenticador.ts'
import Barra from './Barra.tsx'
import Acervo from './Acervo.tsx'
import Busca from './Busca.tsx'
import Login from './Login.tsx'
import { Link } from './Link.tsx'
import { ACERVO, navegar, useRota } from './rotas.ts'
import { ALTURA_DA_BARRA } from './tema.ts'
import TelaDoVideo from './TelaDoVideo.tsx'

// A amostra do sistema visual é grande e sem login: fica num pedaço à parte do bundle.
const Amostra = lazy(() => import('./Amostra.tsx'))

export interface Usuario {
  uid: string
  email: string
  permissoes: string[]
}

// Sem sessão não renderiza nada além do login e não chama a API.
type Sessao =
  | { tipo: 'verificando' }
  | { tipo: 'sem_sessao' }
  | { tipo: 'api_indisponivel' }
  | { tipo: 'ativa'; usuario: Usuario }

export default function App({ autenticador }: { autenticador: Autenticador }) {
  return (
    <AtalhosProvider>
      <Telas autenticador={autenticador} />
    </AtalhosProvider>
  )
}

function Telas({ autenticador }: { autenticador: Autenticador }) {
  const [sessao, setSessao] = useState<Sessao>({ tipo: 'verificando' })
  // Muda a cada saída, para o login recomeçar do zero (inclusive após um 401 logo depois do TOTP).
  const [saidas, setSaidas] = useState(0)
  const rota = useRota()

  const sair = useCallback(async () => {
    await autenticador.sair()
    setSessao({ tipo: 'sem_sessao' })
    setSaidas((n) => n + 1)
  }, [autenticador])

  // O 401 de qualquer tela chega aqui, num lugar só. Chamadas em paralelo podem voltar 401
  // juntas: a sessão cai uma vez só, e o próximo login volta a ouvir o aviso.
  const expirou = useRef(false)
  const aoSessaoExpirada = useCallback(() => {
    if (expirou.current) return
    expirou.current = true
    void sair()
  }, [sair])
  const api = useMemo(
    // O cliente só guarda o callback; o ref é lido quando chega um 401, fora da renderização.
    // oxlint-disable-next-line react/refs
    () => criarClienteDaApi(autenticador, aoSessaoExpirada),
    [autenticador, aoSessaoExpirada],
  )

  // `/` vai ao acervo; o endereço pedido antes do login fica como está e abre depois dele.
  const ativa = sessao.tipo === 'ativa'
  useEffect(() => {
    if (ativa && rota.tipo === 'raiz') navegar(ACERVO, { substituir: true })
  }, [ativa, rota.tipo])

  const verificar = useCallback(async () => {
    try {
      setSessao({ tipo: 'ativa', usuario: await api.eu() })
    } catch (erro) {
      // Sessão expirada: o cliente já avisou e `sair` cuida do resto.
      if (!(erro instanceof SessaoExpirada)) setSessao({ tipo: 'api_indisponivel' })
    }
  }, [api])

  // A amostra abre sem login e sem a API: só verifica a sessão fora dela.
  const naAmostra = rota.tipo === 'amostra'
  useEffect(() => {
    if (naAmostra) return
    // Sincroniza com o SDK de login, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void verificar()
  }, [verificar, naAmostra])

  function reverificar() {
    expirou.current = false
    setSessao({ tipo: 'verificando' })
    void verificar()
  }

  if (naAmostra) {
    return (
      <Suspense fallback={null}>
        <Amostra />
      </Suspense>
    )
  }
  if (sessao.tipo === 'verificando') {
    return (
      <Center h="100vh">
        <Loader role="status" aria-label="Verificando a sessão" />
      </Center>
    )
  }
  if (sessao.tipo === 'sem_sessao') {
    return <Login key={saidas} autenticador={autenticador} aoEntrar={reverificar} />
  }
  if (sessao.tipo === 'api_indisponivel') {
    return (
      <Center h="100vh">
        <Stack w={360}>
          <Alert color="red" variant="light" icon={<IconAlertTriangle />} role="alert">
            Não foi possível falar com a API.
          </Alert>
          <Group>
            <Button type="button" onClick={reverificar}>
              Tentar de novo
            </Button>
            <Button type="button" variant="default" onClick={() => void sair()}>
              Sair
            </Button>
          </Group>
        </Stack>
      </Center>
    )
  }
  const podeEditar = sessao.usuario.permissoes.includes('decupagem.editar')
  const podeAprovar = sessao.usuario.permissoes.includes('correcao.aprovar')
  const podeReprocessar = sessao.usuario.permissoes.includes('video.reprocessar_etapa')
  const podeEnviar = sessao.usuario.permissoes.includes('video.enviar')
  return (
    <AppShell
      header={{ height: ALTURA_DA_BARRA }}
      padding="sm"
    >
      <Barra email={sessao.usuario.email} aoSair={() => void sair()} />
      {rota.tipo === 'video' || rota.tipo === 'video_anterior' ? (
        <AppShell.Main bg="dark.7">
          <TelaDoVideo
            api={api}
            id={rota.id}
            t={rota.t}
            podeEditar={podeEditar}
            podeAprovar={podeAprovar}
            podeReprocessar={podeReprocessar}
            anterior={rota.tipo === 'video_anterior'}
          />
        </AppShell.Main>
      ) : rota.tipo === 'acervo' ? (
        // O front só esconde o envio; quem barra é a API.
        <Acervo api={api} filtros={rota.filtros} podeEnviar={podeEnviar} />
      ) : rota.tipo === 'busca' ? (
        <AppShell.Main bg="dark.7">
          <Busca api={api} consulta={rota.consulta} />
        </AppShell.Main>
      ) : (
        <AppShell.Main bg="dark.7">
          <Center h="60vh">
            <Stack align="center">
              <Text>Página não encontrada.</Text>
              <Link para={ACERVO}>Ir ao acervo</Link>
            </Stack>
          </Center>
        </AppShell.Main>
      )}
    </AppShell>
  )
}
