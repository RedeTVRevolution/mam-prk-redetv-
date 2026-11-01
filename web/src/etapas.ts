/** Os nomes das etapas que a tela mostra durante o reprocessamento. */
const NOMES: Record<string, string> = {
  analise: 'Análise',
  identificacao: 'Identificação',
  referencias: 'Referências',
  comparacao: 'Comparação',
  quadros_chave: 'Quadros-chave',
  indexacao: 'Indexação',
}

export function nomeDaEtapa(etapa: string): string {
  return NOMES[etapa] ?? etapa
}
