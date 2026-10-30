import { MantineProvider } from '@mantine/core'
import { render as renderizar } from '@testing-library/react'
import type { ReactElement } from 'react'
import { tema } from './tema.ts'

export function render(ui: ReactElement) {
  return renderizar(
    <MantineProvider theme={tema} forceColorScheme="dark">
      {ui}
    </MantineProvider>,
  )
}
