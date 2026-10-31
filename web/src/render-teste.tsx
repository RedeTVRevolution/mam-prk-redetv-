import { MantineProvider } from '@mantine/core'
import { render as renderizar } from '@testing-library/react'
import type { ReactElement } from 'react'
import { tema, variaveis } from './tema.ts'

// env="test": sem transições nem portais; gavetas e janelas fechadas saem da tela na hora.
export function render(ui: ReactElement) {
  return renderizar(
    <MantineProvider
      theme={tema}
      cssVariablesResolver={variaveis}
      forceColorScheme="dark"
      env="test"
    >
      {ui}
    </MantineProvider>,
  )
}
