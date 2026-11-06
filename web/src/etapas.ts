/** Os nomes das etapas que a tela mostra durante o reprocessamento. */
const NOMES: Record<string, string> = {
  validacao: 'Validação',
  transcricao: 'Transcrição',
  leitura_da_tela: 'Leitura da tela',
  analise: 'Análise',
  identificacao: 'Identificação',
  quadros_chave: 'Quadros-chave',
  inventario_de_objetos: 'Inventário de objetos',
  indexacao: 'Indexação',
}

export function nomeDaEtapa(etapa: string): string {
  return NOMES[etapa] ?? etapa
}

/** As etapas do Job, na ordem em que rodam (a de `NomeDaEtapa` em api/jobs.py). */
export const ORDEM = [
  'validacao',
  'transcricao',
  'leitura_da_tela',
  'analise',
  'identificacao',
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

/** As falhas que pedem novo envio (`FALHAS_DO_ARQUIVO` em api/ciclo_de_vida.py). */
const FALHAS_DO_ARQUIVO = ['formato_invalido', 'arquivo_corrompido', 'codec_nao_suportado', 'duracao_excedida', 'upload_expirado']

/** "de" + a etapa, para "Reprocessar a partir da leitura da tela?". */
const PARTIDA: Record<string, string> = {
  transcricao: 'da transcrição',
  leitura_da_tela: 'da leitura da tela',
  analise: 'da análise',
  identificacao: 'da identificação',
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
 * api/ciclo_de_vida.py; mude as duas juntas), ou `null` quando não vale: a falha é do
 * arquivo, o processamento parou na validação, o vídeo concluído não tem etapa que tenha
 * falhado ou o Job já está andando.
 */
export function etapaDeReprocesso(job: JobComEtapas): string | null {
  if (job.estado !== 'falhou' && (job.estado !== 'concluido' || job.etapa_atual)) return null
  const falhas = ORDEM.filter((nome) => job.etapas?.some((e) => e.nome === nome && e.resultado === 'falhou'))
  if (job.estado === 'falhou') {
    if (job.codigo_falha === null || FALHAS_DO_ARQUIVO.includes(job.codigo_falha)) return null
    let partida: string | undefined = falhas[0] ?? ETAPA_DA_FALHA[job.codigo_falha]
    if (!partida && job.codigo_falha === 'processamento_interrompido') {
      // O Workflows caiu entre duas etapas: recomeça da primeira que não concluiu.
      partida = ORDEM.find((nome) => !job.etapas?.some((e) => e.nome === nome && e.resultado === 'concluida'))
    }
    return partida && partida !== 'validacao' ? partida : null
  }
  return falhas[0] && DEPOIS_DO_CONCLUIDO.includes(falhas[0]) ? falhas[0] : null
}

/** As etapas que o Curador pode escolher num vídeo concluído, na ordem em que rodam. */
export const ETAPAS_ESCOLHIVEIS = [
  { valor: 'analise', refaz: 'Refaz a decupagem inteira com o modelo, nas instruções de hoje.' },
  {
    valor: 'identificacao',
    refaz: 'Tenta de novo nomear as pessoas sem nome, busca as fotos e compara os rostos.',
  },
  { valor: 'quadros_chave', refaz: 'Extrai de novo os quadros das miniaturas.' },
  {
    valor: 'inventario_de_objetos',
    refaz: 'Lista de novo os objetos de cada plano e atualiza o índice da busca.',
  },
  { valor: 'indexacao', refaz: 'Atualiza o índice da busca com a decupagem atual.' },
] as const

export type EtapaEscolhivel = (typeof ETAPAS_ESCOLHIVEIS)[number]['valor']

/** O que reprocessar a partir de `etapa` faz com a Decupagem, na pergunta de confirmação. */
export function impactoDoReprocessamento(etapa: EtapaEscolhivel): string {
  return etapa === 'analise'
    ? 'Reprocessar a partir da análise? A Decupagem fica indisponível até a nova análise terminar, e as etapas seguintes rodam de novo.'
    : `Reprocessar a partir da etapa ${nomeDaEtapa(etapa)}? Ela e as etapas seguintes rodam de novo; a Decupagem continua disponível.`
}
