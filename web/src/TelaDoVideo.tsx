import { Alert, Button, Center, Loader, Stack, Text } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { type Atalho, useAtalhos } from './atalhos.ts'
import { type ClienteDaApi, FalhaNaApi, NaoEncontrado, SessaoExpirada } from './api.ts'
import type { Job } from './Biblioteca.tsx'
import { Link } from './Link.tsx'
import { ACERVO } from './rotas.ts'
import { CORES } from './tema.ts'
import Video from './Video.tsx'

// As teclas da linha do tempo agem no elemento em foco (o `Video` as trata); aqui só
// entram na lista do `?`.
const DA_LINHA_DO_TEMPO: Atalho[] = [
  { tecla: 'Enter ou Espaço', acao: 'Na faixa: ir à ocorrência em foco', grupo: 'Linha do tempo' },
]
const DAS_ALCAS: Atalho[] = [
  { tecla: '← →', acao: 'Na alça: mover o início ou o fim', grupo: 'Linha do tempo' },
  { tecla: 'Shift + ← →', acao: 'Na alça: mover em passo grande', grupo: 'Linha do tempo' },
  { tecla: 'Enter', acao: 'Na alça: soltar e confirmar o intervalo', grupo: 'Linha do tempo' },
]

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
  podeEditar,
  podeAprovar,
}: {
  api: ClienteDaApi
  id: string
  t: number | null
  podeEditar: boolean
  podeAprovar: boolean
}) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [tentativas, setTentativas] = useState(0)
  useAtalhos(podeEditar ? [...DA_LINHA_DO_TEMPO, ...DAS_ALCAS] : DA_LINHA_DO_TEMPO)

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
    <Video
      key={carga.job.id}
      api={api}
      job={carga.job}
      podeEditar={podeEditar}
      podeAprovar={podeAprovar}
      inicioEmS={t}
    />
  )
}
