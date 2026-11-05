import { Kbd, Modal, Stack, Table, Text, Title } from '@mantine/core'
import type { ReactNode } from 'react'
import { Contexto, useRegistroDeAtalhos } from './atalhos.ts'

/** O registro único de atalhos: ouve o teclado num lugar só e ignora campos de texto. */
export function AtalhosProvider({ children }: { children: ReactNode }) {
  const { valor, aberto, setAberto, grupos } = useRegistroDeAtalhos()

  return (
    <Contexto.Provider value={valor}>
      {children}
      <Modal opened={aberto} onClose={() => setAberto(false)} title="Atalhos" size="md">
        <Stack gap="md">
          {[...grupos].map(([grupo, atalhos]) => (
            <Stack key={grupo} gap="xs">
              <Title order={4}>{grupo}</Title>
              <Table aria-label={grupo}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Tecla</Table.Th>
                    <Table.Th>Ação</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {atalhos.map((a) => (
                    <Table.Tr key={a.tecla + a.acao}>
                      <Table.Td w={90}>
                        <Kbd>{a.tecla}</Kbd>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{a.acao}</Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Stack>
          ))}
        </Stack>
      </Modal>
    </Contexto.Provider>
  )
}

