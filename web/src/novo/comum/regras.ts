import { finalizando, type Job } from '../../jobs.ts'
import { ESTADOS_QUE_VAO_PARA_A_LIXEIRA } from '../../lixeira.ts'

/** Se quem tem estas permissões pode mandar este vídeo para a lixeira (a API confere de novo). */
export function podeIrParaALixeira(job: Pick<Job, 'estado'>, permissoes: readonly string[]): boolean {
  return permissoes.includes('lixeira.gerir') && ESTADOS_QUE_VAO_PARA_A_LIXEIRA.includes(job.estado)
}

/**
 * Se quem tem estas permissões pode reprocessar o vídeo a partir de uma etapa: só o concluído,
 * e não enquanto as etapas de depois rodam, para não disparar um segundo processamento.
 * Depois do prazo, o item continua visível; quem o mostra o desabilita e explica o motivo.
 */
export function podeReprocessar(job: Job, permissoes: readonly string[]): boolean {
  return permissoes.includes('video.reprocessar_etapa') && job.estado === 'concluido' && !finalizando(job)
}

// Espelha a recusa de api/ciclo_de_vida.py; a API fornece o prazo, sem refazer a conta na tela.
export const AVISO_DO_REPROCESSAMENTO = 'O prazo de reprocessamento deste vídeo (7 dias após o envio) terminou: a cópia em alta resolução e o áudio não ficam guardados no MAM. Para reprocessar, envie o vídeo de novo a partir do arquivo da RedeTV.'

export function prazoDeReprocessamentoVencido(job: Job, agora = Date.now()): boolean {
  return agora >= Date.parse(job.reprocessavel_ate)
}
