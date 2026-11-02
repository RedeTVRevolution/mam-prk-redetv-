import { Text } from '@mantine/core'
import type { VideoDoResultado } from './busca.ts'
import { relogio } from './linhaDoTempo.ts'
import { Quadro } from './Miniatura.tsx'
import { enderecoDoVideo, seguir } from './rotas.ts'
import { CORES } from './tema.ts'

const NUMEROS = { fontVariantNumeric: 'tabular-nums' } as const

/** O modo visual: um card por plano, com a miniatura do quadro-chave, em grade. */
export function GradeDePlanos({ videos, busca }: { videos: VideoDoResultado[]; busca: string }) {
  return (
    <ul
      aria-label="Planos"
      style={{
        listStyle: 'none',
        margin: 0,
        padding: 0,
        display: 'grid',
        gap: 'var(--mantine-spacing-sm)',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
      }}
    >
      {videos.flatMap((video) =>
        video.momentos.filter((momento) => momento.tipo === 'plano').map((momento) => {
          const endereco = enderecoDoVideo(video.job_id, momento.inicio_ms / 1000, busca)
          return (
            <li key={`${video.job_id}:${momento.inicio_ms}`}>
              <a
                href={endereco}
                onClick={(e) => seguir(e, endereco)}
                aria-label={`${video.nome} em ${relogio(momento.inicio_ms)}`}
                data-momento={`${video.job_id}:${momento.inicio_ms}`}
                style={{ display: 'block', color: 'inherit', textDecoration: 'none' }}
              >
                <Quadro url={momento.quadro_url} largura={200} altura={113} />
                <Text size="xs" c={CORES.textoSecundario} mt={4} style={NUMEROS}>
                  {[video.programa ?? video.nome, relogio(momento.inicio_ms)].join(' · ')}
                </Text>
                <Text size="sm" lineClamp={2}>
                  {momento.motivo}
                </Text>
              </a>
            </li>
          )
        }),
      )}
    </ul>
  )
}
