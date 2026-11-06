import type { Job } from '../../jobs.ts'

export type DialogoDoVideo = 'reprocessar' | 'lixeira'

/**
 * Ponto de ligação com a fase 2a, que cria os diálogos de reprocessar e de mandar para a lixeira em
 * `novo/comum/`. O menu do vídeo já abre `aberto`; falta trocar este corpo pelos diálogos.
 *
 * TODO fase-2a: renderizar o diálogo de reprocessar com `aoReprocessar(jobDevolvido, etapa)`, que
 * liga o acompanhamento da tela, e o de lixeira com `aoMandarParaLixeira()`, que volta ao acervo.
 */
export function DialogosDoVideo(props: {
  aberto: DialogoDoVideo | null
  job: Job
  aoFechar: () => void
  aoReprocessar: (job: Job, etapa: string) => void
  aoMandarParaLixeira: () => void
}) {
  void props
  return null
}
