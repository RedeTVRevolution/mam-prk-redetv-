import type { ImpactoDaMarca, ImpactoDaPessoa, ImpactoDoVideo, ImpactoPorTipo, TipoDeItem } from './api.ts'

/** Os estados em que a API aceita mandar o vídeo para a lixeira (`api/lixeira.py`). */
export const ESTADOS_QUE_VAO_PARA_A_LIXEIRA = ['concluido', 'falhou', 'cancelado']

export const ROTULO_DO_TIPO: Record<string, string> = { video: 'Vídeo', pessoa: 'Pessoa', marca: 'Marca' }

export function rotuloDoTipo(tipo: string): string {
  return ROTULO_DO_TIPO[tipo] ?? tipo.charAt(0).toUpperCase() + tipo.slice(1)
}

/** "em 26 dias", "em 1 dia", "hoje". */
export function purgaEm(dias: number): string {
  if (dias <= 0) return 'hoje'
  return dias === 1 ? 'em 1 dia' : `em ${dias} dias`
}

function contar(n: number, singular: string, plural: string): string {
  return `${n.toLocaleString('pt-BR')} ${n === 1 ? singular : plural}`
}

function nomes(lista: string[]): string {
  return lista.length < 2 ? lista.join('') : `${lista.slice(0, -1).join(', ')} e ${lista[lista.length - 1]}`
}

export function impactoDoVideo(i: ImpactoDoVideo): string {
  const partes = [
    '1 vídeo',
    contar(i.decupagem, 'decupagem', 'decupagens'),
    contar(i.correcoes, 'correção', 'correções'),
    contar(i.arquivos.copia_limpa, 'cópia limpa', 'cópias limpas'),
    contar(i.arquivos.proxy, 'proxy de reprodução', 'proxies de reprodução'),
    contar(i.arquivos.quadros, 'quadro-chave', 'quadros-chave'),
  ]
  return `${partes.join(', ')}. O arquivo original no storage da RedeTV não é tocado.`
}

/** Quando outro envio aponta para o mesmo processamento; vazio se ninguém mais. */
export function avisoDeOutrosEnvios(i: ImpactoDoVideo): string | null {
  if (i.outros_jobs.length === 0) return null
  return `Este arquivo também foi enviado por ${nomes([...new Set(i.outros_jobs.map((j) => j.enviado_por))])}; a decupagem continua para ${i.outros_jobs.length === 1 ? 'ele' : 'eles'}.`
}

function daPessoa(i: ImpactoDaPessoa): string {
  return `${contar(i.fotos_apagadas, 'foto de rosto', 'fotos de rosto')} (dado biométrico), e ${contar(i.aparicoes_que_perdem_o_nome, 'aparição', 'aparições')} confirmada${i.aparicoes_que_perdem_o_nome === 1 ? '' : 's'} pelo rosto volta${i.aparicoes_que_perdem_o_nome === 1 ? '' : 'm'} a "não identificado".`
}

function daMarca(i: ImpactoDaMarca): string {
  return `${contar(i.ocorrencias_que_perdem_o_vinculo, 'ocorrência', 'ocorrências')} nas decupagens mantêm o texto da marca e perdem o vínculo.`
}

/** O impacto de qualquer tipo, em uma frase. */
export function frasesDoImpacto<T extends TipoDeItem>(tipo: T, i: ImpactoPorTipo[T]): string[] {
  if (tipo === 'video') {
    const v = i as ImpactoDoVideo
    return [impactoDoVideo(v), avisoDeOutrosEnvios(v)].filter((f): f is string => f !== null)
  }
  return [tipo === 'pessoa' ? daPessoa(i as ImpactoDaPessoa) : daMarca(i as ImpactoDaMarca)]
}
