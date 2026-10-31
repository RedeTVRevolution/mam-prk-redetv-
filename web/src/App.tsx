import {
  ActionIcon,
  Alert,
  AppShell,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core'
import { IconAlertTriangle, IconArrowLeft } from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { criarClienteDaApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import Biblioteca from './Biblioteca.tsx'
import Login from './Login.tsx'
import { CORES, NAVBAR_DA_BIBLIOTECA } from './tema.ts'
import Video, { type JobAberto } from './Video.tsx'

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

  // O 401 de qualquer tela chega aqui, num lugar só.
  const api = useMemo(
    () => criarClienteDaApi(autenticador, () => void sair()),
    [autenticador, sair],
  )

  const verificar = useCallback(async () => {
    try {
      setSessao({ tipo: 'ativa', usuario: await api.eu() })
    } catch (erro) {
      // Sessão expirada: o cliente já avisou e `sair` cuida do resto.
      if (!(erro instanceof SessaoExpirada)) setSessao({ tipo: 'api_indisponivel' })
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com o SDK de login, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void verificar()
  }, [verificar])

  function reverificar() {
    setSessao({ tipo: 'verificando' })
    void verificar()
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
  return (
    <AppShell
      header={{ height: 52 }}
      navbar={aberto ? undefined : NAVBAR_DA_BIBLIOTECA}
      padding={aberto ? 'sm' : 'lg'}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            {aberto && (
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Voltar à Biblioteca"
                onClick={() => setAberto(null)}
              >
                <IconArrowLeft />
              </ActionIcon>
            )}
            <Badge color={CORES.marca} variant="filled" radius="sm">
              MAM
            </Badge>
            <Text fw={700}>RedeTV</Text>
            <Text c="dimmed">{aberto ? 'Vídeo' : 'Biblioteca'}</Text>
          </Group>
          <Group gap="xs">
            <Text size="xs" c="dimmed">
              {sessao.usuario.email}
            </Text>
            <Button
              type="button"
              variant="subtle"
              size="xs"
              color="gray"
              onClick={() => void sair()}
            >
              Sair
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      {aberto ? (
        <AppShell.Main bg="dark.7">
          <Video
            api={api}
            job={aberto}
            podeEditar={sessao.usuario.permissoes.includes('decupagem.editar')}
            podeAprovar={sessao.usuario.permissoes.includes('correcao.aprovar')}
          />
        </AppShell.Main>
      ) : (
        // A Biblioteca traz a própria barra lateral e a área principal.
        <Biblioteca
          api={api}
          aoAbrir={setAberto}
          // O front só esconde; quem barra é a API.
          podeEnviar={sessao.usuario.permissoes.includes('video.enviar')}
        />
      )}
    </AppShell>
  )
}
