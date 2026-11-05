// Os tokens da interface atual, sem o Mantine: as regras (jobs.ts, auditoria.ts, …) os usam,
// e a interface nova importa as regras sem levar o Mantine junto (ADR 0014).

// Os tokens do docs/design/sistema-visual.md, que explica cada escolha. Nome de função,
// nunca de tom: quem usa pede "texto secundário", não "cinza 2".
export const CORES = {
  fundo: '#141518',
  superficie: '#1B1D21',
  elevada: '#25272C',
  borda: '#34373D',
  texto: '#E4E6EA',
  textoSecundario: '#A0A5AE',
  textoDesabilitado: '#6E737C',
  // Foco e seleção: um tom só, para o anel do teclado, o item selecionado, a barra do
  // item atual e o botão primário. O texto de link usa a versão clara.
  foco: '#3871DC',
  focoTexto: '#78A3F2',
  concluido: '#5CC98A',
  andamento: '#E5B045',
  falhou: '#F4736A',
  // Só no logotipo.
  marca: '#E03131',
} as const

/** Trecho sem decupagem: listras, não uma transição de cor. */
export const HACHURADO = `repeating-linear-gradient(135deg, ${CORES.borda} 0 2px, transparent 2px 6px)`

/** A barra fixa do topo: no máximo 44 px. */
export const ALTURA_DA_BARRA = 44

// O selo usa a cor do estado como texto, sobre a mesma cor a 10% (variante light).
export const ESTADOS_DO_JOB = {
  aguardando_upload: { cor: CORES.andamento, rotulo: 'Aguardando envio' },
  validando: { cor: CORES.andamento, rotulo: 'Em quarentena' },
  analisando: { cor: CORES.andamento, rotulo: 'Decupando' },
  concluido: { cor: CORES.concluido, rotulo: 'Concluído' },
  falhou: { cor: CORES.falhou, rotulo: 'Falhou' },
  cancelado: { cor: CORES.textoSecundario, rotulo: 'Cancelado' },
} satisfies Record<string, { cor: string; rotulo: string }>

export type EstadoDoJob = keyof typeof ESTADOS_DO_JOB

// Não é um estado da API: é o `concluido` com as etapas depois da análise ainda rodando.
export const FINALIZANDO = { cor: CORES.andamento, rotulo: 'Finalizando' }

// Uma cor por tipo, a mesma na faixa, no chip e no marcador. Distinguíveis entre si
// também na deuteranopia, e legíveis como texto sobre qualquer superfície.
export const CORES_DE_OCORRENCIA = {
  pauta: { cor: '#8A9CF5', rotulo: 'Pautas' },
  aparicao: { cor: '#F5A55A', rotulo: 'Aparições' },
  mencao: { cor: '#F08AAE', rotulo: 'Menções' },
  objeto: { cor: '#A0A030', rotulo: 'Objetos' },
  comercial: { cor: '#D9C2FF', rotulo: 'Comerciais' },
  fala: { cor: '#8E9196', rotulo: 'Fala' },
  texto_na_tela: { cor: '#A8EFC8', rotulo: 'Texto na tela' },
} as const

/**
 * A cor de cada `cor_base` do objeto, para o quadradinho da lista. É a cor do objeto, não a do
 * tipo de ocorrência; a tela sempre escreve a palavra ao lado.
 */
export const CORES_DE_OBJETO = {
  vermelho: '#E03C3C',
  laranja: '#F08A24',
  amarelo: '#F2D13A',
  verde: '#3FAE5A',
  azul: '#3F7FE0',
  roxo: '#8C4FD0',
  rosa: '#F28DB8',
  marrom: '#8B5A2B',
  bege: '#D9C3A0',
  preto: '#0B0C0D',
  branco: '#F5F5F5',
  cinza: '#8A8D93',
  dourado: '#D4AF37',
  prateado: '#C0C4CC',
  // Sem uma cor só: o cinza do texto secundário.
  estampado: CORES.textoSecundario,
} as const

export type TipoDeOcorrencia = keyof typeof CORES_DE_OCORRENCIA

function luminancia(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** Razão de contraste da WCAG 2 entre duas cores `#RRGGBB`, de 1 a 21. */
export function contraste(a: string, b: string): number {
  const [claro, escuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x)
  return (claro + 0.05) / (escuro + 0.05)
}
