import {
  IconBadgeTm,
  IconBox,
  IconListDetails,
  IconMicrophone,
  IconMovie,
  IconQuote,
  IconTextRecognition,
  IconUser,
  type Icon,
} from '@tabler/icons-react'

/**
 * As faixas da linha do tempo, na ordem do `faixasDoVisualizador`; a chave é o prefixo das chaves dos itens.
 * O plano não é faixa: só tem seção no inspetor (a lista e a correção).
 */
export type TipoDaFaixa = 'pauta' | 'aparicao' | 'mencao' | 'objeto' | 'comercial' | 'texto' | 'fala' | 'plano'

/** O ícone e a cor de cada tipo (MAM_DESIGN_SYSTEM 2.5): a cor nunca vem sem o ícone. */
export const TIPOS: Record<TipoDaFaixa, { cor: string; Icone: Icon }> = {
  pauta: { cor: 'var(--color-tipo-pauta)', Icone: IconListDetails },
  aparicao: { cor: 'var(--color-tipo-aparicao)', Icone: IconUser },
  mencao: { cor: 'var(--color-tipo-mencao)', Icone: IconQuote },
  objeto: { cor: 'var(--color-tipo-objeto)', Icone: IconBox },
  plano: { cor: 'var(--color-muted-foreground)', Icone: IconMovie },
  comercial: { cor: 'var(--color-tipo-marca)', Icone: IconBadgeTm },
  texto: { cor: 'var(--color-tipo-texto)', Icone: IconTextRecognition },
  fala: { cor: 'var(--color-tipo-fala)', Icone: IconMicrophone },
}

/** As chaves das consultas do vídeo: tudo sob `['video', id]`, para recarregar ou descartar junto. */
export const chaveDoVideo = (id: string, ...resto: string[]) => ['video', id, ...resto]

/** O tipo de uma chave de item ou de bloco (`aparicao-3`). */
export const tipoDaChave = (chave: string): TipoDaFaixa => chave.slice(0, chave.indexOf('-')) as TipoDaFaixa

/** As faixas ligadas ao abrir, como no protótipo: menções e objetos ficam nos chips. */
export const FAIXAS_DE_INICIO: TipoDaFaixa[] = ['pauta', 'aparicao', 'comercial', 'texto', 'fala']

export type Secao = 'pessoas' | 'pautas' | 'planos' | 'objetos' | 'comerciais' | 'textos' | 'mencoes' | 'falas'

export const SECAO_DO_TIPO: Record<TipoDaFaixa, Secao> = {
  pauta: 'pautas',
  aparicao: 'pessoas',
  mencao: 'mencoes',
  objeto: 'objetos',
  plano: 'planos',
  comercial: 'comerciais',
  texto: 'textos',
  fala: 'falas',
}

