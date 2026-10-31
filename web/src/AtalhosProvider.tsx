import { Kbd, Modal, Stack, Table, Text, Title } from '@mantine/core'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { type Atalho, Contexto, GERAIS } from './atalhos.ts'

function emCampoDeTexto(alvo: EventTarget | null): boolean {
  if (!(alvo instanceof HTMLElement)) return false
  return (
    alvo.isContentEditable ||
    alvo.getAttribute('contenteditable') === 'true' ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(alvo.tagName)
  )
}

/** O registro único de atalhos: ouve o teclado num lugar só e ignora campos de texto. */
export function AtalhosProvider({ children }: { children: ReactNode }) {
  const registros = useRef(new Set<() => Atalho[]>())
  const [aberto, setAberto] = useState(false)
  const [lista, setLista] = useState<Atalho[]>(GERAIS)

  const juntar = useCallback(
    () => [...GERAIS, ...[...registros.current].flatMap((r) => r())],
    [],
  )

  const mostrarAtalhos = useCallback(() => {
    setLista(juntar())
    setAberto(true)
  }, [juntar])

  const registrar = useCallback((atalhos: () => Atalho[]) => {
    registros.current.add(atalhos)
    return () => {
      registros.current.delete(atalhos)
    }
  }, [])

  useEffect(() => {
    function aoTeclar(e: KeyboardEvent) {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
      if (emCampoDeTexto(e.target)) return
      if (e.key === '?') {
        e.preventDefault()
        mostrarAtalhos()
        return
      }
      for (const a of juntar()) {
        if (a.executar && a.tecla === e.key) {
          e.preventDefault()
          a.executar()
          return
        }
      }
    }
    document.addEventListener('keydown', aoTeclar)
    return () => document.removeEventListener('keydown', aoTeclar)
  }, [juntar, mostrarAtalhos])

  const valor = useMemo(() => ({ mostrarAtalhos, registrar }), [mostrarAtalhos, registrar])
  const grupos = new Map<string, Atalho[]>()
  for (const a of lista) grupos.set(a.grupo, [...(grupos.get(a.grupo) ?? []), a])

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

