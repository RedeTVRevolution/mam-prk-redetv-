import { Loader, Stack, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { AlertaDeErro } from './AlertaDeErro.tsx'
import { codigoDoErro, FalhaNaApi, NaoEncontrado, SessaoExpirada, type ClienteDaApi } from './api.ts'
import { contagemDeVideos, type ResultadoDaBusca } from './busca.ts'
import { GradeDePlanos } from './GradeDePlanos.tsx'
import { Link } from './Link.tsx'
import { enderecoDoVideo } from './rotas.ts'

const PLANOS_POR_VEZ = 50

type Carga =
  | { tipo: 'carregando' }
  | { tipo: 'pronta'; resultado: ResultadoDaBusca }
  | { tipo: 'erro'; mensagem: string; codigo: string }

function mensagemDoErro(erro: unknown): string {
  if (erro instanceof NaoEncontrado) return 'Este plano não tem vetor do quadro, então não dá para achar parecidos.'
  if (erro instanceof FalhaNaApi && erro.status === 429) return 'Muitas buscas seguidas. Espere alguns segundos.'
  if (erro instanceof FalhaNaApi && erro.status === 504) return 'A busca demorou demais. Tente de novo.'
  return 'Não foi possível buscar agora. Tente de novo.'
}

/** "Planos parecidos com este" (#271): a grade dos planos mais próximos do quadro, sem enviar imagem. */
export function PlanosParecidos({ api, job, plano }: { api: ClienteDaApi; job: string; plano: number }) {
  const [carga, setCarga] = useState<Carga>({ tipo: 'carregando' })
  const [tentativas, setTentativas] = useState(0)

  useEffect(() => {
    let ativo = true
    // Cada plano ou tentativa nova recomeça pelo carregamento.
    // oxlint-disable-next-line react/set-state-in-effect
    setCarga({ tipo: 'carregando' })
    api.buscarParecidos(job, plano, PLANOS_POR_VEZ).then(
      (resultado) => {
        if (ativo) setCarga({ tipo: 'pronta', resultado })
      },
      (erro: unknown) => {
        if (!ativo || erro instanceof SessaoExpirada) return
        setCarga({ tipo: 'erro', mensagem: mensagemDoErro(erro), codigo: codigoDoErro(erro) })
      },
    )
    return () => {
      ativo = false
    }
  }, [api, job, plano, tentativas])

  const resultado = carga.tipo === 'pronta' ? carga.resultado : null
  const planos = resultado?.videos.flatMap((v) => v.momentos.filter((m) => m.tipo === 'plano')).length ?? 0

  return (
    <Stack gap="sm" component="section" aria-label="Planos parecidos" p="sm">
      <Link para={enderecoDoVideo(job)}>Voltar ao vídeo</Link>
      {carga.tipo === 'carregando' && <Loader role="status" aria-label="Buscando planos parecidos" />}
      {carga.tipo === 'erro' && (
        <AlertaDeErro mensagem={carga.mensagem} codigo={carga.codigo} aoTentar={() => setTentativas((n) => n + 1)} />
      )}
      {resultado && (
        <Stack gap="sm">
          <Text size="sm" role="status">
            {planos === 0
              ? 'Nenhum plano parecido.'
              : `${planos} ${planos === 1 ? 'plano parecido' : 'planos parecidos'} em ${contagemDeVideos(resultado.videos.length)}`}
          </Text>
          <GradeDePlanos videos={resultado.videos} busca="" />
        </Stack>
      )}
    </Stack>
  )
}
