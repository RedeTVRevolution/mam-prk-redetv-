import { createTheme } from '@mantine/core'

export const tema = createTheme({
  primaryColor: 'red',
  defaultRadius: 'md',
})

export const ESTADOS_DO_JOB: Record<string, { cor: string; rotulo: string }> = {
  aguardando_upload: { cor: 'gray', rotulo: 'Aguardando envio' },
  validando: { cor: 'yellow', rotulo: 'Em quarentena' },
  analisando: { cor: 'blue', rotulo: 'Decupando' },
  concluido: { cor: 'green', rotulo: 'Concluído' },
  falhou: { cor: 'red', rotulo: 'Falhou' },
}

export const CORES_DE_OCORRENCIA = {
  pautas: 'teal',
  aparicoes: 'blue',
  mencoes: 'orange',
  comerciais: 'yellow',
  planos: 'lime',
  fala: 'gray',
} as const
