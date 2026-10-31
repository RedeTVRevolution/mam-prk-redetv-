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
  Select,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core'
import { IconAlertTriangle, IconBan, IconPlayerPlay, IconUpload } from '@tabler/icons-react'
import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react'
import type { ClienteDaApi } from './api.ts'
import { validarArquivo } from './envio/arquivo.ts'
import { enviarRetomavel } from './envio/upload.ts'
import { tempo } from './linhaDoTempo.ts'
import { ESTADOS_DO_JOB, type EstadoDoJob } from './tema.ts'
import { enderecoDoVideo, seguir } from './rotas.ts'

export interface Job {
  id: string
  nome: string
  estado: string
  codigo_falha: string | null
  duracao_s?: number | null
  programa?: string | null
  criado_em: string
}

export interface JobCriado extends Job {
  url_de_upload: string
}

type Envio =
  | { tipo: 'parado' }
  | { tipo: 'enviando'; fracao: number }
  | { tipo: 'concluido' }
  | { tipo: 'erro'; mensagem: string }

const ESTADOS = Object.keys(ESTADOS_DO_JOB) as EstadoDoJob[]

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
  if (estado === 'analisando') return <Loader color={ESTADOS_DO_JOB.analisando.cor} />
  return <Loader type="dots" color="gray" />
}

export default function Biblioteca({
  api,
  podeEnviar,
  intervaloMs = 5000,
}: {
  api: ClienteDaApi
  podeEnviar: boolean
  intervaloMs?: number
}) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [envio, setEnvio] = useState<Envio>({ tipo: 'parado' })
  const [listaFalhou, setListaFalhou] = useState(false)
  const [estados, setEstados] = useState<string[]>(ESTADOS)
  // Programas com perfil: sem a lista (falha ao carregar), o envio segue sem programa.
  const [programas, setProgramas] = useState<string[]>([])
  const [programa, setPrograma] = useState<string | null>(null)
  const limparSeletor = useRef<() => void>(null)
  const enviando = envio.tipo === 'enviando'

  const atualizar = useCallback(async () => {
    try {
      setJobs(await api.jobs())
      setListaFalhou(false)
    } catch {
      setListaFalhou(true)
    }
  }, [api])

  useEffect(() => {
    // Sincroniza com a API, um sistema externo.
    // oxlint-disable-next-line react/set-state-in-effect
    void atualizar()
    const relogio = setInterval(() => void atualizar(), intervaloMs)
    return () => clearInterval(relogio)
  }, [atualizar, intervaloMs])

  useEffect(() => {
    if (!podeEnviar) return
    let ativo = true
    api.programas().then(
      (lista) => {
        if (ativo) setProgramas(lista)
      },
      () => {},
    )
    return () => {
      ativo = false
    }
  }, [api, podeEnviar])

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
      const criado = await api.criarJob({
        nome: arquivo.name,
        tamanho_bytes: arquivo.size,
        tipo: arquivo.type,
        ...(programa ? { programa } : {}),
      })
      void atualizar()
      await enviarRetomavel(criado.url_de_upload, arquivo, {
        aoProgresso: (fracao) => setEnvio({ tipo: 'enviando', fracao }),
      })
      setEnvio({ tipo: 'concluido' })
    } catch {
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
              {programas.length > 0 && (
                <Select
                  label="Programa"
                  placeholder="Sem programa"
                  size="xs"
                  clearable
                  data={programas}
                  value={programa}
                  onChange={setPrograma}
                  disabled={enviando}
                />
              )}
              <FileButton
                accept=".mp4,video/mp4"
                onChange={(arquivo) => void escolher(arquivo)}
                resetRef={limparSeletor}
                disabled={enviando}
                inputProps={{
                  'aria-label': 'Enviar vídeo',
                  disabled: enviando,
                }}
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
                <Progress aria-label="Progresso do envio" value={envio.fracao * 100} />
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
              const clicavel = (job.estado === 'concluido' || job.estado === 'falhou')
              return (
                <Card
                  key={job.id}
                  padding="sm"
                  withBorder
                  {...(clicavel
                    ? {
                        component: 'a',
                        href: enderecoDoVideo(job.id),
                        'aria-label': job.nome,
                        onClick: (e: MouseEvent<HTMLAnchorElement>) =>
                          seguir(e, enderecoDoVideo(job.id)),
                        style: { cursor: 'pointer', textAlign: 'left', color: 'inherit' },
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
                    {job.duracao_s != null && ` · ${tempo(job.duracao_s * 1000)}`}
                    {job.programa && ` · ${job.programa}`}
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
