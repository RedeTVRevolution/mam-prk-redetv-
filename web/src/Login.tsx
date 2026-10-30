import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Center,
  Code,
  Modal,
  PasswordInput,
  PinInput,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from '@mantine/core'
import { IconShieldLock } from '@tabler/icons-react'
import { useState, type SubmitEvent } from 'react'
import {
  ContaBloqueada,
  CredencialInvalida,
  type Autenticador,
  type ResultadoDaSenha,
} from './auth/autenticador.ts'

type Etapa = Exclude<ResultadoDaSenha, { tipo: 'logado' }> | { tipo: 'senha' }

export default function Login({
  autenticador,
  aoEntrar,
}: {
  autenticador: Autenticador
  aoEntrar: () => void
}) {
  const [etapa, setEtapa] = useState<Etapa>({ tipo: 'senha' })
  const [erro, setErro] = useState<string | null>(null)
  const [codigo, setCodigo] = useState('')

  function voltarAoInicio() {
    setEtapa({ tipo: 'senha' })
    setCodigo('')
    setErro(null)
  }

  function mensagemDeErro(erro: unknown) {
    return erro instanceof CredencialInvalida
      ? 'Credenciais inválidas. Confira os dados e tente de novo.'
      : erro instanceof ContaBloqueada
        ? 'Muitas tentativas erradas. Espere alguns minutos e tente de novo.'
        : 'Login indisponível no momento.'
  }

  async function enviarSenha(evento: SubmitEvent<HTMLFormElement>) {
    evento.preventDefault()
    const dados = new FormData(evento.currentTarget)
    setErro(null)
    try {
      const resultado = await autenticador.entrar(
        String(dados.get('email')),
        String(dados.get('senha')),
      )
      if (resultado.tipo === 'logado') aoEntrar()
      else setEtapa(resultado)
    } catch (erro) {
      setErro(mensagemDeErro(erro))
    }
  }

  async function enviarCodigo(evento: SubmitEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (etapa.tipo === 'senha') return
    setErro(null)
    try {
      if (etapa.tipo === 'precisa_totp') await autenticador.confirmarTotp(codigo)
      else await autenticador.cadastrarTotp(codigo)
      aoEntrar()
    } catch (erro) {
      setErro(mensagemDeErro(erro))
    }
  }

  const alerta = erro && (
    <Alert color="red" variant="light" role="alert">
      {erro}
    </Alert>
  )

  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing={0} mih="100vh">
      <Box
        pos="relative"
        h="100%"
        visibleFrom="md"
        style={{
          background:
            'linear-gradient(160deg, var(--mantine-color-dark-8) 0%, var(--mantine-color-red-9) 140%)',
        }}
      >
        <Stack gap={4} pos="absolute" bottom={48} left={48}>
          <Badge color="red" size="lg" radius="sm">
            MAM
          </Badge>
          <Title order={1} size={56} c="white">
            MAM RedeTV
          </Title>
          <Text c="gray.4" size="lg">
            Decupagem automática do acervo de vídeo.
          </Text>
        </Stack>
      </Box>
      <Center p="xl">
        <form onSubmit={enviarSenha}>
          <Stack w={360}>
            <Title order={2}>Entrar</Title>
            <Text c="dimmed" size="sm">
              Conta local com autenticador obrigatório.
            </Text>
            <TextInput
              label="E-mail"
              name="email"
              size="md"
              type="email"
              placeholder="nome@redetv.com.br"
              autoComplete="username"
              required
            />
            <PasswordInput
              label="Senha"
              name="senha"
              size="md"
              autoComplete="current-password"
              required
            />
            <Button type="submit" size="md" fullWidth>
              Entrar
            </Button>
            {etapa.tipo === 'senha' && alerta}
          </Stack>
        </form>
      </Center>
      <Modal
        opened={etapa.tipo !== 'senha'}
        onClose={voltarAoInicio}
        title="Verificação em duas etapas"
        centered
        closeOnClickOutside={false}
        closeButtonProps={{ 'aria-label': 'Fechar' }}
      >
        <form onSubmit={enviarCodigo}>
          <Stack align="center">
            <ThemeIcon size={56} radius="xl" variant="light">
              <IconShieldLock size={32} />
            </ThemeIcon>
            {etapa.tipo === 'precisa_cadastro_totp' && (
              <>
                <Text size="sm" ta="center">
                  Primeiro acesso: cadastre um aplicativo autenticador com o segredo abaixo e
                  digite o código que ele mostrar.
                </Text>
                <Code block>{etapa.segredo}</Code>
                <Anchor href={etapa.uri}>Abrir no aplicativo autenticador</Anchor>
              </>
            )}
            <Text size="sm" ta="center">
              Digite o código de 6 dígitos do seu aplicativo autenticador.
            </Text>
            <PinInput
              length={6}
              type="number"
              size="lg"
              oneTimeCode
              autoFocus
              aria-label="Código do autenticador"
              value={codigo}
              onChange={setCodigo}
            />
            <Button type="submit" fullWidth>
              Confirmar
            </Button>
            {etapa.tipo !== 'senha' && alerta}
          </Stack>
        </form>
      </Modal>
    </SimpleGrid>
  )
}
