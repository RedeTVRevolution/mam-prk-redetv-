import {
  Alert,
  AppShell,
  AspectRatio,
  Badge,
  Button,
  Card,
  Center,
  Checkbox,
  FileButton,
  Group,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core'
import { IconAlertTriangle, IconBan, IconPlayerPlay, IconUpload } from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { chamarApi, SessaoExpirada } from './api.ts'
import type { Autenticador } from './auth/autenticador.ts'
import { validarArquivo } from './envio/arquivo.ts'
import { enviarRetomavel } from './envio/upload.ts'
import { ESTADOS_DO_JOB, type EstadoDoJob } from './tema.ts'
import type { JobAberto } from './Video.tsx'

interface Job {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  duracao_s?: number | null
  criado_em: string
}

interface JobCriado extends Job {
  url_de_upload: string
}

type Envio =
  | { tipo: 'parado' }
  | { tipo: 'enviando'; fracao: number }
  | { tipo: 'concluido' }
  | { tipo: 'erro'; mensagem: string }

const ESTADOS = Object.keys(ESTADOS_DO_JOB) as EstadoDoJob[]

function formatarDuracao(segundos: number) {
  const total = Math.round(segundos)
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

function QuadroDoEstado({ estado }: { estado: string }) {
  if (estado === 'concluido') {
    return (
      <ThemeIcon size="xl" variant="light" color="green">
        <IconPlayerPlay />
      </ThemeIcon>
    )
  }
  if (estado === 'falhou') {
    return (
      <ThemeIcon size="xl" variant="light" color="red">
        <IconAlertTriangle />
      </ThemeIcon>
    )
  }
  if (estado === 'cancelado') {
    return (
      <ThemeIcon size="xl" variant="light" color="gray">
        <IconBan />
      </ThemeIcon>
    )
  }
  if (estado === 'analisando') return <Loader color="blue" />
  return <Loader type="dots" color="gray" />
}

export default function Biblioteca({
  autenticador,
  aoSessaoExpirada,
  aoAbrir,
  podeEnviar,
  intervaloMs = 5000,
}: {
  autenticador: Autenticador
  aoSessaoExpirada: () => void
  aoAbrir?: (job: JobAberto) => void
  podeEnviar: boolean
  intervaloMs?: number
}) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [envio, setEnvio] = useState<Envio>({ tipo: 'parado' })
  const [listaFalhou, setListaFalhou] = useState(false)
  const [estados, setEstados] = useState<string[]>(ESTADOS)
  const limparSeletor = useRef<() => void>(null)
  const enviando = envio.tipo === 'enviando'

  const tratar = useCallback(
    (erro: unknown) => {
      if (erro instanceof SessaoExpirada) aoSessaoExpirada()
    },
    [aoSessaoExpirada],
  )

  const atualizar = useCallback(async () => {
    try {
      setJobs(await chamarApi<Job[]>(autenticador, '/v1/jobs'))
      setListaFalhou(false)
    } catch (erro) {
      tratar(erro)
      setListaFalhou(true)
    }
  }, [autenticador, tratar])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void atualizar()
    const relogio = setInterval(() => void atualizar(), intervaloMs)
    return () => clearInterval(relogio)
  }, [atualizar, intervaloMs])

  async function escolher(arquivo: File | null) {
    if (!arquivo) return
    // Sem isso, escolher de novo o mesmo arquivo não dispara a troca.
    limparSeletor.current?.()
    const motivo = await validarArquivo(arquivo)
    if (motivo) {
      setEnvio({ tipo: 'erro', mensagem: motivo })
      return
    }
    setEnvio({ tipo: 'enviando', fracao: 0 })
    try {
      const criado = await chamarApi<JobCriado>(autenticador, '/v1/jobs', {
        metodo: 'POST',
        corpo: { nome: arquivo.name, tamanho_bytes: arquivo.size, tipo: arquivo.type },
      })
      void atualizar()
      await enviarRetomavel(criado.url_de_upload, arquivo, {
        aoProgresso: (fracao) => setEnvio({ tipo: 'enviando', fracao }),
      })
      setEnvio({ tipo: 'concluido' })
    } catch (erro) {
      tratar(erro)
      setEnvio({ tipo: 'erro', mensagem: 'Não foi possível enviar o vídeo.' })
    }
  }

  // Estado fora do mapa não tem caixa no filtro, então nunca some.
  const visiveis = jobs?.filter(
    (job) => !Object.hasOwn(ESTADOS_DO_JOB, job.estado) || estados.includes(job.estado),
  )

  return (
    <>
      <AppShell.Navbar p="sm">
        <Stack gap="lg">
          {podeEnviar && (
            <Stack gap="xs">
              <FileButton
                accept=".mp4,video/mp4"
                onChange={(arquivo) => void escolher(arquivo)}
                resetRef={limparSeletor}
                disabled={enviando}
                inputProps={{ 'aria-label': 'Enviar vídeo', disabled: enviando }}
              >
                {(props) => (
                  <Button
                    {...props}
                    fullWidth
                    leftSection={<IconUpload size={16} />}
                    disabled={enviando}
                  >
                    Enviar MP4
                  </Button>
                )}
              </FileButton>
              {envio.tipo === 'enviando' && (
                <Progress color="red" aria-label="Progresso do envio" value={envio.fracao * 100} />
              )}
              {envio.tipo === 'concluido' && (
                <Text size="xs" c="green">
                  Envio concluído.
                </Text>
              )}
              {envio.tipo === 'erro' && (
                <Alert color="red" variant="light" role="alert">
                  {envio.mensagem}
                </Alert>
              )}
            </Stack>
          )}
          <Checkbox.Group label="Estado" value={estados} onChange={setEstados}>
            <Stack gap="xs" mt="xs">
              {ESTADOS.map((estado) => (
                <Checkbox
                  key={estado}
                  size="xs"
                  value={estado}
                  label={ESTADOS_DO_JOB[estado].rotulo}
                />
              ))}
            </Stack>
          </Checkbox.Group>
        </Stack>
      </AppShell.Navbar>
      <AppShell.Main bg="dark.7">
        {listaFalhou && (
          <Alert color="yellow" variant="light" role="alert" mb="md">
            Não foi possível atualizar a lista; tentando de novo.
          </Alert>
        )}
        {jobs?.length === 0 && (
          <Center>
            <Text c="dimmed">Nenhum vídeo enviado ainda.</Text>
          </Center>
        )}
        {visiveis && visiveis.length > 0 && (
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
            {visiveis.map((job) => {
              const estado = ESTADOS_DO_JOB[job.estado as EstadoDoJob]
              const clicavel = aoAbrir && (job.estado === 'concluido' || job.estado === 'falhou')
              return (
                <Card
                  key={job.id}
                  padding="sm"
                  withBorder
                  {...(clicavel
                    ? {
                        component: 'button',
                        type: 'button',
                        'aria-label': job.nome,
                        onClick: () => aoAbrir(job),
                        style: { cursor: 'pointer', textAlign: 'left' },
                      }
                    : {})}
                >
                  <Card.Section>
                    <AspectRatio ratio={16 / 9}>
                      <Center bg="dark.8">
                        <QuadroDoEstado estado={job.estado} />
                      </Center>
                    </AspectRatio>
                  </Card.Section>
                  <Group justify="space-between" mt="sm" wrap="nowrap">
                    <Text size="sm" fw={600} truncate>
                      {job.nome}
                    </Text>
                    <Badge size="xs" color={estado?.cor}>
                      {estado?.rotulo ?? job.estado}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed">
                    {new Date(job.criado_em).toLocaleString('pt-BR')}
                    {job.duracao_s != null && ` · ${formatarDuracao(job.duracao_s)}`}
                  </Text>
                  {job.codigo_falha && (
                    <Text size="xs" c="red" ff="monospace">
                      {job.codigo_falha}
                    </Text>
                  )}
                </Card>
              )
            })}
          </SimpleGrid>
        )}
      </AppShell.Main>
    </>
  )
}
