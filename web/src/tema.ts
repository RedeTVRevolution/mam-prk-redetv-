import {
  Badge,
  createTheme,
  Loader,
  Menu,
  Modal,
  Popover,
  Table,
  Tooltip,
  type CSSVariablesResolver,
  type MantineColorsTuple,
} from '@mantine/core'
import { CORES } from './cores.ts'

export * from './cores.ts'

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
