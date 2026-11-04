import { Alert, Button, Center, Loader, Stack, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { type ClienteDaApi, FalhaNaApi, NaoEncontrado, SessaoExpirada } from './api.ts'
import type { Job } from './jobs.ts'
import { Link } from './Link.tsx'
import { ACERVO } from './rotas.ts'
import { CORES } from './tema.ts'
import Visualizador from './Visualizador.tsx'

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; job: Job }
  | { tipo: 'ausente' }
  | { tipo: 'erro'; codigo: string }

/** A tela Vídeo a partir do endereço: busca o Job pelo id e posiciona o player em `t`. */
export default function TelaDoVideo({
  api,
  id,
  t,
  busca = null,
  podeEditar,
  podeAprovar,
  podeReprocessar = false,
  podeVerAuditoria = false,
  podeFundir = false,
}: {
  api: ClienteDaApi
  id: string
  t: number | null
  /** O texto da busca de onde a pessoa chegou. */
  busca?: string | null
  podeEditar: boolean
  podeAprovar: boolean
  podeReprocessar?: boolean
  podeVerAuditoria?: boolean
  podeFundir?: boolean
}) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [tentativas, setTentativas] = useState(0)

  useEffect(() => {
    let ativo = true
    // Recomeça a carga quando o endereço troca de vídeo.
    // oxlint-disable-next-line react/set-state-in-effect
    setCarga({ tipo: 'carregando' })
    api.job(id).detalhe().then(
      (job) => {
        if (ativo) setCarga({ tipo: 'pronta', job })
      },
      (erro: unknown) => {
        if (!ativo || erro instanceof SessaoExpirada) return
        if (erro instanceof NaoEncontrado) setCarga({ tipo: 'ausente' })
        else
          setCarga({
            tipo: 'erro',
            codigo: erro instanceof FalhaNaApi ? `http_${erro.status}` : 'api_inacessivel',
          })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, id, tentativas])

  if (carga.tipo === 'carregando') {
    return (
      <Center h="60vh">
        <Loader role="status" aria-label="Carregando o vídeo" />
      </Center>
    )
  }
  if (carga.tipo === 'ausente') {
    return (
      <Center h="60vh">
        <Stack w={360}>
          <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
            Vídeo não encontrado.
          </Alert>
          <Link para={ACERVO}>Voltar ao acervo</Link>
        </Stack>
      </Center>
    )
  }
  if (carga.tipo === 'erro') {
    return (
      <Center h="60vh">
        <Stack w={360}>
          <Alert color={CORES.falhou} variant="light" icon={<IconAlertTriangle />} role="alert">
            <Stack gap="xs" align="flex-start">
              <Text size="sm">Não foi possível abrir o vídeo. Tente de novo em instantes.</Text>
              <Text size="xs" c="dimmed">
                Código para o suporte: {carga.codigo}
              </Text>
              <Button size="xs" variant="default" onClick={() => setTentativas((n) => n + 1)}>
                Tentar de novo
              </Button>
            </Stack>
          </Alert>
          <Link para={ACERVO}>Voltar ao acervo</Link>
        </Stack>
      </Center>
    )
  }
  return (
    <Visualizador
      key={carga.job.id}
      api={api}
      job={carga.job}
      t={t}
      busca={busca}
      podeEditar={podeEditar}
      podeAprovar={podeAprovar}
      podeReprocessar={podeReprocessar}
      podeVerAuditoria={podeVerAuditoria}
      podeFundir={podeFundir}
    />
  )
}
