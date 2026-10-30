import { createTheme, type MantineColor } from '@mantine/core'

export const tema = createTheme({
  primaryColor: 'red',
  defaultRadius: 'md',
})

export const ESTADOS_DO_JOB = {
  aguardando_upload: { cor: 'gray', rotulo: 'Aguardando envio' },
  validando: { cor: 'yellow', rotulo: 'Em quarentena' },
  analisando: { cor: 'blue', rotulo: 'Decupando' },
  concluido: { cor: 'green', rotulo: 'Concluído' },
  falhou: { cor: 'red', rotulo: 'Falhou' },
} satisfies Record<string, { cor: MantineColor; rotulo: string }>

export type EstadoDoJob = keyof typeof ESTADOS_DO_JOB

export const CORES_DE_OCORRENCIA = {
  pautas: 'teal',
  aparicoes: 'blue',
  mencoes: 'orange',
  comerciais: 'yellow',
  planos: 'lime',
  fala: 'gray',
} as const satisfies Record<string, MantineColor>
