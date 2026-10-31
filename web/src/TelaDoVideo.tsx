import { Alert, Center, Loader, Stack } from '@mantine/core'
import { IconAlertTriangle } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { type ClienteDaApi, NaoEncontrado, SessaoExpirada } from './api.ts'
import type { Job } from './Biblioteca.tsx'
import { Link } from './Link.tsx'
import { ACERVO } from './rotas.ts'
import Video from './Video.tsx'

type Carga = { tipo: 'carregando' } | { tipo: 'pronta'; job: Job } | { tipo: 'ausente' } | { tipo: 'erro' }

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
        setCarga({ tipo: erro instanceof NaoEncontrado ? 'ausente' : 'erro' })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, id])

  if (carga.tipo === 'carregando') {
    return (
      <Center h="60vh">
        <Loader role="status" aria-label="Carregando o vídeo" />
      </Center>
    )
  }
  if (carga.tipo !== 'pronta') {
    return (
      <Center h="60vh">
        <Stack w={360}>
          <Alert color="red" variant="light" icon={<IconAlertTriangle />} role="alert">
            {carga.tipo === 'ausente'
              ? 'Vídeo não encontrado.'
              : 'Não foi possível abrir o vídeo. Tente de novo em instantes.'}
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
