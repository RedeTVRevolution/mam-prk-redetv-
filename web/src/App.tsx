import { Alert, AppShell, Badge, Button, Center, Group, Loader, Stack, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useCallback, useEffect, useState } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import Biblioteca from './Biblioteca.tsx'
import Login from './Login.tsx'
import { NAVBAR_DA_BIBLIOTECA } from './tema.ts'
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

  if (sessao.tipo === 'verificando') {
    return (
      <Center h="100vh">
        <Loader color="red" role="status" aria-label="Verificando a sessão" />
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
      padding={aberto ? undefined : 'lg'}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            {/* Espaço do botão de voltar, preenchido pela tela Vídeo. */}
            <Badge color="red" variant="filled" radius="sm">
              MAM
            </Badge>
            <Text fw={700}>RedeTV</Text>
            <Text c="dimmed">{aberto ? 'Vídeo' : 'Biblioteca'}</Text>
          </Group>
          <Group gap="xs">
            <Text size="xs" c="dimmed">
              {sessao.usuario.email}
            </Text>
            <Button type="button" variant="subtle" size="xs" color="gray" onClick={() => void sair()}>
              Sair
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      {aberto ? (
        <AppShell.Main bg="dark.7">
          <Video
            autenticador={autenticador}
            job={aberto}
            aoVoltar={() => setAberto(null)}
            aoSessaoExpirada={() => void sair()}
          />
        </AppShell.Main>
      ) : (
        // A Biblioteca traz a própria barra lateral e a área principal.
        <Biblioteca
          autenticador={autenticador}
          aoSessaoExpirada={() => void sair()}
          aoAbrir={setAberto}
        />
      )}
    </AppShell>
  )
}
