import { finalizando, type Job } from '../../jobs.ts'
import { ESTADOS_QUE_VAO_PARA_A_LIXEIRA } from '../../lixeira.ts'

/** Se quem tem estas permissões pode mandar este vídeo para a lixeira (a API confere de novo). */
export function podeIrParaALixeira(job: Pick<Job, 'estado'>, permissoes: readonly string[]): boolean {
  return permissoes.includes('lixeira.gerir') && ESTADOS_QUE_VAO_PARA_A_LIXEIRA.includes(job.estado)
}

/**
 * Se quem tem estas permissões pode reprocessar o vídeo a partir de uma etapa: só o concluído,
 * e não enquanto as etapas de depois rodam, para não disparar um segundo processamento.
 */
export function podeReprocessar(job: Job, permissoes: readonly string[]): boolean {
  return permissoes.includes('video.reprocessar_etapa') && job.estado === 'concluido' && !finalizando(job)
}
