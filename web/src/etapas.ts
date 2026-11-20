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
  return Object.hasOwn(NOMES, etapa) ? NOMES[etapa] : etapa
}

/** As etapas do Job, na ordem em que rodam (a de `NomeDaEtapa` em api/modelo_do_job.py). */
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
