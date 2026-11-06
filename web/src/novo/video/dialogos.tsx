import { useQueryClient } from '@tanstack/react-query'
import type { EtapaEscolhivel } from '../../etapas.ts'
import type { Job } from '../../jobs.ts'
import { tirarDoAcervo, trocarNoAcervo } from '../acervo/useAcervo.ts'
import { MandarParaLixeira } from '../comum/MandarParaLixeira.tsx'
import { Reprocessar } from '../comum/Reprocessar.tsx'

export type DialogoDoVideo = 'reprocessar' | 'lixeira'

/**
 * Os diálogos do menu do vídeo, os mesmos do acervo. O acervo em cache recebe o Job devolvido ou
 * perde o vídeo na hora, para não mostrar o vídeo velho enquanto a lista ainda vale.
 */
export function DialogosDoVideo({
  aberto,
  job,
  aoFechar,
  aoReprocessar,
  aoMandarParaLixeira,
}: {
  aberto: DialogoDoVideo | null
  job: Job
  aoFechar: () => void
  aoReprocessar: (job: Job, etapa: EtapaEscolhivel) => void
  aoMandarParaLixeira: () => void
}) {
  const cliente = useQueryClient()
  return (
    <>
      <Reprocessar
        video={aberto === 'reprocessar' ? job : null}
        aoFechar={aoFechar}
        aoReprocessar={(novo, etapa) => {
          trocarNoAcervo(cliente, novo)
          aoReprocessar(novo, etapa)
        }}
      />
      <MandarParaLixeira
        video={aberto === 'lixeira' ? job : null}
        aoFechar={aoFechar}
        aoMandar={() => {
          tirarDoAcervo(cliente, new Set([job.id]))
          aoMandarParaLixeira()
        }}
      />
    </>
  )
}
