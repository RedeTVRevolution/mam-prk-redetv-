/** Os nomes das etapas que a tela mostra durante o reprocessamento. */
const NOMES: Record<string, string> = {
  validacao: 'Validação',
  transcricao: 'Transcrição',
  leitura_da_tela: 'Leitura da tela',
  analise: 'Análise',
  identificacao: 'Identificação',
  referencias: 'Referências',
  comparacao: 'Comparação',
  quadros_chave: 'Quadros-chave',
  inventario_de_objetos: 'Inventário de objetos',
  indexacao: 'Indexação',
}

export function nomeDaEtapa(etapa: string): string {
  return NOMES[etapa] ?? etapa
}

/** As etapas do Job, na ordem em que rodam (a de `NomeDaEtapa` em api/jobs.py). */
const ORDEM = [
  'validacao',
  'transcricao',
  'leitura_da_tela',
  'analise',
  'identificacao',
  'referencias',
  'comparacao',
  'quadros_chave',
  'inventario_de_objetos',
  'indexacao',
]

/** Depois do `concluido` só estas rodam; a falha de uma não muda o estado do Job. */
const DEPOIS_DO_CONCLUIDO = ORDEM.slice(4)

/** A etapa que cada falha de etapa aponta (`ETAPA_DA_FALHA` em api/ciclo_de_vida.py). */
const ETAPA_DA_FALHA: Record<string, string> = {
  transcricao_falhou: 'transcricao',
  ocr_falhou: 'leitura_da_tela',
  analise_falhou: 'analise',
}

/** "de" + a etapa, para "Reprocessar a partir da leitura da tela?". */
const PARTIDA: Record<string, string> = {
  transcricao: 'da transcrição',
  leitura_da_tela: 'da leitura da tela',
  analise: 'da análise',
  identificacao: 'da identificação',
  referencias: 'das referências',
  comparacao: 'da comparação',
  quadros_chave: 'dos quadros-chave',
  inventario_de_objetos: 'do inventário de objetos',
  indexacao: 'da indexação',
}

export function partidaDaEtapa(etapa: string): string {
  return PARTIDA[etapa] ?? `da etapa ${nomeDaEtapa(etapa)}`
}

interface JobComEtapas {
  estado: string
  codigo_falha: string | null
  etapa_atual?: string | null
  etapas?: { nome: string; resultado: string | null }[]
}

/**
 * De onde "reprocessar o que falhou" recomeçaria este Job (`etapa_de_partida` em
 * api/ciclo_de_vida.py), ou `null` quando não vale: a falha é do arquivo, o vídeo concluído
 * não tem etapa que tenha falhado ou o Job já está andando.
 */
export function etapaDeReprocesso(job: JobComEtapas): string | null {
  if (job.estado !== 'falhou' && (job.estado !== 'concluido' || job.etapa_atual)) return null
  const falhas = ORDEM.filter((nome) => job.etapas?.some((e) => e.nome === nome && e.resultado === 'falhou'))
  if (job.estado === 'falhou') {
    const partida = falhas[0] ?? (job.codigo_falha ? ETAPA_DA_FALHA[job.codigo_falha] : undefined)
    return partida && partida !== 'validacao' ? partida : null
  }
  return falhas[0] && DEPOIS_DO_CONCLUIDO.includes(falhas[0]) ? falhas[0] : null
}
