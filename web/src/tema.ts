import {
  Badge,
  createTheme,
  Loader,
  Menu,
  Modal,
  Popover,
  Table,
  Tooltip,
  type AppShellNavbarConfiguration,
  type CSSVariablesResolver,
  type MantineColorsTuple,
} from '@mantine/core'

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

// Escala do tema escuro, na ordem em que o Mantine usa cada tom: 0 texto, 2 texto
// secundário, 3 desabilitado e placeholder, 4 borda, 5 hover e superfície elevada,
// 6 superfície e campos, 7 fundo da página.
const ESCURO: MantineColorsTuple = [
  CORES.texto,
  '#C5C9CF',
  CORES.textoSecundario,
  CORES.textoDesabilitado,
  CORES.borda,
  CORES.elevada,
  CORES.superficie,
  CORES.fundo,
  '#101113',
  '#0B0C0D',
]

const FOCO: MantineColorsTuple = [
  '#E9F0FD',
  '#D3E1FB',
  '#ABC6F7',
  '#91B4F5',
  CORES.focoTexto,
  '#5487E8',
  CORES.foco,
  '#2D5EBD',
  '#254D9C',
  '#1D3D7C',
]

/** Trecho sem decupagem: listras, não uma transição de cor. */
export const HACHURADO = `repeating-linear-gradient(135deg, ${CORES.borda} 0 2px, transparent 2px 6px)`

export const tema = createTheme({
  primaryColor: 'foco',
  primaryShade: { light: 6, dark: 6 },
  colors: { dark: ESCURO, foco: FOCO },
  fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  fontFamilyMonospace: "ui-monospace, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace",
  fontSizes: { xs: '12px', sm: '13px', md: '14px', lg: '16px', xl: '18px' },
  lineHeights: { xs: '1.35', sm: '1.4', md: '1.45', lg: '1.5', xl: '1.5' },
  headings: {
    fontWeight: '600',
    sizes: {
      h1: { fontSize: '20px', lineHeight: '1.3' },
      h2: { fontSize: '18px', lineHeight: '1.3' },
      h3: { fontSize: '16px', lineHeight: '1.35' },
      h4: { fontSize: '14px', lineHeight: '1.4' },
      h5: { fontSize: '13px', lineHeight: '1.4' },
      h6: { fontSize: '12px', lineHeight: '1.4' },
    },
  },
  spacing: { xs: '4px', sm: '8px', md: '12px', lg: '16px', xl: '24px' },
  radius: { xs: '2px', sm: '4px', md: '6px', lg: '6px', xl: '6px' },
  defaultRadius: 'sm',
  shadows: {
    xs: '0 1px 2px rgba(0, 0, 0, 0.4)',
    sm: '0 1px 2px rgba(0, 0, 0, 0.4)',
    md: '0 2px 8px rgba(0, 0, 0, 0.4)',
    lg: '0 2px 8px rgba(0, 0, 0, 0.4)',
    xl: '0 2px 8px rgba(0, 0, 0, 0.4)',
  },
  components: {
    Badge: Badge.extend({
      defaultProps: { variant: 'light', radius: 'sm' },
      styles: { root: { textTransform: 'none', fontWeight: 600 } },
    }),
    // 6 + 20 + 6 = 32 px por linha, mais 1 px de borda.
    Table: Table.extend({
      defaultProps: { verticalSpacing: 6, horizontalSpacing: 'sm', fz: 'sm' },
      styles: { th: { lineHeight: '20px' }, td: { lineHeight: '20px' } },
    }),
    Tooltip: Tooltip.extend({ defaultProps: { openDelay: 300 } }),
    Menu: Menu.extend({ styles: { dropdown: { background: CORES.elevada } } }),
    Popover: Popover.extend({ styles: { dropdown: { background: CORES.elevada } } }),
    Modal: Modal.extend({
      // O botão de fechar é só um ícone: sem isto, o leitor de tela não tem o que dizer.
      defaultProps: {
        transitionProps: { duration: 150 },
        closeButtonProps: { 'aria-label': 'Fechar' },
      },
      styles: { content: { background: CORES.elevada }, header: { background: CORES.elevada } },
    }),
    Loader: Loader.extend({ defaultProps: { size: 'sm' } }),
  },
})

// Duas cores que o Mantine não tira da escala: a mensagem de erro dos campos (que seria o
// red.8, abaixo do AA) e o placeholder (que seria o tom de desabilitado, isento só no
// controle inativo). Vale para o MantineProvider do app e o dos testes.
export const variaveis: CSSVariablesResolver = () => ({
  variables: {},
  light: {},
  dark: {
    '--mantine-color-error': CORES.falhou,
    '--mantine-color-placeholder': CORES.textoSecundario,
  },
})

// A barra lateral é da Biblioteca, mas o AppShell é um só (o do App): dois AppShells
// aninhados disputam as mesmas variáveis de layout no :root.
export const NAVBAR_DA_BIBLIOTECA: AppShellNavbarConfiguration = { width: 240, breakpoint: 'sm' }

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
